"""Segunda auditoria de 2026-10-22/23: catálogo D6 congelado e utilização do
gerador nas falhas.

Fixtures técnicas e sintéticas, como no resto dos testes da política.
"""

import json
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.answering.base import AnswerGenerationError, AnsweringContext, GeneratedAnswer
from app.evaluation.policy_v1.artifacts import (
    catalog_bytes,
    code_artifacts,
    corpus_bytes,
    verify_formal_freeze,
)
from app.evaluation.policy_v1.conditions import run_p_e2e
from app.evaluation.policy_v1.corpus_inventory import (
    collect_corpus_inventory,
    corpus_inventory_bytes,
)
from app.evaluation.policy_v1.freeze import (
    FreezeError,
    FrozenArtifact,
    build_freeze_manifest,
)
from app.evaluation.policy_v1.labels import label_set_bytes
from app.models.decision_record import DecisionRecord
from app.models.message import Message
from scripts.p2_labels_tool import main as labels_tool
from tests.decision_support import (
    ReachedCases,
    ScriptedEstimator,
    analysis,
    decide,
    make_world,
    support_by_title,
)
from tests.test_policy_v1_evaluation import CATALOG, LIMITS, REFERENCE, _case, _label_set, _packet
from tests.test_policy_v1_evaluation_audit import CASES, COMMIT, CORPUS_INVENTORY

ENROLMENT = "O prazo de matrícula termina a 30 de setembro."


class _FailingGenerator:
    """O fornecedor é chamado e falha."""

    def __init__(self) -> None:
        self.calls = 0

    def generate(self, context: AnsweringContext) -> GeneratedAnswer:
        self.calls += 1
        raise AnswerGenerationError("The answer generator failed to produce a usable response.")


class _InvalidGenerator:
    """O fornecedor responde, com tokens, mas a resposta não passa a validação."""

    def __init__(self) -> None:
        self.calls = 0

    def generate(self, context: AnsweringContext) -> GeneratedAnswer:
        self.calls += 1
        return GeneratedAnswer(
            answer="Resposta.",
            cited_evidence_ids=("E99",),
            usage={"input_tokens": 9, "output_tokens": 3},
        )


# --- Utilização do gerador nas falhas -------------------------------------------------


@pytest.mark.parametrize(
    ("generator_type", "tokens"),
    [(_FailingGenerator, (None, None)), (_InvalidGenerator, (9, 3))],
    ids=["provider-failure", "invalid-output"],
)
def test_operational_failure_after_the_generator_records_its_attempt(
    client: TestClient,
    policy_enabled,
    install,
    test_session_factory: sessionmaker[Session],
    generator_type: type,
    tokens: tuple[int | None, int | None],
) -> None:
    world = make_world(client)
    world.document(client, "Regulamento de matrículas", ENROLMENT)
    generator = generator_type()
    install(
        ScriptedEstimator(result=analysis(), assess_with=support_by_title({"I1": "matrículas"})),
        generator,
    )

    response = decide(client, world.conversation(client), world.student)

    assert response.status_code == 502
    assert generator.calls == 1
    with test_session_factory() as db:
        assert db.scalar(select(Message.id).limit(1)) is None
        record = db.scalars(select(DecisionRecord)).one()
    assert record.status == "technical_failure"
    assert record.record["usage"]["generator"] == {
        "attempts": 1,
        "input_tokens": tokens[0],
        "output_tokens": tokens[1],
        "cost": None,
    }
    assert record.record["usage"]["estimator"]["attempts"] >= 1


def test_operational_failure_before_the_generator_records_no_generator_attempt(
    client: TestClient,
    policy_enabled,
    install,
    test_session_factory: sessionmaker[Session],
) -> None:
    from app.decision.estimators.base import EstimationError

    world = make_world(client)
    install(
        ScriptedEstimator(result=analysis(), fail_with=EstimationError("timeout")),
        _FailingGenerator(),
    )

    assert decide(client, world.conversation(client), world.student).status_code == 502
    with test_session_factory() as db:
        record = db.scalars(select(DecisionRecord)).one()
    assert record.record["usage"]["generator"] is None


@pytest.mark.parametrize(
    ("generator_type", "tokens"),
    [(_FailingGenerator, (None, None)), (_InvalidGenerator, (9, 3))],
    ids=["provider-failure", "invalid-output"],
)
def test_p_e2e_failure_after_the_generator_records_its_attempt(
    generator_type: type, tokens: tuple[int | None, int | None]
) -> None:
    packet = _packet()
    estimator = ScriptedEstimator(
        result=analysis(), assess_with=support_by_title({"I1": "matrículas"})
    )

    outcome = run_p_e2e(packet, estimator.result, estimator, generator_type(), LIMITS).outcome

    assert outcome.action is None and outcome.failure is not None
    assert outcome.usage["generator"] == {
        "attempts": 1,
        "input_tokens": tokens[0],
        "output_tokens": tokens[1],
        "cost": None,
    }
    assert outcome.usage["estimator"]["attempts"] >= 1


# --- Catálogo D6 congelado --------------------------------------------------------------


def _manifest(catalog: dict[str, Any]) -> dict[str, Any]:
    adjudication = _label_set("ADJ", [_case("C1")], role="adjudication")
    files = {
        "corpus": corpus_bytes(CASES),
        "manifest": corpus_inventory_bytes(CORPUS_INVENTORY),
        "labels": label_set_bytes(adjudication),
        "catalog": catalog_bytes(catalog),
    }
    artifacts = [FrozenArtifact(name, "v1", data) for name, data in files.items()]
    return build_freeze_manifest([*artifacts, *code_artifacts()], code_commit=COMMIT)


def test_the_catalog_is_a_required_frozen_artifact() -> None:
    manifest = _manifest(CATALOG)
    assert manifest["complete"] is True
    assert "catalog" in manifest["artifacts"]
    without = build_freeze_manifest(
        [a for a in [FrozenArtifact("corpus", "v1", b"x")]], code_commit=COMMIT
    )
    assert "catalog" in without["missing_artifacts"]


def test_formal_verification_rejects_a_catalog_different_from_the_frozen_one() -> None:
    manifest = _manifest(CATALOG)
    adjudication = _label_set("ADJ", [_case("C1")], role="adjudication")
    common: dict[str, Any] = {
        "cases_payload": CASES,
        "corpus_inventory_payload": CORPUS_INVENTORY,
        "adjudication": adjudication,
        "commit": COMMIT,
        "head_commit": COMMIT,
        "working_tree_clean": True,
    }
    verify_formal_freeze(manifest, catalog_payload=CATALOG, **common)
    changed = {**CATALOG, "services": []}
    with pytest.raises(FreezeError, match="catalog"):
        verify_formal_freeze(manifest, catalog_payload=changed, **common)


def test_oracle_tool_rejects_a_catalog_different_from_the_frozen_one(tmp_path: Path) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(_manifest(CATALOG)), encoding="utf-8")
    adjudication = tmp_path / "adj.json"
    adjudication.write_text(
        _label_set("ADJ", [_case("C1")], role="adjudication").model_dump_json(), encoding="utf-8"
    )
    cases = tmp_path / "cases.json"
    cases.write_text(json.dumps(CASES), encoding="utf-8")

    def run(catalog: dict[str, Any]) -> int:
        catalog_path = tmp_path / "catalog.json"
        catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
        return labels_tool(
            [
                "oracle",
                "--adjudication",
                str(adjudication),
                "--freeze-manifest",
                str(manifest_path),
                "--catalog",
                str(catalog_path),
                "--cases",
                str(cases),
                "--output",
                str(tmp_path / "out.json"),
            ]
        )

    # Sem serviço competente, R04 passaria a R05: o catálogo muda a decisão.
    assert run({**CATALOG, "services": []}) == 5
    assert run(CATALOG) == 0


# --- Executor: o catálogo ativo na base de dados tem de ser o congelado ----------------


def _executor_inputs(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
    tmp_path: Path,
    *,
    frozen_catalog: dict[str, Any],
) -> list[str]:
    """Publica DEFAULT_CATALOG (versão 1) pela API e congela ``frozen_catalog``."""
    from app.evaluation.snapshot_builder import build_evaluation_snapshot
    from app.models.document_chunk import DocumentChunk
    from app.models.institution import Institution
    from tests.decision_support import DEFAULT_CATALOG

    world = make_world(client, catalog=DEFAULT_CATALOG)
    world.document(client, "Synthetic regulation", "O prazo de matrícula termina em setembro.")
    with test_session_factory() as db:
        code = db.get_one(Institution, world.institution_id).code
        # O manifesto congelado é o inventário da base no momento do
        # congelamento (revisão de 2026-10-23), já não um ficheiro declarado.
        inventory = corpus_inventory_bytes(
            collect_corpus_inventory(db, UUID(str(world.institution_id)))
        )
        chunk_id = str(db.scalar(select(DocumentChunk.id)))
        snapshot = build_evaluation_snapshot(
            db,
            institution_id=UUID(str(world.institution_id)),
            language="pt",
            reference_date=REFERENCE,
            requester_role="student",
            top_k=5,
            official_only=True,
        )
    metadata = {
        "family": "F01",
        "source_kind": "synthetic",
        "expected_snapshot_id": snapshot.snapshot_id,
    }
    cases = {
        **CASES,
        "institution_code": code,
        "cases": [{**case, **metadata} for case in CASES["cases"]],
    }
    adjudication = _label_set(
        "ADJ",
        [
            _case(
                "C1",
                trace={
                    "family": "F01",
                    "source_kind": "synthetic",
                    "snapshot_id": snapshot.snapshot_id,
                    "rationale": "Synthetic technical fixture; not a human scientific annotation.",
                    "items": [
                        {
                            "item_id": "I1",
                            "label": "deadline",
                            "supported": True,
                            "evidence_ids": [chunk_id],
                        }
                    ],
                },
            )
        ],
        role="adjudication",
    )
    files = {
        "corpus": corpus_bytes(cases),
        "manifest": inventory,
        "labels": label_set_bytes(adjudication),
        "catalog": catalog_bytes(frozen_catalog),
    }
    manifest = build_freeze_manifest(
        [*(FrozenArtifact(name, "v1", data) for name, data in files.items()), *code_artifacts()],
        code_commit=COMMIT,
    )
    paths = {
        "cases": json.dumps(cases),
        "adjudication": adjudication.model_dump_json(),
        "freeze-manifest": json.dumps(manifest),
    }
    argv = ["--commit", COMMIT, "--output", str(tmp_path / "report.json")]
    for option, content in paths.items():
        path = tmp_path / f"{option}.json"
        path.write_text(content, encoding="utf-8")
        argv += [f"--{option}", str(path)]
    return argv


@pytest.mark.parametrize("formal", [True, False], ids=["formal", "oracle-outside-formal"])
def test_executor_refuses_an_active_catalog_different_from_the_frozen_one(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
    tmp_path: Path,
    policy_v1_executor,
    formal: bool,
) -> None:
    from scripts.run_policy_v1_evaluation import EXIT_NOT_FROZEN
    from tests.decision_support import DEFAULT_CATALOG

    main, calls = policy_v1_executor
    # Congelado sem serviços; ativo na base de dados com o serviço académico.
    frozen = {"version": 1, **DEFAULT_CATALOG, "services": []}
    argv = _executor_inputs(client, test_session_factory, tmp_path, frozen_catalog=frozen)

    assert main([*argv, "--formal"] if formal else argv) == EXIT_NOT_FROZEN
    assert calls == []
    assert not (tmp_path / "report.json").exists()


@pytest.mark.parametrize("formal", [True, False], ids=["formal", "oracle-outside-formal"])
def test_executor_accepts_the_frozen_active_catalog_and_reaches_the_cases(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
    tmp_path: Path,
    policy_v1_executor,
    formal: bool,
) -> None:
    """Controlo positivo do teste anterior: só o catálogo muda entre os dois."""
    from tests.decision_support import DEFAULT_CATALOG

    main, calls = policy_v1_executor
    frozen = {"version": 1, **DEFAULT_CATALOG}
    argv = _executor_inputs(client, test_session_factory, tmp_path, frozen_catalog=frozen)

    with pytest.raises(ReachedCases):
        main([*argv, "--formal"] if formal else argv)
    assert calls == ["C1"]
