"""Testes da baseline do Momento 5 (Fase 3).

A Fase 3 não avalia: compõe. Estes testes verificam a composição, as
declarações exigidas por D9 e D11, e o artefacto versionado — nunca
recalculam métricas.

Sem base de dados, storage, rede ou fornecedor: as fixtures autouse do
conftest que preparam a base de dados são anuladas neste módulo.
"""

import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from app.evaluation import baseline as baseline_module
from app.evaluation.assets import load_rubric
from app.evaluation.baseline import (
    BASELINE_SCHEMA_VERSION,
    EXPECTED_METRIC_FAILURES,
    UNEXPLAINED,
    PopulationStatus,
    build_baseline,
    build_findings,
    classify_metric_failures,
)
from app.evaluation.results import EvaluationReport, compute_result_digest
from scripts import build_moment05_baseline as build_module
from scripts.build_moment05_baseline import (
    EXIT_NOT_REPRODUCIBLE,
    EXIT_OK,
    EXIT_OUTPUT_EXISTS,
    EXIT_USAGE,
    main,
)
from scripts.evaluate_answering_offline import main as evaluate_offline

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = BACKEND_DIR.parent
BASELINE_JSON = REPOSITORY_ROOT / "docs" / "relatorios" / "moment-05-baseline-p1.json"
VALID_SHA = "0123456789abcdef0123456789abcdef01234567"

UUID_PATTERN = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
WINDOWS_PATH_PATTERN = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/]")
UNIX_PATH_PATTERN = re.compile(r"(?<![A-Za-z0-9])/(?:home|root|Users|var|etc|tmp)/")


# --- Anulação das fixtures de base de dados do conftest ------------------------


@pytest.fixture(scope="session", autouse=True)
def _override_get_db() -> None:
    """Anula a fixture homónima do conftest: aqui não há dependência de DB."""


@pytest.fixture(autouse=True)
def _clean_tables() -> None:
    """Anula a fixture homónima do conftest: aqui não há tabelas a truncar."""


@pytest.fixture(autouse=True)
def _restore_provider_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("OPENAI_API_KEY", "OPENAI_MODEL", "ANSWER_GENERATOR_PROVIDER"):
        monkeypatch.setenv(name, os.environ.get(name, ""))


def _phase2_report(directory: Path, name: str) -> EvaluationReport:
    """Um relatório produzido pelo entrypoint real da Fase 2."""
    output = directory / name
    assert (
        evaluate_offline(
            ["--output", str(output), "--commit-sha", VALID_SHA],
            repository_root=REPOSITORY_ROOT,
            clock=lambda: datetime(2026, 8, 8, 3, 0, 0, tzinfo=UTC),
        )
        == EXIT_OK
    )
    return EvaluationReport.model_validate(json.loads(output.read_text(encoding="utf-8")))


@pytest.fixture(scope="module")
def baseline(tmp_path_factory: pytest.TempPathFactory) -> Any:
    directory = tmp_path_factory.mktemp("phase2-reports")
    return build_baseline(
        _phase2_report(directory, "first.json"),
        _phase2_report(directory, "second.json"),
        output_path="docs/relatorios/moment-05-baseline-p1.json",
    )


METRIC_IDS = ("A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8")


def _case_payload(
    case_id: str,
    *,
    expected_outcome: str,
    failing: tuple[str, ...],
    a7: str = "pass",
) -> dict[str, Any]:
    metrics: dict[str, Any] = {metric: {"status": "pass"} for metric in METRIC_IDS}
    metrics["A7"] = {"status": a7}
    for metric in failing:
        metrics[metric] = {"status": "fail"}
    return {
        "case_id": case_id,
        "expected_outcome": expected_outcome,
        "observed_outcome": expected_outcome if a7 == "pass" else "rejected",
        "metrics": metrics,
    }


def _results_payload(
    cases: list[dict[str, Any]], *, corpus_version: str = "1.0.0"
) -> dict[str, Any]:
    return {"corpus_version": corpus_version, "cases": cases}


@pytest.fixture(scope="module")
def versioned_payload() -> dict[str, Any]:
    payload: dict[str, Any] = json.loads(BASELINE_JSON.read_text(encoding="utf-8"))
    return payload


# --- Populações e métricas não medidas -----------------------------------------


def test_all_three_populations_are_declared(baseline: Any) -> None:
    statuses = {item.population: item.status for item in baseline.populations}
    assert statuses == {
        "P1": PopulationStatus.MEASURED,
        "P2": PopulationStatus.NOT_MEASURED,
        "P3": PopulationStatus.NOT_MEASURED,
    }


def test_measured_population_declares_its_answer_provenance(baseline: Any) -> None:
    p1 = next(item for item in baseline.populations if item.population == "P1")
    assert p1.answer_provenance is not None
    assert "gerador falso" in p1.answer_provenance
    assert p1.automatic_metrics == ["A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "R1"]


def test_unmeasured_populations_have_no_provenance_and_no_metrics(baseline: Any) -> None:
    for name in ("P2", "P3"):
        population = next(item for item in baseline.populations if item.population == name)
        assert population.answer_provenance is None
        assert population.automatic_metrics == []


def test_every_human_metric_is_declared_not_measured(baseline: Any) -> None:
    rubric = load_rubric()
    assert [item.criterion_id for item in baseline.human_metrics] == [
        criterion.criterion_id for criterion in rubric.criteria
    ]
    assert all(
        item.status is PopulationStatus.NOT_MEASURED for item in baseline.human_metrics
    )
    assert all(item.required_population == "P2" for item in baseline.human_metrics)


def test_hybrid_criteria_record_the_automatic_part_that_was_measured(baseline: Any) -> None:
    hybrid = [item for item in baseline.human_metrics if item.assessment == "hybrid"]
    assert {item.criterion_id for item in hybrid} == {
        "citation_support",
        "citation_coverage",
        "fallback_comprehensibility",
    }
    assert all(item.automatic_part_measured for item in hybrid)
    human = [item for item in baseline.human_metrics if item.assessment == "human"]
    assert all(item.automatic_part_measured is None for item in human)


# --- R1 -------------------------------------------------------------------------


def test_reproducibility_is_confirmed_across_two_runs(baseline: Any) -> None:
    reproducibility = baseline.reproducibility
    assert reproducibility.metric == "R1"
    assert reproducibility.runs == 2
    assert reproducibility.results_identical is True
    assert reproducibility.digest_identical is True
    assert reproducibility.result_digest == baseline.report.result_digest


def test_embedded_report_digest_matches_its_results(baseline: Any) -> None:
    payload = baseline.report.results.model_dump(mode="json")
    assert baseline.report.result_digest == compute_result_digest(payload)


def test_baseline_cannot_produce_its_own_digest(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A Fase 3 preserva o digest da Fase 2; não tem caminho para o criar.

    O módulo não importa `compute_result_digest`; injetar uma sentinela no
    seu espaço de nomes não a torna alcançável, e a composição continua a
    funcionar — prova de que o digest não nasce aqui.
    """
    assert not hasattr(baseline_module, "compute_result_digest")

    def _sentinel(*args: Any, **kwargs: Any) -> str:
        msg = "a Fase 3 recalculou o digest"
        raise AssertionError(msg)

    monkeypatch.setattr(baseline_module, "compute_result_digest", _sentinel, raising=False)
    first = _phase2_report(tmp_path, "first.json")
    second = _phase2_report(tmp_path, "second.json")
    produced = build_baseline(first, second, output_path="relatorio.json")
    assert produced.report.result_digest == second.result_digest


def test_baseline_preserves_the_phase_two_report_verbatim(
    baseline: Any, tmp_path: Path
) -> None:
    """Só `output_path` difere — metadado volátil, fora do digest."""
    source = _phase2_report(tmp_path, "source.json")
    assert baseline.report.results.model_dump(mode="json") == source.results.model_dump(
        mode="json"
    )
    assert baseline.report.result_digest == source.result_digest
    assert baseline.report.execution_metadata.commit_sha == source.execution_metadata.commit_sha
    assert baseline.report.execution_metadata.executed_at == (
        source.execution_metadata.executed_at
    )
    assert baseline.report.execution_metadata.output_path != (
        source.execution_metadata.output_path
    )


# --- Classificação dos resultados ------------------------------------------------


def test_no_behavioural_defect_on_the_approved_corpus(baseline: Any) -> None:
    assert baseline.findings.behavioural_defects == []
    assert baseline.findings.layers_with_defects == []
    assert baseline.findings.behavioural_corrections_applied is False


def test_every_failing_cell_is_classified(baseline: Any) -> None:
    failures = baseline.findings.metric_failures
    assert {(item.case_id, item.metric) for item in failures} == {
        ("C012", "A3"),
        ("C013", "A3"),
        ("C015", "A5"),
        ("C016", "A5"),
        ("C017", "A3"),
        ("C017", "A5"),
        ("C018", "A4"),
        ("C019", "A2"),
    }
    assert all(item.outcome_matches_expectation for item in failures)
    assert not [item for item in failures if item.classification == "unexplained"]


def test_the_eight_cells_match_the_approved_matrix_exactly(baseline: Any) -> None:
    observed = {
        (item.case_id, item.metric): item.classification
        for item in baseline.findings.metric_failures
    }
    assert observed == dict(EXPECTED_METRIC_FAILURES)


def test_no_cell_in_the_current_baseline_is_unexplained(baseline: Any) -> None:
    assert [
        item for item in baseline.findings.metric_failures if item.classification == UNEXPLAINED
    ] == []


# --- Classificação fail-closed -----------------------------------------------------


def test_unexpected_a6_failure_in_a_rejected_case_is_unexplained() -> None:
    """Regressão: uma regra por desfecho esconderia esta falha nova."""
    payload = _results_payload(
        [_case_payload("C015", expected_outcome="rejected", failing=("A5", "A6"))]
    )
    classifications = {
        (item.metric): item.classification for item in classify_metric_failures(payload)
    }
    assert classifications["A5"] == "expected_rejection"
    assert classifications["A6"] == UNEXPLAINED
    assert build_findings(payload).behavioural_defects == ["C015"]


def test_unexpected_a3_failure_in_an_answered_case_is_unexplained() -> None:
    """C001 não consta da matriz: um A3 falhado ali é defeito."""
    payload = _results_payload(
        [_case_payload("C001", expected_outcome="answered", failing=("A3",))]
    )
    failures = classify_metric_failures(payload)
    assert [item.classification for item in failures] == [UNEXPLAINED]
    assert build_findings(payload).behavioural_defects == ["C001"]


def test_a_ninth_failing_cell_is_unexplained() -> None:
    """A célula aprovada mantém-se; a nova não é absorvida por ela."""
    payload = _results_payload(
        [_case_payload("C012", expected_outcome="answered", failing=("A3", "A6"))]
    )
    classifications = {
        (item.metric): item.classification for item in classify_metric_failures(payload)
    }
    assert classifications["A3"] == "declared_source_divergence"
    assert classifications["A6"] == UNEXPLAINED
    assert build_findings(payload).behavioural_defects == ["C012"]


def test_a_wrong_outcome_makes_every_cell_of_that_case_unexplained() -> None:
    """Mesmo uma célula da matriz deixa de valer se o desfecho divergiu."""
    payload = _results_payload(
        [_case_payload("C015", expected_outcome="rejected", failing=("A5",), a7="fail")]
    )
    failures = classify_metric_failures(payload)
    assert {item.classification for item in failures} == {UNEXPLAINED}
    findings = build_findings(payload)
    assert findings.behavioural_defects == ["C015"]
    assert findings.layers_with_defects == ["answering"]


def test_another_corpus_version_invalidates_the_matrix() -> None:
    """Fail-closed: a matriz só vale para o corpus a que corresponde."""
    payload = _results_payload(
        [_case_payload("C015", expected_outcome="rejected", failing=("A5",))],
        corpus_version="2.0.0",
    )
    assert [item.classification for item in classify_metric_failures(payload)] == [UNEXPLAINED]


# --- Artefacto versionado ---------------------------------------------------------


def test_versioned_baseline_is_valid_and_complete(versioned_payload: dict[str, Any]) -> None:
    assert versioned_payload["baseline_schema_version"] == BASELINE_SCHEMA_VERSION
    assert versioned_payload["moment"] == "5"
    report = versioned_payload["report"]
    assert report["results"]["population"] == "P1"
    assert report["results"]["case_count"] == 19
    assert len(report["execution_metadata"]["commit_sha"]) == 40
    assert report["execution_metadata"]["executed_at"]
    assert report["result_digest"] == compute_result_digest(report["results"])


def test_versioned_baseline_reproduces_the_current_evaluation(
    versioned_payload: dict[str, Any], baseline: Any
) -> None:
    """O artefacto versionado é reproduzível a partir do repositório."""
    assert versioned_payload["report"]["results"] == baseline.report.results.model_dump(
        mode="json"
    )
    assert versioned_payload["report"]["result_digest"] == baseline.report.result_digest


def test_versioned_baseline_declares_p2_and_p3_not_measured(
    versioned_payload: dict[str, Any],
) -> None:
    statuses = {
        item["population"]: item["status"] for item in versioned_payload["populations"]
    }
    assert statuses == {"P1": "measured", "P2": "not_measured", "P3": "not_measured"}
    assert all(item["status"] == "not_measured" for item in versioned_payload["human_metrics"])


def test_versioned_baseline_carries_no_forbidden_data() -> None:
    raw = BASELINE_JSON.read_text(encoding="utf-8")
    assert not UUID_PATTERN.search(raw)
    assert not WINDOWS_PATH_PATTERN.search(raw)
    assert not UNIX_PATH_PATTERN.search(raw)


def test_the_json_baseline_is_the_only_versioned_artefact() -> None:
    """D9 torna o resumo Markdown opcional; não é produzido nem publicado."""
    assert not BASELINE_JSON.with_suffix(".md").exists()


# --- CLI ---------------------------------------------------------------------------


def test_cli_writes_only_the_json_baseline(tmp_path: Path) -> None:
    output = tmp_path / "baseline.json"
    exit_code = main(
        ["--output", str(output), "--commit-sha", VALID_SHA],
        repository_root=REPOSITORY_ROOT,
    )
    assert exit_code == EXIT_OK
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["moment"] == "5"
    assert [path.name for path in tmp_path.iterdir()] == ["baseline.json"]


def test_cli_refuses_to_overwrite_the_baseline(tmp_path: Path) -> None:
    output = tmp_path / "baseline.json"
    output.write_text("anterior", encoding="utf-8")
    assert (
        main(
            ["--output", str(output), "--commit-sha", VALID_SHA],
            repository_root=REPOSITORY_ROOT,
        )
        == EXIT_OUTPUT_EXISTS
    )
    assert output.read_text(encoding="utf-8") == "anterior"


def test_cli_overwrite_replaces_the_baseline(tmp_path: Path) -> None:
    output = tmp_path / "baseline.json"
    output.write_text("anterior", encoding="utf-8")
    exit_code = main(
        ["--output", str(output), "--commit-sha", VALID_SHA, "--overwrite"],
        repository_root=REPOSITORY_ROOT,
    )
    assert exit_code == EXIT_OK
    assert json.loads(output.read_text(encoding="utf-8"))["moment"] == "5"


def test_cli_refuses_protected_directories() -> None:
    target = REPOSITORY_ROOT / "storage" / "baseline.json"
    assert (
        main(
            ["--output", str(target), "--commit-sha", VALID_SHA],
            repository_root=REPOSITORY_ROOT,
        )
        == EXIT_USAGE
    )
    assert not target.exists()


def test_cli_output_records_a_repository_relative_path(tmp_path: Path) -> None:
    """Nunca um caminho absoluto de máquina num artefacto publicável."""
    output = tmp_path / "baseline.json"
    main(
        ["--output", str(output), "--commit-sha", VALID_SHA],
        repository_root=REPOSITORY_ROOT,
    )
    payload = json.loads(output.read_text(encoding="utf-8"))
    recorded = payload["report"]["execution_metadata"]["output_path"]
    assert not WINDOWS_PATH_PATTERN.search(recorded)
    assert recorded == "baseline.json"


# --- R1 bloqueia a publicação --------------------------------------------------


def _fake_phase_two(payloads: list[dict[str, Any]]) -> Any:
    """Substitui o entrypoint da Fase 2 por escritas controladas.

    Permite forçar divergência entre as duas execuções sem tocar no
    avaliador nem nos seus resultados.
    """
    calls = {"count": 0}

    def _fake(
        argv: list[str],
        *,
        repository_root: Path | None = None,
        clock: Any = None,
    ) -> int:
        destination = Path(argv[argv.index("--output") + 1])
        destination.write_text(
            json.dumps(payloads[calls["count"]], ensure_ascii=False), encoding="utf-8"
        )
        calls["count"] += 1
        return EXIT_OK

    return _fake


def _divergent_payloads(tmp_path: Path, *, differ: str) -> list[dict[str, Any]]:
    source = json.loads(
        (tmp_path / "source.json").read_text(encoding="utf-8")
        if (tmp_path / "source.json").exists()
        else "{}"
    )
    if not source:
        _phase2_report(tmp_path, "source.json")
        source = json.loads((tmp_path / "source.json").read_text(encoding="utf-8"))
    first = json.loads(json.dumps(source))
    second = json.loads(json.dumps(source))
    if differ == "results":
        # `results` diferente, digest deixado igual: isola results_identical.
        second["results"]["cases"][0]["metrics"]["A1"]["status"] = "fail"
    else:
        # `results` igual, digest diferente: isola digest_identical.
        second["result_digest"] = "0" * 64
    return [first, second]


@pytest.mark.parametrize("differ", ["results", "digest"])
def test_non_reproducible_runs_do_not_publish_a_baseline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, differ: str
) -> None:
    payloads = _divergent_payloads(tmp_path, differ=differ)
    monkeypatch.setattr(build_module, "evaluate_offline", _fake_phase_two(payloads))

    output = tmp_path / "baseline.json"
    exit_code = main(
        ["--output", str(output), "--commit-sha", VALID_SHA],
        repository_root=REPOSITORY_ROOT,
    )
    assert exit_code == EXIT_NOT_REPRODUCIBLE
    assert not output.exists()


@pytest.mark.parametrize("differ", ["results", "digest"])
def test_non_reproducible_runs_never_replace_an_existing_baseline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, differ: str
) -> None:
    payloads = _divergent_payloads(tmp_path, differ=differ)
    monkeypatch.setattr(build_module, "evaluate_offline", _fake_phase_two(payloads))

    output = tmp_path / "baseline.json"
    output.write_text("baseline anterior válida", encoding="utf-8")
    exit_code = main(
        ["--output", str(output), "--commit-sha", VALID_SHA, "--overwrite"],
        repository_root=REPOSITORY_ROOT,
    )
    assert exit_code == EXIT_NOT_REPRODUCIBLE
    assert output.read_text(encoding="utf-8") == "baseline anterior válida"
    assert sorted(path.name for path in tmp_path.iterdir() if path.suffix == ".json") == [
        "baseline.json",
        "source.json",
    ]


def test_identical_runs_still_publish(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """O caminho feliz mantém-se: duas execuções iguais publicam."""
    _phase2_report(tmp_path, "source.json")
    source = json.loads((tmp_path / "source.json").read_text(encoding="utf-8"))
    monkeypatch.setattr(build_module, "evaluate_offline", _fake_phase_two([source, source]))

    output = tmp_path / "baseline.json"
    assert (
        main(
            ["--output", str(output), "--commit-sha", VALID_SHA],
            repository_root=REPOSITORY_ROOT,
        )
        == EXIT_OK
    )
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["reproducibility"]["results_identical"] is True
    assert payload["reproducibility"]["digest_identical"] is True
    assert payload["report"]["result_digest"] == source["result_digest"]


def test_the_versioned_baseline_is_still_reproducible(
    versioned_payload: dict[str, Any], tmp_path: Path
) -> None:
    """A baseline oficial continua a reproduzir-se com o mesmo digest."""
    fresh = _phase2_report(tmp_path, "fresh.json")
    assert versioned_payload["report"]["results"] == fresh.results.model_dump(mode="json")
    assert versioned_payload["report"]["result_digest"] == fresh.result_digest
    assert versioned_payload["reproducibility"]["results_identical"] is True
    assert versioned_payload["reproducibility"]["digest_identical"] is True
