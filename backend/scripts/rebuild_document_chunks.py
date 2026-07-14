"""Reconstrói chunks de versões processed sem reextrair ficheiros.

Uso:
    python -m scripts.rebuild_document_chunks
    python -m scripts.rebuild_document_chunks --institution-id UUID
    python -m scripts.rebuild_document_chunks --document-id UUID
"""

import argparse
import logging
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.database.session import SessionLocal
from app.models.document_version import DocumentVersion
from app.services import (
    document_chunk_service,
    document_chunking_service,
    message_source_service,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RebuildSummary:
    versions_found: int
    versions_processed: int
    chunks_created: int
    skipped_referenced: int
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

    version_ids = list(
        db.scalars(
            statement.with_only_columns(DocumentVersion.id).order_by(
                DocumentVersion.created_at, DocumentVersion.id
            )
        ).all()
    )
    # A lista de IDs é um snapshot escalar. Cada versão é recarregada e
    # bloqueada numa transação curta própria antes de qualquer substituição.
    db.rollback()
    processed = 0
    chunks_created = 0
    skipped_referenced = 0
    failures = 0
    for version_id in version_ids:
        try:
            version = db.scalar(
                select(DocumentVersion)
                .where(
                    DocumentVersion.id == version_id,
                    DocumentVersion.processing_status == "processed",
                    DocumentVersion.extracted_text.is_not(None),
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if version is None:
                failures += 1
                logger.warning(
                    "Document chunk rebuild skipped: version_id=%s reason=state_changed",
                    version_id,
                )
                db.rollback()
                continue
            if message_source_service.is_document_version_referenced(
                db,
                version_id=version.id,
                document_id=version.document_id,
                institution_id=version.institution_id,
            ):
                skipped_referenced += 1
                logger.info(
                    "Document chunk rebuild skipped: version_id=%s reason=referenced",
                    version.id,
                )
                db.rollback()
                continue

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
            # Só o id e um motivo controlado; nunca conteúdo ou traceback.
            logger.error(
                "Document chunk rebuild failed: version_id=%s reason=rebuild_failed",
                version_id,
            )
        else:
            processed += 1
            chunks_created += len(entities)

    return RebuildSummary(
        versions_found=len(version_ids),
        versions_processed=processed,
        chunks_created=chunks_created,
        skipped_referenced=skipped_referenced,
        failures=failures,
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--institution-id", type=UUID)
    parser.add_argument("--document-id", type=UUID)
    return parser.parse_args()


def main() -> None:
    # Ativa apenas os eventos operacionais controlados do script isolado.
    logging.basicConfig(level=logging.INFO)
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
    print(f"Skipped referenced: {summary.skipped_referenced}")
    print(f"Failures: {summary.failures}")


if __name__ == "__main__":
    main()
