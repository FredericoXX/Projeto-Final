"""Recolha pelo executor real e reanálise offline das mesmas respostas.

A recolha corre sobre a base de testes, com doubles determinísticos do
estimador, do gerador e do modelo B1. A reanálise corre num processo sem driver
de base de dados, sem SDK de fornecedores e sem rede. Fixtures técnicas e
sintéticas; nada aqui é anotação humana ou resultado da tese.
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.evaluation.policy_v1.conditions import BaselineResponse
from app.evaluation.policy_v1.freeze import sha256
from tests.decision_support import (
    DEFAULT_CATALOG,
    RecordingGenerator,
    ScriptedEstimator,
    analysis,
    support_by_title,
)
from tests.policy_v1_offline_support import run_offline
from tests.test_policy_v1_audit_round2 import _executor_inputs
from tests.test_policy_v1_evaluation import _Baseline
from tests.test_policy_v1_evaluation_audit import COMMIT


def test_a_collection_is_rescored_offline_with_the_same_metrics(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.evaluation.policy_v1 import baseline_openai
    from scripts import run_policy_v1_evaluation as module

    argv = _executor_inputs(
        client, test_session_factory, tmp_path, frozen_catalog={"version": 1, **DEFAULT_CATALOG}
    )
    estimator = ScriptedEstimator(
        result=analysis(), assess_with=support_by_title({"I1": "regulation"})
    )
    baseline = _Baseline(BaselineResponse("answer", "Resposta sintética do B1.", ("E1",), None))
    monkeypatch.setattr(module, "SessionLocal", test_session_factory)
    monkeypatch.setattr(module, "git_state", lambda repository: (COMMIT, True))
    monkeypatch.setattr(module, "get_dimension_estimator", lambda: estimator)
    monkeypatch.setattr(module, "get_answer_generator", RecordingGenerator)
    monkeypatch.setattr(baseline_openai, "OpenAIBaselineModel", lambda: baseline)

    assert module.main(argv) == 0

    report_path = tmp_path / "report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    manifest = json.loads((tmp_path / "freeze-manifest.json").read_text(encoding="utf-8"))
    assert report["report_schema_version"] == "policy_v1_report_2"
    assert report["git"] == {"head": COMMIT, "working_tree_clean": True}
    assert report["metrics"]["P-e2e"]["message_quality"]["status"] == "not_measured"
    # As entradas da recolha ficam identificadas, incluindo o inventário lido da base.
    inputs = report["inputs"]
    frozen = {name: entry["sha256"] for name, entry in manifest["artifacts"].items()}
    assert inputs["corpus_inventory"]["frozen_sha256"] == frozen["manifest"]
    assert inputs["catalog"]["frozen_sha256"] == frozen["catalog"]
    assert inputs["adjudication"]["frozen_sha256"] == frozen["labels"]
    assert inputs["cases"]["file_sha256"] == sha256((tmp_path / "cases.json").read_bytes())
    original = report_path.read_bytes()

    completed = run_offline(
        [
            "--report",
            str(report_path),
            "--cases",
            str(tmp_path / "cases.json"),
            "--adjudication",
            str(tmp_path / "adjudication.json"),
            "--freeze-manifest",
            str(tmp_path / "freeze-manifest.json"),
            "--output",
            str(tmp_path / "analysis.json"),
        ]
    )

    assert completed.returncode == 0, completed.stderr
    assert "LOADED:\n" in completed.stderr
    result = json.loads((tmp_path / "analysis.json").read_text(encoding="utf-8"))
    assert result["collection_metrics_reproduction"]["status"] == "identical"
    assert result["metrics"] == report["metrics"]
    assert result["verification"]["level"] == "full"
    assert result["source_report"]["collection_id"] == report["collection_id"]
    # O relatório de origem fica intacto.
    assert report_path.read_bytes() == original
