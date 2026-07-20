"""Regressões de imutabilidade para versões citadas por respostas persistidas.

Os testes usam o PostgreSQL real da suite e um gerador local determinístico.
Não há chamadas de rede nem dependência de ``OPENAI_API_KEY``.
"""

import io
import threading
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.answering.base import AnswerGenerator, AnsweringContext, GeneratedAnswer
from app.answering.dependencies import get_answer_generator
from app.core.config import settings
from app.core.exceptions import ConflictError
from app.main import app
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.document_version import DocumentVersion
from app.models.message import Message
from app.models.message_source import MessageSource
from app.schemas.answering import AnswerSourceRead
from app.services import document_processing_service, message_source_service
from app.services.document_extraction_service import ExtractionResult
from app.storage import get_document_storage
from scripts.rebuild_document_chunks import rebuild_document_chunks

BOOTSTRAP_HEADERS = {"X-Bootstrap-Token": settings.bootstrap_token or ""}
_ADMIN_PASSWORD = "supersecret123"


class _FirstEvidenceGenerator:
    """Gerador puramente local que cita sempre a primeira evidência."""

    def generate(self, context: AnsweringContext) -> GeneratedAnswer:
        return GeneratedAnswer(
            answer="A informação consta da fonte institucional citada.",
            cited_evidence_ids=(context.evidence[0].evidence_id,),
        )


@pytest.fixture
def local_answer_generator() -> Iterator[AnswerGenerator]:
    generator = _FirstEvidenceGenerator()
    app.dependency_overrides[get_answer_generator] = lambda: generator
    yield generator
    app.dependency_overrides.pop(get_answer_generator, None)


def _create_institution(client: TestClient) -> dict:
    response = client.post(
        "/api/v1/institutions",
        json={
            "name": "Instituição de Referências",
            "code": f"REF-{uuid.uuid4().hex[:8].upper()}",
            "default_language": "pt",
            "supported_languages": ["pt", "en"],
        },
        headers=BOOTSTRAP_HEADERS,
    )
    assert response.status_code == 201
    return response.json()


def _create_admin(
    client: TestClient, institution_id: str
) -> tuple[dict[str, str], uuid.UUID]:
    email = f"admin-{uuid.uuid4().hex[:8]}@example.com"
    registered = client.post(
        "/api/v1/auth/register-initial-admin",
        json={
            "institution_id": institution_id,
            "full_name": "Admin References",
            "email": email,
            "password": _ADMIN_PASSWORD,
        },
        headers=BOOTSTRAP_HEADERS,
    )
    assert registered.status_code == 201
    login = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": _ADMIN_PASSWORD},
    )
    assert login.status_code == 200
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    return headers, uuid.UUID(registered.json()["id"])


def _create_document(
    client: TestClient,
    headers: dict[str, str],
    *,
    title: str = "Regulamento Institucional",
) -> dict:
    response = client.post(
        "/api/v1/documents",
        json={
            "title": title,
            "language": "pt",
            "official_source": True,
            "source_url": f"https://example.edu/{uuid.uuid4().hex}",
        },
        headers=headers,
    )
    assert response.status_code == 201
    return response.json()


def _upload(
    client: TestClient,
    headers: dict[str, str],
    document_id: str,
    text: str,
) -> dict:
    response = client.post(
        f"/api/v1/documents/{document_id}/versions",
        files={
            "file": (
                f"document-{uuid.uuid4().hex[:8]}.txt",
                io.BytesIO(text.encode()),
                "text/plain",
            )
        },
        headers=headers,
    )
    assert response.status_code == 201
    assert response.json()["processing_status"] == "processed"
    return response.json()


def _create_conversation(client: TestClient, headers: dict[str, str]) -> dict:
    response = client.post(
        "/api/v1/conversations",
        json={"title": "Consulta documental", "language": "pt"},
        headers=headers,
    )
    assert response.status_code == 201
    return response.json()


def _ask(
    client: TestClient,
    headers: dict[str, str],
    conversation_id: str,
    query: str,
) -> dict:
    response = client.post(
        f"/api/v1/conversations/{conversation_id}/ask",
        json={"query": query, "language": "pt", "official_only": True},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "answered"
    assert len(body["assistant_message"]["sources"]) == 1
    return body


def _chunks(db: Session, version_id: uuid.UUID) -> list[DocumentChunk]:
    return list(
        db.scalars(
            select(DocumentChunk)
            .where(DocumentChunk.document_version_id == version_id)
            .order_by(DocumentChunk.chunk_index)
        ).all()
    )


def _chunk_snapshot(db: Session, version_id: uuid.UUID) -> tuple[tuple[object, ...], ...]:
    return tuple(
        (
            chunk.id,
            chunk.chunk_index,
            chunk.content,
            chunk.normalized_content,
            chunk.content_sha256,
            chunk.start_char,
            chunk.end_char,
            chunk.language,
        )
        for chunk in _chunks(db, version_id)
    )


def _chunk_semantics(db: Session, version_id: uuid.UUID) -> tuple[tuple[object, ...], ...]:
    return tuple(snapshot[1:] for snapshot in _chunk_snapshot(db, version_id))


def _message_source_snapshot(source: MessageSource) -> tuple[object, ...]:
    return (
        source.id,
        source.institution_id,
        source.message_id,
        source.message_role,
        source.chunk_id,
        source.document_id,
        source.document_version_id,
        source.evidence_id,
        source.citation_index,
        source.document_title,
        source.chunk_index,
        source.source_url,
        source.official_source,
        source.language,
        source.valid_from,
        source.valid_until,
        source.content_sha256,
        source.created_at,
    )


@dataclass(frozen=True)
class _VersionState:
    processing_status: str
    processing_error: str | None
    extracted_text: str | None
    page_count: int | None
    processed_at: datetime | None
    chunks: tuple[tuple[object, ...], ...]


def _version_state(db: Session, version_id: uuid.UUID) -> _VersionState:
    version = db.get(DocumentVersion, version_id)
    assert version is not None
    return _VersionState(
        processing_status=version.processing_status,
        processing_error=version.processing_error,
        extracted_text=version.extracted_text,
        page_count=version.page_count,
        processed_at=version.processed_at,
        chunks=_chunk_snapshot(db, version_id),
    )


def _source_dto(db: Session, document_id: uuid.UUID, version_id: uuid.UUID) -> AnswerSourceRead:
    document = db.get(Document, document_id)
    assert document is not None
    chunk = db.scalar(
        select(DocumentChunk)
        .where(DocumentChunk.document_version_id == version_id)
        .order_by(DocumentChunk.chunk_index)
        .limit(1)
    )
    assert chunk is not None
    source = AnswerSourceRead(
        evidence_id="E1",
        chunk_id=chunk.id,
        document_id=document.id,
        document_version_id=version_id,
        document_title=document.title,
        chunk_index=chunk.chunk_index,
        source_url=document.source_url,
        official_source=document.official_source,
        language=document.language,
        valid_from=document.valid_from,
        valid_until=document.valid_until,
    )
    source.set_internal_content_sha256(chunk.content_sha256)
    return source


def _create_assistant_message(
    client: TestClient,
    headers: dict[str, str],
    db_factory: sessionmaker[Session],
    *,
    institution_id: uuid.UUID,
    user_id: uuid.UUID,
) -> uuid.UUID:
    conversation = _create_conversation(client, headers)
    user_message = client.post(
        f"/api/v1/conversations/{conversation['id']}/messages",
        json={"content": "Pergunta para concorrência", "language": "pt"},
        headers=headers,
    )
    assert user_message.status_code == 201

    db = db_factory()
    try:
        assistant = Message(
            conversation_id=uuid.UUID(conversation["id"]),
            institution_id=institution_id,
            user_id=None,
            role="assistant",
            content="Resposta pendente de associação à fonte.",
            language="pt",
            reply_to_message_id=uuid.UUID(user_message.json()["id"]),
            extra_metadata={"answer_status": "answered"},
        )
        db.add(assistant)
        db.commit()
        return assistant.id
    finally:
        db.close()


def _count_sources(db: Session, version_id: uuid.UUID) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(MessageSource)
            .where(MessageSource.document_version_id == version_id)
        )
        or 0
    )


def test_referenced_version_returns_409_without_mutating_history(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
    local_answer_generator: AnswerGenerator,
) -> None:
    institution = _create_institution(client)
    headers, _ = _create_admin(client, institution["id"])
    document = _create_document(client, headers)
    version = _upload(
        client,
        headers,
        document["id"],
        "prazo matricula setembro regulamento historico",
    )
    conversation = _create_conversation(client, headers)
    answer = _ask(client, headers, conversation["id"], "prazo matricula setembro")
    source_id = uuid.UUID(answer["assistant_message"]["sources"][0]["id"])
    version_id = uuid.UUID(version["id"])

    db = test_session_factory()
    try:
        before_version = _version_state(db, version_id)
        source = db.get(MessageSource, source_id)
        assert source is not None
        before_source = _message_source_snapshot(source)
    finally:
        db.close()

    response = client.post(
        f"/api/v1/documents/{document['id']}/versions/{version['id']}/reprocess",
        headers=headers,
    )
    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "resource_conflict",
        "message": message_source_service.REFERENCED_VERSION_MESSAGE,
    }

    db = test_session_factory()
    try:
        assert _version_state(db, version_id) == before_version
        source = db.get(MessageSource, source_id)
        assert source is not None
        assert _message_source_snapshot(source) == before_source
        assert _count_sources(db, version_id) == 1
    finally:
        db.close()


def test_unreferenced_version_can_be_reprocessed(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
) -> None:
    institution = _create_institution(client)
    headers, _ = _create_admin(client, institution["id"])
    document = _create_document(client, headers)
    version = _upload(client, headers, document["id"], "versao sem qualquer referencia")
    version_id = uuid.UUID(version["id"])

    db = test_session_factory()
    try:
        before_ids = {chunk.id for chunk in _chunks(db, version_id)}
        before_semantics = _chunk_semantics(db, version_id)
        assert before_ids
        assert _count_sources(db, version_id) == 0
    finally:
        db.close()

    response = client.post(
        f"/api/v1/documents/{document['id']}/versions/{version['id']}/reprocess",
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["id"] == version["id"]
    assert response.json()["version_number"] == 1
    assert response.json()["processing_status"] == "processed"

    db = test_session_factory()
    try:
        after_ids = {chunk.id for chunk in _chunks(db, version_id)}
        assert after_ids
        assert before_ids.isdisjoint(after_ids)
        assert _chunk_semantics(db, version_id) == before_semantics
        assert _count_sources(db, version_id) == 0
    finally:
        db.close()


def test_new_version_is_used_without_rewriting_old_answer_history(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
    local_answer_generator: AnswerGenerator,
) -> None:
    institution = _create_institution(client)
    headers, _ = _create_admin(client, institution["id"])
    document = _create_document(client, headers)
    version_1 = _upload(
        client,
        headers,
        document["id"],
        "calendario matricula setembro versao antiga",
    )
    conversation = _create_conversation(client, headers)
    answer_1 = _ask(client, headers, conversation["id"], "calendario matricula setembro")
    source_1_id = uuid.UUID(answer_1["assistant_message"]["sources"][0]["id"])

    db = test_session_factory()
    try:
        source_1 = db.get(MessageSource, source_1_id)
        assert source_1 is not None
        source_1_before = _message_source_snapshot(source_1)
    finally:
        db.close()

    version_2 = _upload(
        client,
        headers,
        document["id"],
        "calendario matricula setembro versao nova atualizada",
    )
    assert version_2["version_number"] == 2
    answer_2 = _ask(client, headers, conversation["id"], "calendario matricula setembro")

    returned_1 = answer_1["assistant_message"]["sources"][0]
    returned_2 = answer_2["assistant_message"]["sources"][0]
    assert returned_1["document_version_id"] == version_1["id"]
    assert returned_2["document_version_id"] == version_2["id"]
    assert returned_1["chunk_id"] != returned_2["chunk_id"]

    db = test_session_factory()
    try:
        source_1 = db.get(MessageSource, source_1_id)
        assert source_1 is not None
        assert _message_source_snapshot(source_1) == source_1_before

        sources = list(
            db.scalars(
                select(MessageSource).order_by(MessageSource.created_at, MessageSource.id)
            ).all()
        )
        assert {source.document_version_id for source in sources} == {
            uuid.UUID(version_1["id"]),
            uuid.UUID(version_2["id"]),
        }
        assert db.get(DocumentChunk, source_1.chunk_id) is not None
        assert _chunks(db, uuid.UUID(version_1["id"]))
        assert _chunks(db, uuid.UUID(version_2["id"]))
    finally:
        db.close()


def test_rebuild_skips_referenced_and_remains_idempotent_for_other_versions(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
    local_answer_generator: AnswerGenerator,
) -> None:
    institution = _create_institution(client)
    headers, _ = _create_admin(client, institution["id"])

    referenced_document = _create_document(client, headers, title="Documento citado")
    referenced_version = _upload(
        client,
        headers,
        referenced_document["id"],
        "bolsa candidatura outubro documento citado",
    )
    conversation = _create_conversation(client, headers)
    _ask(client, headers, conversation["id"], "bolsa candidatura outubro")

    free_document = _create_document(client, headers, title="Documento não citado")
    free_version = _upload(
        client,
        headers,
        free_document["id"],
        "biblioteca horario prolongado documento livre",
    )
    referenced_id = uuid.UUID(referenced_version["id"])
    free_id = uuid.UUID(free_version["id"])

    db = test_session_factory()
    try:
        referenced_before = _chunk_snapshot(db, referenced_id)
        free_before_ids = {chunk.id for chunk in _chunks(db, free_id)}
        free_semantics = _chunk_semantics(db, free_id)

        first = rebuild_document_chunks(db, institution_id=uuid.UUID(institution["id"]))
        referenced_after_first = _chunk_snapshot(db, referenced_id)
        free_after_first_ids = {chunk.id for chunk in _chunks(db, free_id)}

        assert first.versions_found == 2
        assert first.versions_processed == 1
        assert first.skipped_referenced == 1
        assert first.failures == 0
        assert first.chunks_created == len(free_after_first_ids)
        assert referenced_after_first == referenced_before
        assert free_before_ids.isdisjoint(free_after_first_ids)
        assert _chunk_semantics(db, free_id) == free_semantics

        second = rebuild_document_chunks(db, institution_id=uuid.UUID(institution["id"]))
        free_after_second_ids = {chunk.id for chunk in _chunks(db, free_id)}

        assert second == first
        assert _chunk_snapshot(db, referenced_id) == referenced_before
        assert free_after_first_ids.isdisjoint(free_after_second_ids)
        assert _chunk_semantics(db, free_id) == free_semantics
        assert _count_sources(db, referenced_id) == 1
        assert _count_sources(db, free_id) == 0
    finally:
        db.close()


def test_concurrent_source_first_makes_reprocessing_fail_without_extraction(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    institution = _create_institution(client)
    headers, user_id = _create_admin(client, institution["id"])
    institution_id = uuid.UUID(institution["id"])
    document = _create_document(client, headers)
    version = _upload(client, headers, document["id"], "fonte primeiro concorrencia")
    document_id = uuid.UUID(document["id"])
    version_id = uuid.UUID(version["id"])
    assistant_id = _create_assistant_message(
        client,
        headers,
        test_session_factory,
        institution_id=institution_id,
        user_id=user_id,
    )

    setup_db = test_session_factory()
    try:
        source_dto = _source_dto(setup_db, document_id, version_id)
        before = _version_state(setup_db, version_id)
    finally:
        setup_db.close()

    source_locked = threading.Event()
    reprocess_started = threading.Event()
    source_errors: list[Exception] = []
    reprocess_errors: list[Exception] = []
    extraction_calls = 0
    result_lock = threading.Lock()

    def unexpected_extract(*_args: object, **_kwargs: object) -> ExtractionResult:
        nonlocal extraction_calls
        with result_lock:
            extraction_calls += 1
        return ExtractionResult(text="não deveria extrair", page_count=None)

    monkeypatch.setattr(document_processing_service, "extract_text", unexpected_extract)
    storage = get_document_storage()

    def persist_source() -> None:
        db = test_session_factory()
        try:
            snapshots = message_source_service.revalidate_and_lock_sources(
                db,
                institution_id=institution_id,
                cited_sources=[source_dto],
                language="pt",
                reference_date=datetime.now(UTC).date(),
                official_only=True,
            )
            assistant = db.get(Message, assistant_id)
            assert assistant is not None
            message_source_service.create_message_sources(
                db, assistant_message=assistant, snapshots=snapshots
            )
            db.flush()
            source_locked.set()
            if not reprocess_started.wait(timeout=10):
                raise TimeoutError("reprocessing did not enter the race")
            db.commit()
        except Exception as exc:  # noqa: BLE001 - recolhido para asserção
            db.rollback()
            source_errors.append(exc)
            source_locked.set()
        finally:
            db.close()

    def reprocess() -> None:
        db = test_session_factory()
        try:
            stored = db.get(DocumentVersion, version_id)
            assert stored is not None
            reprocess_started.set()
            document_processing_service.reprocess_version(db, stored, storage)
        except Exception as exc:  # noqa: BLE001 - recolhido para asserção
            db.rollback()
            reprocess_errors.append(exc)
        finally:
            db.close()

    source_thread = threading.Thread(target=persist_source)
    source_thread.start()
    assert source_locked.wait(timeout=10)
    reprocess_thread = threading.Thread(target=reprocess)
    reprocess_thread.start()

    for thread in (source_thread, reprocess_thread):
        thread.join(timeout=15)
        assert not thread.is_alive()

    assert source_errors == []
    assert len(reprocess_errors) == 1
    assert isinstance(reprocess_errors[0], ConflictError)
    assert str(reprocess_errors[0]) == message_source_service.REFERENCED_VERSION_MESSAGE
    assert extraction_calls == 0

    db = test_session_factory()
    try:
        assert _version_state(db, version_id) == before
        assert _count_sources(db, version_id) == 1
    finally:
        db.close()


def test_concurrent_reprocessing_first_rejects_stale_source_then_completes(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    institution = _create_institution(client)
    headers, user_id = _create_admin(client, institution["id"])
    institution_id = uuid.UUID(institution["id"])
    document = _create_document(client, headers)
    version = _upload(client, headers, document["id"], "reprocessamento primeiro fonte")
    document_id = uuid.UUID(document["id"])
    version_id = uuid.UUID(version["id"])
    assistant_id = _create_assistant_message(
        client,
        headers,
        test_session_factory,
        institution_id=institution_id,
        user_id=user_id,
    )

    setup_db = test_session_factory()
    try:
        stale_source = _source_dto(setup_db, document_id, version_id)
        old_chunk_ids = {chunk.id for chunk in _chunks(setup_db, version_id)}
    finally:
        setup_db.close()

    extraction_started = threading.Event()
    release_extraction = threading.Event()
    source_finished = threading.Event()
    reprocess_results: list[str] = []
    reprocess_errors: list[Exception] = []
    source_errors: list[Exception] = []

    def blocking_extract(*_args: object, **_kwargs: object) -> ExtractionResult:
        extraction_started.set()
        if not release_extraction.wait(timeout=10):
            raise TimeoutError("source validation did not finish")
        return ExtractionResult(text="reprocessamento primeiro fonte", page_count=None)

    monkeypatch.setattr(document_processing_service, "extract_text", blocking_extract)
    storage = get_document_storage()

    def reprocess() -> None:
        db = test_session_factory()
        try:
            stored = db.get(DocumentVersion, version_id)
            assert stored is not None
            result = document_processing_service.reprocess_version(db, stored, storage)
            reprocess_results.append(result.processing_status)
        except Exception as exc:  # noqa: BLE001 - recolhido para asserção
            db.rollback()
            reprocess_errors.append(exc)
        finally:
            db.close()

    def persist_stale_source() -> None:
        db = test_session_factory()
        try:
            snapshots = message_source_service.revalidate_and_lock_sources(
                db,
                institution_id=institution_id,
                cited_sources=[stale_source],
                language="pt",
                reference_date=datetime.now(UTC).date(),
                official_only=True,
            )
            assistant = db.get(Message, assistant_id)
            assert assistant is not None
            message_source_service.create_message_sources(
                db, assistant_message=assistant, snapshots=snapshots
            )
            db.commit()
        except Exception as exc:  # noqa: BLE001 - recolhido para asserção
            db.rollback()
            source_errors.append(exc)
        finally:
            db.close()
            source_finished.set()

    reprocess_thread = threading.Thread(target=reprocess)
    reprocess_thread.start()
    assert extraction_started.wait(timeout=10)

    source_thread = threading.Thread(target=persist_stale_source)
    source_thread.start()
    assert source_finished.wait(timeout=10)
    release_extraction.set()

    for thread in (source_thread, reprocess_thread):
        thread.join(timeout=15)
        assert not thread.is_alive()

    assert reprocess_errors == []
    assert reprocess_results == ["processed"]
    assert len(source_errors) == 1
    assert isinstance(source_errors[0], ConflictError)
    assert str(source_errors[0]) == message_source_service.SOURCES_CHANGED_MESSAGE

    db = test_session_factory()
    try:
        assert _count_sources(db, version_id) == 0
        version_row = db.get(DocumentVersion, version_id)
        assert version_row is not None
        assert version_row.processing_status == "processed"
        new_chunk_ids = {chunk.id for chunk in _chunks(db, version_id)}
        assert new_chunk_ids
        assert old_chunk_ids.isdisjoint(new_chunk_ids)
    finally:
        db.close()


def test_reverse_multi_version_source_orders_do_not_deadlock(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
) -> None:
    """Duas transações citam as mesmas versões em ordens opostas.

    ``revalidate_and_lock_sources`` deve ordenar UUIDs antes de ``FOR UPDATE``;
    por isso ambas terminam, ainda que uma espere pela outra.
    """
    institution = _create_institution(client)
    headers, user_id = _create_admin(client, institution["id"])
    institution_id = uuid.UUID(institution["id"])
    document_a = _create_document(client, headers, title="Fonte concorrente A")
    document_b = _create_document(client, headers, title="Fonte concorrente B")
    version_a = _upload(client, headers, document_a["id"], "conteudo concorrente alfa")
    version_b = _upload(client, headers, document_b["id"], "conteudo concorrente beta")
    assistant_a = _create_assistant_message(
        client,
        headers,
        test_session_factory,
        institution_id=institution_id,
        user_id=user_id,
    )
    assistant_b = _create_assistant_message(
        client,
        headers,
        test_session_factory,
        institution_id=institution_id,
        user_id=user_id,
    )

    setup_db = test_session_factory()
    try:
        source_a = _source_dto(
            setup_db, uuid.UUID(document_a["id"]), uuid.UUID(version_a["id"])
        )
        source_b = _source_dto(
            setup_db, uuid.UUID(document_b["id"]), uuid.UUID(version_b["id"])
        )
    finally:
        setup_db.close()

    orders = (
        (
            assistant_a,
            [source_a, source_b.model_copy(update={"evidence_id": "E2"})],
        ),
        (
            assistant_b,
            [source_b, source_a.model_copy(update={"evidence_id": "E2"})],
        ),
    )
    barrier = threading.Barrier(2)
    errors: list[Exception] = []

    def persist(assistant_id: uuid.UUID, sources: list[AnswerSourceRead]) -> None:
        db = test_session_factory()
        try:
            barrier.wait(timeout=10)
            snapshots = message_source_service.revalidate_and_lock_sources(
                db,
                institution_id=institution_id,
                cited_sources=sources,
                language="pt",
                reference_date=datetime.now(UTC).date(),
                official_only=True,
            )
            assistant = db.get(Message, assistant_id)
            assert assistant is not None
            message_source_service.create_message_sources(
                db, assistant_message=assistant, snapshots=snapshots
            )
            db.commit()
        except Exception as exc:  # noqa: BLE001 - recolhido para asserção
            db.rollback()
            errors.append(exc)
        finally:
            db.close()

    threads = [threading.Thread(target=persist, args=order) for order in orders]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)
        assert not thread.is_alive(), "possible database deadlock"

    assert errors == []
    db = test_session_factory()
    try:
        for assistant_id, _ in orders:
            count = db.scalar(
                select(func.count())
                .select_from(MessageSource)
                .where(MessageSource.message_id == assistant_id)
            )
            assert count == 2
    finally:
        db.close()
