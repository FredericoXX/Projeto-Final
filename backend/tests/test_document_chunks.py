"""Testes dos chunks documentais: constraints PostgreSQL do modelo
DocumentChunk, integração com o processamento/reprocessamento e
independência entre versões e instituições.

Corre contra a base de dados de teste dedicada (ver conftest.py) — as
constraints compostas e os CHECKs são validados no PostgreSQL real,
nunca em SQLite.
"""

import hashlib
import io
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.models.document_chunk import DocumentChunk
from app.models.document_version import DocumentVersion
from app.services import (
    document_chunk_service,
    document_chunking_service,
    document_processing_service,
)
from app.services.document_extraction_service import ExtractionError
from app.storage import get_document_storage

_ADMIN_PASSWORD = "supersecret123"

BOOTSTRAP_HEADERS = {"X-Bootstrap-Token": settings.bootstrap_token or ""}


def _institution_payload() -> dict:
    return {
        "name": "Test Institution",
        "code": f"TST-{uuid.uuid4().hex[:8].upper()}",
        "default_language": "pt",
        "supported_languages": ["pt", "en"],
    }


def _create_institution(client: TestClient) -> str:
    response = client.post(
        "/api/v1/institutions", json=_institution_payload(), headers=BOOTSTRAP_HEADERS
    )
    assert response.status_code == 201
    return response.json()["id"]


def _create_admin_and_login(client: TestClient, institution_id: str) -> dict[str, str]:
    payload = {
        "institution_id": institution_id,
        "full_name": "Admin User",
        "email": f"admin-{uuid.uuid4().hex[:8]}@example.com",
        "password": _ADMIN_PASSWORD,
    }
    response = client.post(
        "/api/v1/auth/register-initial-admin", json=payload, headers=BOOTSTRAP_HEADERS
    )
    assert response.status_code == 201

    login = client.post(
        "/api/v1/auth/login",
        json={"email": payload["email"], "password": _ADMIN_PASSWORD},
    )
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _create_document(client: TestClient, headers: dict[str, str], **overrides: object) -> dict:
    payload: dict = {"title": "Test Document"}
    payload.update(overrides)
    response = client.post("/api/v1/documents", json=payload, headers=headers)
    assert response.status_code == 201
    return response.json()


def _upload(
    client: TestClient,
    headers: dict[str, str],
    document_id: str,
    content: bytes,
    filename: str = "notes.txt",
):
    return client.post(
        f"/api/v1/documents/{document_id}/versions",
        files={"file": (filename, io.BytesIO(content), "text/plain")},
        headers=headers,
    )


def _setup(client: TestClient) -> tuple[str, dict[str, str], dict]:
    institution_id = _create_institution(client)
    headers = _create_admin_and_login(client, institution_id)
    document = _create_document(client, headers)
    return institution_id, headers, document


def _setup_with_version(
    client: TestClient, content: bytes = b"conteudo de teste para chunks"
) -> tuple[str, dict[str, str], dict, dict]:
    institution_id, headers, document = _setup(client)
    upload = _upload(client, headers, document["id"], content)
    assert upload.status_code == 201
    return institution_id, headers, document, upload.json()


def _chunk_kwargs(
    institution_id: str,
    document_id: str,
    version_id: str,
    **overrides: object,
) -> dict:
    content = "conteúdo válido do chunk"
    kwargs: dict = {
        "institution_id": uuid.UUID(institution_id),
        "document_id": uuid.UUID(document_id),
        "document_version_id": uuid.UUID(version_id),
        "chunk_index": 0,
        "content": content,
        "normalized_content": "conteudo valido do chunk",
        "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "start_char": 0,
        "end_char": len(content),
        "language": "pt",
    }
    kwargs.update(overrides)
    return kwargs


def _count_chunks(session: Session, version_id: str) -> int:
    return (
        session.scalar(
            select(func.count())
            .select_from(DocumentChunk)
            .where(DocumentChunk.document_version_id == uuid.UUID(version_id))
        )
        or 0
    )


# --- Constraints do modelo (PostgreSQL real) ---------------------------------


def test_valid_chunk_creation(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> None:
    institution_id, _, document, version = _setup_with_version(client)

    session = test_session_factory()
    try:
        # O processamento já criou chunks (índices a partir de 0); este
        # insere manualmente o índice seguinte.
        next_index = _count_chunks(session, version["id"])
        chunk = DocumentChunk(
            **_chunk_kwargs(
                institution_id, document["id"], version["id"], chunk_index=next_index
            )
        )
        session.add(chunk)
        session.commit()

        stored = session.get(DocumentChunk, chunk.id)
        assert stored is not None
        assert stored.institution_id == uuid.UUID(institution_id)
        assert stored.document_id == uuid.UUID(document["id"])
        assert stored.document_version_id == uuid.UUID(version["id"])
        assert stored.created_at is not None
    finally:
        session.close()


@pytest.mark.parametrize(
    "overrides",
    [
        {"chunk_index": -1},
        {"start_char": -1},
        {"start_char": 10, "end_char": 10},
        {"start_char": 10, "end_char": 5},
        # btrim(...) por omissão corta espaços: vazio e só-espaços são
        # rejeitados (o chunker nunca produz conteúdo whitespace-only; a
        # constraint é defesa em profundidade).
        {"content": ""},
        {"content": "   "},
        {"normalized_content": ""},
        {"normalized_content": "   "},
    ],
)
def test_invalid_chunk_values_are_rejected_by_postgres(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
    overrides: dict,
) -> None:
    institution_id, _, document, version = _setup_with_version(client)

    session = test_session_factory()
    try:
        next_index = _count_chunks(session, version["id"])
        kwargs = _chunk_kwargs(
            institution_id, document["id"], version["id"], chunk_index=next_index
        )
        kwargs.update(overrides)
        session.add(DocumentChunk(**kwargs))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
    finally:
        session.close()


def test_duplicate_chunk_index_in_same_version_is_rejected(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> None:
    institution_id, _, document, version = _setup_with_version(client)

    session = test_session_factory()
    try:
        # O índice 0 já existe (criado pelo processamento do upload).
        assert _count_chunks(session, version["id"]) >= 1
        session.add(
            DocumentChunk(
                **_chunk_kwargs(institution_id, document["id"], version["id"], chunk_index=0)
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
    finally:
        session.close()


def test_cross_institution_chunk_is_rejected_by_postgres(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> None:
    _, _, document_a, version_a = _setup_with_version(client)

    institution_b = _create_institution(client)
    _create_admin_and_login(client, institution_b)

    session = test_session_factory()
    try:
        # Versão e documento da instituição A com institution_id da B: a
        # foreign key composta rejeita a combinação, mesmo que todos os ids
        # existam individualmente.
        session.add(
            DocumentChunk(
                **_chunk_kwargs(
                    institution_b,
                    document_a["id"],
                    version_a["id"],
                    chunk_index=99,
                )
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
    finally:
        session.close()


def test_chunk_with_wrong_document_is_rejected_by_postgres(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> None:
    institution_id, headers, _, version_a = _setup_with_version(client)
    other_document = _create_document(client, headers, title="Outro Documento")

    session = test_session_factory()
    try:
        # Versão do documento A associada ao documento B (mesma instituição):
        # a foreign key composta também rejeita esta combinação.
        session.add(
            DocumentChunk(
                **_chunk_kwargs(
                    institution_id,
                    other_document["id"],
                    version_a["id"],
                    chunk_index=99,
                )
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
    finally:
        session.close()


def test_equal_chunks_in_different_versions_are_allowed(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> None:
    institution_id, headers, document, version_1 = _setup_with_version(client)
    upload_2 = _upload(client, headers, document["id"], b"conteudo diferente da versao dois")
    assert upload_2.status_code == 201
    version_2 = upload_2.json()

    session = test_session_factory()
    try:
        # O mesmo chunk_index e o mesmo checksum podem existir em versões
        # diferentes: a unicidade é por (document_version_id, chunk_index).
        index_1 = _count_chunks(session, version_1["id"])
        index_2 = _count_chunks(session, version_2["id"])
        shared = _chunk_kwargs(institution_id, document["id"], version_1["id"])
        session.add(
            DocumentChunk(**{**shared, "chunk_index": index_1})
        )
        session.add(
            DocumentChunk(
                **{
                    **shared,
                    "document_version_id": uuid.UUID(version_2["id"]),
                    "chunk_index": index_2,
                }
            )
        )
        session.commit()
    finally:
        session.close()


# --- Processamento cria chunks -------------------------------------------------


def test_successful_processing_creates_chunks(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> None:
    text = "Primeiro parágrafo do documento.\n\nSegundo parágrafo, com mais texto."
    institution_id, _, document, version = _setup_with_version(client, text.encode())
    assert version["processing_status"] == "processed"

    session = test_session_factory()
    try:
        chunks = document_chunk_service.list_version_chunks(session, uuid.UUID(version["id"]))
        assert len(chunks) >= 1
        for position, chunk in enumerate(chunks):
            assert chunk.chunk_index == position
            assert chunk.institution_id == uuid.UUID(institution_id)
            assert chunk.document_id == uuid.UUID(document["id"])
            assert chunk.language == document["language"]
            # Os offsets reconstroem o content a partir do texto extraído.
            assert chunk.content == text[chunk.start_char : chunk.end_char]
            assert (
                chunk.content_sha256
                == hashlib.sha256(chunk.content.encode("utf-8")).hexdigest()
            )
    finally:
        session.close()


def test_processing_creates_expected_chunk_count(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "document_chunk_size_chars", 40)
    monkeypatch.setattr(settings, "document_chunk_overlap_chars", 8)

    text = "Parágrafo um do regulamento.\n\nParágrafo dois do regulamento.\n\n" + (
        "Texto corrido bastante mais longo do que a janela configurada. " * 4
    )
    _, _, _, version = _setup_with_version(client, text.encode())
    assert version["processing_status"] == "processed"

    expected = document_chunking_service.chunk_text(text, 40, 8)
    assert len(expected) > 1

    session = test_session_factory()
    try:
        stored = document_chunk_service.list_version_chunks(session, uuid.UUID(version["id"]))
        assert len(stored) == len(expected)
        assert [c.content for c in stored] == [c.content for c in expected]
        assert [c.content_sha256 for c in stored] == [c.content_sha256 for c in expected]
        assert [(c.start_char, c.end_char) for c in stored] == [
            (c.start_char, c.end_char) for c in expected
        ]
    finally:
        session.close()


def test_extracted_text_remains_stored_alongside_chunks(client: TestClient) -> None:
    text = "Texto extraído que continua disponível no endpoint de conteúdo."
    _, headers, document, version = _setup_with_version(client, text.encode())

    response = client.get(
        f"/api/v1/documents/{document['id']}/versions/{version['id']}/content",
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["text"] == text


def test_failed_extraction_creates_no_chunks(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> None:
    # Bytes inválidos em UTF-8: a versão é criada (201) mas fica failed.
    _, _, _, version = _setup_with_version(client, b"\xff\xfe invalid utf-8")
    assert version["processing_status"] == "failed"

    session = test_session_factory()
    try:
        assert _count_chunks(session, version["id"]) == 0
    finally:
        session.close()


def test_chunk_persistence_failure_marks_version_failed_without_partial_chunks(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_replace = document_chunk_service.replace_version_chunks

    def failing_replace(db, version, chunks):  # type: ignore[no-untyped-def]
        # Insere realmente os chunks (ficam pendentes na transação) e só
        # depois falha: o rollback tem de os descartar todos.
        real_replace(db, version, chunks)
        msg = "simulated chunk persistence failure"
        raise RuntimeError(msg)

    monkeypatch.setattr(document_chunk_service, "replace_version_chunks", failing_replace)

    text = "Parágrafo um.\n\nParágrafo dois.\n\nParágrafo três."
    _, _, _, version = _setup_with_version(client, text.encode())

    # A versão nunca fica processed sem os chunks persistidos.
    assert version["processing_status"] == "failed"
    assert version["processing_error"] == document_processing_service.CHUNKING_ERROR_MESSAGE
    assert "Traceback" not in version["processing_error"]
    assert "SQL" not in version["processing_error"]

    session = test_session_factory()
    try:
        assert _count_chunks(session, version["id"]) == 0
    finally:
        session.close()


def test_chunk_commit_failure_marks_version_failed_without_partial_chunks(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Uma falha no commit final também é uma falha de persistência.

    O primeiro commit grava processing; o segundo, que confirmaria chunks +
    processed, falha; o terceiro grava failed depois do rollback.
    """
    _, _, _, version = _setup_with_version(
        client, b"conteudo inicialmente processado para testar commit"
    )
    version_id = uuid.UUID(version["id"])

    session = test_session_factory()
    try:
        stored_version = session.get(DocumentVersion, version_id)
        assert stored_version is not None
        real_commit = session.commit
        commit_calls = 0

        def fail_final_chunk_commit() -> None:
            nonlocal commit_calls
            commit_calls += 1
            if commit_calls == 2:
                msg = "simulated final chunk commit failure"
                raise RuntimeError(msg)
            real_commit()

        monkeypatch.setattr(session, "commit", fail_final_chunk_commit)

        processed = document_processing_service.reprocess_version(
            session,
            stored_version,
            get_document_storage(),
        )

        assert commit_calls == 3
        assert processed.processing_status == "failed"
        assert processed.processing_error == document_processing_service.CHUNKING_ERROR_MESSAGE
    finally:
        session.close()

    verify = test_session_factory()
    try:
        assert _count_chunks(verify, version["id"]) == 0
        stored_version = verify.get(DocumentVersion, version_id)
        assert stored_version is not None
        assert stored_version.processing_status == "failed"
    finally:
        verify.close()


# --- Reprocessamento -------------------------------------------------------------


def test_reprocessing_replaces_chunks_without_duplicates(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = "Um parágrafo razoavelmente longo para ser dividido em vários chunks. " * 5
    _, headers, document, version = _setup_with_version(client, text.encode())

    session = test_session_factory()
    try:
        original = document_chunk_service.list_version_chunks(session, uuid.UUID(version["id"]))
        original_ids = {chunk.id for chunk in original}
        assert original_ids
    finally:
        session.close()

    # Reprocessa com uma janela diferente: o conjunto tem de ser substituído
    # por inteiro (linhas novas), sem duplicar índices.
    monkeypatch.setattr(settings, "document_chunk_size_chars", 60)
    monkeypatch.setattr(settings, "document_chunk_overlap_chars", 10)
    response = client.post(
        f"/api/v1/documents/{document['id']}/versions/{version['id']}/reprocess",
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["processing_status"] == "processed"

    session = test_session_factory()
    try:
        replaced = document_chunk_service.list_version_chunks(session, uuid.UUID(version["id"]))
        replaced_ids = {chunk.id for chunk in replaced}
        assert replaced_ids.isdisjoint(original_ids)
        indices = [chunk.chunk_index for chunk in replaced]
        assert indices == list(range(len(replaced)))
        expected = document_chunking_service.chunk_text(text, 60, 10)
        assert len(replaced) == len(expected)
    finally:
        session.close()


def test_reprocessing_same_settings_keeps_chunk_count_stable(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> None:
    text = "Conteúdo estável para reprocessamento idempotente.\n\nSegundo parágrafo."
    _, headers, document, version = _setup_with_version(client, text.encode())

    session = test_session_factory()
    try:
        count_before = _count_chunks(session, version["id"])
    finally:
        session.close()

    for _ in range(2):
        response = client.post(
            f"/api/v1/documents/{document['id']}/versions/{version['id']}/reprocess",
            headers=headers,
        )
        assert response.status_code == 200

    session = test_session_factory()
    try:
        chunks = document_chunk_service.list_version_chunks(session, uuid.UUID(version["id"]))
        assert len(chunks) == count_before
        indices = [chunk.chunk_index for chunk in chunks]
        assert indices == sorted(set(indices))
    finally:
        session.close()


def test_reprocessing_one_version_does_not_touch_another(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> None:
    _, headers, document, version_1 = _setup_with_version(
        client, b"conteudo da primeira versao do documento"
    )
    upload_2 = _upload(client, headers, document["id"], b"conteudo da segunda versao, distinto")
    assert upload_2.status_code == 201
    version_2 = upload_2.json()

    session = test_session_factory()
    try:
        v1_ids_before = {
            chunk.id
            for chunk in document_chunk_service.list_version_chunks(
                session, uuid.UUID(version_1["id"])
            )
        }
        assert v1_ids_before
    finally:
        session.close()

    response = client.post(
        f"/api/v1/documents/{document['id']}/versions/{version_2['id']}/reprocess",
        headers=headers,
    )
    assert response.status_code == 200

    session = test_session_factory()
    try:
        v1_ids_after = {
            chunk.id
            for chunk in document_chunk_service.list_version_chunks(
                session, uuid.UUID(version_1["id"])
            )
        }
        assert v1_ids_after == v1_ids_before
    finally:
        session.close()


def test_new_version_keeps_previous_version_chunks(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> None:
    _, headers, document, version_1 = _setup_with_version(
        client, b"versao historica que mantem os seus chunks"
    )

    upload_2 = _upload(client, headers, document["id"], b"nova versao com conteudo novo")
    assert upload_2.status_code == 201
    version_2 = upload_2.json()

    session = test_session_factory()
    try:
        assert _count_chunks(session, version_1["id"]) >= 1
        assert _count_chunks(session, version_2["id"]) >= 1
    finally:
        session.close()


def test_failed_reprocessing_removes_stale_chunks(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, headers, document, version = _setup_with_version(
        client, b"conteudo processado com sucesso na primeira passagem"
    )

    session = test_session_factory()
    try:
        assert _count_chunks(session, version["id"]) >= 1
    finally:
        session.close()

    def failing_extract(*_args: object, **_kwargs: object):  # type: ignore[no-untyped-def]
        msg = "No extractable text was found in this document."
        raise ExtractionError(msg)

    monkeypatch.setattr(document_processing_service, "extract_text", failing_extract)

    response = client.post(
        f"/api/v1/documents/{document['id']}/versions/{version['id']}/reprocess",
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["processing_status"] == "failed"

    # Uma versão failed não mantém chunks (equivalência chunks <=> processed):
    # os do processamento anterior foram removidos na mesma transação.
    session = test_session_factory()
    try:
        assert _count_chunks(session, version["id"]) == 0
    finally:
        session.close()
