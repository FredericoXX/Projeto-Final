"""Regressões da auditoria de 2026-10-27 à reanálise offline (quatro lacunas).

1. A identidade e a receita do manifesto de congelamento não eram verificadas.
2. O comando offline exigia a configuração operacional da aplicação.
3. Estimativas malformadas só falhavam a meio do cálculo.
4. M7 aparecia como medida sem nenhum juízo aplicável.

Fixtures técnicas e sintéticas (:mod:`tests.policy_v1_offline_support`); nada
aqui é anotação humana ou resultado da tese.
"""

import copy
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from app.evaluation.policy_v1.freeze import FreezeError
from app.evaluation.policy_v1.labels import LabelSet, verified_adjudication
from scripts.export_policy_v1_message_review import main as export_review
from tests.policy_v1_offline_support import (
    SyntheticCollection,
    build_collection,
    fill_draft,
    run_offline,
    score_argv,
)

FORMAL_GIT = ("b" * 40, True)


@pytest.fixture(scope="module")
def collection() -> SyntheticCollection:
    return build_collection()


@pytest.fixture(scope="module")
def formal() -> SyntheticCollection:
    return build_collection(set_id="policy-v1-test", mode="formal", traced=True)


@pytest.fixture
def score(monkeypatch: pytest.MonkeyPatch) -> Callable[[list[str]], int]:
    from scripts import score_policy_v1_report as module

    # A reanálise formal exige uma árvore limpa; o estado real do Git não conta aqui.
    monkeypatch.setattr(module, "git_state", lambda repository: FORMAL_GIT)
    return module.main


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


# --- 1. Identidade e receita do manifesto ------------------------------------------------


def _with_manifest(collection: SyntheticCollection, change: Callable[[dict], None]) -> Any:
    copied = copy.deepcopy(collection)
    change(copied.manifest)
    return copied


@pytest.mark.parametrize("formal_mode", [True, False], ids=["formal", "development"])
def test_a_manifest_from_another_recipe_is_refused(
    formal: SyntheticCollection,
    collection: SyntheticCollection,
    score: Callable[[list[str]], int],
    tmp_path: Path,
    formal_mode: bool,
) -> None:
    source = formal if formal_mode else collection
    paths = _with_manifest(source, lambda m: m.update(recipe_version="outra_receita")).write(
        tmp_path
    )
    output = tmp_path / "analysis.json"

    assert score(score_argv(paths, output, inventory=True, formal=formal_mode)) == 5
    assert not output.exists()


def test_a_manifest_other_than_the_one_the_collection_read_is_refused(
    formal: SyntheticCollection, score: Callable[[list[str]], int], tmp_path: Path
) -> None:
    # Os oito digests continuam a coincidir; só o manifesto deixou de ser o lido.
    paths = _with_manifest(formal, lambda m: m.update(python_version="0.0.0")).write(tmp_path)
    output = tmp_path / "analysis.json"

    assert score(score_argv(paths, output, inventory=True, formal=True)) == 5
    assert not output.exists()


def test_the_manifest_contract_refuses_unknown_fields(
    collection: SyntheticCollection, score: Callable[[list[str]], int], tmp_path: Path
) -> None:
    paths = _with_manifest(collection, lambda m: m.update(signed_by="ninguém")).write(tmp_path)

    assert score(score_argv(paths, tmp_path / "analysis.json")) == 3


def test_a_reformatted_manifest_with_the_same_content_is_accepted(
    formal: SyntheticCollection, score: Callable[[list[str]], int], tmp_path: Path
) -> None:
    paths = formal.write(tmp_path)
    paths["freeze-manifest"].write_text(json.dumps(formal.manifest, indent=4), encoding="utf-8")

    assert score(score_argv(paths, tmp_path / "a.json", inventory=True, formal=True)) == 0
    analysis = _read(tmp_path / "a.json")
    assert analysis["verification"]["checks"]["freeze_manifest_vs_collection"] == (
        "verified_by_content"
    )
    assert analysis["inputs"]["freeze_manifest"]["recipe_version"] == (
        formal.manifest["recipe_version"]
    )


def test_the_identical_manifest_is_verified_by_digest(
    formal: SyntheticCollection, score: Callable[[list[str]], int], tmp_path: Path
) -> None:
    paths = formal.write(tmp_path)

    assert score(score_argv(paths, tmp_path / "a.json", inventory=True, formal=True)) == 0
    checks = _read(tmp_path / "a.json")["verification"]["checks"]
    assert checks["freeze_manifest_vs_collection"] == "verified_by_digest"
    assert checks["freeze_manifest_contract"] == "verified"


def test_a_collection_without_its_manifest_is_never_formal(
    formal: SyntheticCollection, score: Callable[[list[str]], int], tmp_path: Path
) -> None:
    report = copy.deepcopy(formal.report)
    report["inputs"]["freeze_manifest"] = None
    paths = formal.write(tmp_path, report=report)

    assert score(score_argv(paths, tmp_path / "a.json", inventory=True, formal=True)) == 6
    assert not (tmp_path / "a.json").exists()


def test_the_collection_and_the_oracle_refuse_another_recipe(
    collection: SyntheticCollection,
) -> None:
    adjudication = LabelSet.model_validate(collection.adjudication)
    other = {**collection.manifest, "recipe_version": "outra_receita"}

    assert verified_adjudication(adjudication, collection.manifest) is adjudication
    with pytest.raises(FreezeError, match="recipe"):
        verified_adjudication(adjudication, other)


# --- 1b. Adjudicação do mesmo conjunto de casos (terceira revisão de 2026-10-27) ---------


@pytest.mark.parametrize("formal_mode", [True, False], ids=["formal", "development"])
def test_an_adjudication_of_another_case_set_is_refused(
    score: Callable[[list[str]], int],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    formal_mode: bool,
) -> None:
    # Mesmos case_id e digests coerentes com o congelamento e com a recolha: só o
    # set_id da adjudicação difere do dos casos e do relatório.
    mismatched = build_collection(
        set_id="policy-v1-test" if formal_mode else "policy-v1-dev",
        mode="formal" if formal_mode else "development_trial",
        traced=True,
        adjudication_set_id="another-case-set",
    )
    paths = mismatched.write(tmp_path)
    output = tmp_path / "analysis.json"

    assert score(score_argv(paths, output, inventory=True, formal=formal_mode)) == 5
    assert not output.exists()
    assert "another case set" in capsys.readouterr().err


def test_the_matching_case_set_is_recorded(
    formal: SyntheticCollection, score: Callable[[list[str]], int], tmp_path: Path
) -> None:
    paths = formal.write(tmp_path)

    assert score(score_argv(paths, tmp_path / "a.json", inventory=True, formal=True)) == 0
    assert _read(tmp_path / "a.json")["verification"]["checks"]["adjudication_set_vs_cases"] == (
        "same"
    )


def _other_set_inputs(tmp_path: Path) -> dict[str, Path]:
    from tests.test_policy_v1_evaluation import _case, _label_set
    from tests.test_policy_v1_evaluation_audit import CASES

    adjudication = _label_set("ADJ", [_case("C1")], role="adjudication").model_copy(
        update={"set_id": "another-case-set"}
    )
    paths = {"cases": tmp_path / "cases.json", "adjudication": tmp_path / "adjudication.json"}
    paths["cases"].write_text(json.dumps(CASES), encoding="utf-8")
    paths["adjudication"].write_text(adjudication.model_dump_json(), encoding="utf-8")
    return paths


def test_the_collection_refuses_another_case_set_before_any_model_call(
    tmp_path: Path, policy_v1_executor: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from scripts import run_policy_v1_evaluation as module

    main, calls = policy_v1_executor

    def no_database() -> None:
        raise AssertionError("the collection opened the database")

    monkeypatch.setattr(module, "SessionLocal", no_database)
    paths = _other_set_inputs(tmp_path)
    report = tmp_path / "report.json"
    argv = ["--cases", str(paths["cases"]), "--adjudication", str(paths["adjudication"])]

    assert main([*argv, "--commit", "a" * 40, "--output", str(report)]) == module.EXIT_INVALID
    assert calls == []
    assert not report.exists()


def test_the_oracle_tool_refuses_another_case_set(tmp_path: Path) -> None:
    from scripts.p2_labels_tool import EXIT_NOT_COMPARABLE
    from scripts.p2_labels_tool import main as labels_tool
    from tests.test_policy_v1_evaluation import CATALOG

    paths = _other_set_inputs(tmp_path)
    (tmp_path / "manifest.json").write_text("{}", encoding="utf-8")
    (tmp_path / "catalog.json").write_text(json.dumps(CATALOG), encoding="utf-8")
    argv = [
        "oracle",
        "--adjudication",
        str(paths["adjudication"]),
        "--cases",
        str(paths["cases"]),
        "--freeze-manifest",
        str(tmp_path / "manifest.json"),
        "--catalog",
        str(tmp_path / "catalog.json"),
    ]

    assert labels_tool(argv) == EXIT_NOT_COMPARABLE


# --- 2. Sem configuração operacional ------------------------------------------------------


def test_the_offline_commands_run_without_application_configuration(
    collection: SyntheticCollection, tmp_path: Path
) -> None:
    paths = collection.write(tmp_path)

    # ``app.core.config`` bloqueado e DATABASE_URL, JWT_SECRET_KEY e chaves fora do
    # ambiente: nem o exportador nem a reanálise precisam deles.
    exported = run_offline(
        ["--report", str(paths["report"]), "--output-dir", str(tmp_path / "review")],
        module="scripts.export_policy_v1_message_review",
    )
    scored = run_offline(score_argv(paths, tmp_path / "analysis.json"))

    assert exported.returncode == 0, exported.stderr
    assert scored.returncode == 0, scored.stderr
    assert "LOADED:\n" in exported.stderr and "LOADED:\n" in scored.stderr
    assert _read(tmp_path / "analysis.json")["collection_metrics_reproduction"]["status"] == (
        "identical"
    )


def test_the_retrieval_contracts_load_without_the_lexical_implementation() -> None:
    import importlib
    import subprocess

    probe = (
        "import sys\n"
        "sys.modules['app.core.config'] = None\n"
        "import app.retrieval.base\n"
        "assert 'app.retrieval.lexical' not in sys.modules\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    # Os nomes públicos do pacote continuam disponíveis.
    retrieval = importlib.import_module("app.retrieval")
    from app.retrieval.dependencies import get_retriever
    from app.retrieval.lexical import PostgresLexicalRetriever

    assert retrieval.get_retriever is get_retriever
    assert retrieval.PostgresLexicalRetriever is PostgresLexicalRetriever
    with pytest.raises(AttributeError):
        _ = retrieval.not_a_name


# --- 3. Estimativas validadas por condição -------------------------------------------------


def _outcome(report: dict[str, Any], case_id: str, condition: str, run: int = 1) -> dict:
    return next(
        o
        for o in report["outcomes"]
        if (o["case_id"], o["condition"], o["run_number"]) == (case_id, condition, run)
    )


def _scope_maybe(report: dict[str, Any]) -> None:
    _outcome(report, "DEV-01", "A-sem-diagnóstico")["estimates"]["scope"]["value"] = "maybe"


ESTIMATE_MUTATIONS: dict[str, Callable[[dict[str, Any]], None]] = {
    "p-e2e-empty": lambda r: _outcome(r, "DEV-01", "P-e2e").update(estimates={}),
    "p-e2e-missing": lambda r: _outcome(r, "DEV-01", "P-e2e").update(estimates=None),
    "p-e2e-extra-key": lambda r: _outcome(r, "DEV-01", "P-e2e")["estimates"].update(extra=1),
    "a-sem-diagnostico-invalid-scope": _scope_maybe,
    "b0-with-estimates": lambda r: _outcome(r, "DEV-01", "B0").update(estimates={"x": 1}),
    "oracle-with-estimates": lambda r: _outcome(r, "DEV-01", "P-oráculo").update(
        estimates={"x": 1}
    ),
    "failure-with-estimates": lambda r: _outcome(r, "DEV-02", "P-e2e").update(
        estimates=copy.deepcopy(_outcome(r, "DEV-01", "P-e2e")["estimates"])
    ),
}


@pytest.mark.parametrize("mutation", sorted(ESTIMATE_MUTATIONS))
def test_malformed_estimates_are_refused_before_any_metric(
    collection: SyntheticCollection,
    score: Callable[[list[str]], int],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    mutation: str,
) -> None:
    report = copy.deepcopy(collection.report)
    ESTIMATE_MUTATIONS[mutation](report)
    paths = collection.write(tmp_path, report=report)
    output = tmp_path / "analysis.json"

    assert score(score_argv(paths, output)) == 3
    assert not output.exists()
    assert "invalid collection report" in capsys.readouterr().err


def test_free_form_b1_dimensions_are_not_policy_inputs(
    collection: SyntheticCollection, score: Callable[[list[str]], int], tmp_path: Path
) -> None:
    report = copy.deepcopy(collection.report)
    _outcome(report, "DEV-01", "B1-plena").update(estimates={"d1": "in_scope"})
    paths = collection.write(tmp_path, report=report)

    # O B1 arquiva as dimensões do modelo em forma livre; não entram em M8/M9.
    assert score(score_argv(paths, tmp_path / "analysis.json")) == 0


# --- 3b. Tipos estritos nas entradas da política (segunda revisão de 2026-10-27) ----------


def _estimates(report: dict[str, Any], case_id: str, condition: str, run: int = 1) -> dict:
    estimates: dict[str, Any] = _outcome(report, case_id, condition, run)["estimates"]
    return estimates


def _set_conflict(report: dict[str, Any], value: Any) -> None:
    _estimates(report, "DEV-01", "P-e2e")["conflict"]["conflicts"] = [
        {"item_id": "I1", "evidence_ids": ["E1", "E2"], "resolvable": value}
    ]


#: Cada campo e onde vive nas fixtures sintéticas. DEV-02, na execução 2, tem
#: suporte parcial — o único caso com ``partial_misleading`` aplicável.
TYPED_FIELDS: dict[str, Callable[[dict[str, Any], Any], None]] = {
    "supported": lambda r, v: _estimates(r, "DEV-01", "P-e2e")["support"]["items"][0].update(
        supported=v
    ),
    "supported-a-sem-diagnostico": lambda r, v: _estimates(r, "DEV-01", "A-sem-diagnóstico")[
        "support"
    ]["items"][0].update(supported=v),
    "ambiguity_material": lambda r, v: _estimates(r, "DEV-01", "P-e2e")["specificity"].update(
        ambiguity_material=v
    ),
    "user_can_distinguish": lambda r, v: _estimates(r, "DEV-01", "P-e2e")["specificity"].update(
        user_can_distinguish=v
    ),
    "partial_misleading": lambda r, v: _estimates(r, "DEV-02", "P-e2e", run=2)["support"].update(
        partial_misleading=v
    ),
    "resolvable": _set_conflict,
}
FIELD_NAMES = {"supported-a-sem-diagnostico": "supported"}


@pytest.mark.parametrize("value", ["false", "true", 0, 1], ids=["false", "true", "zero", "one"])
@pytest.mark.parametrize("field", sorted(TYPED_FIELDS))
def test_policy_input_booleans_must_be_json_booleans(
    formal: SyntheticCollection,
    score: Callable[[list[str]], int],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    field: str,
    value: Any,
) -> None:
    report = copy.deepcopy(formal.report)
    TYPED_FIELDS[field](report, value)
    paths = formal.write(tmp_path, report=report)
    output = tmp_path / "analysis.json"

    assert score(score_argv(paths, output, inventory=True, formal=True)) == 3
    assert not output.exists()
    error = capsys.readouterr().err
    assert "invalid policy inputs" in error
    assert FIELD_NAMES.get(field, field) in error


def _first_item(report: dict[str, Any]) -> dict[str, Any]:
    item: dict[str, Any] = _estimates(report, "DEV-01", "P-e2e")["support"]["items"][0]
    return item


#: Campos não booleanos, com o nome que o erro tem de indicar.
OTHER_TYPED_FIELDS: dict[str, tuple[Callable[[dict[str, Any]], None], str]] = {
    "catalog-version-as-text": (
        lambda r: _estimates(r, "DEV-01", "P-e2e")["destination"].update(catalog_version="1"),
        "catalog_version",
    ),
    "scope-as-number": (
        lambda r: _estimates(r, "DEV-01", "P-e2e")["scope"].update(value=1),
        "scope",
    ),
    "evidence-ids-as-text": (
        lambda r: _first_item(r).update(evidence_ids="E1"),
        "evidence_ids",
    ),
}


@pytest.mark.parametrize("case", sorted(OTHER_TYPED_FIELDS))
def test_other_policy_input_fields_are_strictly_typed(
    collection: SyntheticCollection,
    score: Callable[[list[str]], int],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    case: str,
) -> None:
    change, name = OTHER_TYPED_FIELDS[case]
    report = copy.deepcopy(collection.report)
    change(report)
    paths = collection.write(tmp_path, report=report)

    assert score(score_argv(paths, tmp_path / "analysis.json")) == 3
    assert name in capsys.readouterr().err


def test_genuine_policy_inputs_pass_the_strict_contract(collection: SyntheticCollection) -> None:
    from app.evaluation.policy_v1.report import ArchivedPolicyInput

    validated = [
        ArchivedPolicyInput.model_validate(outcome["estimates"])
        for outcome in collection.report["outcomes"]
        if outcome["condition"] in {"P-e2e", "A-sem-diagnóstico"} and outcome["failure"] is None
    ]
    assert validated
    supports = [item.support for item in validated if item.support is not None]
    assert supports and all(isinstance(entry.items[0].supported, bool) for entry in supports)


# --- 4. M7 só medida com juízos aplicáveis ------------------------------------------------


def _ratings(
    collection: SyntheticCollection, tmp_path: Path, keep: Callable[[dict[str, Any]], bool]
) -> tuple[dict[str, Path], Path]:
    paths = collection.write(tmp_path)
    review = tmp_path / "review"
    assert export_review(["--report", str(paths["report"]), "--output-dir", str(review)]) == 0
    filled = fill_draft(_read(review / "ratings-draft.json"))
    filled["ratings"] = [item for item in filled["ratings"] if keep(item)]
    ratings = tmp_path / "ratings.json"
    ratings.write_text(json.dumps(filled, ensure_ascii=False), encoding="utf-8")
    return paths, ratings


def test_an_empty_rating_set_leaves_m7_not_measured(
    collection: SyntheticCollection, score: Callable[[list[str]], int], tmp_path: Path
) -> None:
    paths, ratings = _ratings(collection, tmp_path, lambda item: False)

    assert score(score_argv(paths, tmp_path / "analysis.json", ratings=ratings)) == 0
    analysis = _read(tmp_path / "analysis.json")
    metrics = analysis["metrics"]
    conditions = ("B0", "P-e2e", "A-sem-diagnóstico", "B1-plena", "B1-composição")
    for condition in conditions:
        quality = metrics[condition]["message_quality"]
        assert quality["status"] == "not_measured", condition
        assert "denominator" not in quality
    for stratum in metrics["by_stratum"].values():
        for condition in conditions:
            assert stratum[condition]["message_quality"]["status"] == "not_measured"
    paired = [c for c in metrics["paired_comparisons"] if c["measure"] == "message_acceptable"]
    assert paired and all(c["status"] == "not_measured" for c in paired)
    assert analysis["message_ratings"]["status"] == "no_judgments"


def test_m7_is_measured_only_where_human_ratings_apply(
    collection: SyntheticCollection, score: Callable[[list[str]], int], tmp_path: Path
) -> None:
    # Juízos técnicos só para P-e2e nas fontes reais (DEV-01, DEV-03, DEV-04).
    paths, ratings = _ratings(
        collection,
        tmp_path,
        lambda item: item["condition"] == "P-e2e" and item["case_id"] in {"DEV-01", "DEV-03"},
    )

    assert score(score_argv(paths, tmp_path / "analysis.json", ratings=ratings)) == 0
    metrics = _read(tmp_path / "analysis.json")["metrics"]
    p_e2e = metrics["P-e2e"]["message_quality"]
    assert (p_e2e["status"], p_e2e["numerator"], p_e2e["denominator"]) == ("measured", 2, 2)
    assert p_e2e["unrated"] == 1
    # Outra condição, e o estrato F14, ficam sem juízos: não medidos, nunca 0/0.
    b0 = metrics["B0"]["message_quality"]
    assert (b0["status"], b0["unrated"]) == ("not_measured", 3)
    f14 = metrics["by_stratum"]["F14_synthetic"]["P-e2e"]["message_quality"]
    assert f14["status"] == "not_measured"
    # Sem juízos em A-sem-diagnóstico, a comparação emparelhada não é medida.
    paired = next(
        c for c in metrics["paired_comparisons"] if c["measure"] == "message_acceptable"
    )
    assert paired["status"] == "not_measured"
