"""Baseline lexical de evidências usando PostgreSQL Full-Text Search.

Suporta perguntas naturais através de pesquisa progressiva (ver
app.retrieval.query_planning): a consulta exata atual, depois os termos
informativos com AND e, por fim, com OR. A primeira estratégia que
produzir evidências vence; resultados e scores de estratégias diferentes
nunca são misturados nem comparados entre si.
"""

import logging

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.document_version import DocumentVersion
from app.retrieval.base import Evidence, RetrievalContext
from app.retrieval.query_planning import LexicalQueryVariant, plan_lexical_query

logger = logging.getLogger(__name__)


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
        plan = plan_lexical_query(query, context.language)
        for variant in plan.variants:
            evidence = self._execute_variant(db, variant, context, top_k, official_only)
            if evidence:
                # Apenas metadados operacionais: nunca a pergunta, os
                # termos extraídos ou o conteúdo documental.
                logger.info(
                    "Lexical retrieval: strategy=%s results=%d institution=%s language=%s",
                    variant.strategy,
                    len(evidence),
                    context.institution_id,
                    context.language,
                )
                return evidence
        logger.info(
            "Lexical retrieval: no results strategies=%d institution=%s language=%s",
            len(plan.variants),
            context.institution_id,
            context.language,
        )
        return []

    def _execute_variant(
        self,
        db: Session,
        variant: LexicalQueryVariant,
        context: RetrievalContext,
        top_k: int,
        official_only: bool,
    ) -> list[Evidence]:
        # O texto da variante é sempre um parâmetro de websearch_to_tsquery
        # (bind param), nunca SQL interpolado.
        ts_query = func.websearch_to_tsquery("simple", variant.websearch_input)
        statement = self._build_statement(ts_query, context, top_k, official_only)
        return [_row_to_evidence(row) for row in db.execute(statement)]

    def _latest_processed_subquery(self, context: RetrievalContext):
        """Window restrita desde a origem à instituição e a versões
        processed: rn=1 é a maior version_number processada por documento."""
        return (
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

    def _build_statement(
        self,
        ts_query,
        context: RetrievalContext,
        top_k: int,
        official_only: bool,
    ) -> Select:
        """Seleção base partilhada por todas as estratégias: os filtros de
        instituição, estado, idioma, validade e versão são idênticos em
        todas as variantes e aplicados no PostgreSQL."""
        latest_processed = self._latest_processed_subquery(context)
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
        return statement


def _row_to_evidence(row) -> Evidence:
    return Evidence(
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
