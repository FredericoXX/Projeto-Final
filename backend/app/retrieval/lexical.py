"""Baseline lexical de evidências usando PostgreSQL Full-Text Search."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.document_version import DocumentVersion
from app.retrieval.base import Evidence, RetrievalContext


class PostgresLexicalRetriever:
    """Retriever substituível baseado em TSVECTOR/GIN e ranking lexical."""

    def search(
        self,
        db: Session,
        query: str,
        context: RetrievalContext,
        top_k: int,
        official_only: bool,
    ) -> list[Evidence]:
        # Window restrita desde a origem à instituição e a versões processed:
        # rn=1 representa a maior version_number processada de cada documento.
        latest_processed = (
            select(
                DocumentVersion.id.label("version_id"),
                DocumentVersion.document_id.label("document_id"),
                func.row_number()
                .over(
                    partition_by=DocumentVersion.document_id,
                    order_by=DocumentVersion.version_number.desc(),
                )
                .label("rn"),
            )
            .where(
                DocumentVersion.institution_id == context.institution_id,
                DocumentVersion.processing_status == "processed",
            )
            .subquery("latest_processed_versions")
        )

        ts_query = func.websearch_to_tsquery("simple", query)
        score = func.ts_rank_cd(DocumentChunk.search_vector, ts_query).label("score")

        statement = (
            select(
                DocumentChunk.id.label("chunk_id"),
                Document.id.label("document_id"),
                DocumentChunk.document_version_id.label("document_version_id"),
                Document.title.label("document_title"),
                DocumentChunk.chunk_index,
                DocumentChunk.content,
                score,
                DocumentChunk.language,
                Document.official_source,
                Document.source_url,
                Document.valid_from,
                Document.valid_until,
            )
            .join(Document, Document.id == DocumentChunk.document_id)
            .join(
                latest_processed,
                (latest_processed.c.version_id == DocumentChunk.document_version_id)
                & (latest_processed.c.document_id == DocumentChunk.document_id),
            )
            .where(
                latest_processed.c.rn == 1,
                DocumentChunk.institution_id == context.institution_id,
                Document.institution_id == context.institution_id,
                Document.is_active.is_(True),
                Document.language == context.language,
                DocumentChunk.language == context.language,
                (Document.valid_from.is_(None))
                | (Document.valid_from <= context.reference_date),
                (Document.valid_until.is_(None))
                | (Document.valid_until >= context.reference_date),
                DocumentChunk.search_vector.op("@@")(ts_query),
            )
            .order_by(
                score.desc(),
                Document.id.asc(),
                DocumentChunk.chunk_index.asc(),
                DocumentChunk.id.asc(),
            )
            .limit(top_k)
        )
        if official_only:
            statement = statement.where(Document.official_source.is_(True))

        return [
            Evidence(
                chunk_id=row.chunk_id,
                document_id=row.document_id,
                document_version_id=row.document_version_id,
                document_title=row.document_title,
                chunk_index=row.chunk_index,
                content=row.content,
                score=float(row.score),
                language=row.language,
                official_source=row.official_source,
                source_url=row.source_url,
                valid_from=row.valid_from,
                valid_until=row.valid_until,
            )
            for row in db.execute(statement)
        ]
