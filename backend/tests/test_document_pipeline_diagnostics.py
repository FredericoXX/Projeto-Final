"""Cobertura do diagnóstico interno e read-only do pipeline documental.

Os 80 testes correspondem, pela ordem, aos 80 cenários obrigatórios do
prompt do Momento 1. Dados documentais são inteiramente sintéticos.
"""

from __future__ import annotations

import inspect
import json
import os
import uuid
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, insert, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

import app.diagnostics.document_pipeline as diagnostic
import scripts.diagnose_document_pipeline as cli
from app.core.config import settings
from app.core.text_normalization import normalize_text
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.document_version import DocumentVersion
from app.models.institution import Institution
from app.retrieval.base import (
    Evidence,
    RetrievalResult,
    RetrievalTrace,
    ScoreKind,
    ScoreSemantics,
)

BOOTSTRAP_HEADERS = {"X-Bootstrap-Token": settings.bootstrap_token or ""}


class EmptyRetriever:
    """Retriever sem resultados e **sem** trace lexical.

    Cumpre o contrato: devolve sempre um ``RetrievalTrace`` genérico. O que não
    produz é o detalhe lexical, porque não faz correspondência lexical nenhuma
    — é exatamente a situação de um retriever de outra estratégia.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, Any, int, bool]] = []

    def search(
        self, db: Session, query: str, context: Any, top_k: int, official_only: bool
    ) -> RetrievalResult:
        self.calls.append((query, context, top_k, official_only))
        return RetrievalResult(
            evidence=(),
            trace=RetrievalTrace(candidates_evaluated=0, result_count_before_limit=0),
            score_semantics=ScoreSemantics(
                kind=ScoreKind.SYNTHETIC,
                version="test_fake_v1",
                comparable_across_queries=False,
            ),
        )


def _question() -> diagnostic.DiagnosticQuestion:
    return diagnostic.DiagnosticQuestion(
        id="synthetic-event",
        question="Quando decorre o evento sintético?",
        language="pt",
        expected_answer="10 de março de 2031",
        expected_facts=(
            diagnostic.ExpectedFact("event", ("Evento sintético",)),
            diagnostic.ExpectedFact("date", ("10 de março de 2031",)),
        ),
    )


def _question_payload() -> list[dict[str, Any]]:
    return [
        {
            "id": "synthetic-event",
            "question": "Quando decorre o evento sintético?",
            "language": "pt",
            "expected_answer": "10 de março de 2031",
            "expected_facts": [
                {"name": "event", "alternatives": ["Evento sintético"]},
                {"name": "date", "alternatives": ["10 de março de 2031"]},
            ],
        }
    ]


def _document(**overrides: Any) -> Document:
    values: dict[str, Any] = {
        "id": uuid4(),
        "institution_id": uuid4(),
        "created_by_user_id": uuid4(),
        "title": "Documento sintético",
        "description": None,
        "language": "pt",
        "source_url": None,
        "official_source": True,
        "is_active": True,
        "valid_from": None,
        "valid_until": None,
    }
    values.update(overrides)
    return Document(**values)


def _version(document: Document, **overrides: Any) -> DocumentVersion:
    values: dict[str, Any] = {
        "id": uuid4(),
        "document_id": document.id,
        "institution_id": document.institution_id,
        "uploaded_by_user_id": document.created_by_user_id,
        "version_number": 1,
        "original_filename": "synthetic.txt",
        "mime_type": "text/plain",
        "size_bytes": 64,
        "checksum_sha256": "a" * 64,
        "storage_path": "synthetic/file.txt",
        "processing_status": "processed",
        "processing_error": None,
        "extracted_text": "Evento sintético em 10 de março de 2031.",
        "page_count": 1,
        "processed_at": datetime(2031, 1, 1, tzinfo=UTC),
    }
    values.update(overrides)
    return DocumentVersion(**values)


def _chunk(
    document: Document,
    version: DocumentVersion,
    content: str,
    *,
    index: int = 0,
    start: int = 0,
    end: int | None = None,
    page_number: int | None = None,
    section_title: str | None = None,
    structure_type: str | None = None,
    chunking_strategy: str | None = None,
) -> DocumentChunk:
    return DocumentChunk(
        id=uuid4(),
        institution_id=document.institution_id,
        document_id=document.id,
        document_version_id=version.id,
        chunk_index=index,
        content=content,
        normalized_content=normalize_text(content),
        content_sha256="b" * 64,
        start_char=start,
        end_char=len(content) if end is None else end,
        page_number=page_number,
        section_title=section_title,
        structure_type=structure_type,
        chunking_strategy=chunking_strategy,
        language="pt",
    )


def _presence(name: str, found: bool = True) -> diagnostic.FactPresence:
    occurrence = diagnostic.FactOccurrence(
        alternative=name,
        normalized_start=0,
        original_start=0 if found else None,
        original_end=len(name) if found else None,
        excerpt=name if found else None,
        approximate_page=None,
        crosses_page_break=False,
    )
    return diagnostic.FactPresence(
        fact_name=name,
        found=found,
        matched_alternative=name if found else None,
        occurrence_count=1 if found else 0,
        occurrences=(occurrence,) if found else (),
        position_mapping_exact=True,
    )


def _classification_state() -> tuple[Any, ...]:
    question = _question()
    document = _document()
    version = _version(document)
    selection = diagnostic.SelectionContext(document, version, version, "effective")
    extraction = (_presence("event"), _presence("date"))
    chunk_id = uuid4()
    chunks = diagnostic.QuestionChunkAnalysis(
        all_facts_in_extracted_text=True,
        all_facts_present_in_chunks=True,
        all_facts_in_same_chunk=True,
        facts_split_across_chunks=False,
        missing_from_chunks=(),
        matching_chunk_ids=(chunk_id,),
        covering_chunk_sets=((chunk_id,),),
        minimum_covering_chunk_count=1,
        relevant_chunks=(),
        fact_pair_proximity_by_chunk=(),
    )
    eligibility = diagnostic.VersionEligibility(
        version.id,
        1,
        "processed",
        (diagnostic.EligibilityCondition("ok", True, "ok"),),
        True,
    )
    retrieval = diagnostic.QuestionRetrievalAnalysis(
        query=question.question,
        language="pt",
        reference_date=date(2031, 3, 1),
        top_k=5,
        official_only=True,
        result_count=1,
        results=(),
        target_document_retrieved=True,
        selected_version_retrieved=True,
        effective_retrieval_version_retrieved=True,
        matching_chunk_retrieved=True,
        covering_chunk_set_retrieved=True,
        expected_fact_coverage_across_results=("event", "date"),
        all_expected_facts_covered_across_results=True,
        irrelevant_for_expected_facts_count=0,
        retrieval_returned_only_results_without_expected_facts=False,
        eligible_evidence_exists_but_was_not_retrieved=False,
        correct_target_evidence_exists_but_other_document_was_used=False,
        other_document_covers_all_expected_facts=False,
    )
    integrity = diagnostic.ChunkIntegritySummary(1, 10, 10, 10.0, (), (), False, 0, 0)
    return (
        question,
        document,
        version,
        selection,
        extraction,
        chunks,
        eligibility,
        retrieval,
        integrity,
    )


def _minimal_report(**overrides: Any) -> diagnostic.DiagnosticReport:
    institution_id = uuid4()
    document_id = uuid4()
    version_id = uuid4()
    values: dict[str, Any] = {
        "diagnostic_report_version": 1,
        "execution": diagnostic.ExecutionInfo(
            "2031-03-01T00:00:00+00:00", date(2031, 3, 1), "markdown", 5, True, 240, 1, None
        ),
        "institution": diagnostic.InstitutionInfo(institution_id, "Instituição sintética"),
        "document": diagnostic.DocumentInfo(
            document_id, "Documento sintético", "pt", True, True, None, None
        ),
        "selected_version": diagnostic.SelectedVersionInfo(
            version_id,
            1,
            "synthetic.txt",
            "text/plain",
            64,
            "a" * 12,
            "processed",
            None,
            1,
            42,
            "2031-01-01T00:00:00+00:00",
            # Metadados de extração do Momento 2 (None: versão histórica).
            extraction_method=None,
            extraction_quality=None,
            extraction_warning=None,
            native_page_count=None,
            ocr_page_count=None,
            low_quality_page_count=None,
            page_summaries=(),
        ),
        "effective_retrieval_version": diagnostic.EffectiveVersionInfo(
            version_id, 1, "processed", "effective", False
        ),
        "configuration": diagnostic.ConfigurationInfo(1200, 200, 5, date(2031, 3, 1)),
        "chunk_integrity": diagnostic.ChunkIntegritySummary(
            0, None, None, None, (), (), False, 0, 0
        ),
        "questions": (),
        "global_conclusion": diagnostic.GlobalConclusion((), (), "Conclusão sintética."),
        "limitations": ("Limitação sintética.",),
    }
    values.update(overrides)
    return diagnostic.DiagnosticReport(**values)


def _create_institution(client: TestClient, label: str) -> dict[str, Any]:
    response = client.post(
        "/api/v1/institutions",
        json={
            "name": f"Instituição sintética {label}",
            "code": f"DIA-{uuid.uuid4().hex[:8].upper()}",
            "default_language": "pt",
            "supported_languages": ["pt"],
        },
        headers=BOOTSTRAP_HEADERS,
    )
    assert response.status_code == 201
    return response.json()


def _create_admin(client: TestClient, institution_id: str) -> dict[str, str]:
    email = f"diag-{uuid.uuid4().hex[:10]}@example.com"
    response = client.post(
        "/api/v1/auth/register-initial-admin",
        json={
            "institution_id": institution_id,
            "full_name": "Admin Sintético",
            "email": email,
            "password": "synthetic-password-123",
        },
        headers=BOOTSTRAP_HEADERS,
    )
    assert response.status_code == 201
    login = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "synthetic-password-123"},
    )
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _create_document_api(client: TestClient, headers: dict[str, str], title: str) -> dict[str, Any]:
    response = client.post(
        "/api/v1/documents",
        json={"title": title, "language": "pt", "official_source": True},
        headers=headers,
    )
    assert response.status_code == 201
    return response.json()


def _upload_text(
    client: TestClient,
    headers: dict[str, str],
    document_id: str,
    content: str,
    filename: str = "synthetic-evidence.txt",
) -> dict[str, Any]:
    response = client.post(
        f"/api/v1/documents/{document_id}/versions",
        files={"file": (filename, content.encode("utf-8"), "text/plain")},
        headers=headers,
    )
    assert response.status_code == 201
    return response.json()


def _persisted_graph(client: TestClient, label: str = "A") -> tuple[dict[str, Any], ...]:
    institution = _create_institution(client, label)
    headers = _create_admin(client, institution["id"])
    document = _create_document_api(client, headers, f"Documento sintético {label}")
    version = _upload_text(
        client,
        headers,
        document["id"],
        "Evento sintético em 10 de março de 2031.",
    )
    return institution, headers, document, version


def _valid_cli_args(root: Path) -> list[str]:
    questions = root / "questions.json"
    questions.write_text(json.dumps(_question_payload()), encoding="utf-8")
    return [
        "--institution-id",
        str(uuid4()),
        "--document-id",
        str(uuid4()),
        "--questions-file",
        str(questions),
        "--output",
        str(root / "docs" / "diagnostics" / "generated" / "report.md"),
    ]


# 1
def test_01_argument_parsing() -> None:
    args = cli.build_parser().parse_args(
        [
            "--institution-id",
            str(uuid4()),
            "--document-id",
            str(uuid4()),
            "--questions-file",
            "questions.json",
            "--output",
            "report.md",
        ]
    )
    assert args.format == "markdown" and args.top_k == 5


# 2
def test_02_selection_group_is_mutually_exclusive() -> None:
    parser = cli.build_parser()
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(
            [
                "--institution-id",
                str(uuid4()),
                "--document-id",
                str(uuid4()),
                "--version-id",
                str(uuid4()),
                "--questions-file",
                "q.json",
                "--output",
                "o.md",
            ]
        )
    assert exc.value.code == 2


# 3
def test_03_institution_id_is_required() -> None:
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(
            ["--document-id", str(uuid4()), "--questions-file", "q.json", "--output", "o.md"]
        )


# 4
def test_04_questions_file_is_required() -> None:
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(
            ["--institution-id", str(uuid4()), "--document-id", str(uuid4()), "--output", "o.md"]
        )


# 5
def test_05_output_is_required() -> None:
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(
            [
                "--institution-id",
                str(uuid4()),
                "--document-id",
                str(uuid4()),
                "--questions-file",
                "q.json",
            ]
        )


# 6
def test_06_output_outside_generated_is_rejected(tmp_path: Path) -> None:
    output, code = cli._validate_output_path(tmp_path / "outside.md", "markdown", tmp_path, False)
    assert output is None and code == cli.EXIT_USAGE


# 7
def test_07_output_extension_must_match_format(tmp_path: Path) -> None:
    target = tmp_path / "docs" / "diagnostics" / "generated" / "report.json"
    output, code = cli._validate_output_path(target, "markdown", tmp_path, False)
    assert output is None and code == cli.EXIT_USAGE


# 8
def test_08_overwrite_must_be_explicit(tmp_path: Path) -> None:
    target = tmp_path / "docs" / "diagnostics" / "generated" / "report.md"
    target.parent.mkdir(parents=True)
    target.write_text("old", encoding="utf-8")
    assert (
        cli._validate_output_path(target, "markdown", tmp_path, False)[1] == cli.EXIT_OUTPUT_EXISTS
    )
    assert cli._validate_output_path(target, "markdown", tmp_path, True)[0] == target


# 9
def test_09_select_by_document_id(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> None:
    institution, _, document, version = _persisted_graph(client)
    with test_session_factory() as db:
        selected = diagnostic.select_by_document_id(
            db, institution_id=UUID(institution["id"]), document_id=UUID(document["id"])
        )
    assert selected.selected_version.id == UUID(version["id"])


# 10
def test_10_select_by_version_id(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> None:
    institution, _, document, version = _persisted_graph(client)
    with test_session_factory() as db:
        selected = diagnostic.select_by_version_id(
            db, institution_id=UUID(institution["id"]), version_id=UUID(version["id"])
        )
    assert selected.document.id == UUID(document["id"])


# 11
def test_11_select_by_exact_filename(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> None:
    institution, _, document, _ = _persisted_graph(client)
    with test_session_factory() as db:
        selected = diagnostic.select_by_filename(
            db, institution_id=UUID(institution["id"]), filename="synthetic-evidence.txt"
        )
    assert selected.document.id == UUID(document["id"])


# 12
def test_12_filename_is_case_insensitive(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> None:
    institution, _, _, version = _persisted_graph(client)
    with test_session_factory() as db:
        selected = diagnostic.select_by_filename(
            db, institution_id=UUID(institution["id"]), filename="SYNTHETIC-EVIDENCE.TXT"
        )
    assert selected.selected_version.id == UUID(version["id"])


# 13
def test_13_missing_filename_is_controlled(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> None:
    institution, _, _, _ = _persisted_graph(client)
    with test_session_factory() as db, pytest.raises(diagnostic.DocumentSelectionError):
        diagnostic.select_by_filename(
            db, institution_id=UUID(institution["id"]), filename="missing.txt"
        )


# 14
def test_14_same_filename_versions_of_one_document_are_not_ambiguous(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> None:
    institution, headers, document, _ = _persisted_graph(client)
    latest = _upload_text(
        client,
        headers,
        document["id"],
        "Segunda versão sintética com conteúdo diferente.",
    )
    with test_session_factory() as db:
        selected = diagnostic.select_by_filename(
            db, institution_id=UUID(institution["id"]), filename="synthetic-evidence.txt"
        )
    assert selected.selected_version.id == UUID(latest["id"])


# 15
def test_15_same_filename_across_documents_is_ambiguous(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> None:
    institution, headers, _, _ = _persisted_graph(client)
    other = _create_document_api(client, headers, "Outro documento sintético")
    _upload_text(client, headers, other["id"], "Conteúdo distinto para ambiguidade.")
    with test_session_factory() as db, pytest.raises(diagnostic.AmbiguousFilenameError):
        diagnostic.select_by_filename(
            db, institution_id=UUID(institution["id"]), filename="synthetic-evidence.txt"
        )


# 16
def test_16_document_without_versions_is_controlled(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> None:
    institution = _create_institution(client, "no-version")
    headers = _create_admin(client, institution["id"])
    document = _create_document_api(client, headers, "Documento sem versão")
    with test_session_factory() as db, pytest.raises(diagnostic.VersionSelectionError):
        diagnostic.select_by_document_id(
            db, institution_id=UUID(institution["id"]), document_id=UUID(document["id"])
        )


# 17
def test_17_version_without_extracted_text_is_controlled(monkeypatch: pytest.MonkeyPatch) -> None:
    document = _document()
    version = _version(document, extracted_text=None)
    selection = diagnostic.SelectionContext(document, version, version, "effective")
    db = cast(Session, SimpleNamespace(rollback=lambda: None, execute=lambda statement: None))
    monkeypatch.setattr(
        diagnostic, "load_institution", lambda *_: SimpleNamespace(id=document.institution_id)
    )
    monkeypatch.setattr(diagnostic, "select_by_version_id", lambda *_, **__: selection)
    with pytest.raises(diagnostic.UnusableExtractedTextError):
        diagnostic.run_diagnostic(
            db,
            EmptyRetriever(),
            institution_id=document.institution_id,
            questions=(_question(),),
            version_id=version.id,
        )


# 18
def test_18_institution_isolation(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> None:
    institution_a, _, document_a, _ = _persisted_graph(client, "A")
    institution_b, _, _, _ = _persisted_graph(client, "B")
    with test_session_factory() as db, pytest.raises(diagnostic.DocumentSelectionError):
        diagnostic.select_by_document_id(
            db,
            institution_id=UUID(institution_b["id"]),
            document_id=UUID(document_a["id"]),
        )
    assert institution_a["id"] != institution_b["id"]


# 19
def test_19_foreign_version_id_is_not_found(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> None:
    _, _, _, version_a = _persisted_graph(client, "A")
    institution_b, _, _, _ = _persisted_graph(client, "B")
    with test_session_factory() as db, pytest.raises(diagnostic.VersionSelectionError) as exc:
        diagnostic.select_by_version_id(
            db,
            institution_id=UUID(institution_b["id"]),
            version_id=UUID(version_a["id"]),
        )
    assert "another" not in str(exc.value).lower()


# 20
def test_20_all_own_queries_include_institution_id() -> None:
    functions = (
        diagnostic._load_document,
        diagnostic._latest_version,
        diagnostic._effective_retrieval_version,
        diagnostic.select_by_version_id,
        diagnostic.select_by_filename,
        diagnostic.load_version_chunks,
        diagnostic.verify_results_institution,
    )
    for function in functions:
        source = inspect.getsource(function)
        assert "institution_id" in source
    assert "Institution.id == institution_id" in inspect.getsource(diagnostic.load_institution)


# 21
def test_21_read_only_transaction_is_activated(monkeypatch: pytest.MonkeyPatch) -> None:
    document = _document()
    version = _version(document, extracted_text=None)
    selection = diagnostic.SelectionContext(document, version, version, "effective")
    statements: list[str] = []
    db = cast(
        Session,
        SimpleNamespace(
            rollback=lambda: None,
            execute=lambda statement: statements.append(str(statement)),
        ),
    )
    monkeypatch.setattr(
        diagnostic, "load_institution", lambda *_: SimpleNamespace(id=document.institution_id)
    )
    monkeypatch.setattr(diagnostic, "select_by_version_id", lambda *_, **__: selection)
    with pytest.raises(diagnostic.UnusableExtractedTextError):
        diagnostic.run_diagnostic(
            db,
            EmptyRetriever(),
            institution_id=document.institution_id,
            questions=(_question(),),
            version_id=version.id,
        )
    assert statements == ["SET TRANSACTION READ ONLY"]


# 22
def test_22_diagnostic_does_not_change_persisted_data(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> None:
    institution, _, document, _ = _persisted_graph(client)
    tables = (Document, DocumentVersion, DocumentChunk)
    with test_session_factory() as db:
        before = tuple(db.scalar(select(func.count()).select_from(model)) for model in tables)
        report = diagnostic.run_diagnostic(
            db,
            EmptyRetriever(),
            institution_id=UUID(institution["id"]),
            questions=(_question(),),
            document_id=UUID(document["id"]),
            reference_date=date(2031, 3, 1),
            clock=lambda: datetime(2031, 3, 1, tzinfo=UTC),
        )
        after = tuple(db.scalar(select(func.count()).select_from(model)) for model in tables)
    assert before == after and report.document.document_id == UUID(document["id"])


# 23
def test_23_diagnostic_never_commits(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    institution, _, document, _ = _persisted_graph(client)
    with test_session_factory() as db:
        monkeypatch.setattr(db, "commit", lambda: pytest.fail("commit must not be called"))
        diagnostic.run_diagnostic(
            db,
            EmptyRetriever(),
            institution_id=UUID(institution["id"]),
            questions=(_question(),),
            document_id=UUID(document["id"]),
            reference_date=date(2031, 3, 1),
        )


# 24
def test_24_accidental_write_fails_in_read_only_transaction(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> None:
    institution, _, _, _ = _persisted_graph(client)
    with test_session_factory() as db:
        db.rollback()
        db.execute(text("SET TRANSACTION READ ONLY"))
        with pytest.raises(DBAPIError):
            db.execute(
                insert(Institution).values(
                    id=uuid4(),
                    name="Escrita proibida",
                    code=f"WR-{uuid.uuid4().hex[:8]}",
                    default_language="pt",
                    supported_languages=["pt"],
                )
            )
        db.rollback()
    assert institution["id"]


# 25
def test_25_cli_always_closes_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    args = _valid_cli_args(tmp_path)
    state = SimpleNamespace(closed=False)
    session = cast(Session, SimpleNamespace(close=lambda: setattr(state, "closed", True)))
    monkeypatch.setattr(
        cli,
        "run_diagnostic",
        lambda *_, **__: (_ for _ in ()).throw(diagnostic.InstitutionNotFoundError("missing")),
    )
    code = cli.main(
        args,
        session_factory=lambda: session,
        retriever=EmptyRetriever(),
        repository_root=tmp_path,
    )
    assert code == cli.EXIT_INSTITUTION_NOT_FOUND and state.closed


# 26
def test_26_questions_file_payload_is_validated() -> None:
    parsed = diagnostic.parse_questions_payload(_question_payload())
    assert parsed == (_question(),)


# 27
def test_27_unknown_question_fields_are_rejected() -> None:
    payload = _question_payload()
    payload[0]["unknown"] = True
    with pytest.raises(diagnostic.QuestionsFileError):
        diagnostic.parse_questions_payload(payload)


# 28
def test_28_duplicate_question_ids_are_rejected() -> None:
    payload = _question_payload() * 2
    with pytest.raises(diagnostic.QuestionsFileError, match="duplicate"):
        diagnostic.parse_questions_payload(payload)


# 29
def test_29_empty_expected_facts_are_rejected() -> None:
    payload = _question_payload()
    payload[0]["expected_facts"] = []
    with pytest.raises(diagnostic.QuestionsFileError):
        diagnostic.parse_questions_payload(payload)


# 30
def test_30_empty_fact_alternative_is_rejected() -> None:
    payload = _question_payload()
    payload[0]["expected_facts"][0]["alternatives"] = [""]
    with pytest.raises(diagnostic.QuestionsFileError):
        diagnostic.parse_questions_payload(payload)


# 31
def test_31_fact_present_in_extracted_text() -> None:
    source = "Evento sintético em março."
    result = diagnostic.find_fact_in_text(
        diagnostic.build_normalized_index(source),
        source,
        diagnostic.ExpectedFact("event", ("Evento sintético",)),
        80,
    )
    assert result.found and result.occurrence_count == 1


# 32
def test_32_fact_absent_from_extracted_text() -> None:
    source = "Texto sem a informação esperada."
    result = diagnostic.find_fact_in_text(
        diagnostic.build_normalized_index(source),
        source,
        diagnostic.ExpectedFact("event", ("Evento sintético",)),
        80,
    )
    assert not result.found and result.occurrences == ()


# 33
def test_33_multiple_fact_occurrences_are_counted() -> None:
    source = "Evento sintético; Evento sintético; Evento sintético."
    result = diagnostic.find_fact_in_text(
        diagnostic.build_normalized_index(source),
        source,
        diagnostic.ExpectedFact("event", ("Evento sintético",)),
        80,
    )
    assert result.occurrence_count == 3


# 34
def test_34_excerpt_is_strictly_limited() -> None:
    source = "x" * 100 + " Evento sintético " + "y" * 100
    result = diagnostic.find_fact_in_text(
        diagnostic.build_normalized_index(source),
        source,
        diagnostic.ExpectedFact("event", ("Evento sintético",)),
        80,
    )
    assert result.occurrences[0].excerpt is not None
    assert len(result.occurrences[0].excerpt or "") <= 80


# 35
def test_35_existing_normalization_handles_accents() -> None:
    source = "A inscrição académica começa hoje."
    result = diagnostic.find_fact_in_text(
        diagnostic.build_normalized_index(source),
        source,
        diagnostic.ExpectedFact("event", ("inscricao academica",)),
        80,
    )
    assert result.found


# 36
def test_36_position_mapping_does_not_claim_inexact_original_offset() -> None:
    source = "Straße"
    index = diagnostic.build_normalized_index(source)
    result = diagnostic.find_fact_in_text(
        index, source, diagnostic.ExpectedFact("word", ("strasse",)), 80
    )
    if not index.exact:
        assert result.occurrences[0].original_start is None
    else:
        assert result.occurrences[0].original_start == 0


# 37
def test_37_all_facts_can_be_in_same_chunk() -> None:
    document = _document()
    version = _version(document)
    content = version.extracted_text or ""
    chunks = [_chunk(document, version, content)]
    extraction = (_presence("event"), _presence("date"))
    result = diagnostic.analyze_question_chunks(_question(), chunks, extraction, 80)
    assert result.all_facts_in_same_chunk and result.minimum_covering_chunk_count == 1


# 38
def test_38_split_facts_create_finding_not_automatic_failure() -> None:
    state = list(_classification_state())
    chunks = replace(
        state[5],
        all_facts_in_same_chunk=False,
        facts_split_across_chunks=True,
        matching_chunk_ids=(),
        minimum_covering_chunk_count=2,
    )
    conclusion, findings, _ = diagnostic.classify_question(
        state[0], state[4], chunks, state[6], state[7], state[8], state[3]
    )
    assert conclusion is diagnostic.PrimaryConclusion.PRE_GENERATION_PIPELINE_OK
    assert diagnostic.DiagnosticFinding.CONTEXT_FRAGMENTATION_RISK in findings


# 39
def test_39_two_chunks_jointly_cover_all_facts() -> None:
    document = _document()
    version = _version(document)
    first = "Evento sintético."
    second = "Data: 10 de março de 2031."
    chunks = [
        _chunk(document, version, first, index=0),
        _chunk(document, version, second, index=1, start=len(first)),
    ]
    result = diagnostic.analyze_question_chunks(
        _question(), chunks, (_presence("event"), _presence("date")), 80
    )
    assert result.facts_split_across_chunks and result.minimum_covering_chunk_count == 2


# 40
def test_40_fact_in_text_but_missing_from_chunks() -> None:
    document = _document()
    version = _version(document)
    chunks = [_chunk(document, version, "Evento sintético.")]
    result = diagnostic.analyze_question_chunks(
        _question(), chunks, (_presence("event"), _presence("date")), 80
    )
    assert result.missing_from_chunks == ("date",)


# 41
def test_41_correct_chunk_offsets_have_no_integrity_issue() -> None:
    document = _document()
    version = _version(document)
    text_value = version.extracted_text or ""
    result = diagnostic.analyze_chunk_integrity([_chunk(document, version, text_value)], text_value)
    assert result.issues == ()


# 42
def test_42_negative_chunk_offset_is_detected() -> None:
    document = _document()
    version = _version(document)
    chunk = _chunk(document, version, "abc", start=-1, end=2)
    result = diagnostic.analyze_chunk_integrity([chunk], "abc")
    assert any("negative" in issue.issue for issue in result.issues)


# 43
def test_43_chunk_end_outside_text_is_detected() -> None:
    document = _document()
    version = _version(document)
    result = diagnostic.analyze_chunk_integrity([_chunk(document, version, "abc", end=10)], "abc")
    assert any("exceeds" in issue.issue for issue in result.issues)


# 44
def test_44_chunk_content_divergence_is_detected() -> None:
    document = _document()
    version = _version(document)
    result = diagnostic.analyze_chunk_integrity([_chunk(document, version, "xyz", end=3)], "abc")
    assert any("differs" in issue.issue for issue in result.issues)


# 45
def test_45_blank_chunk_is_detected() -> None:
    document = _document()
    version = _version(document)
    result = diagnostic.analyze_chunk_integrity([_chunk(document, version, "   ", end=3)], "   ")
    assert any("blank" in issue.issue for issue in result.issues)


# 46
def test_46_gap_between_chunks_is_detected() -> None:
    document = _document()
    version = _version(document)
    chunks = [
        _chunk(document, version, "abc", index=0, start=0, end=3),
        _chunk(document, version, "ghi", index=1, start=6, end=9),
    ]
    result = diagnostic.analyze_chunk_integrity(chunks, "abc---ghi")
    assert result.gap_count == 1


def test_page_separator_is_a_valid_structural_gap() -> None:
    document = _document()
    version = _version(document)
    chunks = [
        _chunk(
            document,
            version,
            "abc",
            index=0,
            start=0,
            end=3,
            page_number=1,
            structure_type="paragraph",
            chunking_strategy="structured_v1",
        ),
        _chunk(
            document,
            version,
            "def",
            index=1,
            start=4,
            end=7,
            page_number=2,
            structure_type="paragraph",
            chunking_strategy="structured_v1",
        ),
    ]
    result = diagnostic.analyze_chunk_integrity(chunks, "abc\fdef")
    assert result.gap_count == 0
    assert result.cross_page_chunk_count == 0
    assert result.chunks_by_page == ((1, 1), (2, 1))


def test_cross_page_chunk_and_structural_counts_are_reported() -> None:
    document = _document()
    version = _version(document)
    text_value = "Evento | Data\fOutro"
    chunk = _chunk(
        document,
        version,
        text_value,
        end=len(text_value),
        page_number=1,
        structure_type="fallback_fragment",
        chunking_strategy="character_fallback_v1",
    )
    result = diagnostic.analyze_chunk_integrity([chunk], text_value)
    assert result.cross_page_chunk_count == 1
    assert result.fallback_fragment_count == 1
    assert any("PAGE_SEPARATOR" in issue.issue for issue in result.issues)


def test_split_table_row_is_reported() -> None:
    document = _document()
    version = _version(document)
    text_value = "Evento sintético | Período sintético"
    split = text_value.index("|")
    chunks = [
        _chunk(
            document,
            version,
            text_value[: split + 1],
            index=0,
            start=0,
            end=split + 1,
            page_number=1,
            structure_type="fallback_fragment",
            chunking_strategy="character_fallback_v1",
        ),
        _chunk(
            document,
            version,
            text_value[split - 2 :],
            index=1,
            start=split - 2,
            end=len(text_value),
            page_number=1,
            structure_type="fallback_fragment",
            chunking_strategy="character_fallback_v1",
        ),
    ]
    result = diagnostic.analyze_chunk_integrity(chunks, text_value)
    assert result.split_table_row_count == 1


def test_expected_facts_in_same_table_row_are_reported() -> None:
    question = _question()
    document = _document()
    text_value = "Evento sintético | 10 de março de 2031"
    version = _version(document, extracted_text=text_value)
    chunk = _chunk(
        document,
        version,
        text_value,
        page_number=1,
        section_title="AGENDA SINTÉTICA",
        structure_type="table_row",
        chunking_strategy="structured_v1",
    )
    index = diagnostic.build_normalized_index(text_value)
    extraction = tuple(
        diagnostic.find_fact_in_text(index, text_value, fact, 240)
        for fact in question.expected_facts
    )
    result = diagnostic.analyze_question_chunks(
        question, [chunk], extraction, 240
    )
    assert result.all_facts_in_same_chunk is True
    assert result.expected_facts_in_same_table_row is True
    assert result.relevant_chunks[0].page_number == 1
    assert result.relevant_chunks[0].section_title == "AGENDA SINTÉTICA"
    assert result.relevant_chunks[0].structure_type == "table_row"


def _retrieval_inputs() -> tuple[Any, ...]:
    question, document, version, selection, extraction, chunks, eligibility, _, _ = (
        _classification_state()
    )
    return question, document, version, selection, extraction, chunks, eligibility


def _evidence(
    document: Document,
    version: DocumentVersion,
    content: str,
    *,
    chunk_id: UUID | None = None,
) -> Evidence:
    return Evidence(
        chunk_id=chunk_id or uuid4(),
        document_id=document.id,
        document_version_id=version.id,
        document_title=document.title,
        chunk_index=0,
        content=content,
        score=0.8,
        language="pt",
        official_source=True,
        source_url=None,
        valid_from=None,
        valid_until=None,
    )


def _analyze_retrieval(
    inputs: tuple[Any, ...], results: list[Evidence]
) -> diagnostic.QuestionRetrievalAnalysis:
    question, _, _, selection, _, chunks, eligibility = inputs
    return diagnostic.analyze_question_retrieval(
        question,
        results,
        selection,
        chunks,
        eligibility,
        reference_date=date(2031, 3, 1),
        top_k=5,
        official_only=True,
        max_excerpt_chars=80,
    )


# 47
def test_47_retrieval_one_chunk_covers_all_facts() -> None:
    inputs = _retrieval_inputs()
    _, document, version, *_ = inputs
    result = _analyze_retrieval(
        inputs, [_evidence(document, version, "Evento sintético em 10 de março de 2031.")]
    )
    assert result.all_expected_facts_covered_across_results


# 48
def test_48_retrieval_union_of_two_chunks_covers_all_facts() -> None:
    inputs = _retrieval_inputs()
    _, document, version, *_ = inputs
    results = [
        _evidence(document, version, "Evento sintético."),
        _evidence(document, version, "10 de março de 2031."),
    ]
    assert _analyze_retrieval(inputs, results).all_expected_facts_covered_across_results


# 49
def test_49_retrieval_other_document_can_cover_expected_facts() -> None:
    inputs = _retrieval_inputs()
    other_document = _document(institution_id=inputs[1].institution_id)
    other_version = _version(other_document)
    result = _analyze_retrieval(
        inputs,
        [_evidence(other_document, other_version, "Evento sintético em 10 de março de 2031.")],
    )
    assert result.other_document_covers_all_expected_facts
    assert not result.target_document_retrieved


# 50
def test_50_eligible_evidence_not_retrieved_is_detected() -> None:
    inputs = _retrieval_inputs()
    result = _analyze_retrieval(inputs, [])
    assert result.eligible_evidence_exists_but_was_not_retrieved


# 51
def test_51_inactive_document_is_not_eligible() -> None:
    document = _document(is_active=False)
    version = _version(document)
    selection = diagnostic.SelectionContext(document, version, version, "effective")
    result = diagnostic.evaluate_eligibility(
        selection,
        version,
        question_language="pt",
        reference_date=date(2031, 3, 1),
        official_only=True,
        chunks=[_chunk(document, version, "Evento sintético em 10 de março de 2031.")],
    )
    assert not result.eligible
    assert not next(c for c in result.conditions if c.name == "document_active").satisfied


# 52
def test_52_non_official_document_is_filtered_by_default() -> None:
    document = _document(official_source=False)
    version = _version(document)
    selection = diagnostic.SelectionContext(document, version, version, "effective")
    result = diagnostic.evaluate_eligibility(
        selection,
        version,
        question_language="pt",
        reference_date=date(2031, 3, 1),
        official_only=True,
        chunks=[_chunk(document, version, "Evento sintético em 10 de março de 2031.")],
    )
    assert not result.eligible


# 53
def test_53_document_outside_validity_is_not_eligible() -> None:
    document = _document(valid_until=date(2030, 12, 31))
    version = _version(document)
    selection = diagnostic.SelectionContext(document, version, version, "effective")
    result = diagnostic.evaluate_eligibility(
        selection,
        version,
        question_language="pt",
        reference_date=date(2031, 3, 1),
        official_only=True,
        chunks=[_chunk(document, version, "Evento sintético em 10 de março de 2031.")],
    )
    assert not result.eligible


# 54
def test_54_failed_selected_version_can_differ_from_processed_effective() -> None:
    document = _document()
    effective = _version(document, version_number=1)
    selected = _version(
        document, id=uuid4(), version_number=2, processing_status="failed", checksum_sha256="c" * 64
    )
    selection = diagnostic.SelectionContext(document, selected, effective, "older processed")
    result = diagnostic.evaluate_eligibility(
        selection,
        selected,
        question_language="pt",
        reference_date=date(2031, 3, 1),
        official_only=True,
        chunks=[_chunk(document, selected, "Evento sintético em 10 de março de 2031.")],
    )
    assert not result.eligible and selection.effective_retrieval_version is effective


# 55
def test_55_processing_selected_version_can_differ_from_processed_effective() -> None:
    document = _document()
    effective = _version(document, version_number=1)
    selected = _version(
        document,
        id=uuid4(),
        version_number=2,
        processing_status="processing",
        checksum_sha256="d" * 64,
    )
    selection = diagnostic.SelectionContext(document, selected, effective, "older processed")
    assert selection.selected_version.processing_status == "processing"
    assert selection.effective_retrieval_version is effective


# 56
def test_56_absence_of_effective_retrieval_version_is_reportable() -> None:
    document = _document()
    selected = _version(document, processing_status="failed")
    selection = diagnostic.SelectionContext(document, selected, None, "none")
    result = diagnostic.evaluate_eligibility(
        selection,
        None,
        question_language="pt",
        reference_date=date(2031, 3, 1),
        official_only=True,
        chunks=(),
    )
    assert not result.eligible and result.version_id is None


# 57
def test_57_classification_extraction_failure() -> None:
    state = list(_classification_state())
    extraction = (_presence("event"), _presence("date", False))
    conclusion, _, _ = diagnostic.classify_question(
        state[0], extraction, state[5], state[6], state[7], state[8], state[3]
    )
    assert conclusion is diagnostic.PrimaryConclusion.EXTRACTION_FAILURE


# 58
def test_58_classification_chunk_integrity_failure() -> None:
    state = list(_classification_state())
    chunks = replace(state[5], missing_from_chunks=("date",), all_facts_present_in_chunks=False)
    conclusion, _, _ = diagnostic.classify_question(
        state[0], state[4], chunks, state[6], state[7], state[8], state[3]
    )
    assert conclusion is diagnostic.PrimaryConclusion.CHUNK_INTEGRITY_FAILURE


# 59
def test_59_classification_retrieval_failure() -> None:
    state = list(_classification_state())
    retrieval = replace(
        state[7],
        result_count=0,
        target_document_retrieved=False,
        expected_fact_coverage_across_results=(),
        all_expected_facts_covered_across_results=False,
    )
    conclusion, _, _ = diagnostic.classify_question(
        state[0], state[4], state[5], state[6], retrieval, state[8], state[3]
    )
    assert conclusion is diagnostic.PrimaryConclusion.RETRIEVAL_FAILURE


# 60
def test_60_classification_document_not_retrieval_eligible() -> None:
    state = list(_classification_state())
    eligibility = diagnostic.VersionEligibility(
        state[2].id,
        1,
        "processed",
        (diagnostic.EligibilityCondition("document_active", False, "inactive"),),
        False,
    )
    conclusion, _, _ = diagnostic.classify_question(
        state[0], state[4], state[5], eligibility, state[7], state[8], state[3]
    )
    assert conclusion is diagnostic.PrimaryConclusion.DOCUMENT_NOT_RETRIEVAL_ELIGIBLE


# 61
def test_61_classification_pre_generation_ok_with_one_chunk() -> None:
    state = list(_classification_state())
    conclusion, _, summary = diagnostic.classify_question(
        state[0], state[4], state[5], state[6], state[7], state[8], state[3]
    )
    assert conclusion is diagnostic.PrimaryConclusion.PRE_GENERATION_PIPELINE_OK
    assert diagnostic.PRE_GENERATION_OK_MESSAGE in summary


# 62
def test_62_classification_pre_generation_ok_with_multiple_chunks() -> None:
    state = list(_classification_state())
    chunks = replace(
        state[5],
        all_facts_in_same_chunk=False,
        facts_split_across_chunks=True,
        matching_chunk_ids=(),
        minimum_covering_chunk_count=2,
    )
    conclusion, _, _ = diagnostic.classify_question(
        state[0], state[4], chunks, state[6], state[7], state[8], state[3]
    )
    assert conclusion is diagnostic.PrimaryConclusion.PRE_GENERATION_PIPELINE_OK


# 63
def test_63_context_fragmentation_risk_finding() -> None:
    state = list(_classification_state())
    chunks = replace(state[5], all_facts_in_same_chunk=False, facts_split_across_chunks=True)
    _, findings, _ = diagnostic.classify_question(
        state[0], state[4], chunks, state[6], state[7], state[8], state[3]
    )
    assert diagnostic.DiagnosticFinding.CONTEXT_FRAGMENTATION_RISK in findings


# 64
def test_64_selected_version_differs_from_effective_finding() -> None:
    state = list(_classification_state())
    older = _version(state[1], id=uuid4(), version_number=0)
    selection = diagnostic.SelectionContext(state[1], state[2], older, "older")
    _, findings, _ = diagnostic.classify_question(
        state[0], state[4], state[5], state[6], state[7], state[8], selection
    )
    expected = (
        diagnostic.DiagnosticFinding.SELECTED_VERSION_DIFFERS_FROM_EFFECTIVE_RETRIEVAL_VERSION
    )
    assert expected in findings


# 65
def test_65_markdown_contains_required_sections() -> None:
    rendered = diagnostic.render_markdown(_minimal_report())
    required = (
        "## Execução",
        "## Identificação institucional",
        "## Documento",
        "## Versão selecionada",
        "## Versão efetiva do retrieval",
        "## Integridade dos chunks",
        "## Resultados por pergunta",
        "## Conclusão global",
        "## Limitações",
    )
    assert all(section in rendered for section in required)


# 66
def test_66_markdown_escapes_problematic_content() -> None:
    report = _minimal_report(
        institution=diagnostic.InstitutionInfo(uuid4(), "# título\n<script>|`_*"),
    )
    rendered = diagnostic.render_markdown(report)
    assert "<script>" not in rendered
    assert "\n<script>" not in rendered
    assert "\\|" in rendered and "\\#" in rendered


# 67
def test_67_json_has_defined_schema() -> None:
    payload = json.loads(diagnostic.render_json(_minimal_report()))
    assert tuple(payload) == (
        "diagnostic_report_version",
        "execution",
        "institution",
        "document",
        "selected_version",
        "effective_retrieval_version",
        "configuration",
        "chunk_integrity",
        "questions",
        "global_conclusion",
        "limitations",
    )


# 68
def test_68_rendering_is_deterministic() -> None:
    report = _minimal_report()
    assert diagnostic.render_json(report) == diagnostic.render_json(report)
    assert diagnostic.render_markdown(report) == diagnostic.render_markdown(report)


# 69
def test_69_atomic_write_replaces_destination(tmp_path: Path) -> None:
    destination = tmp_path / "report.md"
    destination.write_text("old", encoding="utf-8")
    cli.atomic_write(destination, "new")
    assert destination.read_text(encoding="utf-8") == "new"
    assert list(tmp_path.glob("*.tmp")) == []


# 70
def test_70_existing_output_without_overwrite_has_exit_9(tmp_path: Path) -> None:
    destination = tmp_path / "docs" / "diagnostics" / "generated" / "report.md"
    destination.parent.mkdir(parents=True)
    destination.write_text("existing", encoding="utf-8")
    assert cli._validate_output_path(destination, "markdown", tmp_path, False)[1] == 9


# 71
def test_71_atomic_write_failure_removes_temporary_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "report.md"
    monkeypatch.setattr(os, "replace", lambda *_: (_ for _ in ()).throw(OSError("synthetic")))
    with pytest.raises(OSError):
        cli.atomic_write(destination, "content")
    assert list(tmp_path.iterdir()) == []


# 72
def test_72_exit_codes_are_stable_and_distinct() -> None:
    codes = (
        cli.EXIT_OK,
        cli.EXIT_USAGE,
        cli.EXIT_INSTITUTION_NOT_FOUND,
        cli.EXIT_DOCUMENT_NOT_FOUND,
        cli.EXIT_VERSION_NOT_FOUND,
        cli.EXIT_NO_EXTRACTED_TEXT,
        cli.EXIT_DATABASE_ERROR,
        cli.EXIT_WRITE_FAILED,
        cli.EXIT_OUTPUT_EXISTS,
    )
    assert codes == (0, 2, 3, 4, 5, 6, 7, 8, 9)


# 73
def test_73_report_does_not_contain_storage_path() -> None:
    rendered = diagnostic.render_json(_minimal_report())
    assert "storage_path" not in rendered


# 74
def test_74_report_does_not_contain_database_url() -> None:
    rendered = diagnostic.render_json(_minimal_report())
    assert "DATABASE_URL" not in rendered and "postgresql://" not in rendered


# 75
def test_75_report_does_not_contain_secret_fields() -> None:
    rendered = diagnostic.render_json(_minimal_report()).lower()
    assert all(
        name not in rendered for name in ("password", "jwt", "openai_api_key", "bootstrap_token")
    )


# 76
def test_76_answering_pipeline_is_not_called_or_imported() -> None:
    source = inspect.getsource(diagnostic)
    assert "app.services.answer" not in source
    assert ".answer(" not in source


# 77
def test_77_openai_client_is_not_created() -> None:
    source = inspect.getsource(diagnostic)
    assert "OpenAI(" not in source and "AsyncOpenAI(" not in source


# 78
def test_78_openai_provider_is_not_required_to_import_diagnostic() -> None:
    imported_names = {
        value.__module__ for value in vars(diagnostic).values() if hasattr(value, "__module__")
    }
    assert not any(name.startswith("openai") for name in imported_names)


# 79
def test_79_diagnostic_uses_no_network_client() -> None:
    source = inspect.getsource(diagnostic)
    forbidden = ("requests.", "httpx.", "urllib.request", "socket.")
    assert all(item not in source for item in forbidden)


# 80
def test_80_synthetic_fixture_has_no_real_ids_or_private_data() -> None:
    fixture = Path(__file__).parent / "fixtures" / "document_pipeline_diagnostic_questions.json"
    raw = fixture.read_text(encoding="utf-8")
    payload = json.loads(raw)
    assert all(item["id"].startswith("synthetic-") for item in payload)
    assert all(
        forbidden not in raw for forbidden in ("institution_id", "storage_path", "token", "@")
    )


# --- Momento 2: metadados de extração no relatório ---------------------------


def _selected_version_with_ocr_metadata() -> diagnostic.SelectedVersionInfo:
    base = _minimal_report().selected_version
    return diagnostic.SelectedVersionInfo(
        version_id=base.version_id,
        version_number=base.version_number,
        original_filename="scanned.pdf",
        mime_type="application/pdf",
        size_bytes=base.size_bytes,
        checksum_sha256_prefix=base.checksum_sha256_prefix,
        processing_status="processed",
        processing_error=None,
        page_count=2,
        extracted_text_length=base.extracted_text_length,
        processed_at=base.processed_at,
        extraction_method="mixed",
        extraction_quality="low",
        extraction_warning="OCR completed, but the extracted text may require manual review.",
        native_page_count=1,
        ocr_page_count=1,
        low_quality_page_count=1,
        page_summaries=(
            diagnostic.ExtractionPageSummary(1, "native", 400, None, "high", None),
            diagnostic.ExtractionPageSummary(2, "ocr", 120, 42.5, "low", "aviso"),
        ),
    )


def test_report_shows_extraction_metadata_and_page_table() -> None:
    report = _minimal_report(selected_version=_selected_version_with_ocr_metadata())
    rendered = diagnostic.render_markdown(report)
    assert "- extraction_method: mixed" in rendered
    assert "- extraction_quality: low" in rendered
    assert "manual review" in rendered
    assert "| Página | Método | Caracteres | Confiança OCR | Qualidade | Aviso |" in rendered
    assert "| 2 | ocr | 120 | 42.5 | low | aviso |" in rendered
    payload = json.loads(diagnostic.render_json(report))
    assert payload["selected_version"]["extraction_method"] == "mixed"
    assert payload["selected_version"]["page_summaries"][1]["ocr_confidence"] == 42.5


def test_report_supports_historical_versions_with_null_metadata() -> None:
    rendered = diagnostic.render_markdown(_minimal_report())
    assert "- extraction_method: —" in rendered
    assert "- extraction_quality: —" in rendered
    # Sem metadados não há tabela por página.
    assert "| Página | Método |" not in rendered


def test_real_retriever_populates_lexical_trace_in_report(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> None:
    """Com o PostgresLexicalRetriever, o relatório inclui o trace lexical
    (config FTS, termos, quotas por variante, orçamento global e motivos de
    exclusão tipados), e o formato do relatório é a versão 5.

    A versão subiu de 4 para 5 na Fase 4 da issue #24: o bloco de
    elegibilidade passou a declarar a política avaliada e a incluir C8.
    """
    from app.retrieval.lexical import PostgresLexicalRetriever

    institution, _, document, _ = _persisted_graph(client)
    with test_session_factory() as db:
        report = diagnostic.run_diagnostic(
            db,
            PostgresLexicalRetriever(),
            institution_id=UUID(institution["id"]),
            questions=(_question(),),
            document_id=UUID(document["id"]),
            reference_date=date(2031, 3, 1),
            clock=lambda: datetime(2031, 3, 1, tzinfo=UTC),
        )
    assert report.diagnostic_report_version == 5
    trace = report.questions[0].lexical_trace
    assert trace is not None
    assert trace.fts_config == "portuguese"
    # O relatório recebe a **contagem** de termos, nunca os termos.
    assert trace.informative_term_count > 0
    assert trace.planned_variants  # pelo menos a variante exact
    # Contagens matematicamente consistentes entre si.
    assert trace.candidates_evaluated == trace.unique_after_dedup
    assert trace.candidates_evaluated == (
        trace.final_result_count
        + trace.excluded_no_content_match
        + trace.excluded_insufficient_coverage
        + trace.excluded_below_threshold
    )
    assert sum(variant.quota for variant in trace.variants) <= trace.global_candidate_limit

    rendered = diagnostic.render_markdown(report)
    assert "#### Trace do retrieval lexical" in rendered
    assert "- Configuração FTS: portuguese" in rendered
    assert "- Limite global de candidatos:" in rendered
    assert "- Removidos por cobertura insuficiente:" in rendered
    assert "- Resultados finais:" in rendered
    # A dominância deixou de existir: nenhum vestígio no relatório.
    assert "dominância" not in rendered
    assert "candidate_ceiling" not in rendered
    # O trace também é serializável em JSON, sem conteúdo documental.
    payload = json.loads(diagnostic.render_json(report))
    trace_payload = payload["questions"][0]["lexical_trace"]
    assert trace_payload["fts_config"] == "portuguese"
    assert "global_candidate_limit" in trace_payload
    # Privacidade: a secção do trace expõe contagens, não os termos derivados.
    assert "informative_terms" not in trace_payload
    assert "matched_terms" not in json.dumps(trace_payload)
    assert trace_payload["informative_term_count"] > 0


def test_lexical_trace_does_not_duplicate_question_terms(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> None:
    """O trace lexical não acrescenta uma segunda cópia dos termos.

    Âmbito exato desta garantia: o relatório **contém deliberadamente** a
    pergunta e a resposta esperada (`QuestionDiagnostic.question`), que são
    o input do próprio operador e existem desde a v1 — o artefacto traz
    aviso de confidencialidade por isso mesmo. O que a secção do trace não
    pode fazer é derivar e duplicar essa informação em formas canónicas
    (`informative_terms`, `matched_terms`), que atravessariam para o
    relatório sem que ninguém as tenha pedido. Essas passam a contagens.

    A proibição literal de registar a pergunta aplica-se aos **logs**,
    verificada em `test_retrieval_logs_only_controlled_metadata`.
    """
    from app.retrieval.lexical import PostgresLexicalRetriever

    institution, _, document, _ = _persisted_graph(client)
    question = _question()
    with test_session_factory() as db:
        report = diagnostic.run_diagnostic(
            db,
            PostgresLexicalRetriever(),
            institution_id=UUID(institution["id"]),
            questions=(question,),
            document_id=UUID(document["id"]),
            reference_date=date(2031, 3, 1),
            clock=lambda: datetime(2031, 3, 1, tzinfo=UTC),
        )
    trace = report.questions[0].lexical_trace
    assert trace is not None
    rendered_trace: list[str] = []
    diagnostic._add_lexical_trace(rendered_trace.append, trace)
    trace_markdown = "\n".join(rendered_trace)
    trace_json = json.dumps(diagnostic._to_jsonable(trace), ensure_ascii=False)

    # Nenhum termo informativo da pergunta aparece na secção do trace.
    for term in ("evento", "sintetico", "decorre", "quando"):
        assert term not in trace_markdown.lower()
        assert term not in trace_json.lower()
    # Mas as contagens continuam lá, para o relatório continuar auditável.
    assert "- Termos informativos: " in trace_markdown
    assert "termos correspondidos" in trace_markdown


def test_empty_retriever_leaves_lexical_trace_absent() -> None:
    """Um retriever que não produz detalhe lexical mantém o relatório válido.

    O trace genérico é sempre obrigatório pelo contrato; o que é opcional é a
    subclasse lexical. Sem ela, a secção lexical do relatório fica ausente — é
    a leitura correta, não uma degradação."""
    state = _classification_state()
    report = _minimal_report(
        diagnostic_report_version=4,
        questions=(
            diagnostic.QuestionDiagnostic(
                question_id="q",
                question="Quando decorre o evento sintético?",
                language="pt",
                expected_answer="10 de março de 2031",
                extraction=state[4],
                fact_pair_proximity=(),
                chunk_analysis=state[5],
                selected_version_eligibility=state[6],
                effective_version_eligibility=state[6],
                retrieval=state[7],
                primary_conclusion=diagnostic.PrimaryConclusion.PRE_GENERATION_PIPELINE_OK,
                findings=(),
                evidence_summary=(),
            ),
        ),
    )
    assert report.questions[0].lexical_trace is None
    rendered = diagnostic.render_markdown(report)
    assert "#### Trace do retrieval lexical" not in rendered


def test_page_summary_builder_tolerates_malformed_details() -> None:
    summaries, native_pages, ocr_pages, low_pages = (
        diagnostic._build_extraction_page_summaries(
            [
                {"page_number": 1, "method": "native", "quality": "high",
                 "extracted_characters": 10},
                {"page_number": "x", "method": 3, "ocr_confidence": "abc"},
                "entrada inválida",
                {"page_number": 2, "method": "ocr", "quality": "low",
                 "ocr_confidence": 55, "warning": "w\x00arn"},
            ]
        )
    )
    assert native_pages == 1 and ocr_pages == 1 and low_pages == 1
    assert len(summaries) == 3  # a entrada não-dict é ignorada
    assert summaries[1].page_number is None and summaries[1].method is None
    assert summaries[2].ocr_confidence == 55.0
    assert "\x00" not in (summaries[2].warning or "")
    assert diagnostic._build_extraction_page_summaries(None) == ((), None, None, None)
