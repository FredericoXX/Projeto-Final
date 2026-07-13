"""Reconstrói chunks de versões processed sem reextrair ficheiros.

Uso:
    python -m scripts.rebuild_document_chunks
    python -m scripts.rebuild_document_chunks --institution-id UUID
    python -m scripts.rebuild_document_chunks --document-id UUID
"""

import argparse
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.database.session import SessionLocal
from app.models.document_version import DocumentVersion
from app.services import document_chunk_service, document_chunking_service


@dataclass(frozen=True)
class RebuildSummary:
    versions_found: int
    versions_processed: int
    chunks_created: int
    failures: int


def rebuild_document_chunks(
    db: Session,
    *,
    institution_id: UUID | None = None,
    document_id: UUID | None = None,
) -> RebuildSummary:
    statement = select(DocumentVersion).where(
        DocumentVersion.processing_status == "processed",
        DocumentVersion.extracted_text.is_not(None),
    )
    if institution_id is not None:
        statement = statement.where(DocumentVersion.institution_id == institution_id)
    if document_id is not None:
        statement = statement.where(DocumentVersion.document_id == document_id)

    versions = list(
        db.scalars(statement.order_by(DocumentVersion.created_at, DocumentVersion.id)).all()
    )
    processed = 0
    chunks_created = 0
    failures = 0
    for version in versions:
        try:
            chunks = document_chunking_service.chunk_text(
                version.extracted_text or "",
                settings.document_chunk_size_chars,
                settings.document_chunk_overlap_chars,
            )
            entities = document_chunk_service.replace_version_chunks(db, version, chunks)
            db.commit()
        except Exception:
            db.rollback()
            failures += 1
        else:
            processed += 1
            chunks_created += len(entities)

    return RebuildSummary(
        versions_found=len(versions),
        versions_processed=processed,
        chunks_created=chunks_created,
        failures=failures,
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--institution-id", type=UUID)
    parser.add_argument("--document-id", type=UUID)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    with SessionLocal() as db:
        summary = rebuild_document_chunks(
            db,
            institution_id=args.institution_id,
            document_id=args.document_id,
        )
    print(f"Versions found: {summary.versions_found}")
    print(f"Versions processed: {summary.versions_processed}")
    print(f"Chunks created: {summary.chunks_created}")
    print(f"Failures: {summary.failures}")


if __name__ == "__main__":
    main()
