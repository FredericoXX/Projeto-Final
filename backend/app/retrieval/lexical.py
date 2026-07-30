"""Retrieval lexical de evidências institucionais (PostgreSQL FTS + rerank).

Duas etapas determinísticas e explicáveis:

- **Etapa A — candidate generation.** Planeia variantes da consulta (ver
  app.retrieval.query_planning), executa-as **todas** contra o índice GIN
  com a configuração FTS por idioma (app.retrieval.fts_config) e recolhe um
  conjunto limitado de candidatos elegíveis. Os filtros de segurança
  (instituição, estado, idioma, validade, official_only, versão processed
  mais recente) são idênticos em todas as variantes e aplicados no
  PostgreSQL, antes do reranking. Nenhuma variante devolve imediatamente:
  os candidatos de todas as variantes são agregados e deduplicados por
  chunk_id, preservando a melhor estratégia e o melhor score FTS cru.

- **Etapa B — reranking lexical determinístico.** Reordena os candidatos
  por uma política de cobertura/proximidade/estrutura (app.retrieval.
  reranking) e aplica um limiar mínimo de relevância. O score público da
  Evidence passa a ser a relevância lexical composta em [0, 1]; o score
  FTS cru fica disponível apenas no trace interno.

Sem embeddings, sem pesquisa vetorial/semântica, sem LLM, sem sinónimos.
Determinístico: a mesma entrada produz sempre a mesma ordenação.
"""

import logging
from dataclasses import dataclass, replace

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.document_version import DocumentVersion
from app.retrieval.base import Evidence, RetrievalContext
from app.retrieval.fts_config import resolve_fts_config
from app.retrieval.lexical_normalization import build_lexical_representation
from app.retrieval.query_planning import (
    LexicalQueryStrategy,
    LexicalQueryVariant,
    plan_lexical_query,
)
from app.retrieval.reranking import (
    LexicalCandidate,
    RankedCandidate,
    RemovalReason,
    rerank,
)

logger = logging.getLogger(__name__)

# --- Limites do candidate pool (constantes nomeadas, secção 19) -------------
# candidate_limit = min(MAX, max(MIN, top_k * MULTIPLIER)). Proporcional a
# top_k, com um mínimo razoável e um máximo absoluto: nunca uma consulta
# ilimitada, nunca todos os chunks da instituição.
CANDIDATE_MIN = 20
CANDIDATE_MAX = 100
CANDIDATE_MULTIPLIER = 5

# Ordem de qualidade das estratégias, para escolher a melhor quando um chunk
# é recuperado por várias variantes (exact > reduced_and > reduced_or).
_STRATEGY_RANK: dict[LexicalQueryStrategy, int] = {
    LexicalQueryStrategy.EXACT: 3,
    LexicalQueryStrategy.REDUCED_AND: 2,
    LexicalQueryStrategy.REDUCED_OR: 1,
}

# Nº máximo de candidatos excluídos a registar no trace (evita traces enormes).
_MAX_EXCLUDED_IN_TRACE = 20


@dataclass(frozen=True)
class VariantTrace:
    strategy: str
    candidate_count: int


@dataclass(frozen=True)
class RankedResultTrace:
    """Linha auditável do ranking — apenas métricas, nunca conteúdo."""

    chunk_id: str
    document_id: str
    chunk_index: int
    strategy: str
    raw_score: float
    score: float
    coverage: float
    exact_phrase: float
    proximity: float
    title_overlap: float
    section_overlap: float
    structure_type: str | None
    matched_terms: tuple[str, ...]
    reason: str
    # Presente apenas nas linhas excluídas: motivo estável da remoção
    # ("below_threshold" ou "dominated").
    removal_reason: str | None = None


@dataclass(frozen=True)
class LexicalRetrievalTrace:
    """Trace interno do retrieval lexical (diagnóstico e testes).

    Não altera o comportamento da pesquisa, não é endpoint público, não
    contém documentos completos nem segredos: só metadados de ranking e as
    formas canónicas dos termos da consulta.
    """

    fts_config: str
    informative_terms: tuple[str, ...]
    query_ordinals: tuple[int, ...]
    query_ranges: tuple[str, ...]
    planned_variants: tuple[str, ...]
    variant_candidate_counts: tuple[VariantTrace, ...]
    candidate_limit: int
    candidate_ceiling: int
    unique_candidate_count: int
    candidates_before_threshold: int
    removed_by_threshold: int
    removed_by_dominance: int
    results: tuple[RankedResultTrace, ...]
    excluded: tuple[RankedResultTrace, ...]


def _candidate_limit(top_k: int) -> int:
    return min(CANDIDATE_MAX, max(CANDIDATE_MIN, top_k * CANDIDATE_MULTIPLIER))


def _apply_candidate_ceiling(candidates: list[LexicalCandidate]) -> list[LexicalCandidate]:
    """Limita o pool agregado a CANDIDATE_MAX, deterministicamente.

    A ordenação é por melhor score FTS cru (desc) e desempates estáveis;
    só corta quando o total agregado das variantes excede o teto (caso de
    top_k elevado). Cada variante já foi limitada a candidate_limit em SQL.
    """
    if len(candidates) <= CANDIDATE_MAX:
        return candidates
    ordered = sorted(
        candidates,
        key=lambda candidate: (
            -candidate.raw_score,
            str(candidate.document_id),
            candidate.chunk_index,
            str(candidate.chunk_id),
        ),
    )
    return ordered[:CANDIDATE_MAX]


def _better_strategy(
    left: LexicalQueryStrategy, right: LexicalQueryStrategy
) -> LexicalQueryStrategy:
    return left if _STRATEGY_RANK[left] >= _STRATEGY_RANK[right] else right


class PostgresLexicalRetriever:
    """Retriever substituível: candidate generation FTS + rerank lexical."""

    def search(
        self,
        db: Session,
        query: str,
        context: RetrievalContext,
        top_k: int,
        official_only: bool,
    ) -> list[Evidence]:
        evidence, _trace = self.search_with_trace(db, query, context, top_k, official_only)
        return evidence

    def search_with_trace(
        self,
        db: Session,
        query: str,
        context: RetrievalContext,
        top_k: int,
        official_only: bool,
    ) -> tuple[list[Evidence], LexicalRetrievalTrace]:
        """Como ``search``, mas devolve também o trace interno auditável.

        Executa a pesquisa exatamente uma vez; o trace é um subproduto, não
        uma segunda pesquisa. O ``Retriever`` genérico não depende deste
        método (o diagnóstico usa-o opcionalmente por introspeção).
        """
        fts_config = resolve_fts_config(context.language)
        plan = plan_lexical_query(query, context.language)
        candidate_limit = _candidate_limit(top_k)

        candidates: dict = {}
        variant_traces: list[VariantTrace] = []
        for variant in plan.variants:
            rows = self._execute_variant(
                db, variant, context, candidate_limit, official_only, fts_config.value
            )
            variant_traces.append(VariantTrace(variant.strategy.value, len(rows)))
            for row in rows:
                self._merge_candidate(candidates, row, variant.strategy)

        # Teto global do candidate pool: cada variante já trouxe no máximo
        # candidate_limit candidatos; a agregação de N variantes é limitada a
        # CANDIDATE_MAX no total, deterministicamente, por melhor score FTS
        # cru. Garante que o reranker nunca recebe um pool ilimitado.
        pool = _apply_candidate_ceiling(list(candidates.values()))

        result = rerank(
            query,
            pool,
            context.language,
            min_relevance_score=settings.retrieval_min_relevance_score,
        )
        top_results = result.ranked[:top_k]
        evidence = [_ranked_to_evidence(ranked) for ranked in top_results]

        trace = self._build_trace(
            query=query,
            language=context.language,
            fts_config=fts_config.value,
            plan_variants=tuple(variant.strategy.value for variant in plan.variants),
            variant_traces=tuple(variant_traces),
            candidate_limit=candidate_limit,
            unique_candidate_count=len(candidates),
            result=result,
            top_results=top_results,
        )

        # Apenas metadados operacionais: nunca a pergunta, os termos ou o
        # conteúdo documental (ver secção 41 do Momento 4).
        logger.info(
            "Lexical retrieval: fts=%s variants=%d candidates=%d results=%d "
            "thresholded=%d dominated=%d institution=%s language=%s",
            fts_config.value,
            len(plan.variants),
            len(candidates),
            len(evidence),
            len(result.removed_by_threshold),
            len(result.removed_by_dominance),
            context.institution_id,
            context.language,
        )
        return evidence, trace

    def _merge_candidate(
        self, candidates: dict, row, strategy: LexicalQueryStrategy
    ) -> None:
        existing: LexicalCandidate | None = candidates.get(row.chunk_id)
        if existing is None:
            candidates[row.chunk_id] = _row_to_candidate(row, strategy)
            return
        candidates[row.chunk_id] = replace(
            existing,
            strategy=_better_strategy(existing.strategy, strategy),
            raw_score=max(existing.raw_score, float(row.score)),
        )

    def _execute_variant(
        self,
        db: Session,
        variant: LexicalQueryVariant,
        context: RetrievalContext,
        candidate_limit: int,
        official_only: bool,
        fts_config_name: str,
    ) -> list:
        # O texto da variante e o nome da configuração são sempre parâmetros
        # (bind params) de websearch_to_tsquery, nunca SQL interpolado. O
        # nome da configuração provém de uma allowlist fechada.
        ts_query = func.websearch_to_tsquery(fts_config_name, variant.websearch_input)
        statement = self._build_statement(ts_query, context, candidate_limit, official_only)
        return list(db.execute(statement))

    def _latest_processed_subquery(self, context: RetrievalContext):
        """Window restrita à instituição e a versões processed: rn=1 é a
        maior version_number processada por documento."""
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
        candidate_limit: int,
        official_only: bool,
    ) -> Select:
        """Seleção base partilhada por todas as variantes.

        Traz numa única consulta (sem N+1) tudo o que o reranking e o
        diagnóstico precisam, incluindo os metadados estruturais usados só
        internamente. Os filtros são idênticos aos da baseline e aplicados
        no PostgreSQL antes do reranking. O LIMIT é o candidate_limit, não
        o top_k final.
        """
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
                DocumentChunk.normalized_content,
                score,
                DocumentChunk.language,
                Document.official_source,
                Document.source_url,
                Document.valid_from,
                Document.valid_until,
                DocumentChunk.page_number,
                DocumentChunk.section_title,
                DocumentChunk.structure_type,
                DocumentChunk.chunking_strategy,
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
            # Ordenação apenas para escolher deterministicamente os
            # candidate_limit candidatos por variante; a ordenação final é
            # feita pelo reranker.
            .order_by(
                score.desc(),
                Document.id.asc(),
                DocumentChunk.chunk_index.asc(),
                DocumentChunk.id.asc(),
            )
            .limit(candidate_limit)
        )
        if official_only:
            statement = statement.where(Document.official_source.is_(True))
        return statement

    def _build_trace(
        self,
        *,
        query: str,
        language: str,
        fts_config: str,
        plan_variants: tuple[str, ...],
        variant_traces: tuple[VariantTrace, ...],
        candidate_limit: int,
        unique_candidate_count: int,
        result,
        top_results: tuple[RankedCandidate, ...],
    ) -> LexicalRetrievalTrace:
        representation = build_lexical_representation(query, language)
        ordinals = tuple(
            token.ordinal for token in representation.tokens if token.ordinal is not None
        )
        ranges = tuple(numeric_range.canonical for numeric_range in representation.ranges)
        excluded: list[RankedResultTrace] = [
            _ranked_to_trace(ranked, RemovalReason.DOMINATED.value)
            for ranked in result.removed_by_dominance
        ]
        excluded += [
            _ranked_to_trace(ranked, RemovalReason.BELOW_THRESHOLD.value)
            for ranked in result.removed_by_threshold
        ]
        candidates_before_threshold = (
            len(result.ranked)
            + len(result.removed_by_threshold)
            + len(result.removed_by_dominance)
        )
        return LexicalRetrievalTrace(
            fts_config=fts_config,
            informative_terms=result.query_terms,
            query_ordinals=ordinals,
            query_ranges=ranges,
            planned_variants=plan_variants,
            variant_candidate_counts=variant_traces,
            candidate_limit=candidate_limit,
            candidate_ceiling=CANDIDATE_MAX,
            unique_candidate_count=unique_candidate_count,
            candidates_before_threshold=candidates_before_threshold,
            removed_by_threshold=len(result.removed_by_threshold),
            removed_by_dominance=len(result.removed_by_dominance),
            results=tuple(_ranked_to_trace(ranked) for ranked in top_results),
            excluded=tuple(excluded[:_MAX_EXCLUDED_IN_TRACE]),
        )


def _row_to_candidate(row, strategy: LexicalQueryStrategy) -> LexicalCandidate:
    return LexicalCandidate(
        chunk_id=row.chunk_id,
        document_id=row.document_id,
        document_version_id=row.document_version_id,
        document_title=row.document_title,
        chunk_index=row.chunk_index,
        content=row.content,
        normalized_content=row.normalized_content,
        language=row.language,
        official_source=row.official_source,
        source_url=row.source_url,
        valid_from=row.valid_from,
        valid_until=row.valid_until,
        page_number=row.page_number,
        section_title=row.section_title,
        structure_type=row.structure_type,
        chunking_strategy=row.chunking_strategy,
        raw_score=float(row.score),
        strategy=strategy,
    )


def _ranked_to_evidence(ranked: RankedCandidate) -> Evidence:
    candidate = ranked.candidate
    return Evidence(
        chunk_id=candidate.chunk_id,
        document_id=candidate.document_id,
        document_version_id=candidate.document_version_id,
        document_title=candidate.document_title,
        chunk_index=candidate.chunk_index,
        content=candidate.content,
        # Score público = relevância lexical composta em [0, 1] (secção 22).
        score=ranked.score,
        language=candidate.language,
        official_source=candidate.official_source,
        source_url=candidate.source_url,
        valid_from=candidate.valid_from,
        valid_until=candidate.valid_until,
    )


def _ranked_to_trace(
    ranked: RankedCandidate, removal_reason: str | None = None
) -> RankedResultTrace:
    candidate = ranked.candidate
    features = ranked.features
    return RankedResultTrace(
        chunk_id=str(candidate.chunk_id),
        document_id=str(candidate.document_id),
        chunk_index=candidate.chunk_index,
        strategy=candidate.strategy.value,
        raw_score=candidate.raw_score,
        score=ranked.score,
        coverage=features.coverage,
        exact_phrase=features.exact_phrase,
        proximity=features.proximity,
        title_overlap=features.title_overlap,
        section_overlap=features.section_overlap,
        structure_type=candidate.structure_type,
        matched_terms=tuple(sorted(features.matched_terms)),
        reason=ranked.reason,
        removal_reason=removal_reason,
    )
