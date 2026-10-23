"""Revisão de 2026-10-23 sobre a ``main`` ``8d3164b`` (PR #67).

- M6 resolve as citações no packet da própria condição;
- o inventário documental congelado é confrontado com a base;
- M3 é a matriz de confusão, com ação preferida, acordo estrito e aceitável;
- as comparações emparelhadas cobrem todas as condições;
- as regras dadas a B1 declaram a exclusão que o código aplica.

Fixtures técnicas e sintéticas, como no resto dos testes da política.
"""

import json
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.decision.definitions import DECISION_RULES
from app.evaluation.policy_v1.artifacts import file_artifact_bytes
from app.evaluation.policy_v1.conditions import CaseOutcome, Condition, b1_system_prompt
from app.evaluation.policy_v1.config import PAIRED_COMPARISONS
from app.evaluation.policy_v1.corpus_inventory import (
    collect_corpus_inventory,
    corpus_inventory_bytes,
)
from app.evaluation.policy_v1.freeze import FreezeError
from app.evaluation.policy_v1.labels import CaseLabels, LabelSet, MessageRatingSet
from app.evaluation.policy_v1.metrics import (
    action_confusion,
    citation_admissibility,
    compute_metrics,
    configured_paired_comparisons,
    paired_comparison,
)
from app.evaluation.policy_v1.packets import EvidencePacket
from app.evaluation.policy_v1.runs import CaseSummary, summarize
from tests.decision_support import DEFAULT_CATALOG, make_world
from tests.test_policy_v1_audit_round2 import _executor_inputs
from tests.test_policy_v1_evaluation import REFERENCE, _case, _packet
from tests.test_policy_v1_evaluation_audit import CORPUS_INVENTORY

EXPIRED_DOCUMENT = "00000000-0000-4000-8000-0000000000ff"


def _cited(
    condition: Condition,
    packet: EvidencePacket,
    *evidence_ids: str,
    case_id: str = "C1",
    action: str = "answer",
) -> CaseOutcome:
    return CaseOutcome(
        case_id=case_id,
        condition=condition,
        run_number=1,
        action=action,
        rule=None,
        message="Resposta.",
        cited_evidence_ids=evidence_ids,
        destination_service_id=None,
        failure=None,
        packet_digest=packet.digest,
        duration_ms=0,
    )


def _with_validity(
    packet: EvidencePacket, *, valid_until: date | None, document_id: str | None = None
) -> EvidencePacket:
    passage = replace(
        packet.passages[0],
        valid_until=valid_until,
        document_id=document_id or packet.passages[0].document_id,
    )
    return replace(packet, passages=(passage, *packet.passages[1:]))


def _gold(**overrides: Any) -> dict[str, CaseLabels]:
    return {"C1": CaseLabels.model_validate(_case("C1", **overrides))}


# --- M6: citações no contexto da própria condição ----------------------------------------


def test_m6_counts_an_expired_citation_that_shares_an_id_with_a_current_one() -> None:
    """O cenário reproduzido pela revisão: devolvia 0 citações inadmissíveis."""
    p_e2e = _packet("p_e2e")
    # O mesmo E1 é, em A-sem-filtro, outro documento, caducado na data.
    no_filter = _with_validity(
        _packet("b0_without_validity_filter"),
        valid_until=REFERENCE - timedelta(days=1),
        document_id=EXPIRED_DOCUMENT,
    )
    packets = {p_e2e.digest: p_e2e, no_filter.digest: no_filter}
    outcome = _cited(Condition.A_NO_FILTER, no_filter, "E1")

    metrics = compute_metrics({"C1": summarize([outcome])}, _gold(), packets)

    rate = metrics["rates"]["inadmissible_citations"]
    assert (rate["numerator"], rate["denominator"]) == (1, 1)
    [citation] = metrics["inadmissible_citation_details"]["C1"]
    assert citation["status"] == "outside_validity"
    assert citation["document_id"] == EXPIRED_DOCUMENT
    assert citation["chunk_id"] == no_filter.passages[0].chunk_id
    # E o E1 de P-e2e, o mesmo identificador, continua admissível.
    current = _cited(Condition.P_E2E, p_e2e, "E1")
    assert [c["status"] for c in citation_admissibility(current, packets)] == ["admissible"]


def test_m6_accepts_an_admissible_b0_citation_that_p_e2e_did_not_retrieve() -> None:
    """O erro inverso da comparação com o packet de P-e2e: falso positivo."""
    p_e2e = _packet("p_e2e")
    b0 = _packet(
        "b0",
        passages=(
            ("E1", "Regulamento de matrículas", "O prazo termina a 30 de setembro."),
            ("E2", "Calendário escolar", "As aulas começam a 15 de setembro."),
        ),
    )
    packets = {p_e2e.digest: p_e2e, b0.digest: b0}
    outcome = _cited(Condition.B0, b0, "E2")

    rate = compute_metrics({"C1": summarize([outcome])}, _gold(), packets)["rates"][
        "inadmissible_citations"
    ]

    assert (rate["numerator"], rate["denominator"]) == (0, 1)


def test_m6_reports_a_citation_missing_from_the_condition_packet() -> None:
    packet = _packet("p_e2e")
    statuses = citation_admissibility(
        _cited(Condition.B1_FULL, packet, "E1", "E9"), {packet.digest: packet}
    )
    assert [c["status"] for c in statuses] == ["admissible", "not_in_packet"]


@pytest.mark.parametrize(
    ("valid_until", "status"),
    [(REFERENCE, "admissible"), (REFERENCE - timedelta(days=1), "outside_validity")],
    ids=["last-day-in-force", "day-after-expiry"],
)
def test_m6_validity_limits_follow_c9_c10(valid_until: date, status: str) -> None:
    packet = _with_validity(_packet("b0_without_validity_filter"), valid_until=valid_until)
    [citation] = citation_admissibility(
        _cited(Condition.A_NO_FILTER, packet, "E1"), {packet.digest: packet}
    )
    assert citation["status"] == status


def test_m6_refuses_citations_without_their_packet() -> None:
    packet = _packet("p_e2e")
    with pytest.raises(ValueError, match="packet is not available"):
        citation_admissibility(_cited(Condition.P_E2E, packet, "E1"), {})


# --- M3: matriz de confusão, acordo estrito e aceitável -----------------------------------


def _summary(case_id: str, action: str | None, condition: Condition = Condition.P_E2E):
    return summarize(
        [
            CaseOutcome(
                case_id=case_id,
                condition=condition,
                run_number=1,
                action=action,
                rule=None,
                message=None,
                cited_evidence_ids=(),
                destination_service_id=None,
                failure=None if action else "timeout",
                packet_digest=None,
                duration_ms=0,
            )
        ]
    )


def test_m3_is_a_confusion_matrix_with_strict_and_acceptable_agreement() -> None:
    gold = {
        "C1": CaseLabels.model_validate(
            _case("C1", acceptable_actions=["answer", "clarify"], preferred_action="clarify")
        ),
        "C2": CaseLabels.model_validate(_case("C2", acceptable_actions=["escalate"])),
        "C3": CaseLabels.model_validate(_case("C3", acceptable_actions=["abstain"])),
    }
    summaries = {
        "C1": _summary("C1", "answer"),  # aceitável, não preferida
        "C2": _summary("C2", "escalate"),  # preferida
        "C3": _summary("C3", None),  # falha técnica
    }

    confusion = action_confusion(summaries, gold)

    assert confusion["v1_7_id"] == "M3"
    assert confusion["matrix"]["clarify"]["answer"] == 1
    assert confusion["matrix"]["escalate"]["escalate"] == 1
    assert confusion["matrix"]["abstain"]["technical_failure"] == 1
    assert sum(sum(row.values()) for row in confusion["matrix"].values()) == 3
    strict, acceptable = confusion["strict_agreement"], confusion["acceptable_agreement"]
    # A falha técnica fica fora dos dois denominadores.
    assert (strict["numerator"], strict["denominator"]) == (1, 2)
    assert (acceptable["numerator"], acceptable["denominator"]) == (2, 2)


def test_labels_require_a_preferred_action_in_schema_v2() -> None:
    case = _case("C1")
    del case["preferred_action"]
    with pytest.raises(ValueError, match="preferred_action"):
        CaseLabels.model_validate(case)
    with pytest.raises(ValueError, match="schema_version"):
        LabelSet.model_validate(
            {
                "schema_version": "policy_v1_labels_1",
                "set_id": "policy-v1-dev",
                "annotator": {"annotator_id": "A1", "role": "annotator"},
                "cases": [_case("C1")],
            }
        )


# --- Comparações emparelhadas --------------------------------------------------------------


def test_every_configured_pair_and_measure_is_reported() -> None:
    gold = _gold()
    summaries = {condition: {"C1": _summary("C1", "answer", condition)} for condition in Condition}

    results = configured_paired_comparisons(summaries, gold, packets={})

    expected = [
        (pair["first"], pair["second"], measure)
        for pair in PAIRED_COMPARISONS["pairs"]
        for measure in pair["measures"]
    ]
    assert [(r["first"], r["second"], r["measure"]) for r in results] == expected
    assert {(r["first"], r["second"]) for r in results} >= {
        ("P-e2e", "B0"),
        ("P-e2e", "B1-plena"),
        ("P-e2e", "B1-composição"),
        ("P-oráculo", "P-e2e"),
        ("B0", "A-sem-filtro"),
        ("P-e2e", "A-sem-diagnóstico"),
    }
    quality = next(r for r in results if r["measure"] == "message_acceptable")
    assert quality["status"] == "not_measured"


def test_the_filter_ablation_is_compared_on_inadmissible_citations() -> None:
    b0 = _packet("b0")
    no_filter = _with_validity(
        _packet("b0_without_validity_filter"),
        valid_until=REFERENCE - timedelta(days=1),
        document_id=EXPIRED_DOCUMENT,
    )
    packets = {b0.digest: b0, no_filter.digest: no_filter}
    first = {"C1": summarize([_cited(Condition.B0, b0, "E1")])}
    second = {"C1": summarize([_cited(Condition.A_NO_FILTER, no_filter, "E1")])}

    comparison = paired_comparison(
        first, second, _gold(), measure="inadmissible_citation", packets=packets
    )

    assert comparison["n_pairs"] == 1
    assert comparison["estimate"] == -1.0


def test_the_diagnostic_ablation_is_compared_on_human_message_ratings() -> None:
    ratings = MessageRatingSet.model_validate(
        {
            "schema_version": "policy_v1_message_ratings_1",
            "set_id": "policy-v1-dev",
            "ratings": [
                {"case_id": "C1", "condition": "P-e2e", "rater_id": "R1", "acceptable": True},
                {
                    "case_id": "C1",
                    "condition": "A-sem-diagnóstico",
                    "rater_id": "R1",
                    "acceptable": False,
                },
            ],
        }
    )
    first: dict[str, CaseSummary] = {"C1": _summary("C1", "abstain", Condition.P_E2E)}
    second = {"C1": _summary("C1", "abstain", Condition.A_NO_DIAGNOSTIC)}
    unrated = {"C2": _summary("C2", "abstain", Condition.P_E2E)}
    gold = {**_gold(), "C2": CaseLabels.model_validate(_case("C2"))}

    comparison = paired_comparison(
        {**first, **unrated},
        {**second, "C2": _summary("C2", "abstain", Condition.A_NO_DIAGNOSTIC)},
        gold,
        measure="message_acceptable",
        ratings=ratings,
    )

    assert comparison["n_pairs"] == 1
    assert comparison["estimate"] == 1.0
    assert comparison["excluded_unmeasured"] == 1


def test_every_comparison_declares_its_effect_outcome_denominator_and_unit() -> None:
    """Condição da confirmação de 2026-10-23: cada comparação explicita o efeito
    isolado, o denominador e a unidade estatística."""
    measures = PAIRED_COMPARISONS["measures"]
    for pair in PAIRED_COMPARISONS["pairs"]:
        assert pair["isolates"].strip()
        for measure in pair["measures"]:
            assert measures[measure]["outcome"].strip()
            assert measures[measure]["denominator"].strip()
    assert "caso" in PAIRED_COMPARISONS["unit"]
    assert "Newcombe" in PAIRED_COMPARISONS["interval"]
    # Todas as medidas declaradas são medidas implementadas, e só essas.
    for measure in measures:
        paired_comparison({}, {}, {}, measure=measure, ratings=None)
    with pytest.raises(ValueError, match="unknown paired measure"):
        paired_comparison({}, {}, {}, measure="undeclared")

    summaries = {condition: {"C1": _summary("C1", "answer", condition)} for condition in Condition}
    for result in configured_paired_comparisons(summaries, _gold(), packets={}):
        pair = next(
            p
            for p in PAIRED_COMPARISONS["pairs"]
            if (p["first"], p["second"]) == (result["first"], result["second"])
        )
        assert result["isolates"] == pair["isolates"]
        assert result["denominator"] == measures[result["measure"]]["denominator"]
        assert result["unit"] == PAIRED_COMPARISONS["unit"]


def test_paired_comparisons_are_frozen_with_the_config(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.evaluation.policy_v1.artifacts import code_artifacts, verify_code_artifacts
    from app.evaluation.policy_v1.freeze import build_freeze_manifest

    manifest = build_freeze_manifest(code_artifacts(), code_commit="a" * 40)
    verify_code_artifacts(manifest)
    monkeypatch.setitem(PAIRED_COMPARISONS["pairs"][0], "measures", ["acceptable_action"])
    with pytest.raises(FreezeError, match="config"):
        verify_code_artifacts(manifest)


def test_metric_ids_record_their_origin_and_are_not_normative() -> None:
    from app.evaluation.policy_v1.config import METRIC_IDS

    assert METRIC_IDS["normative"] is False
    assert "calibration" in METRIC_IDS["conformance"]
    assert set(METRIC_IDS["origins"]) == set(METRIC_IDS["ids"])
    # The full working document is now the explicit source, not guessed numbering.
    assert all("section 9.1" in source for source in METRIC_IDS["origins"].values())
    assert METRIC_IDS["ids"]["M9"] == "error_attribution"


# --- Regras em linguagem natural dadas a B1 ------------------------------------------------


def test_b1_rules_state_the_ambiguity_exclusion_the_code_applies() -> None:
    lines = DECISION_RULES.replace("\\\n", "").splitlines()
    r09 = next(line for line in lines if line.startswith("R09"))
    r10 = next(line for line in lines if line.startswith("R10"))
    r11 = next(line for line in lines if line.startswith("R11"))
    assert "no material ambiguity left unresolved by R06" in r09
    assert "no material ambiguity left unresolved by R06" in r10
    assert "material ambiguity that R06 could not clarify" in r11
    for variant in ("full", "composition"):
        assert r09 in b1_system_prompt(variant)


# --- Inventário documental congelado -------------------------------------------------------


def test_the_frozen_manifest_must_be_a_valid_ordered_inventory() -> None:
    corpus_inventory_bytes(CORPUS_INVENTORY)
    with pytest.raises(FreezeError, match="inventory"):
        file_artifact_bytes("manifest", {"corpus": "P2", "documents": [{"id": "SYN-DOC-1"}]})
    second = {
        **CORPUS_INVENTORY["documents"][0],
        "document_id": "00000000-0000-4000-8000-0000000000a0",
    }
    unordered = {**CORPUS_INVENTORY, "documents": [CORPUS_INVENTORY["documents"][0], second]}
    # A receita preserva a ordem dos arrays: um inventário fora de ordem é
    # recusado, nunca reordenado.
    with pytest.raises(FreezeError, match="inventory"):
        corpus_inventory_bytes(unordered)


def test_the_inventory_covers_expired_and_restricted_documents_and_detects_changes(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> None:
    world = make_world(client)
    world.document(client, "Regulamento vigente", "O prazo termina a 30 de setembro.")
    world.document(
        client,
        "Regulamento caducado",
        "O prazo terminava a 31 de julho.",
        valid_until=date(2020, 12, 31),
    )
    world.document(client, "Normas internas", "Só para serviços.", access_roles=["staff"])
    institution_id = UUID(str(world.institution_id))

    with test_session_factory() as db:
        before = corpus_inventory_bytes(collect_corpus_inventory(db, institution_id))
    inventory = json.loads(before)
    titles = {document["title"] for document in inventory["documents"]}
    assert titles == {"Regulamento vigente", "Regulamento caducado", "Normas internas"}
    assert all(d["versions"][0]["chunks"] for d in inventory["documents"])
    restricted = next(d for d in inventory["documents"] if d["title"] == "Normas internas")
    assert restricted["access_roles"] == ["staff"]
    # Nenhum conteúdo dos documentos entra no inventário, só hashes.
    assert "30 de setembro" not in before.decode("utf-8")

    world.document(client, "Documento acrescentado", "Conteúdo novo.")
    with test_session_factory() as db:
        after = corpus_inventory_bytes(collect_corpus_inventory(db, institution_id))
    assert after != before


def _capture_world(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    import tests.test_policy_v1_audit_round2 as round2

    worlds: list[Any] = []
    original = round2.make_world

    def capture(*args: Any, **kwargs: Any) -> Any:
        worlds.append(original(*args, **kwargs))
        return worlds[-1]

    monkeypatch.setattr(round2, "make_world", capture)
    return worlds


@pytest.mark.parametrize("formal", [True, False], ids=["formal", "oracle-outside-formal"])
def test_executor_refuses_a_database_changed_after_the_freeze(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
    tmp_path: Path,
    policy_v1_executor,
    monkeypatch: pytest.MonkeyPatch,
    formal: bool,
) -> None:
    from scripts.run_policy_v1_evaluation import EXIT_NOT_FROZEN

    worlds = _capture_world(monkeypatch)
    main, calls = policy_v1_executor
    argv = _executor_inputs(
        client, test_session_factory, tmp_path, frozen_catalog={"version": 1, **DEFAULT_CATALOG}
    )
    worlds[0].document(client, "Documento acrescentado depois", "Conteúdo novo.")

    assert main([*argv, "--formal"] if formal else argv) == EXIT_NOT_FROZEN
    assert calls == []
    assert not (tmp_path / "report.json").exists()


def test_executor_refuses_a_database_changed_during_the_evaluation(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.evaluation.policy_v1.executor import CaseRun
    from scripts import run_policy_v1_evaluation as module

    worlds = _capture_world(monkeypatch)
    calls: list[int] = []

    def changes_the_corpus(db: Session, case: Any, *, run_number: int, **kwargs: Any) -> CaseRun:
        if not calls:
            worlds[0].document(client, "Acrescentado a meio", "Conteúdo novo.")
        calls.append(run_number)
        return CaseRun(case_id=case.case_id, run_number=run_number, packets={})

    monkeypatch.setattr(module, "SessionLocal", test_session_factory)
    monkeypatch.setattr(module, "git_state", lambda repository: ("a" * 40, True))
    monkeypatch.setattr(module, "get_retriever", lambda: None)
    monkeypatch.setattr(module, "get_answer_generator", lambda: None)
    monkeypatch.setattr(module, "run_case", changes_the_corpus)
    argv = _executor_inputs(
        client, test_session_factory, tmp_path, frozen_catalog={"version": 1, **DEFAULT_CATALOG}
    )

    assert module.main([*argv, "--formal"]) == module.EXIT_NOT_FROZEN
    assert calls == [1, 2, 3]
    assert not (tmp_path / "report.json").exists()


def test_the_export_script_writes_the_inventory_the_executor_verifies(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.models.institution import Institution
    from scripts import export_policy_v1_corpus_inventory as module

    world = make_world(client)
    world.document(client, "Regulamento vigente", "O prazo termina a 30 de setembro.")
    monkeypatch.setattr(module, "SessionLocal", test_session_factory)
    with test_session_factory() as db:
        code = db.get_one(Institution, world.institution_id).code
        expected = corpus_inventory_bytes(
            collect_corpus_inventory(db, UUID(str(world.institution_id)))
        )
    output = tmp_path / "inventory.json"

    assert module.main(["--institution-code", code, "--output", str(output)]) == 0
    assert output.read_bytes() == expected
    assert not output.read_bytes().endswith(b"\n")
    assert file_artifact_bytes("manifest", json.loads(output.read_bytes())) == expected
    assert module.main(["--institution-code", "NOPE", "--output", str(output)]) == 3
