"""Testes do script administrativo idempotente de reconstrução de chunks."""

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.models.document_chunk import DocumentChunk
from app.models.document_version import DocumentVersion
from scripts.rebuild_document_chunks import rebuild_document_chunks
from tests.test_retrieval import (
    _create_admin,
    _create_document,
    _create_institution,
    _upload,
)


def _count_chunks(db: Session, version_id: str) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(DocumentChunk)
            .where(DocumentChunk.document_version_id == uuid.UUID(version_id))
        )
        or 0
    )


def test_processed_version_without_chunks_receives_chunks(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> None:
    institution = _create_institution(client)
    headers, _ = _create_admin(client, institution["id"])
    document = _create_document(client, headers)
    version = _upload(client, headers, document["id"], b"texto para reconstruir chunks")

    session = test_session_factory()
    try:
        session.execute(
            delete(DocumentChunk).where(
                DocumentChunk.document_version_id == uuid.UUID(version["id"])
            )
        )
        session.commit()
        assert _count_chunks(session, version["id"]) == 0

        summary = rebuild_document_chunks(session)
        assert summary.versions_found == 1
        assert summary.versions_processed == 1
        assert summary.chunks_created >= 1
        assert summary.processed_versions == 1
        assert summary.structured_versions == 1
        assert summary.generated_chunks >= 1
        assert summary.table_row_chunks == 0
        assert summary.fallback_chunks == 0
        assert summary.failures == 0
        assert _count_chunks(session, version["id"]) >= 1
        rebuilt = list(
            session.scalars(
                select(DocumentChunk).where(
                    DocumentChunk.document_version_id == uuid.UUID(version["id"])
                )
            ).all()
        )
        assert all(chunk.page_number == 1 for chunk in rebuilt)
        assert all(chunk.chunking_strategy == "structured_v1" for chunk in rebuilt)
    finally:
        session.close()


def test_rebuild_replaces_existing_set_and_is_idempotent(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> None:
    institution = _create_institution(client)
    headers, _ = _create_admin(client, institution["id"])
    document = _create_document(client, headers)
    version = _upload(client, headers, document["id"], b"conteudo estavel para reconstruir")

    session = test_session_factory()
    try:
        before_ids = set(
            session.scalars(
                select(DocumentChunk.id).where(
                    DocumentChunk.document_version_id == uuid.UUID(version["id"])
                )
            ).all()
        )
        first = rebuild_document_chunks(session)
        after_first = set(
            session.scalars(
                select(DocumentChunk.id).where(
                    DocumentChunk.document_version_id == uuid.UUID(version["id"])
                )
            ).all()
        )
        second = rebuild_document_chunks(session)
        after_second = set(
            session.scalars(
                select(DocumentChunk.id).where(
                    DocumentChunk.document_version_id == uuid.UUID(version["id"])
                )
            ).all()
        )
        assert before_ids.isdisjoint(after_first)
        assert after_first.isdisjoint(after_second)
        assert first.chunks_created == second.chunks_created == len(after_second)
        assert _count_chunks(session, version["id"]) == len(after_second)
    finally:
        session.close()


def test_failed_and_pending_versions_are_ignored(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> None:
    institution = _create_institution(client)
    headers, _ = _create_admin(client, institution["id"])
    document = _create_document(client, headers)
    failed = _upload(client, headers, document["id"], b"\xff\xfe invalid")
    pending = _upload(client, headers, document["id"], b"conteudo que sera pendente")

    session = test_session_factory()
    try:
        pending_row = session.get(DocumentVersion, uuid.UUID(pending["id"]))
        assert pending_row is not None
        pending_row.processing_status = "pending"
        session.commit()
        summary = rebuild_document_chunks(session)
        assert summary.versions_found == 0
        assert summary.versions_processed == 0
        assert _count_chunks(session, failed["id"]) == 0
    finally:
        session.close()


def test_rebuild_filters_and_institution_isolation(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> None:
    institution_a = _create_institution(client)
    headers_a, _ = _create_admin(client, institution_a["id"])
    document_a = _create_document(client, headers_a)
    version_a = _upload(client, headers_a, document_a["id"], b"conteudo instituicao alfa")

    institution_b = _create_institution(client)
    headers_b, _ = _create_admin(client, institution_b["id"])
    document_b = _create_document(client, headers_b)
    version_b = _upload(client, headers_b, document_b["id"], b"conteudo instituicao beta")

    session = test_session_factory()
    try:
        ids_b_before = set(
            session.scalars(
                select(DocumentChunk.id).where(
                    DocumentChunk.document_version_id == uuid.UUID(version_b["id"])
                )
            ).all()
        )
        by_institution = rebuild_document_chunks(
            session, institution_id=uuid.UUID(institution_a["id"])
        )
        assert by_institution.versions_found == 1
        ids_b_after = set(
            session.scalars(
                select(DocumentChunk.id).where(
                    DocumentChunk.document_version_id == uuid.UUID(version_b["id"])
                )
            ).all()
        )
        assert ids_b_after == ids_b_before

        by_document = rebuild_document_chunks(
            session, document_id=uuid.UUID(document_a["id"])
        )
        assert by_document.versions_found == 1
        assert _count_chunks(session, version_a["id"]) >= 1
    finally:
        session.close()
