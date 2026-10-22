"""Adapter OpenAI dos estimadores de dimensões (desenvolvimento).

Todo o conhecimento do fornecedor vive aqui. O resto do backend só conhece os
contratos de :mod:`app.decision.estimators.base`.

- Saída estruturada com ``json_schema`` estrito; o parsing continua defensivo.
- Tentativas e timeout **fixos** pela configuração
  (``DECISION_ESTIMATOR_MAX_ATTEMPTS``, ``DECISION_ESTIMATOR_TIMEOUT_SECONDS``),
  contados em :class:`EstimationUsage`.
- Uma falha nunca inventa valores: depois da última tentativa levanta
  :class:`EstimationError` (502).
- Nos logs só ficam o tipo de erro e códigos estáveis; nunca o pedido, as
  passagens nem a resposta do fornecedor.
"""

import json
import logging
from collections.abc import Callable
from typing import Any

import openai

from app.core.config import settings
from app.decision.contracts import RequestConstraint, ScopeClass
from app.decision.definitions import DEFINITIONS_VERSION
from app.decision.dimensions import EstimateOrigin, Specificity
from app.decision.estimators.base import (
    ESTIMATOR_UNAVAILABLE_MESSAGE,
    AnalysisRequest,
    AssessmentRequest,
    ConflictDraft,
    EstimationError,
    EstimationUsage,
    EstimatorIdentity,
    EstimatorUnavailableError,
    EvidenceAssessment,
    ItemDraft,
    ItemSupportDraft,
    ReadingDraft,
    RequestAnalysis,
)
from app.decision.estimators.prompts import (
    ANALYSIS_PROMPT_VERSION,
    ANALYSIS_SYSTEM_PROMPT,
    ASSESSMENT_PROMPT_VERSION,
    ASSESSMENT_SYSTEM_PROMPT,
    build_analysis_user_prompt,
    build_assessment_user_prompt,
)

logger = logging.getLogger(__name__)

_NULLABLE_STRING = {"type": ["string", "null"]}
_ITEM = {
    "type": "object",
    "properties": {"item_id": {"type": "string"}, "label": {"type": "string"}},
    "required": ["item_id", "label"],
    "additionalProperties": False,
}

_ANALYSIS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "scope": {"type": "string", "enum": [s.value for s in ScopeClass]},
        "constraints": {
            "type": "array",
            "items": {"type": "string", "enum": [c.value for c in RequestConstraint]},
        },
        "specificity": {"type": "string", "enum": [s.value for s in Specificity]},
        "ambiguity_material": {"type": "boolean"},
        "user_can_distinguish": {"type": "boolean"},
        "readings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "reading_id": {"type": "string"},
                    "label": {"type": "string"},
                    "search_query": {"type": "string"},
                },
                "required": ["reading_id", "label", "search_query"],
                "additionalProperties": False,
            },
        },
        "items": {"type": "array", "items": _ITEM},
        "topic": _NULLABLE_STRING,
        "procedure_item": {"anyOf": [_ITEM, {"type": "null"}]},
    },
    "required": [
        "scope",
        "constraints",
        "specificity",
        "ambiguity_material",
        "user_can_distinguish",
        "readings",
        "items",
        "topic",
        "procedure_item",
    ],
    "additionalProperties": False,
}

_EVIDENCE_IDS = {"type": "array", "items": {"type": "string"}}

_ASSESSMENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "reading_coverage": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"reading_id": {"type": "string"}, "evidence_ids": _EVIDENCE_IDS},
                "required": ["reading_id", "evidence_ids"],
                "additionalProperties": False,
            },
        },
        "item_support": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "item_id": {"type": "string"},
                    "supported": {"type": "boolean"},
                    "evidence_ids": _EVIDENCE_IDS,
                },
                "required": ["item_id", "supported", "evidence_ids"],
                "additionalProperties": False,
            },
        },
        "partial_misleading": {"type": ["boolean", "null"]},
        "conflicts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "item_id": {"type": "string"},
                    "evidence_ids": _EVIDENCE_IDS,
                    "resolvable": {"type": "boolean"},
                },
                "required": ["item_id", "evidence_ids", "resolvable"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["reading_coverage", "item_support", "partial_misleading", "conflicts"],
    "additionalProperties": False,
}


def _response_format(name: str, schema: dict[str, Any]) -> dict[str, Any]:
    return {"type": "json_schema", "json_schema": {"name": name, "strict": True, "schema": schema}}


class _Invalid(Exception):
    """Saída do fornecedor que não respeita o formato esperado."""


def _as_str(value: Any) -> str:
    if not isinstance(value, str):
        raise _Invalid
    return value


def _as_bool(value: Any) -> bool:
    if not isinstance(value, bool):
        raise _Invalid
    return value


def _as_list(value: Any) -> list[Any]:
    if not isinstance(value, list):
        raise _Invalid
    return value


def _as_ids(value: Any) -> frozenset[str]:
    return frozenset(_as_str(item) for item in _as_list(value))


def _item(value: Any) -> ItemDraft:
    if not isinstance(value, dict):
        raise _Invalid
    return ItemDraft(item_id=_as_str(value.get("item_id")), label=_as_str(value.get("label")))


def _reading(value: Any) -> ReadingDraft:
    if not isinstance(value, dict):
        raise _Invalid
    return ReadingDraft(
        reading_id=_as_str(value.get("reading_id")),
        label=_as_str(value.get("label")),
        search_query=_as_str(value.get("search_query")),
    )


def parse_analysis(payload: Any) -> RequestAnalysis:
    if not isinstance(payload, dict):
        raise _Invalid
    try:
        procedure = payload.get("procedure_item")
        topic = payload.get("topic")
        return RequestAnalysis(
            scope=ScopeClass(_as_str(payload.get("scope"))),
            constraints=frozenset(
                RequestConstraint(_as_str(item)) for item in _as_list(payload.get("constraints"))
            ),
            specificity=Specificity(_as_str(payload.get("specificity"))),
            ambiguity_material=_as_bool(payload.get("ambiguity_material")),
            user_can_distinguish=_as_bool(payload.get("user_can_distinguish")),
            readings=tuple(_reading(reading) for reading in _as_list(payload.get("readings"))),
            items=tuple(_item(item) for item in _as_list(payload.get("items"))),
            topic=None if topic is None else _as_str(topic),
            procedure_item=None if procedure is None else _item(procedure),
        )
    except ValueError as exc:
        raise _Invalid from exc


def parse_assessment(payload: Any) -> EvidenceAssessment:
    if not isinstance(payload, dict):
        raise _Invalid
    coverage: dict[str, frozenset[str]] = {}
    for entry in _as_list(payload.get("reading_coverage")):
        if not isinstance(entry, dict):
            raise _Invalid
        reading_id = _as_str(entry.get("reading_id"))
        if reading_id in coverage:
            raise _Invalid
        coverage[reading_id] = _as_ids(entry.get("evidence_ids"))
    supports = []
    for entry in _as_list(payload.get("item_support")):
        if not isinstance(entry, dict):
            raise _Invalid
        supports.append(
            ItemSupportDraft(
                item_id=_as_str(entry.get("item_id")),
                supported=_as_bool(entry.get("supported")),
                evidence_ids=_as_ids(entry.get("evidence_ids")),
            )
        )
    conflicts = []
    for entry in _as_list(payload.get("conflicts")):
        if not isinstance(entry, dict):
            raise _Invalid
        conflicts.append(
            ConflictDraft(
                item_id=_as_str(entry.get("item_id")),
                evidence_ids=tuple(_as_str(item) for item in _as_list(entry.get("evidence_ids"))),
                resolvable=_as_bool(entry.get("resolvable")),
            )
        )
    misleading = payload.get("partial_misleading")
    return EvidenceAssessment(
        reading_coverage=coverage,
        item_support=tuple(supports),
        partial_misleading=None if misleading is None else _as_bool(misleading),
        conflicts=tuple(conflicts),
    )


class OpenAIDimensionEstimator:
    """Estimador real, configurável em desenvolvimento. Nunca usado nos testes."""

    def __init__(self, client: Any | None = None) -> None:
        # Cliente injetável apenas para testes com doubles do SDK.
        self._client = client
        self._usage = EstimationUsage()

    @property
    def identity(self) -> EstimatorIdentity:
        return EstimatorIdentity(
            provider="openai",
            model=self._model(),
            analysis_prompt_version=ANALYSIS_PROMPT_VERSION,
            assessment_prompt_version=ASSESSMENT_PROMPT_VERSION,
            definitions_version=DEFINITIONS_VERSION,
            origin=EstimateOrigin.MODEL,
        )

    @property
    def usage(self) -> EstimationUsage:
        return self._usage

    def analyze(self, request: AnalysisRequest) -> RequestAnalysis:
        return self._call(
            ANALYSIS_SYSTEM_PROMPT,
            build_analysis_user_prompt(request),
            _response_format("decision_analysis", _ANALYSIS_SCHEMA),
            parse_analysis,
        )

    def assess(self, request: AssessmentRequest) -> EvidenceAssessment:
        return self._call(
            ASSESSMENT_SYSTEM_PROMPT,
            build_assessment_user_prompt(request),
            _response_format("decision_assessment", _ASSESSMENT_SCHEMA),
            parse_assessment,
        )

    def _model(self) -> str | None:
        return settings.decision_estimator_model or settings.openai_model

    def _call[T](
        self,
        system_prompt: str,
        user_prompt: str,
        response_format: dict[str, Any],
        parse: Callable[[Any], T],
    ) -> T:
        model = self._model()
        if not model:
            raise EstimatorUnavailableError(ESTIMATOR_UNAVAILABLE_MESSAGE)
        client = self._client if self._client is not None else self._build_client()
        last_reason = "provider_error"
        for _ in range(settings.decision_estimator_max_attempts):
            self._usage.attempts += 1
            try:
                completion = client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    response_format=response_format,
                )
            except Exception as exc:
                # Só o tipo do erro: a mensagem do SDK pode conter o pedido.
                logger.warning(
                    "Decision estimator request failed: error_type=%s", type(exc).__name__
                )
                last_reason = (
                    "timeout" if isinstance(exc, openai.APITimeoutError) else "provider_error"
                )
                self._usage.failures.append(last_reason)
                continue
            usage = getattr(completion, "usage", None)
            self._usage.add_tokens(
                getattr(usage, "prompt_tokens", None), getattr(usage, "completion_tokens", None)
            )
            try:
                content = completion.choices[0].message.content
                return parse(json.loads(content))
            except (_Invalid, AttributeError, IndexError, TypeError, ValueError):
                logger.warning("Decision estimator returned invalid output")
                last_reason = "invalid_output"
                self._usage.failures.append(last_reason)
        raise EstimationError(last_reason)

    def _build_client(self) -> Any:
        api_key = settings.openai_api_key
        if not api_key:
            raise EstimatorUnavailableError(ESTIMATOR_UNAVAILABLE_MESSAGE)
        return openai.OpenAI(
            api_key=api_key,
            timeout=settings.decision_estimator_timeout_seconds,
            max_retries=0,
        )
