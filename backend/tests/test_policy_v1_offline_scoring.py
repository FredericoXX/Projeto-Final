"""Reanálise offline de recolhas arquivadas e identidade das mensagens julgadas (M7).

Fixtures técnicas e sintéticas (:mod:`tests.policy_v1_offline_support`): os
casos, os "rótulos" e os "juízos" daqui fixam o comportamento do código; não são
anotação humana nem resultados da tese.
"""

import copy
import json
import unicodedata
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from app.evaluation.policy_v1.freeze import sha256
from app.evaluation.policy_v1.message_ratings import (
    RUBRIC_CRITERIA,
    BoundMessageRatingSet,
    RatingProvenance,
    message_sha256,
    outcome_id,
)
from scripts.export_policy_v1_message_review import main as export_review
from scripts.p2_labels_tool import SCHEMA_KINDS, contract_schema
from scripts.score_policy_v1_report import main as score
from tests.policy_v1_offline_support import (
    COLLECTION_ID,
    INVENTORY_CHUNK,
    SyntheticCollection,
    build_collection,
    fill_draft,
    legacy_report,
    run_offline,
    score_argv,
)
from tests.test_policy_v1_evaluation_audit import COMMIT

DOCS = Path(__file__).resolve().parents[2] / "docs" / "evaluation" / "policy-v1"


@pytest.fixture(scope="module")
def collection() -> SyntheticCollection:
    return build_collection()


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _export(paths: dict[str, Path], directory: Path) -> dict[str, Any]:
    assert export_review(["--report", str(paths["report"]), "--output-dir", str(directory)]) == 0
    return _read(directory / "ratings-draft.json")


def _write(path: Path, payload: Any) -> Path:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _booleans(value: Any) -> list[bool]:
    if isinstance(value, bool):
        return [value]
    if isinstance(value, dict):
        return [found for item in value.values() for found in _booleans(item)]
    if isinstance(value, list):
        return [found for item in value for found in _booleans(item)]
    return []


# --- Reanálise sem base de dados, rede ou modelos ---------------------------------------


def test_offline_rescoring_reproduces_the_archived_metrics_without_db_network_or_models(
    collection: SyntheticCollection, tmp_path: Path
) -> None:
    paths = collection.write(tmp_path)
    output = tmp_path / "analysis.json"

    completed = run_offline(score_argv(paths, output))

    assert completed.returncode == 0, completed.stderr
    # Nem a sessão da base de dados nem nenhum adaptador de fornecedor foram carregados.
    assert "LOADED:\n" in completed.stderr
    analysis = _read(output)
    assert analysis["collection_metrics_reproduction"]["status"] == "identical"
    assert analysis["metrics"] == collection.report["metrics"]
    assert analysis["mode"] == "development_reanalysis"
    assert analysis["verification"]["level"] == "full"
    assert analysis["verification"]["unverifiable"] == []
    assert analysis["p_oracle"] == {"source": "archived"}
    source = analysis["source_report"]
    assert source["collection_id"] == COLLECTION_ID
    assert source["file_sha256"] == sha256(paths["report"].read_bytes())
    assert source["file_name"] == "report.json"
    # O commit da recolha e o da reanálise são registados em separado.
    assert source["collection_commit"] == COMMIT
    assert analysis["analysis"]["code_commit"] != COMMIT
    assert analysis["inputs"]["cases"]["file_sha256"] == sha256(paths["cases"].read_bytes())
    assert analysis["inputs"]["freeze_manifest"]["file_sha256"] == sha256(
        paths["freeze-manifest"].read_bytes()
    )
    # O terminal só recebe o resumo: nenhum pedido, mensagem ou excerto.
    assert "prazo" not in completed.stdout + completed.stderr
    assert json.loads(completed.stdout)["collection_metrics_reproduction"] == "identical"


def test_the_source_report_is_preserved_byte_for_byte(
    collection: SyntheticCollection, tmp_path: Path
) -> None:
    paths = collection.write(tmp_path)
    original = paths["report"].read_bytes()
    existing = tmp_path / "existing.json"
    existing.write_bytes(b"previous analysis")
    output = tmp_path / "analysis.json"

    assert score(score_argv(paths, paths["report"])) == 2
    assert score(score_argv(paths, existing)) == 2
    assert score(score_argv(paths, output)) == 0
    # Uma segunda análise nunca substitui a primeira.
    assert score(score_argv(paths, output)) == 2

    assert paths["report"].read_bytes() == original
    assert existing.read_bytes() == b"previous analysis"


def test_m7_is_not_measured_without_human_ratings(
    collection: SyntheticCollection, tmp_path: Path
) -> None:
    paths = collection.write(tmp_path)
    assert score(score_argv(paths, tmp_path / "analysis.json")) == 0
    analysis = _read(tmp_path / "analysis.json")

    for condition in ("B0", "P-e2e", "A-sem-diagnóstico", "B1-plena"):
        quality = analysis["metrics"][condition]["message_quality"]
        assert quality["status"] == "not_measured", condition
    paired = [
        comparison
        for comparison in analysis["metrics"]["paired_comparisons"]
        if comparison["measure"] == "message_acceptable"
    ]
    assert paired and all(comparison["status"] == "not_measured" for comparison in paired)
    assert analysis["message_ratings"] == {"status": "not_provided", "m7": "not_measured"}


def test_primary_run_failures_strata_and_denominators_are_preserved(
    collection: SyntheticCollection, tmp_path: Path
) -> None:
    paths = collection.write(tmp_path)
    assert score(score_argv(paths, tmp_path / "analysis.json")) == 0
    analysis = _read(tmp_path / "analysis.json")
    metrics = analysis["metrics"]

    # Fontes reais, sintéticas e F14 em estratos separados; só as reais no principal.
    assert set(metrics["by_stratum"]) == {"real", "synthetic", "F14_synthetic"}
    assert metrics["P-e2e"]["cases"] == 3
    assert analysis["case_traces"]["DEV-05"]["primary_scope"] is False
    assert metrics["by_stratum"]["F14_synthetic"]["P-e2e"]["cases"] == 1

    # M4 e M5: denominador estrito da ação preferida ESCALATE (DEV-04).
    b0 = metrics["B0"]["rates"]
    p_e2e = metrics["P-e2e"]["rates"]
    assert (b0["under_escalation"]["numerator"], b0["under_escalation"]["denominator"]) == (1, 1)
    assert (p_e2e["under_escalation"]["numerator"], p_e2e["under_escalation"]["denominator"]) == (
        0,
        1,
    )
    total = p_e2e["destination_correct_total"]
    assert (total["numerator"], total["denominator"]) == (1, 1)

    # Uma falha técnica na execução principal fica à parte e fora dos denominadores.
    synthetic = metrics["by_stratum"]["synthetic"]["P-e2e"]
    assert synthetic["technical_failures_primary_run"] == 1
    assert synthetic["rates"]["non_answer_outside_acceptable"]["denominator"] == 0
    assert synthetic["action_confusion"]["matrix"]["answer"]["technical_failure"] == 1
    failed = analysis["case_traces"]["DEV-02"]["conditions"]["P-e2e"]
    assert failed["primary"]["failure"] == "timeout"
    assert failed["primary"]["action"] is None
    assert not any(entry["denominator"] for entry in failed["metric_membership"].values())
    assert [run["failure"] for run in failed["runs"]] == ["timeout", None, None]

    # A primeira execução numerada decide; a instabilidade das repetições é separada.
    unstable = analysis["case_traces"]["DEV-01"]["conditions"]["B1-plena"]
    assert unstable["primary"]["action"] == "answer"
    assert [run["action"] for run in unstable["runs"]] == ["answer", "abstain", "answer"]
    assert unstable["unstable"] is True and unstable["modal_action"] == "answer"
    assert metrics["B1-plena"]["instability"]["numerator"] == 1


# --- Exportação para revisão humana ------------------------------------------------------


def test_the_review_export_separates_the_material_from_an_empty_draft(
    collection: SyntheticCollection, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    paths = collection.write(tmp_path)
    review = tmp_path / "review"

    draft = _export(paths, review)
    printed = capsys.readouterr()

    material = (review / "review-material.md").read_text(encoding="utf-8")
    manifest = _read(review / "review-manifest.json")
    assert draft["schema_version"] == "policy_v1_message_ratings_draft_1"
    assert draft["source_report"] == {
        "collection_id": COLLECTION_ID,
        "report_sha256": sha256(paths["report"].read_bytes()),
    }
    # Nenhum juízo por omissão: nem um único booleano no rascunho.
    assert draft["provenance"]["kind"] == "pending"
    assert _booleans(draft["ratings"]) == []
    for item in draft["ratings"]:
        assert (item["rater_id"], item["acceptable"]) == (None, "pending")
        assert set(item["criteria"]) == set(RUBRIC_CRITERIA)
        assert set(item["criteria"].values()) == {"pending"}
    # Só a execução principal, sem falhas técnicas nem P-oráculo, com a identidade exata.
    archived = {
        (o["case_id"], o["condition"], o["run_number"]): o for o in collection.report["outcomes"]
    }
    keys = {(item["case_id"], item["condition"], item["run_number"]) for item in draft["ratings"]}
    assert ("DEV-02", "P-e2e", 1) not in keys
    assert not any(condition == "P-oráculo" or run != 1 for _, condition, run in keys)
    for item in draft["ratings"]:
        outcome = archived[(item["case_id"], item["condition"], item["run_number"])]
        assert outcome["failure"] is None
        assert item["message_sha256"] == message_sha256(outcome["message"])
        assert item["outcome_id"] == outcome_id(outcome)
        assert item["packet_digest"] == outcome["packet_digest"]
    assert manifest["items"] == len(draft["ratings"]) == 27
    assert manifest["excluded"] == {
        "condition_without_message": 5,
        "not_primary_run": 60,
        "technical_failure": 3,
    }
    for name in ("review-material.md", "ratings-draft.json"):
        assert manifest["files"][name]["sha256"] == sha256((review / name).read_bytes())
    # O material traz as mensagens exatas e a evidência — e avisa que é confidencial.
    assert "Material do ambiente autorizado" in material
    assert "O prazo de matrícula termina a 30 de setembro." in material
    assert "Resposta sintética fundamentada." in material
    # Nada disso chega ao terminal.
    assert "prazo" not in printed.out + printed.err
    assert "Resposta sintética" not in printed.out + printed.err
    # E nunca sobrescreve um pacote existente.
    assert export_review(["--report", str(paths["report"]), "--output-dir", str(review)]) == 2


# --- Juízos M7 vinculados às mensagens ----------------------------------------------------


def test_bound_ratings_are_counted_for_the_rated_messages_only(
    collection: SyntheticCollection, tmp_path: Path
) -> None:
    paths = collection.write(tmp_path)
    draft = _export(paths, tmp_path / "review")
    # Juízo técnico: só a mensagem de P-e2e em DEV-01 é inaceitável.
    filled = fill_draft(
        draft,
        acceptable=lambda item: (item["case_id"], item["condition"]) != ("DEV-01", "P-e2e"),
    )
    ratings = _write(tmp_path / "ratings.json", filled)

    assert score(score_argv(paths, tmp_path / "analysis.json", ratings=ratings)) == 0
    analysis = _read(tmp_path / "analysis.json")

    quality = analysis["metrics"]["P-e2e"]["message_quality"]
    # Agregado principal: as mensagens de P-e2e das três fontes reais.
    assert quality["status"] == "measured"
    assert (quality["numerator"], quality["denominator"], quality["unrated"]) == (2, 3, 0)
    assert quality["raters"] == ["SYN-R1"]
    # A mensagem de A-sem-diagnóstico em DEV-01 tem o mesmo texto, mas é outra mensagem.
    assert analysis["metrics"]["A-sem-diagnóstico"]["message_quality"]["numerator"] == 3
    traces = analysis["case_traces"]["DEV-01"]["conditions"]
    assert traces["P-e2e"]["message_rating"]["acceptable"] is False
    assert traces["A-sem-diagnóstico"]["message_rating"]["acceptable"] is True
    paired = next(
        comparison
        for comparison in analysis["metrics"]["paired_comparisons"]
        if comparison["measure"] == "message_acceptable"
    )
    assert paired["n_pairs"] == 3
    # Tudo o resto é o que a recolha calculou.
    assert analysis["collection_metrics_reproduction"]["status"] == "identical"
    for condition in ("B0", "P-e2e", "B1-plena"):
        assert analysis["metrics"][condition]["rates"] == (
            collection.report["metrics"][condition]["rates"]
        )
    assert analysis["message_ratings"]["unrated_primary_messages"] == 0
    assert analysis["inputs"]["message_ratings"]["file_sha256"] == sha256(ratings.read_bytes())


def test_a_human_consolidation_is_accepted_without_automatic_averaging(
    collection: SyntheticCollection, tmp_path: Path
) -> None:
    paths = collection.write(tmp_path)
    filled = fill_draft(_export(paths, tmp_path / "review"), rater="SYN-CONS")
    filled["provenance"] = {
        "kind": "human_consolidation",
        "raters": ["SYN-R1", "SYN-R2"],
        "consolidated_by": ["SYN-CONS"],
    }
    ratings = _write(tmp_path / "ratings.json", filled)

    assert score(score_argv(paths, tmp_path / "analysis.json", ratings=ratings)) == 0
    analysis = _read(tmp_path / "analysis.json")
    assert analysis["message_ratings"]["provenance"]["kind"] == "human_consolidation"
    with pytest.raises(ValueError, match="consolidated_by"):
        RatingProvenance.model_validate({"kind": "human_consolidation", "raters": ["SYN-R1"]})
    with pytest.raises(ValueError, match="consolidated_by"):
        RatingProvenance.model_validate(
            {"kind": "one_rater_per_message", "raters": ["SYN-R1"], "consolidated_by": ["X"]}
        )


def _item(ratings: dict[str, Any], case_id: str, condition: str) -> dict[str, Any]:
    return next(
        item
        for item in ratings["ratings"]
        if (item["case_id"], item["condition"]) == (case_id, condition)
    )


def _unrateable(report: dict[str, Any], case_id: str, condition: str) -> dict[str, Any]:
    archived = next(
        o
        for o in report["outcomes"]
        if (o["case_id"], o["condition"], o["run_number"]) == (case_id, condition, 1)
    )
    return {
        "case_id": case_id,
        "condition": condition,
        "run_number": 1,
        "message_sha256": "3" * 64,
        "packet_digest": archived["packet_digest"],
        "outcome_id": outcome_id(archived),
        "rater_id": "SYN-R1",
        "acceptable": True,
        "criteria": dict.fromkeys(RUBRIC_CRITERIA, True),
    }


def _swap_condition(ratings: dict[str, Any], report: dict[str, Any]) -> None:
    # O texto de P-e2e e de A-sem-diagnóstico em DEV-01 é o mesmo: só a identidade
    # do resultado distingue as duas mensagens.
    ratings["ratings"].remove(_item(ratings, "DEV-01", "A-sem-diagnóstico"))
    _item(ratings, "DEV-01", "P-e2e")["condition"] = "A-sem-diagnóstico"


RATING_MUTATIONS: dict[str, Callable[[dict[str, Any], dict[str, Any]], None]] = {
    "altered-message-hash": lambda r, _: _item(r, "DEV-01", "P-e2e").update(
        message_sha256="0" * 64
    ),
    "unknown-reference": lambda r, _: _item(r, "DEV-01", "P-e2e").update(case_id="DEV-99"),
    "duplicate": lambda r, _: r["ratings"].append(copy.deepcopy(_item(r, "DEV-01", "P-e2e"))),
    "another-run": lambda r, _: _item(r, "DEV-01", "P-e2e").update(run_number=2),
    "another-condition": _swap_condition,
    "another-collection": lambda r, _: r["source_report"].update(
        collection_id="00000000-0000-4000-8000-000000000999"
    ),
    "another-report": lambda r, _: r["source_report"].update(report_sha256="1" * 64),
    "altered-outcome": lambda r, _: _item(r, "DEV-01", "P-e2e").update(outcome_id="2" * 64),
    "technical-failure": lambda r, report: r["ratings"].append(
        _unrateable(report, "DEV-02", "P-e2e")
    ),
    "oracle-has-no-message": lambda r, report: r["ratings"].append(
        _unrateable(report, "DEV-01", "P-oráculo")
    ),
    "pending-left": lambda r, _: _item(r, "DEV-01", "P-e2e").update(acceptable="pending"),
    "boolean-as-text": lambda r, _: _item(r, "DEV-01", "P-e2e")["criteria"].update(
        supported_and_complete="true"
    ),
    "required-criterion-not-applicable": lambda r, _: _item(r, "DEV-01", "B0")["criteria"].update(
        supported_and_complete=None
    ),
    "f02-notice-not-applicable": lambda r, _: _item(r, "DEV-03", "P-e2e")["criteria"].update(
        outdated_notice_present=None
    ),
    "unaccountable-rater": lambda r, _: _item(r, "DEV-01", "P-e2e").update(rater_id="SOMEONE"),
}


@pytest.mark.parametrize("mutation", sorted(RATING_MUTATIONS))
def test_ratings_that_do_not_match_the_archived_message_are_refused(
    collection: SyntheticCollection, tmp_path: Path, mutation: str
) -> None:
    paths = collection.write(tmp_path)
    ratings = fill_draft(_export(paths, tmp_path / "review"))
    RATING_MUTATIONS[mutation](ratings, collection.report)
    path = _write(tmp_path / "ratings.json", ratings)
    output = tmp_path / "analysis.json"

    assert score(score_argv(paths, output, ratings=path)) == 7
    assert not output.exists()


@pytest.mark.parametrize("kind", ["draft", "legacy-v1"])
def test_drafts_and_unbound_v1_ratings_are_never_accepted(
    collection: SyntheticCollection, tmp_path: Path, kind: str
) -> None:
    paths = collection.write(tmp_path)
    draft = _export(paths, tmp_path / "review")
    payload = (
        draft
        if kind == "draft"
        else {
            "schema_version": "policy_v1_message_ratings_1",
            "set_id": "policy-v1-dev",
            "ratings": [
                {"case_id": "DEV-01", "condition": "P-e2e", "rater_id": "R1", "acceptable": True}
            ],
        }
    )
    output = tmp_path / "analysis.json"

    path = _write(tmp_path / "ratings.json", payload)
    assert score(score_argv(paths, output, ratings=path)) == 7
    assert not output.exists()


def test_message_identity_is_the_exact_text() -> None:
    text = "O prazo termina a 30 de setembro."
    assert message_sha256(text) == sha256(text.encode("utf-8"))
    # Sem normalização: espaços, quebras de linha e formas Unicode contam.
    assert message_sha256(text) != message_sha256(text + " ")
    assert message_sha256("a\nb") != message_sha256("a\r\nb")
    assert message_sha256("ação") != message_sha256(unicodedata.normalize("NFD", "ação"))
    assert outcome_id({"a": 1, "b": [2, 3]}) == outcome_id({"b": [2, 3], "a": 1})
    assert outcome_id({"a": 1, "b": [2, 3]}) != outcome_id({"a": 1, "b": [3, 2]})


# --- Incompatibilidades entre relatório, casos, adjudicação e congelamento ---------------


def _mutate(collection: SyntheticCollection, part: str, change: Callable[[Any], None]) -> Any:
    copied = copy.deepcopy(collection)
    change(getattr(copied, part))
    return copied


def _first(items: list[dict[str, Any]], **match: Any) -> dict[str, Any]:
    return next(item for item in items if all(item[k] == v for k, v in match.items()))


INPUT_MUTATIONS: dict[str, tuple[str, Callable[[Any], None], int]] = {
    "case-query-edited": (
        "cases",
        lambda c: c["cases"][0].update(query=c["cases"][0]["query"] + " (editado)"),
        5,
    ),
    "case-set-differs": ("cases", lambda c: c.update(set_id="policy-v1-dev-outro"), 5),
    "adjudication-changed": (
        "adjudication",
        lambda a: a["cases"][0].update(acceptable_actions=["answer", "clarify"]),
        5,
    ),
    "annotator-not-adjudication": (
        "adjudication",
        lambda a: a.update(annotator={"annotator_id": "A1", "role": "annotator"}),
        5,
    ),
    "freeze-incomplete": ("manifest", lambda m: m.update(complete=False), 5),
    "collection-ran-other-prompts": (
        "manifest",
        lambda m: m["artifacts"]["prompts"].update(sha256="0" * 64),
        5,
    ),
    "frozen-catalog-differs": (
        "manifest",
        lambda m: m["artifacts"]["catalog"].update(sha256="0" * 64),
        5,
    ),
    "frozen-inventory-differs": (
        "manifest",
        lambda m: m["artifacts"]["manifest"].update(sha256="0" * 64),
        5,
    ),
    "packet-content-altered": (
        "report",
        lambda r: _first(r["packets"], case_id="DEV-01", family="b0")["passages"][0].update(
            content="O prazo de matrícula termina a 31 de outubro."
        ),
        3,
    ),
    "outcome-missing": (
        "report",
        lambda r: r["outcomes"].remove(
            _first(r["outcomes"], case_id="DEV-01", condition="B0", run_number=3)
        ),
        3,
    ),
    "outcome-without-its-packet": (
        "report",
        lambda r: _first(r["outcomes"], case_id="DEV-01", condition="B0", run_number=1).update(
            packet_digest="9" * 64
        ),
        3,
    ),
    "failure-with-a-message": (
        "report",
        lambda r: _first(r["outcomes"], case_id="DEV-02", condition="P-e2e", run_number=1).update(
            message="Mensagem inventada."
        ),
        3,
    ),
    "evaluation-config-differs": (
        "report",
        lambda r: r["config"]["thresholds"].update(kappa_minimum=0.5),
        5,
    ),
    "runtime-not-the-frozen-one": (
        "report",
        lambda r: r["runtime"].update(answer_model="outro-modelo"),
        5,
    ),
    "archived-oracle-disagrees": (
        "report",
        lambda r: _first(r["outcomes"], case_id="DEV-01", condition="P-oráculo").update(
            action="abstain"
        ),
        5,
    ),
}


@pytest.mark.parametrize("mutation", sorted(INPUT_MUTATIONS))
def test_mismatched_inputs_are_refused(
    collection: SyntheticCollection, tmp_path: Path, mutation: str
) -> None:
    part, change, expected = INPUT_MUTATIONS[mutation]
    mutated = _mutate(collection, part, change)
    paths = mutated.write(tmp_path)
    output = tmp_path / "analysis.json"

    assert score(score_argv(paths, output)) == expected
    assert not output.exists()


def test_an_analysis_is_not_accepted_as_a_collection_report(
    collection: SyntheticCollection, tmp_path: Path
) -> None:
    paths = collection.write(tmp_path)
    assert score(score_argv(paths, tmp_path / "analysis.json")) == 0
    analysis_paths = {**paths, "report": tmp_path / "analysis.json"}

    assert score(score_argv(analysis_paths, tmp_path / "again.json")) == 3


# --- Relatórios antigos, modo formal e P-oráculo ------------------------------------------


def test_legacy_reports_are_rescored_with_declared_partial_verification(
    collection: SyntheticCollection, tmp_path: Path
) -> None:
    legacy = legacy_report(collection.report)
    paths = collection.write(tmp_path, report=legacy)

    assert score(score_argv(paths, tmp_path / "analysis.json")) == 0
    analysis = _read(tmp_path / "analysis.json")
    verification = analysis["verification"]
    assert verification["level"] == "legacy_partial"
    assert set(verification["unverifiable"]) == {
        "adjudication_used_in_collection",
        "freeze_manifest_used_in_collection",
        "corpus_inventory",
        "runtime_configuration",
        "collection_git_state",
    }
    assert verification["formal_conformance"].startswith("not attributed")
    assert analysis["source_report"]["collection_id"] is None
    assert analysis["source_report"]["report_schema_version"] is None
    assert analysis["collection_metrics_reproduction"]["status"] == "identical"

    # Os juízos ligam-se pelos bytes do relatório quando não há identidade da recolha.
    draft = _export(paths, tmp_path / "review")
    assert draft["source_report"]["collection_id"] is None
    ratings = _write(tmp_path / "ratings.json", fill_draft(draft))
    assert score(score_argv(paths, tmp_path / "rated.json", ratings=ratings)) == 0
    assert _read(tmp_path / "rated.json")["metrics"]["P-e2e"]["message_quality"]["status"] == (
        "measured"
    )

    # Um relatório antigo marcado como formal nunca ganha conformidade formal.
    formal = collection.write(tmp_path / "formal", report={**legacy, "mode": "formal"})
    assert score(score_argv(formal, tmp_path / "f.json", inventory=True, formal=True)) == 6


def test_formal_reanalysis_needs_a_formal_collection_and_the_reserved_set_needs_it(
    collection: SyntheticCollection, tmp_path: Path
) -> None:
    paths = collection.write(tmp_path / "dev")
    assert score(score_argv(paths, tmp_path / "a.json", inventory=True, formal=True)) == 6

    reserved = build_collection(set_id="policy-v1-test").write(tmp_path / "reserved")
    # O conjunto reservado nunca é reanalisado como ensaio de desenvolvimento.
    assert score(score_argv(reserved, tmp_path / "b.json")) == 6
    assert not (tmp_path / "a.json").exists() and not (tmp_path / "b.json").exists()


def test_a_formal_collection_is_reanalysed_formally_only_on_a_clean_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from scripts import score_policy_v1_report as module

    formal = build_collection(set_id="policy-v1-test", mode="formal", traced=True)
    paths = formal.write(tmp_path)

    monkeypatch.setattr(module, "git_state", lambda repository: ("b" * 40, False))
    assert module.main(score_argv(paths, tmp_path / "dirty.json", inventory=True, formal=True)) == 6
    monkeypatch.setattr(module, "git_state", lambda repository: ("b" * 40, True))
    assert module.main(score_argv(paths, tmp_path / "missing.json", formal=True)) == 6
    assert module.main(score_argv(paths, tmp_path / "ok.json", inventory=True, formal=True)) == 0

    analysis = _read(tmp_path / "ok.json")
    assert analysis["mode"] == "formal_reanalysis"
    assert analysis["verification"]["formal_conformance"].startswith("verified")
    assert analysis["verification"]["checks"]["corpus_inventory_file"] == "verified"
    assert analysis["collection_metrics_reproduction"]["status"] == "identical"
    assert analysis["case_traces"]["DEV-01"]["adjudication"]["evidence_chunk_ids"] == [
        INVENTORY_CHUNK
    ]


def test_the_oracle_is_computed_offline_when_the_collection_had_no_adjudication(
    tmp_path: Path,
) -> None:
    paths = build_collection(with_adjudication=False).write(tmp_path)

    assert score(score_argv(paths, tmp_path / "analysis.json")) == 0
    analysis = _read(tmp_path / "analysis.json")
    assert analysis["p_oracle"] == {"source": "computed_offline"}
    assert analysis["verification"]["checks"]["adjudication_vs_collection"] == (
        "not_used_in_collection"
    )
    assert analysis["collection_metrics_reproduction"]["status"] == "not_computed_at_collection"
    assert "P-oráculo" in analysis["metrics"]


# --- Rastreabilidade de um caso ------------------------------------------------------------


def test_a_case_is_traced_from_its_documents_to_each_metric(
    collection: SyntheticCollection, tmp_path: Path
) -> None:
    paths = collection.write(tmp_path)
    ratings = _write(
        tmp_path / "ratings.json", fill_draft(_export(paths, tmp_path / "review"))
    )
    assert score(score_argv(paths, tmp_path / "analysis.json", ratings=ratings)) == 0
    trace = _read(tmp_path / "analysis.json")["case_traces"]["DEV-01"]
    archived = _first(
        collection.report["outcomes"], case_id="DEV-01", condition="P-e2e", run_number=1
    )

    assert trace["adjudication"]["preferred_action"] == "answer"
    p_e2e = trace["conditions"]["P-e2e"]
    document = p_e2e["primary"]["packet_documents"][0]
    citation = p_e2e["primary"]["citations"][0]
    # Documento → passagem citada, admissível na data de referência.
    assert (citation["chunk_id"], citation["status"]) == (document["chunk_id"], "admissible")
    # Estimativas contra a adjudicação, regra, mensagem e juízo humano.
    assert p_e2e["dimensions"]["d4.sufficiency"] == {"adjudicated": "full", "estimated": "full"}
    assert p_e2e["primary"]["rule"] == archived["rule"]
    assert p_e2e["primary"]["outcome_id"] == outcome_id(archived)
    assert p_e2e["primary"]["message_sha256"] == message_sha256(archived["message"])
    assert p_e2e["message_rating"]["acceptable"] is True
    # Pertença a cada métrica, pelas mesmas fórmulas das métricas agregadas.
    assert p_e2e["metric_membership"]["acceptable_agreement"] == {
        "v1_7_id": "M3",
        "denominator": True,
        "numerator": True,
    }
    assert p_e2e["metric_membership"]["answer_when_not_acceptable"]["denominator"] is False
    # A-sem-filtro citou a passagem caducada que só ele recebeu (M6).
    ablation = trace["conditions"]["A-sem-filtro"]
    assert "outside_validity" in {c["status"] for c in ablation["primary"]["citations"]}
    assert ablation["metric_membership"]["inadmissible_citations"]["numerator"] is True


# --- Executor, esquemas -----------------------------------------------------------------


def test_the_collection_refuses_ratings_and_never_overwrites_a_report(tmp_path: Path) -> None:
    from scripts.run_policy_v1_evaluation import EXIT_REFUSED, EXIT_USAGE, main

    cases = tmp_path / "cases.json"
    existing = tmp_path / "report.json"
    existing.write_bytes(b"archived collection")

    assert (
        main(
            [
                "--cases",
                str(cases),
                "--commit",
                COMMIT,
                "--output",
                str(tmp_path / "new.json"),
                "--message-ratings",
                str(tmp_path / "ratings.json"),
            ]
        )
        == EXIT_REFUSED
    )
    assert main(["--cases", str(cases), "--commit", COMMIT, "--output", str(existing)]) == (
        EXIT_USAGE
    )
    assert existing.read_bytes() == b"archived collection"
    assert not (tmp_path / "new.json").exists()


def test_versioned_schemas_match_the_models() -> None:
    for kind in SCHEMA_KINDS:
        path = DOCS / f"{kind}.schema.json"
        assert json.loads(path.read_text(encoding="utf-8")) == contract_schema(kind), kind
    assert contract_schema("message-ratings")["title"] == BoundMessageRatingSet.__name__
