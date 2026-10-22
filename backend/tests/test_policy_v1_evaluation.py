"""Infraestrutura de avaliação da política v1 — preparada, não executada.

Fixtures técnicas e sintéticas. Os "rótulos" daqui servem para testar o
código da ferramenta; não são anotação científica e não entram em nenhum
conjunto de avaliação.
"""

import ast
import inspect
import json
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.decision.contracts import RequestConstraint, ScopeClass
from app.decision.dimensions import ExcludedByValidity, TemporalDiagnostic, policy_input_to_dict
from app.decision.estimators.base import ItemDraft
from app.decision.policy import decide
from app.evaluation.policy_v1 import conditions as conditions_module
from app.evaluation.policy_v1 import executor as executor_module
from app.evaluation.policy_v1.conditions import (
    BaselineResponse,
    CaseOutcome,
    Condition,
    Limits,
    run_b0,
    run_b1_composition,
    run_b1_full,
    run_oracle,
    run_p_e2e,
    run_without_diagnostic,
)
from app.evaluation.policy_v1.freeze import (
    FreezeError,
    FrozenArtifact,
    build_freeze_manifest,
    canonical_bytes,
    freeze_cases,
    non_nfc_strings,
    sha256,
    verify_artifact,
)
from app.evaluation.policy_v1.labels import (
    CaseLabels,
    LabelCheckError,
    LabelSet,
    check_agreement,
    label_set_bytes,
    oracle_policy_input,
    verified_adjudication,
)
from app.evaluation.policy_v1.metrics import compute_metrics, paired_comparison
from app.evaluation.policy_v1.packets import EvidencePacket, PacketPassage
from app.evaluation.policy_v1.runs import run_numbers, summarize
from app.evaluation.policy_v1.statistics import (
    cohen_kappa,
    paired_difference_interval,
    wilson_interval,
)
from scripts.p2_labels_tool import labels_schema
from scripts.p2_labels_tool import main as labels_tool
from tests.decision_support import (
    RecordingGenerator,
    ScriptedEstimator,
    analysis,
    make_world,
    support_by_title,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
LABELS_SCHEMA_PATH = REPO_ROOT / "docs" / "evaluation" / "policy-v1" / "labels.schema.json"
LIMITS = Limits(max_context_chars=12000, max_answer_chars=4000)
REFERENCE = date(2026, 10, 1)
CATALOG: dict[str, Any] = {
    "version": 1,
    "scope_description": "Atendimento académico sintético.",
    "topics": [{"code": "enrolment", "label": "Matrículas"}, {"code": "fees", "label": "Propinas"}],
    "services": [
        {
            "service_id": "academic-office",
            "name": "Serviços Académicos (sintético)",
            "email": "academicos@example.org",
            "topics": ["enrolment"],
        }
    ],
}


# --- Receita de congelamento -------------------------------------------------------------


def test_freeze_recipe_bytes_are_exact_and_reproducible() -> None:
    cases: list[dict[str, Any]] = [
        {"case_id": "C2", "tags": ["z", "a"]},
        {"case_id": "C1", "text": "ação"},
    ]

    frozen = freeze_cases(cases)

    assert frozen == freeze_cases(list(reversed(cases)))
    assert frozen.decode("utf-8") == (
        '[{"case_id":"C1","text":"ação"},{"case_id":"C2","tags":["z","a"]}]'
    )
    assert not frozen.startswith(b"\xef\xbb\xbf")
    assert not frozen.endswith(b"\n")
    assert sha256(frozen) == sha256(freeze_cases(cases))


def test_freeze_rejects_duplicates_and_nan() -> None:
    with pytest.raises(FreezeError, match="unique"):
        freeze_cases([{"case_id": "C1"}, {"case_id": "C1"}])
    with pytest.raises(FreezeError, match="NaN"):
        canonical_bytes({"value": float("nan")})


def test_freeze_reports_non_nfc_without_normalizing() -> None:
    decomposed = "à"  # "à" decomposto
    payload = {"cases": [{"case_id": "C1", "query": decomposed}]}

    assert non_nfc_strings(payload) == ["$.cases[0].query"]
    assert decomposed.encode() in canonical_bytes(payload)


def test_freeze_manifest_identifies_every_artifact() -> None:
    """Expectativa alterada (segunda auditoria, 2026-10-23): o catálogo
    institucional D6 passou a ser um artefacto obrigatório do congelamento; um
    manifesto sem ele já não é completo."""
    artifacts = [
        FrozenArtifact(name, "v1", canonical_bytes({"name": name}))
        for name in (
            "corpus",
            "manifest",
            "labels",
            "policy",
            "schema",
            "prompts",
            "config",
            "catalog",
        )
    ]
    manifest = build_freeze_manifest(artifacts, code_commit="0" * 40)

    assert manifest["complete"] is True
    assert set(manifest["artifacts"]) == {artifact.name for artifact in artifacts}
    verify_artifact(manifest, "labels", canonical_bytes({"name": "labels"}))
    with pytest.raises(FreezeError):
        verify_artifact(manifest, "labels", canonical_bytes({"name": "other"}))
    partial = build_freeze_manifest(artifacts[:2], code_commit="0" * 40)
    assert partial["complete"] is False


# --- Estatística ---------------------------------------------------------------------------


def test_wilson_interval_is_informative_at_zero_and_undefined_without_denominator() -> None:
    zero = wilson_interval(0, 20)
    assert zero.estimate == 0 and zero.lower == 0 and zero.upper is not None and zero.upper > 0.1
    assert wilson_interval(0, 0).estimate is None


def test_paired_difference_uses_the_case_as_unit() -> None:
    a = [True, True, True, False, True, False]
    b = [True, False, False, False, True, False]
    result = paired_difference_interval(a, b)
    assert result.n_pairs == 6 and result.only_a == 2 and result.only_b == 0
    assert result.lower is not None and result.upper is not None
    assert result.estimate is not None
    assert result.lower <= result.estimate <= result.upper
    with pytest.raises(ValueError):
        paired_difference_interval([True], [True, False])


def test_kappa_is_symmetric_and_undefined_for_a_single_category() -> None:
    first = ["a", "a", "b", "b", "a"]
    second = ["a", "b", "b", "b", "a"]
    assert cohen_kappa(first, second).as_dict() == cohen_kappa(second, first).as_dict()
    assert cohen_kappa(["a", "a"], ["a", "a"]).kappa is None


# --- Rótulos ----------------------------------------------------------------------------------


def _case(case_id: str, **overrides: Any) -> dict[str, Any]:
    case: dict[str, Any] = {
        "case_id": case_id,
        "d1": {"scope": "in_scope"},
        "d2": {"constraints": []},
        "d3": {
            "specificity": "specified",
            "materiality": False,
            "disambiguation": None,
            "coverage": None,
        },
        "d4": {"sufficiency": "full", "partial_misleading": None},
        "d5": {"unresolvable_conflict": False},
        "d6": {"has_competent_service": True, "service_id": "academic-office"},
        "acceptable_actions": ["answer"],
    }
    case.update(overrides)
    return case


def _label_set(annotator: str, cases: list[dict[str, Any]], *, role: str = "annotator") -> LabelSet:
    return LabelSet.model_validate(
        {
            "schema_version": "policy_v1_labels_1",
            "set_id": "policy-v1-dev",
            "annotator": {
                "annotator_id": annotator,
                "role": role,
                "adjudicators": ["A1", "A2"] if role == "adjudication" else [],
            },
            "cases": cases,
        }
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"d4": {"sufficiency": "full", "partial_misleading": False}},
        {"d4": {"sufficiency": "partial", "partial_misleading": None}},
        {
            "d3": {
                "specificity": "specified",
                "materiality": True,
                "disambiguation": True,
                "coverage": True,
            }
        },
        {
            "d3": {
                "specificity": "underspecified",
                "materiality": True,
                "disambiguation": None,
                "coverage": True,
            }
        },
        {
            "d3": {
                "specificity": None,
                "materiality": False,
                "disambiguation": None,
                "coverage": None,
            }
        },
        {"d6": {"has_competent_service": False, "service_id": "academic-office"}},
        {"acceptable_actions": []},
        {"d1": {"scope": "not_applicable"}},
    ],
    ids=[
        "misleading-without-partial",
        "partial-without-misleading",
        "specified-material",
        "material-without-disambiguation",
        "na-with-sublabels",
        "service-without-flag",
        "no-acceptable-action",
        "na-as-category",
    ],
)
def test_label_schema_is_dependent_and_keeps_na_separate(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        CaseLabels.model_validate(_case("C1", **overrides))


def test_label_files_need_unique_ids_and_identified_adjudication() -> None:
    with pytest.raises(ValueError, match="unique"):
        _label_set("A1", [_case("C1"), _case("C1")])
    with pytest.raises(ValueError, match="adjudicators"):
        LabelSet.model_validate(
            {
                "schema_version": "policy_v1_labels_1",
                "set_id": "s",
                "annotator": {"annotator_id": "ADJ", "role": "adjudication"},
                "cases": [],
            }
        )


def test_check_reports_agreement_asymmetry_and_is_swap_invariant() -> None:
    first = _label_set(
        "A1", [_case("C1"), _case("C2"), _case("C3", d5={"unresolvable_conflict": None})]
    )
    second = _label_set(
        "A2",
        [
            _case("C1"),
            _case("C2", d1={"scope": "out_of_scope"}, acceptable_actions=["abstain"]),
            _case("C3"),
        ],
    )

    report = check_agreement(first, second)

    assert report["n_cases"] == 3
    assert report["fields"]["d1.scope"]["n"] == 3
    assert report["fields"]["d1.scope"]["raw_agreement"]["numerator"] == 2
    assert report["fields"]["d5.unresolvable_conflict"]["asymmetric_applicability"] == ["C3"]
    assert report["symmetric_applicability"] is False
    assert report == check_agreement(second, first)
    # O modo check não calcula ações nem altera rótulos.
    assert "action" not in json.dumps(report).replace("acceptable_actions", "")
    assert first.cases[2].d5.unresolvable_conflict is None


def test_check_refuses_different_case_sets() -> None:
    with pytest.raises(LabelCheckError):
        check_agreement(_label_set("A1", [_case("C1")]), _label_set("A2", [_case("C2")]))


def test_oracle_requires_identified_and_frozen_adjudication() -> None:
    """O manifesto completo inclui o catálogo desde a segunda auditoria."""
    adjudication = _label_set("ADJ", [_case("C1")], role="adjudication")
    artifacts = [
        FrozenArtifact(name, "v1", label_set_bytes(adjudication) if name == "labels" else b"x")
        for name in (
            "corpus",
            "manifest",
            "labels",
            "policy",
            "schema",
            "prompts",
            "config",
            "catalog",
        )
    ]
    manifest = build_freeze_manifest(artifacts, code_commit="0" * 40)

    assert verified_adjudication(adjudication, manifest) is adjudication
    with pytest.raises(FreezeError, match="identified adjudication"):
        verified_adjudication(_label_set("A1", [_case("C1")]), manifest)
    changed = _label_set("ADJ", [_case("C1", acceptable_actions=["abstain"])], role="adjudication")
    with pytest.raises(FreezeError, match="frozen digest"):
        verified_adjudication(changed, manifest)


@pytest.mark.parametrize(
    ("overrides", "rule"),
    [
        ({"d1": {"scope": "out_of_scope"}}, "R01"),
        ({"d2": {"constraints": ["personal_data_required"]}}, "R04"),
        (
            {
                "d3": {
                    "specificity": "underspecified",
                    "materiality": True,
                    "disambiguation": True,
                    "coverage": True,
                },
            },
            "R06",
        ),
        (
            {
                "d3": {
                    "specificity": "underspecified",
                    "materiality": True,
                    "disambiguation": True,
                    "coverage": False,
                },
            },
            "R11",
        ),
        ({"d5": {"unresolvable_conflict": True}}, "R07"),
        ({"d4": {"sufficiency": "partial", "partial_misleading": False}}, "R10"),
        ({"d4": {"sufficiency": "partial", "partial_misleading": True}}, "R11"),
        (
            {
                "d4": {"sufficiency": "none", "partial_misleading": None},
                "d6": {"has_competent_service": False, "service_id": None},
            },
            "R12",
        ),
        ({}, "R09"),
    ],
)
def test_oracle_uses_the_same_policy_implementation(overrides: dict[str, Any], rule: str) -> None:
    labels = CaseLabels.model_validate(_case("C1", **overrides))

    outcome = run_oracle(labels, catalog=CATALOG, reference_date=REFERENCE)
    direct = decide(
        oracle_policy_input(
            labels, services=CATALOG["services"], catalog_version=1, reference_date=REFERENCE
        )
    )

    assert outcome.rule == rule == direct.rule.value
    assert outcome.condition is Condition.P_ORACLE
    assert run_numbers(Condition.P_ORACLE) == (1,)


def test_versioned_labels_schema_matches_the_models() -> None:
    assert json.loads(LABELS_SCHEMA_PATH.read_text(encoding="utf-8")) == labels_schema()


def test_labels_tool_check_and_oracle_refusal(tmp_path: Path) -> None:
    first = tmp_path / "a1.json"
    second = tmp_path / "a2.json"
    report = tmp_path / "report.json"
    first.write_text(_label_set("A1", [_case("C1")]).model_dump_json(), encoding="utf-8")
    second.write_text(_label_set("A2", [_case("C1")]).model_dump_json(), encoding="utf-8")

    assert labels_tool(["check", str(first), str(second), "--output", str(report)]) == 0
    assert json.loads(report.read_text(encoding="utf-8"))["n_cases"] == 1

    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"complete": False, "artifacts": {}}), encoding="utf-8")
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps(CATALOG), encoding="utf-8")
    cases = tmp_path / "cases.json"
    cases.write_text(
        json.dumps(
            {
                "schema_version": "policy_v1_cases_1",
                "set_id": "policy-v1-dev",
                "corpus": "P2",
                "institution_code": "SYN",
                "cases": [
                    {
                        "case_id": "C1",
                        "query": "q",
                        "language": "pt",
                        "reference_date": "2026-10-01",
                        "requester_role": "student",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    adjudication = tmp_path / "adj.json"
    adjudication.write_text(
        _label_set("ADJ", [_case("C1")], role="adjudication").model_dump_json(), encoding="utf-8"
    )
    refused = labels_tool(
        [
            "oracle",
            "--adjudication",
            str(adjudication),
            "--freeze-manifest",
            str(manifest),
            "--catalog",
            str(catalog),
            "--cases",
            str(cases),
        ]
    )
    assert refused == 5


# --- Packets e condições --------------------------------------------------------------------


def _packet(
    family: str = "p_e2e",
    *,
    run_number: int = 1,
    passages: tuple[tuple[str, str, str], ...] = (
        ("E1", "Regulamento de matrículas", "O prazo termina a 30 de setembro."),
    ),
    diagnostic: TemporalDiagnostic | None = None,
) -> EvidencePacket:
    return EvidencePacket(
        case_id="C1",
        family=family,  # type: ignore[arg-type]
        run_number=run_number,
        query="Qual é o prazo de matrícula?",
        language="pt",
        reference_date=REFERENCE,
        requester_role="student",
        catalog=CATALOG,
        passages=tuple(
            PacketPassage(
                evidence_id=evidence_id,
                chunk_id=f"00000000-0000-4000-8000-00000000000{index}",
                document_id=f"00000000-0000-4000-8000-0000000000a{index}",
                document_version_id=f"00000000-0000-4000-8000-0000000000b{index}",
                document_title=title,
                chunk_index=0,
                content=content,
                content_sha256=sha256(content.encode()),
                official_source=True,
                source_url=None,
                language="pt",
                valid_from=None,
                valid_until=None,
            )
            for index, (evidence_id, title, content) in enumerate(passages, start=1)
        ),
        diagnostic=diagnostic or TemporalDiagnostic(),
        retrieval={
            "eligibility_policy": "RetrievalEligibility",
            "conditions": [],
            "access_policy_version": "v",
        },
    )


def test_packet_digest_is_reproducible_through_the_archive() -> None:
    packet = _packet()
    restored = EvidencePacket.from_dict(json.loads(canonical_bytes(packet.to_dict())))
    assert restored == packet
    assert restored.digest == packet.digest
    assert replace(packet, query="outro").digest != packet.digest


class _Baseline:
    def __init__(self, response: BaselineResponse | Exception) -> None:
        self.response = response
        self.prompts: list[tuple[str, str]] = []

    def respond(self, system_prompt: str, user_prompt: str) -> BaselineResponse:
        self.prompts.append((system_prompt, user_prompt))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def _p_e2e(packet: EvidencePacket | None = None, **analysis_overrides: Any):  # type: ignore[no-untyped-def]
    packet = packet or _packet()
    estimator = ScriptedEstimator(
        result=analysis(**analysis_overrides),
        assess_with=support_by_title({"I1": "matrículas"}),
    )
    return packet, run_p_e2e(packet, estimator.result, estimator, RecordingGenerator(), LIMITS)


def test_b1_conditions_receive_the_same_packet_and_the_same_estimates() -> None:
    packet, p_e2e = _p_e2e()
    baseline = _Baseline(BaselineResponse("answer", "Resposta.", ("E1",), None, {}))

    full = run_b1_full(packet, baseline)
    composition = run_b1_composition(packet, p_e2e, baseline)

    assert {p_e2e.outcome.packet_digest, full.packet_digest, composition.packet_digest} == {
        packet.digest
    }
    full_payload = json.loads(baseline.prompts[0][1])
    composition_payload = json.loads(baseline.prompts[1][1])
    assert full_payload["passages"] == composition_payload["passages"]
    assert full_payload["estimates"] is None
    assert p_e2e.policy_input is not None
    assert composition_payload["estimates"] == json.loads(
        json.dumps(policy_input_to_dict(p_e2e.policy_input))
    )
    # As mesmas definições e regras em linguagem natural.
    assert "R12" in baseline.prompts[0][0] and "D5 Conflict" in baseline.prompts[0][0]


@pytest.mark.parametrize(
    "response",
    [
        BaselineResponse("answer", "x", ("E9",), None),
        BaselineResponse("escalate", "x", (), None),
        BaselineResponse("defer", "x", (), None),
        BaselineResponse("escalate", "x", (), "unknown-service"),
    ],
    ids=[
        "inadmissible-citation",
        "escalate-without-destination",
        "unknown-action",
        "unknown-service",
    ],
)
def test_invalid_baseline_output_is_a_failure_not_an_action(response: BaselineResponse) -> None:
    outcome = run_b1_full(_packet(), _Baseline(response))
    assert (outcome.action, outcome.failure) == (None, "invalid_output")


def test_no_operational_condition_can_receive_gold_labels() -> None:
    for name in (
        "run_b0",
        "run_p_e2e",
        "run_without_diagnostic",
        "run_b1_full",
        "run_b1_composition",
    ):
        function = getattr(conditions_module, name)
        annotations = {
            str(value) for value in inspect.get_annotations(function, eval_str=True).values()
        }
        assert not any(
            "CaseLabels" in annotation or "LabelSet" in annotation for annotation in annotations
        ), name
    assert "labels" not in {
        node.module.rsplit(".", 1)[-1]
        for node in ast.walk(ast.parse(inspect.getsource(executor_module)))
        if isinstance(node, ast.ImportFrom) and node.module
    }


def test_without_diagnostic_keeps_decision_and_removes_only_the_notice() -> None:
    diagnostic = TemporalDiagnostic(
        excluded=(
            ExcludedByValidity("d", "Calendário antigo", date(2025, 1, 1), date(2025, 12, 31)),
        )
    )
    packet, p_e2e = _p_e2e(_packet(passages=(), diagnostic=diagnostic), topic="fees")

    ablated = run_without_diagnostic(packet, p_e2e, RecordingGenerator(), LIMITS)

    assert (p_e2e.outcome.action, ablated.action) == ("abstain", "abstain")
    assert ablated.rule == p_e2e.outcome.rule
    assert "Calendário antigo" in (p_e2e.outcome.message or "")
    assert "Calendário antigo" not in (ablated.message or "")
    assert ablated.packet_digest == p_e2e.outcome.packet_digest


def test_b0_keeps_its_legacy_mapping_on_packets() -> None:
    generator = RecordingGenerator()
    answered = run_b0(_packet("b0"), generator, LIMITS)
    empty = run_b0(_packet("b0", passages=()), generator, LIMITS)

    assert (answered.action, empty.action) == ("answer", "abstain")
    assert answered.cited_evidence_ids == ("E1",)
    with pytest.raises(ValueError):
        run_b0(_packet("p_e2e"), generator, LIMITS)


def test_p_e2e_failure_is_recorded_not_converted() -> None:
    from app.decision.estimators.base import EstimationError

    packet = _packet()
    estimator = ScriptedEstimator(result=analysis())

    def fail(request):  # type: ignore[no-untyped-def]
        raise EstimationError("timeout")

    estimator.assess_with = fail
    result = run_p_e2e(packet, estimator.result, estimator, RecordingGenerator(), LIMITS)

    assert (result.outcome.action, result.outcome.failure) == (None, "timeout")


# --- Execuções numeradas e métricas ------------------------------------------------------------


def _outcome(
    run: int,
    action: str | None,
    *,
    condition: Condition = Condition.P_E2E,
    case_id: str = "C1",
    destination: str | None = None,
) -> CaseOutcome:
    return CaseOutcome(
        case_id=case_id,
        condition=condition,
        run_number=run,
        action=action,
        rule=None,
        message=None,
        cited_evidence_ids=(),
        destination_service_id=destination,
        failure=None if action else "timeout",
        packet_digest=None,
        duration_ms=0,
    )


def test_primary_is_the_first_run_and_ties_go_to_it() -> None:
    summary = summarize([_outcome(2, "abstain"), _outcome(1, "answer"), _outcome(3, "escalate")])
    assert summary.primary.action == "answer"
    assert summary.modal_action == "answer"
    assert summary.unstable is True
    modal = summarize([_outcome(1, "answer"), _outcome(2, "abstain"), _outcome(3, "abstain")])
    assert modal.primary.action == "answer" and modal.modal_action == "abstain"
    failed_first = summarize([_outcome(1, None), _outcome(2, "abstain"), _outcome(3, "answer")])
    assert failed_first.failures == 1 and failed_first.modal_action == "abstain"
    with pytest.raises(ValueError, match="primary"):
        summarize([_outcome(2, "answer")])


def test_m1_and_m2_follow_their_definitions() -> None:
    gold = {
        "C1": CaseLabels.model_validate(_case("C1", acceptable_actions=["abstain"])),
        "C2": CaseLabels.model_validate(_case("C2", acceptable_actions=["answer"])),
        "C3": CaseLabels.model_validate(_case("C3", acceptable_actions=["answer", "clarify"])),
        "C4": CaseLabels.model_validate(_case("C4", acceptable_actions=["escalate"])),
    }
    summaries = {
        "C1": summarize([_outcome(1, "answer", case_id="C1")]),
        "C2": summarize([_outcome(1, "abstain", case_id="C2")]),
        "C3": summarize([_outcome(1, "clarify", case_id="C3")]),
        "C4": summarize([_outcome(1, "escalate", case_id="C4", destination="academic-office")]),
    }

    metrics = compute_metrics(summaries, gold, {})

    m1 = metrics["rates"]["answer_when_not_acceptable"]
    m2 = metrics["rates"]["non_answer_outside_acceptable"]
    assert (m1["numerator"], m1["denominator"]) == (1, 2)  # C1 de {C1, C4}
    assert (m2["numerator"], m2["denominator"]) == (1, 2)  # C2 de {C2, C3}; C3 é aceitável
    assert metrics["definitions"]["answer_when_not_acceptable"]["v1_7_id"] == "M1"
    # Expectativa alterada (auditoria de 2026-10-22, achado 1): M3–M8 passaram
    # de "pendente" a identificadores provisórios pela ordem do prompt v1.7,
    # versionados em config.METRIC_IDS; M9 continua por atribuir.
    assert metrics["definitions"]["over_escalation"]["v1_7_id"] == "M3"
    assert metrics["unassigned_ids"] == ["M9"]
    destination = metrics["rates"]["destination_correct_total"]
    assert (destination["numerator"], destination["denominator"]) == (1, 1)
    assert metrics["message_quality"]["status"] == "not_measured"


def test_failures_are_excluded_with_explicit_denominators() -> None:
    gold = {"C1": CaseLabels.model_validate(_case("C1", acceptable_actions=["abstain"]))}
    metrics = compute_metrics({"C1": summarize([_outcome(1, None, case_id="C1")])}, gold, {})
    assert metrics["technical_failures_primary_run"] == 1
    assert metrics["rates"]["answer_when_not_acceptable"]["denominator"] == 0
    assert metrics["rates"]["answer_when_not_acceptable"]["estimate"] is None
    assert metrics["action_distribution"] == {"technical_failure": 1}


def test_paired_comparison_counts_cases_once() -> None:
    gold = {f"C{n}": CaseLabels.model_validate(_case(f"C{n}")) for n in range(1, 4)}
    first = {f"C{n}": summarize([_outcome(1, "answer", case_id=f"C{n}")]) for n in range(1, 4)}
    second = {
        "C1": summarize([_outcome(1, "abstain", case_id="C1", condition=Condition.B0)]),
        "C2": summarize([_outcome(1, "answer", case_id="C2", condition=Condition.B0)]),
        "C3": summarize([_outcome(1, None, case_id="C3", condition=Condition.B0)]),
    }
    comparison = paired_comparison(first, second, gold)
    assert comparison["n_pairs"] == 2
    assert comparison["excluded_for_failures"] == 1


# --- Executor sobre a base de dados -------------------------------------------------------------


def test_executor_pairs_packets_and_confines_the_ablation(
    client: TestClient, test_session_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import select

    from app.evaluation.policy_v1.executor import EvaluationCase, run_case
    from app.models.decision_catalog import InstitutionDecisionCatalog
    from app.retrieval.dependencies import get_retriever

    world = make_world(client)
    today = datetime.now(UTC).date()
    world.document(
        client, "Regulamento de matrículas", "O prazo de matrícula termina a 30 de setembro."
    )
    world.document(
        client,
        "Calendário antigo",
        "O prazo de matrícula antigo terminava a 1 de setembro.",
        valid_from=today - timedelta(days=400),
        valid_until=today - timedelta(days=1),
    )
    case = EvaluationCase(
        case_id="DEV-C1",
        query="Qual é o prazo de matrícula?",
        language="pt",
        reference_date=today,
        requester_role="student",
    )
    estimator = ScriptedEstimator(
        result=analysis(), assess_with=support_by_title({"I1": "matrículas"})
    )
    baseline = _Baseline(BaselineResponse("answer", "Resposta.", ("E1",), None))
    with test_session_factory() as db:
        catalog = db.scalar(select(InstitutionDecisionCatalog))
        assert catalog is not None
        run = run_case(
            db,
            case,
            run_number=1,
            institution_id=catalog.institution_id,
            catalog=catalog,
            retriever=get_retriever(),
            estimator_factory=lambda: estimator,
            generator=RecordingGenerator(),
            baseline_model=baseline,
            limits=LIMITS,
            b0_top_k=5,
        )

    by_condition = {outcome.condition: outcome for outcome in run.outcomes}
    assert set(by_condition) == set(Condition) - {Condition.P_ORACLE}
    shared = run.packets["p_e2e"].digest
    for condition in (
        Condition.P_E2E,
        Condition.A_NO_DIAGNOSTIC,
        Condition.B1_FULL,
        Condition.B1_COMPOSITION,
    ):
        assert by_condition[condition].packet_digest == shared, condition
    b0_titles = {p.document_title for p in run.packets["b0"].passages}
    ablated_titles = {p.document_title for p in run.packets["b0_without_validity_filter"].passages}
    assert "Calendário antigo" not in b0_titles
    assert "Calendário antigo" in ablated_titles
    assert run.packets["b0_without_validity_filter"].retrieval["relaxed_conditions"] == [
        "valid_from_compatible",
        "valid_until_compatible",
    ]
    assert run.packets["p_e2e"].snapshot_id is not None
    assert run.packets["p_e2e"].corpus_digest is not None

    monkeypatch.setattr(settings, "environment", "production")
    with test_session_factory() as db, pytest.raises(RuntimeError, match="isolated"):
        run_case(
            db,
            case,
            run_number=2,
            institution_id=catalog.institution_id,
            catalog=catalog,
            retriever=get_retriever(),
            estimator_factory=lambda: estimator,
            generator=RecordingGenerator(),
            baseline_model=baseline,
            limits=LIMITS,
            b0_top_k=5,
        )


def test_analysis_failure_is_recorded_for_every_dependent_condition(
    client: TestClient, test_session_factory
) -> None:
    from sqlalchemy import select

    from app.decision.estimators.base import EstimationError
    from app.evaluation.policy_v1.executor import EvaluationCase, run_case
    from app.models.decision_catalog import InstitutionDecisionCatalog
    from app.retrieval.dependencies import get_retriever

    make_world(client)
    estimator = ScriptedEstimator(result=analysis(), fail_with=EstimationError("timeout"))
    case = EvaluationCase(
        case_id="DEV-C2",
        query="prazo",
        language="pt",
        reference_date=REFERENCE,
        requester_role="student",
    )
    with test_session_factory() as db:
        catalog = db.scalar(select(InstitutionDecisionCatalog))
        assert catalog is not None
        run = run_case(
            db,
            case,
            run_number=1,
            institution_id=catalog.institution_id,
            catalog=catalog,
            retriever=get_retriever(),
            estimator_factory=lambda: estimator,
            generator=RecordingGenerator(),
            baseline_model=_Baseline(RuntimeError()),
            limits=LIMITS,
            b0_top_k=5,
        )
    failed = [o for o in run.outcomes if o.failure is not None]
    assert {o.condition for o in failed} == {
        Condition.P_E2E,
        Condition.A_NO_DIAGNOSTIC,
        Condition.B1_FULL,
        Condition.B1_COMPOSITION,
    }
    assert all(o.action is None and o.failure == "analysis:timeout" for o in failed)


def test_constraint_path_matches_the_operational_flow() -> None:
    """Como em operação: o procedimento só entra como excerto citado de
    evidência admissível, e o gerador não é chamado."""
    packet = _packet()
    estimator = ScriptedEstimator(
        result=analysis(
            constraints=frozenset({RequestConstraint.PERSONAL_DATA_REQUIRED}),
            topic="enrolment",
            procedure_item=ItemDraft("P1", "como consultar o prazo"),
        ),
        assess_with=support_by_title({"P1": "matrículas"}),
    )
    generator = RecordingGenerator()

    result = run_p_e2e(packet, estimator.result, estimator, generator, LIMITS)

    assert (result.outcome.action, result.outcome.rule) == ("escalate", "R04")
    assert result.outcome.cited_evidence_ids == ("E1",)
    assert "30 de setembro" in (result.outcome.message or "")
    assert generator.calls == []
    assert result.policy_input is not None
    assert result.policy_input.scope is ScopeClass.IN_SCOPE
