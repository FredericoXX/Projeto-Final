"""Estimadores da política v1.7: contrato, validação e adaptador real isolado.

Sem rede e sem chave: o adaptador OpenAI recebe um cliente falso. Os pedidos
e respostas são fixtures técnicas sintéticas.
"""

import json
import subprocess
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import openai
import pytest

from app.core.config import settings
from app.decision.contracts import RequestConstraint, ScopeClass
from app.decision.dimensions import EstimateOrigin, Specificity
from app.decision.estimators.base import (
    AnalysisRequest,
    AssessmentRequest,
    CatalogTopicView,
    EstimationError,
    EstimatorUnavailableError,
    EvidenceAssessment,
    ItemDraft,
    ItemSupportDraft,
    PassageView,
    ReadingDraft,
    RequestAnalysis,
    validate_analysis,
    validate_assessment,
)
from app.decision.estimators.dependencies import get_dimension_estimator
from app.decision.estimators.providers.openai import OpenAIDimensionEstimator

BACKEND_DIR = Path(__file__).resolve().parents[1]

ANALYSIS_REQUEST = AnalysisRequest(
    query="Como faço a inscrição?",
    language="pt",
    reference_date=date(2026, 10, 1),
    requester_role="student",
    scope_description="Atendimento académico sintético.",
    topics=(CatalogTopicView("enrolment", "Matrículas"),),
)

ANALYSIS_PAYLOAD: dict[str, Any] = {
    "scope": "in_scope",
    "constraints": [],
    "specificity": "specified",
    "ambiguity_material": False,
    "user_can_distinguish": False,
    "readings": [{"reading_id": "L1", "label": "inscrição", "search_query": "inscrição"}],
    "items": [{"item_id": "I1", "label": "como fazer a inscrição"}],
    "topic": "enrolment",
    "procedure_item": None,
}

ASSESSMENT_REQUEST = AssessmentRequest(
    query="Como faço a inscrição?",
    language="pt",
    reference_date=date(2026, 10, 1),
    readings=(ReadingDraft("L1", "inscrição", "inscrição"),),
    items=(ItemDraft("I1", "como fazer a inscrição"),),
    passages=(PassageView("E1", "Regulamento", "A inscrição faz-se no portal.", True, None, None),),
)


class _FakeCompletions:
    def __init__(self, outcomes: list[Any]) -> None:
        self.outcomes = outcomes
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=outcome))],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
        )


def _client(*outcomes: Any) -> Any:
    completions = _FakeCompletions(list(outcomes))
    return SimpleNamespace(chat=SimpleNamespace(completions=completions)), completions


@pytest.fixture
def configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "openai_model", "test-model")


def test_adapter_parses_a_structured_analysis(configured: None) -> None:
    client, completions = _client(json.dumps(ANALYSIS_PAYLOAD))
    estimator = OpenAIDimensionEstimator(client=client)

    result = estimator.analyze(ANALYSIS_REQUEST)

    assert result.scope is ScopeClass.IN_SCOPE
    assert result.items == (ItemDraft("I1", "como fazer a inscrição"),)
    assert estimator.usage.attempts == 1
    assert estimator.usage.input_tokens == 10
    assert estimator.identity.origin is EstimateOrigin.MODEL
    # Instruções estáticas; o pedido segue só como dado JSON.
    system, user = completions.calls[0]["messages"]
    assert "Como faço a inscrição?" not in system["content"]
    assert json.loads(user["content"])["request"] == "Como faço a inscrição?"
    # Nunca se pede ao modelo uma ação.
    assert "ANSWER" not in system["content"]


def test_invalid_output_is_a_technical_failure_after_the_fixed_attempts(
    configured: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "decision_estimator_max_attempts", 2)
    client, completions = _client("not json", json.dumps({"scope": "maybe"}))
    estimator = OpenAIDimensionEstimator(client=client)

    with pytest.raises(EstimationError) as raised:
        estimator.analyze(ANALYSIS_REQUEST)

    assert raised.value.reason_code == "invalid_output"
    assert estimator.usage.attempts == 2
    assert estimator.usage.failures == ["invalid_output", "invalid_output"]
    assert len(completions.calls) == 2


def test_timeout_is_reported_as_timeout_never_as_a_value(configured: None) -> None:
    request = SimpleNamespace(method="POST", url="https://example.invalid")
    client, _ = _client(openai.APITimeoutError(request=request))  # type: ignore[arg-type]
    estimator = OpenAIDimensionEstimator(client=client)

    with pytest.raises(EstimationError) as raised:
        estimator.assess(ASSESSMENT_REQUEST)

    assert raised.value.reason_code == "timeout"


def test_a_retry_that_succeeds_counts_both_attempts(
    configured: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "decision_estimator_max_attempts", 2)
    client, _ = _client(RuntimeError("boom"), json.dumps(ANALYSIS_PAYLOAD))
    estimator = OpenAIDimensionEstimator(client=client)

    estimator.analyze(ANALYSIS_REQUEST)

    assert estimator.usage.attempts == 2
    assert estimator.usage.failures == ["provider_error"]


def test_missing_model_or_key_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "openai_model", None)
    monkeypatch.setattr(settings, "decision_estimator_model", None)
    with pytest.raises(EstimatorUnavailableError):
        OpenAIDimensionEstimator().analyze(ANALYSIS_REQUEST)

    monkeypatch.setattr(settings, "openai_model", "test-model")
    monkeypatch.setattr(settings, "openai_api_key", None)
    with pytest.raises(EstimatorUnavailableError):
        OpenAIDimensionEstimator().analyze(ANALYSIS_REQUEST)


def test_unknown_provider_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "decision_estimator_provider", "disabled")
    with pytest.raises(EstimatorUnavailableError):
        get_dimension_estimator()


def test_importing_the_application_does_not_load_the_estimator_sdk_adapter() -> None:
    code = (
        "import sys; import app.main; "
        "print('app.decision.estimators.providers.openai' in sys.modules)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=BACKEND_DIR, capture_output=True, text=True, check=True
    )
    assert result.stdout.strip() == "False"


# --- Validação estrutural ------------------------------------------------------------


def _analysis(**overrides: Any) -> RequestAnalysis:
    values: dict[str, Any] = {
        "scope": ScopeClass.IN_SCOPE,
        "constraints": frozenset(),
        "specificity": Specificity.SPECIFIED,
        "ambiguity_material": False,
        "user_can_distinguish": False,
        "readings": (),
        "items": (ItemDraft("I1", "prazo"),),
        "topic": "enrolment",
    }
    values.update(overrides)
    return RequestAnalysis(**values)


@pytest.mark.parametrize(
    "overrides",
    [
        {"topic": "invented-topic"},
        {"items": ()},
        {"items": (ItemDraft("I1", "a"), ItemDraft("I1", "b"))},
        {"ambiguity_material": True, "readings": (ReadingDraft("L1", "a", "a"),)},
        {
            "ambiguity_material": True,
            "specificity": Specificity.SPECIFIED,
            "readings": (ReadingDraft("L1", "a", "a"), ReadingDraft("L2", "b", "b")),
        },
        {"items": tuple(ItemDraft(f"I{n}", "x") for n in range(7))},
    ],
    ids=["unknown-topic", "no-items", "duplicate-items", "one-reading", "specified", "too-many"],
)
def test_incoherent_analysis_is_rejected_not_completed(overrides: dict[str, Any]) -> None:
    with pytest.raises(EstimationError) as raised:
        validate_analysis(_analysis(**overrides), ["enrolment"])
    assert raised.value.reason_code == "invalid_analysis"


def test_out_of_scope_or_constrained_requests_may_have_no_items() -> None:
    validate_analysis(_analysis(scope=ScopeClass.OUT_OF_SCOPE, items=(), topic=None), [])
    validate_analysis(
        _analysis(constraints=frozenset({RequestConstraint.PERSONAL_DATA_REQUIRED}), items=()),
        ["enrolment"],
    )


def _assessment(**overrides: Any) -> EvidenceAssessment:
    values: dict[str, Any] = {
        "reading_coverage": {"L1": frozenset({"E1"})},
        "item_support": (ItemSupportDraft("I1", True, frozenset({"E1"})),),
        "partial_misleading": None,
        "conflicts": (),
    }
    values.update(overrides)
    return EvidenceAssessment(**values)


def test_valid_assessment_passes() -> None:
    validate_assessment(_assessment(), ASSESSMENT_REQUEST)


@pytest.mark.parametrize(
    "overrides",
    [
        {"item_support": (ItemSupportDraft("I1", True, frozenset({"E9"})),)},
        {"reading_coverage": {"L1": frozenset({"E9"})}},
        {"reading_coverage": {}},
        {"item_support": ()},
        {"item_support": (ItemSupportDraft("I1", True, frozenset()),)},
        {"partial_misleading": False},
    ],
    ids=[
        "support-not-admissible",
        "coverage-not-admissible",
        "reading-missing",
        "item-missing",
        "supported-without-evidence",
        "misleading-without-partial",
    ],
)
def test_assessment_referring_outside_d0_or_incoherent_is_rejected(
    overrides: dict[str, Any],
) -> None:
    with pytest.raises(EstimationError) as raised:
        validate_assessment(_assessment(**overrides), ASSESSMENT_REQUEST)
    assert raised.value.reason_code == "invalid_assessment"
