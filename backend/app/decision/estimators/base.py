"""Contrato dos estimadores das dimensões D1–D5 (e do tema de D6).

Os estimadores são **separados das regras**: produzem saídas estruturadas, que
são validadas aqui, e nunca escolhem a ação. São substituíveis — um double
determinístico nos testes, um adaptador real configurável em desenvolvimento
(:mod:`app.decision.estimators.providers.openai`).

Duas etapas, pela ordem de recolha (não pela precedência das regras):

1. :meth:`DimensionEstimator.analyze` — antes de qualquer recuperação: âmbito
   (D1), restrições (D2), especificidade e leituras (D3, sem cobertura), itens
   do pedido (D4, sem suporte) e tema do catálogo (D6).
2. :meth:`DimensionEstimator.assess` — depois da recuperação e de D0, só sobre
   passagens admissíveis: cobertura de cada leitura, suporte por item,
   parcial enganosa e conflitos.

Uma saída que viole o contrato **não** é corrigida nem completada: é uma falha
técnica (:class:`EstimationError`, 502), que nunca se converte em ``ABSTAIN``.
Palavras-chave e scores do retriever não são juízos de âmbito, intenção,
suporte ou conflito, e nenhum estimador operacional os usa como tal.

Este módulo não importa nenhum SDK.
"""

from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from datetime import date
from typing import Final, Protocol

from app.core.exceptions import ServiceUnavailableError, UpstreamServiceError
from app.decision.contracts import RequestConstraint, ScopeClass
from app.decision.dimensions import EstimateOrigin, Specificity

#: Limites explícitos da decomposição: leituras e itens.
MAX_READINGS: Final = 4
MAX_ITEMS: Final = 6
MAX_LABEL_CHARS: Final = 300
MAX_SEARCH_QUERY_CHARS: Final = 500

ESTIMATOR_UNAVAILABLE_MESSAGE: Final = "Decision estimation is not configured on this server."
ESTIMATION_FAILED_MESSAGE: Final = "The decision estimator failed to produce a usable result."


class EstimatorUnavailableError(ServiceUnavailableError):
    """O estimador não está configurado (503). Nunca impede o arranque."""


class EstimationError(UpstreamServiceError):
    """O estimador falhou ou devolveu saída inválida (502).

    ``reason_code`` é um código estável controlado pela aplicação; a exceção
    nunca guarda valores devolvidos pelo fornecedor.
    """

    def __init__(self, reason_code: str, message: str = ESTIMATION_FAILED_MESSAGE) -> None:
        super().__init__(message)
        self.reason_code = reason_code


# ---------------------------------------------------------------------------
# Etapa 1 — análise do pedido
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CatalogTopicView:
    code: str
    label: str


@dataclass(frozen=True)
class AnalysisRequest:
    query: str
    language: str
    reference_date: date
    requester_role: str
    scope_description: str
    topics: tuple[CatalogTopicView, ...]
    #: Leitura escolhida pelo utilizador numa continuação de clarificação.
    selected_reading: str | None = None


@dataclass(frozen=True)
class ReadingDraft:
    reading_id: str
    label: str
    #: Texto de pesquisa desta leitura, para a recuperação por leitura.
    search_query: str


@dataclass(frozen=True)
class ItemDraft:
    item_id: str
    label: str


@dataclass(frozen=True)
class RequestAnalysis:
    scope: ScopeClass
    constraints: frozenset[RequestConstraint]
    specificity: Specificity
    ambiguity_material: bool
    user_can_distinguish: bool
    readings: tuple[ReadingDraft, ...]
    items: tuple[ItemDraft, ...]
    topic: str | None
    #: Item que pede o procedimento documentado, quando há restrições (R02/R04).
    procedure_item: ItemDraft | None = None


# ---------------------------------------------------------------------------
# Etapa 2 — avaliação sobre evidência admissível
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PassageView:
    """O que o estimador vê de uma passagem admissível."""

    evidence_id: str
    document_title: str
    content: str
    official_source: bool
    valid_from: date | None
    valid_until: date | None


@dataclass(frozen=True)
class AssessmentRequest:
    query: str
    language: str
    reference_date: date
    readings: tuple[ReadingDraft, ...]
    items: tuple[ItemDraft, ...]
    passages: tuple[PassageView, ...]


@dataclass(frozen=True)
class ItemSupportDraft:
    item_id: str
    supported: bool
    evidence_ids: frozenset[str]


@dataclass(frozen=True)
class ConflictDraft:
    item_id: str
    evidence_ids: tuple[str, ...]
    resolvable: bool


@dataclass(frozen=True)
class EvidenceAssessment:
    reading_coverage: Mapping[str, frozenset[str]]
    item_support: tuple[ItemSupportDraft, ...]
    partial_misleading: bool | None
    conflicts: tuple[ConflictDraft, ...] = ()


# ---------------------------------------------------------------------------
# Identidade e utilização
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EstimatorIdentity:
    """Versões que identificam as estimativas de uma execução."""

    provider: str
    model: str | None
    analysis_prompt_version: str
    assessment_prompt_version: str
    definitions_version: str
    origin: EstimateOrigin

    def as_dict(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "model": self.model,
            "analysis_prompt_version": self.analysis_prompt_version,
            "assessment_prompt_version": self.assessment_prompt_version,
            "definitions_version": self.definitions_version,
            "origin": self.origin.value,
        }


@dataclass
class EstimationUsage:
    """Tentativas e tokens, acumulados pelo adaptador numa execução."""

    attempts: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    failures: list[str] = field(default_factory=list)

    def add_tokens(self, input_tokens: int | None, output_tokens: int | None) -> None:
        if input_tokens is not None:
            self.input_tokens = (self.input_tokens or 0) + input_tokens
        if output_tokens is not None:
            self.output_tokens = (self.output_tokens or 0) + output_tokens

    def as_dict(self) -> dict[str, object]:
        return {
            "attempts": self.attempts,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "failures": list(self.failures),
            # Custo monetário não é calculado: depende de tarifas externas.
            "cost": None,
        }


class DimensionEstimator(Protocol):
    @property
    def identity(self) -> EstimatorIdentity: ...

    @property
    def usage(self) -> EstimationUsage: ...

    def analyze(self, request: AnalysisRequest) -> RequestAnalysis: ...

    def assess(self, request: AssessmentRequest) -> EvidenceAssessment: ...


# ---------------------------------------------------------------------------
# Validação estrutural
# ---------------------------------------------------------------------------


def _valid_label(value: str, limit: int = MAX_LABEL_CHARS) -> bool:
    return isinstance(value, str) and bool(value.strip()) and len(value) <= limit


def validate_analysis(analysis: RequestAnalysis, topic_codes: Collection[str]) -> None:
    """Recusa uma análise incoerente; nunca a completa."""
    reading_ids = [reading.reading_id for reading in analysis.readings]
    item_ids = [item.item_id for item in analysis.items]
    problems = (
        len(set(reading_ids)) != len(reading_ids)
        or len(set(item_ids)) != len(item_ids)
        or len(analysis.readings) > MAX_READINGS
        or len(analysis.items) > MAX_ITEMS
        or not all(_valid_label(reading.label) for reading in analysis.readings)
        or not all(
            _valid_label(reading.search_query, MAX_SEARCH_QUERY_CHARS)
            for reading in analysis.readings
        )
        or not all(_valid_label(item.label) for item in analysis.items)
        or (analysis.topic is not None and analysis.topic not in topic_codes)
        or (
            analysis.ambiguity_material
            and (
                analysis.specificity is not Specificity.UNDERSPECIFIED or len(analysis.readings) < 2
            )
        )
        or (analysis.procedure_item is not None and not _valid_label(analysis.procedure_item.label))
    )
    documentary = analysis.scope is ScopeClass.IN_SCOPE and not analysis.constraints
    if problems or (documentary and not analysis.items):
        raise EstimationError("invalid_analysis")


def validate_assessment(
    assessment: EvidenceAssessment,
    request: AssessmentRequest,
) -> None:
    """D0 antes de D3/D4/D5: só passagens admissíveis podem ser referidas."""
    admissible = {passage.evidence_id for passage in request.passages}
    reading_ids = {reading.reading_id for reading in request.readings}
    item_ids = [item.item_id for item in request.items]
    support_ids = [support.item_id for support in assessment.item_support]

    referenced: set[str] = set()
    for evidence_ids in assessment.reading_coverage.values():
        referenced.update(evidence_ids)
    for support in assessment.item_support:
        referenced.update(support.evidence_ids)
    for conflict in assessment.conflicts:
        referenced.update(conflict.evidence_ids)

    supported = sum(1 for support in assessment.item_support if support.supported)
    partial = 0 < supported < len(assessment.item_support)
    problems = (
        set(assessment.reading_coverage) != reading_ids
        or sorted(support_ids) != sorted(item_ids)
        or bool(referenced - admissible)
        or any(
            support.supported != bool(support.evidence_ids) for support in assessment.item_support
        )
        or (partial and assessment.partial_misleading is None)
        or (not partial and assessment.partial_misleading is not None)
        or any(
            conflict.item_id not in item_ids or len(set(conflict.evidence_ids)) < 2
            for conflict in assessment.conflicts
        )
    )
    if problems:
        raise EstimationError("invalid_assessment")
