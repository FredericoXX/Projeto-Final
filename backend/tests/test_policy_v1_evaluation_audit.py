"""Correções da auditoria de 2026-10-22 à infraestrutura de avaliação v1.

Achados cobertos aqui: M3–M9 e atribuição de erros (1), snapshot por papel (2),
congelamento formal completo (3) e utilização das condições com modelo (4).
Fixtures técnicas e sintéticas; nenhum rótulo daqui é anotação científica.
"""

import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.answering.base import AnsweringContext, ContextEvidence, GeneratedAnswer
from app.core.config import settings
from app.decision.dimensions import policy_input_to_dict
from app.evaluation.policy_v1 import artifacts as artifacts_module
from app.evaluation.policy_v1.artifacts import (
    catalog_bytes,
    code_artifacts,
    corpus_bytes,
    file_artifact_bytes,
    verify_code_artifacts,
    verify_formal_freeze,
)
from app.evaluation.policy_v1.attribution import attribute_errors
from app.evaluation.policy_v1.conditions import (
    BaselineResponse,
    CaseOutcome,
    Condition,
    run_b0,
    run_b1_full,
    run_p_e2e,
)
from app.evaluation.policy_v1.corpus_inventory import corpus_inventory_bytes
from app.evaluation.policy_v1.freeze import (
    FreezeError,
    FrozenArtifact,
    build_freeze_manifest,
)
from app.evaluation.policy_v1.labels import (
    CaseLabels,
    LabelSet,
    MessageRatingSet,
    label_set_bytes,
    oracle_policy_input,
)
from app.evaluation.policy_v1.metrics import METRIC_DEFINITIONS, compute_metrics
from app.evaluation.policy_v1.runs import summarize
from app.evaluation.snapshot_builder import build_evaluation_snapshot
from scripts.p2_labels_tool import main as labels_tool
from tests.decision_support import ScriptedEstimator, analysis, make_world, support_by_title
from tests.test_policy_v1_evaluation import (
    CATALOG,
    LIMITS,
    REFERENCE,
    _Baseline,
    _case,
    _label_set,
    _packet,
)

COMMIT = "a" * 40
CASES: dict[str, Any] = {
    "schema_version": "policy_v1_cases_1",
    "set_id": "policy-v1-dev",
    "corpus": "P2",
    "institution_code": "SYN",
    "cases": [
        {
            "case_id": "C1",
            "query": "Qual é o prazo de matrícula?",
            "language": "pt",
            "reference_date": "2026-10-01",
            "requester_role": "student",
        }
    ],
}
#: Inventário documental sintético e válido: o artefacto ``manifest``. Até à
#: revisão de 2026-10-23 o manifesto era um JSON livre; agora é o inventário
#: exportado da base, e um JSON livre é recusado.
CORPUS_INVENTORY: dict[str, Any] = {
    "inventory_version": "policy_v1_corpus_inventory_1",
    "institution_id": "00000000-0000-4000-8000-000000000001",
    "institution_code": "SYN",
    "documents": [
        {
            "document_id": "00000000-0000-4000-8000-0000000000a1",
            "title": "Regulamento de matrículas",
            "language": "pt",
            "official_source": True,
            "is_active": True,
            "access_roles": [],
            "valid_from": None,
            "valid_until": None,
            "source_url": None,
            "versions": [
                {
                    "document_version_id": "00000000-0000-4000-8000-0000000000b1",
                    "version_number": 1,
                    "checksum_sha256": "0" * 64,
                    "processing_status": "processed",
                    "chunks": [
                        {
                            "chunk_id": "00000000-0000-4000-8000-0000000000c1",
                            "chunk_index": 0,
                            "language": "pt",
                            "content_sha256": "1" * 64,
                            "normalized_content_sha256": "2" * 64,
                            "section_title": None,
                            "structure_type": None,
                        }
                    ],
                }
            ],
        }
    ],
}


# --- Achado 1: identificadores, qualidade da mensagem e atribuição ----------------------


def test_metric_ids_follow_the_supplied_working_specification() -> None:
    ids = {definition.name: definition.v1_7_id for definition in METRIC_DEFINITIONS}
    # Expectativa alterada (revisão de 2026-10-23 sobre a main 8d3164b): M3 é a
    # matriz de confusão das quatro ações, com acordo estrito e aceitável; o
    # encaminhamento excessivo e insuficiente passou a componentes de M4.
    assert ids == {
        "answer_when_not_acceptable": "M1",
        "non_answer_outside_acceptable": "M2",
        "strict_agreement": "M3",
        "acceptable_agreement": "M3",
        "over_escalation": None,
        "under_escalation": "M4",
        "destination_correct_conditional": "M5",
        "destination_correct_total": "M5",
        "inadmissible_citations": "M6",
    }
    gold = {"C1": CaseLabels.model_validate(_case("C1"))}
    summary = summarize([_outcome("C1", "answer", message="Resposta.")])
    metrics = compute_metrics({"C1": summary}, gold, {})
    assert metrics["unassigned_ids"] == []
    assert "section 9.1" in metrics["metric_ids_status"]
    assert metrics["message_quality"]["status"] == "not_measured"


def _outcome(
    case_id: str,
    action: str | None,
    *,
    message: str | None = None,
    estimates: dict[str, Any] | None = None,
    destination: str | None = None,
) -> CaseOutcome:
    return CaseOutcome(
        case_id=case_id,
        condition=Condition.P_E2E,
        run_number=1,
        action=action,
        rule=None,
        message=message,
        cited_evidence_ids=(),
        destination_service_id=destination,
        failure=None if action else "timeout",
        packet_digest=None,
        duration_ms=0,
        estimates=estimates,
    )


def test_message_quality_comes_only_from_identified_human_ratings() -> None:
    gold = {f"C{n}": CaseLabels.model_validate(_case(f"C{n}")) for n in range(1, 4)}
    summaries = {
        f"C{n}": summarize([_outcome(f"C{n}", "answer", message=f"Mensagem {n}.")])
        for n in range(1, 4)
    }
    ratings = MessageRatingSet.model_validate(
        {
            "schema_version": "policy_v1_message_ratings_1",
            "set_id": "policy-v1-dev",
            "ratings": [
                {"case_id": "C1", "condition": "P-e2e", "rater_id": "R1", "acceptable": True},
                {"case_id": "C2", "condition": "P-e2e", "rater_id": "R1", "acceptable": False},
            ],
        }
    )

    quality = compute_metrics(summaries, gold, {}, ratings)["message_quality"]

    assert quality["status"] == "measured"
    assert (quality["numerator"], quality["denominator"], quality["unrated"]) == (1, 2, 1)
    assert quality["v1_7_id"] == "M7"
    with pytest.raises(ValueError, match="one rating"):
        MessageRatingSet.model_validate(
            {
                "schema_version": "policy_v1_message_ratings_1",
                "set_id": "s",
                "ratings": [
                    {"case_id": "C1", "condition": "P-e2e", "rater_id": "R1", "acceptable": True},
                    {"case_id": "C1", "condition": "P-e2e", "rater_id": "R2", "acceptable": True},
                ],
            }
        )


def _estimates_from(labels: dict[str, Any]) -> dict[str, Any]:
    """Estimativas sintéticas: as de uma adjudicação diferente da verdadeira."""
    return policy_input_to_dict(
        oracle_policy_input(
            CaseLabels.model_validate(labels),
            services=CATALOG["services"],
            catalog_version=1,
            reference_date=REFERENCE,
        )
    )


def _attribute(gold_case: dict[str, Any], estimated_case: dict[str, Any], action: str, **kw: Any):  # type: ignore[no-untyped-def]
    gold = {"C1": CaseLabels.model_validate(gold_case)}
    summary = summarize([_outcome("C1", action, estimates=_estimates_from(estimated_case), **kw)])
    return attribute_errors(
        {"C1": summary},
        gold,
        services=CATALOG["services"],
        catalog_version=1,
        reference_dates={"C1": REFERENCE},
    )


def test_attribution_isolates_a_single_estimation_cause_by_replay() -> None:
    # A adjudicação diz "dentro do âmbito, suportado"; a estimativa errou D1.
    result = _attribute(_case("C1"), _case("C1", d1={"scope": "out_of_scope"}), "abstain")

    assert len(result) == 1
    attribution = result[0].as_dict()
    assert attribution["causes"] == ["d1_scope"]
    assert attribution["determinacy"] == "single"
    assert attribution["replay"]["d1_scope"] == "corrects"
    assert attribution["inspection"]["status"] == "pending"


def test_attribution_reports_multiple_causes() -> None:
    wrong = _case(
        "C1",
        d4={"sufficiency": "none", "partial_misleading": None},
        d5={"unresolvable_conflict": True},
    )
    attribution = _attribute(_case("C1"), wrong, "escalate")[0]

    assert attribution.determinacy == "multiple"
    assert set(attribution.causes) == {"d4_support", "d5_conflict"}


def test_attribution_is_indeterminate_when_the_adjudicated_dimensions_also_fail() -> None:
    # Com as dimensões adjudicadas a política dá R09/ANSWER, mas a adjudicação
    # só aceita ABSTAIN: regra ou adjudicação em causa, não estimação.
    gold = _case("C1", acceptable_actions=["abstain"])
    attribution = _attribute(gold, _case("C1"), "answer")[0]

    assert attribution.determinacy == "indeterminate"
    assert attribution.causes == ("policy_rule", "adjudication")
    assert attribution.oracle_corrects is False


def test_attribution_covers_a_wrong_destination() -> None:
    gold = _case(
        "C1", d2={"constraints": ["personal_data_required"]}, acceptable_actions=["escalate"]
    )
    estimated = _case(
        "C1",
        d2={"constraints": ["personal_data_required"]},
        d6={"has_competent_service": True, "service_id": "academic-office"},
    )
    gold["d6"] = {"has_competent_service": True, "service_id": "academic-office"}
    result = _attribute(gold, estimated, "escalate", destination="other-office")

    assert result[0].error_kind == "wrong_destination"


# --- Achado 2: snapshot com o papel do caso -----------------------------------------------


def test_snapshot_identity_includes_the_role_only_when_given(
    client: TestClient, test_session_factory
) -> None:
    from sqlalchemy import select

    from app.models.decision_catalog import InstitutionDecisionCatalog

    world = make_world(client)
    world.document(client, "Público", "O prazo de matrícula termina a 30 de setembro.")
    world.document(
        client,
        "Só staff",
        "O prazo de matrícula interno termina a 1 de setembro.",
        access_roles=["staff"],
    )
    with test_session_factory() as db:
        institution_id = db.scalar(select(InstitutionDecisionCatalog.institution_id))
        assert institution_id is not None

        def snapshot(role: str | None):  # type: ignore[no-untyped-def]
            return build_evaluation_snapshot(
                db,
                institution_id=institution_id,
                language="pt",
                reference_date=date.today(),
                top_k=5,
                official_only=True,
                requester_role=role,
            )

        without, student, staff = snapshot(None), snapshot("student"), snapshot("staff")

    titles = {
        role: {entry.document_title for entry in snap.corpus}
        for role, snap in (("none", without), ("student", student), ("staff", staff))
    }
    assert titles == {"none": {"Público"}, "student": {"Público"}, "staff": {"Público", "Só staff"}}
    # Sem papel, o payload é o histórico: nenhum campo novo.
    assert "requester_role" not in without.retrieval.canonical()
    # O corpus visível ao aluno coincide com o sem papel, mas a experiência não.
    assert student.corpus_digest == without.corpus_digest
    assert student.snapshot_id != without.snapshot_id
    assert staff.corpus_digest != student.corpus_digest
    assert staff.retrieval.canonical()["document_access_policy"] == "document_role_access_v1"


# --- Achado 3: congelamento formal ------------------------------------------------------------


def _adjudication() -> LabelSet:
    return _label_set("ADJ", [_case("C1")], role="adjudication")


def _full_manifest(**overrides: bytes) -> dict[str, Any]:
    files = {
        "corpus": corpus_bytes(CASES),
        "manifest": corpus_inventory_bytes(CORPUS_INVENTORY),
        "labels": label_set_bytes(_adjudication()),
        # Artefacto obrigatório desde a segunda auditoria (2026-10-23).
        "catalog": catalog_bytes(CATALOG),
    }
    files.update(overrides)
    artifacts = [FrozenArtifact(name, "v1", data) for name, data in files.items()]
    return build_freeze_manifest([*artifacts, *code_artifacts()], code_commit=COMMIT)


def _verify(manifest: dict[str, Any], **overrides: Any) -> None:
    values: dict[str, Any] = {
        "cases_payload": CASES,
        "corpus_inventory_payload": CORPUS_INVENTORY,
        "adjudication": _adjudication(),
        "catalog_payload": CATALOG,
        "commit": COMMIT,
        "head_commit": COMMIT,
        "working_tree_clean": True,
    }
    values.update(overrides)
    verify_formal_freeze(manifest, **values)


def test_formal_freeze_verifies_every_artifact_commit_and_tree() -> None:
    manifest = _full_manifest()
    _verify(manifest)

    with pytest.raises(FreezeError, match="HEAD"):
        _verify(manifest, head_commit="b" * 40)
    with pytest.raises(FreezeError, match="uncommitted"):
        _verify(manifest, working_tree_clean=False)
    other_cases = {**CASES, "cases": [{**CASES["cases"][0], "query": "Outra pergunta"}]}
    with pytest.raises(FreezeError, match="corpus"):
        _verify(manifest, cases_payload=other_cases)
    with pytest.raises(FreezeError, match="manifest"):
        _verify(manifest, corpus_inventory_payload={**CORPUS_INVENTORY, "documents": []})
    incomplete = build_freeze_manifest(code_artifacts(), code_commit=COMMIT)
    with pytest.raises(FreezeError, match="incomplete"):
        _verify(incomplete)


@pytest.mark.parametrize(
    "payload", ["policy_payload", "prompts_payload", "config_payload", "schema_payload"]
)
def test_changed_code_artifacts_no_longer_match_the_freeze(
    monkeypatch: pytest.MonkeyPatch, payload: str
) -> None:
    """Política, prompts, configuração e esquema vêm do código em execução: uma
    alteração deixa de corresponder ao congelado."""
    manifest = _full_manifest()
    original = getattr(artifacts_module, payload)
    monkeypatch.setattr(artifacts_module, payload, lambda: {**original(), "changed": True})

    with pytest.raises(FreezeError, match="frozen digest"):
        verify_code_artifacts(manifest)


def test_code_artifacts_cannot_be_supplied_as_files() -> None:
    for name in ("policy", "schema", "prompts", "config"):
        with pytest.raises(FreezeError, match="generated from the code"):
            file_artifact_bytes(name, {})


def test_oracle_tool_requires_the_frozen_case_file(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(_full_manifest()), encoding="utf-8")
    adjudication = tmp_path / "adj.json"
    adjudication.write_text(_adjudication().model_dump_json(), encoding="utf-8")
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps(CATALOG), encoding="utf-8")
    frozen_cases = tmp_path / "cases.json"
    frozen_cases.write_text(json.dumps(CASES), encoding="utf-8")
    other_cases = tmp_path / "other.json"
    other_cases.write_text(
        json.dumps({**CASES, "cases": [{**CASES["cases"][0], "query": "Outra"}]}),
        encoding="utf-8",
    )
    output = tmp_path / "oracle.json"

    def run(cases: Path) -> int:
        return labels_tool(
            [
                "oracle",
                "--adjudication",
                str(adjudication),
                "--freeze-manifest",
                str(manifest_path),
                "--catalog",
                str(catalog),
                "--cases",
                str(cases),
                "--output",
                str(output),
            ]
        )

    assert run(other_cases) == 5
    assert run(frozen_cases) == 0
    assert json.loads(output.read_text(encoding="utf-8"))["outcomes"][0]["rule"] == "R09"


# --- Achado 4: utilização de todas as condições com modelo ------------------------------------


class _UsageGenerator:
    def generate(self, context: AnsweringContext) -> GeneratedAnswer:
        return GeneratedAnswer(
            answer="Resposta.",
            cited_evidence_ids=(context.evidence[0].evidence_id,),
            usage={"input_tokens": 11, "output_tokens": 7},
        )


def test_every_model_condition_records_attempts_and_tokens() -> None:
    b0 = run_b0(_packet("b0"), _UsageGenerator(), LIMITS)
    assert b0.usage["generator"] == {
        "attempts": 1,
        "input_tokens": 11,
        "output_tokens": 7,
        "cost": None,
    }

    packet = _packet()
    estimator = ScriptedEstimator(
        result=analysis(), assess_with=support_by_title({"I1": "matrículas"})
    )
    p_e2e = run_p_e2e(packet, estimator.result, estimator, _UsageGenerator(), LIMITS).outcome
    assert p_e2e.usage["generator"]["input_tokens"] == 11
    assert p_e2e.usage["estimator"]["attempts"] == 1

    b1 = run_b1_full(
        packet,
        _Baseline(
            BaselineResponse(
                "abstain", "Não sei.", (), None, usage={"input_tokens": 5, "output_tokens": 2}
            )
        ),
    )
    assert b1.usage["baseline_model"]["input_tokens"] == 5
    failed = run_b1_full(packet, _Baseline(BaselineResponse("defer", "x", (), None)))
    assert failed.failure == "invalid_output"
    assert failed.usage["baseline_model"]["attempts"] == 1


def test_openai_generator_reports_usage_without_exposing_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.answering.providers.openai import OpenAIAnswerGenerator

    monkeypatch.setattr(settings, "openai_model", "test-model")
    completion = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=json.dumps({"answer": "Resposta.", "cited_evidence_ids": ["E1"]})
                )
            )
        ],
        usage=SimpleNamespace(prompt_tokens=13, completion_tokens=4),
    )
    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kwargs: completion))
    )
    entry: ContextEvidence = _packet().entries()[0]

    generated = OpenAIAnswerGenerator(client=client).generate(
        AnsweringContext("q", "pt", "Inst", (entry,), 12000)
    )

    assert generated.usage == {"input_tokens": 13, "output_tokens": 4}
