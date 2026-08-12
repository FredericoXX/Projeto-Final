"""Retrieval lexical de evidências institucionais (PostgreSQL FTS + rerank).

Duas etapas determinísticas e explicáveis:

- **Etapa A — candidate generation.** Planeia variantes da consulta (ver
  app.retrieval.query_planning) e calcula **antes de qualquer consulta**
  um orçamento global de candidatos, distribuído por quotas entre as
  variantes ativas por ordem de prioridade. Cada variante é executada
  contra o índice GIN com a configuração FTS por idioma
  (app.retrieval.fts_config), limitada em SQL à sua quota — nenhuma
  consulta corre sem LIMIT. A admissibilidade documental (instituição,
  estado, idioma, validade, official_only, versão processed mais recente)
  **não é definida aqui**: vem de ``RetrievalEligibility``, em
  app.documents.retrievability, é idêntica em todas as variantes e
  continua aplicada no PostgreSQL. Os candidatos são agregados e
  deduplicados por chunk_id, preservando a melhor estratégia e o melhor
  score FTS cru.

  Como a soma das quotas nunca excede o orçamento, **não existe qualquer
  corte global por FTS cru depois da agregação**: tudo o que as consultas
  devolvem é avaliado. A única seleção por ``ts_rank_cd`` acontece dentro
  da quota **reservada** de cada variante, entre candidatos dessa mesma
  variante — um candidato ``exact`` nunca perde o lugar para candidatos de
  variantes menos prioritárias, por mais alto que seja o FTS destes. Uma
  variante cujas correspondências excedam a própria quota continua, essa
  sim, a ficar pelos melhores ``ts_rank_cd``: o orçamento é finito por
  desenho.

- **Etapa B — elegibilidade e ranking.** Cada candidato passa primeiro
  por uma decisão de elegibilidade (app.retrieval.eligibility) baseada só
  no conteúdo, e só os elegíveis são pontuados e ordenados
  (app.retrieval.reranking), com um limiar mínimo de relevância aplicado a
  todos. O score público da Evidence é a relevância lexical composta em
  [0, 1]; o score FTS cru fica disponível apenas no trace interno.

Sem embeddings, sem pesquisa vetorial/semântica, sem LLM, sem sinónimos.
Determinístico: a mesma entrada produz sempre a mesma ordenação.
"""

import logging
from dataclasses import dataclass, replace

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.documents.retrievability import (
    RetrievabilityContext,
    RetrievalEligibility,
    latest_processed_version_subquery,
)
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.document_version import DocumentVersion
from app.retrieval.base import (
    Evidence,
    RetrievalContext,
    RetrievalResult,
    RetrievalTrace,
    ScoreKind,
    ScoreSemantics,
)
from app.retrieval.eligibility import ExclusionReason
from app.retrieval.fts_config import resolve_fts_config
from app.retrieval.lexical_normalization import build_lexical_representation
from app.retrieval.query_planning import (
    STRATEGY_PRIORITY,
    LexicalQueryStrategy,
    LexicalQueryVariant,
    plan_lexical_query,
)
from app.retrieval.reranking import (
    SCORING_VERSION,
    ExcludedCandidate,
    LexicalCandidate,
    RankedCandidate,
    RerankResult,
    rerank,
)

logger = logging.getLogger(__name__)

# Semântica do score devolvido por este retriever. Constante: não depende da
# pergunta nem do resultado, só da política de scoring do módulo de reranking.
# `comparable_across_queries` é False por derivação do algoritmo, não por
# prudência — ver ScoreSemantics em app.retrieval.base.
LEXICAL_SCORE_SEMANTICS = ScoreSemantics(
    kind=ScoreKind.LEXICAL_RELEVANCE,
    version=SCORING_VERSION,
    comparable_across_queries=False,
)

# --- Orçamento global do candidate pool -------------------------------------
# global_candidate_limit = min(MAX, max(MIN, top_k * MULTIPLIER)). Proporcional
# a top_k, com um mínimo razoável e um máximo absoluto. É calculado **antes**
# das consultas e repartido por quotas entre as variantes: nunca uma consulta
# ilimitada, nunca todos os chunks da instituição, e nunca um corte a
# posteriori que descarte candidatos já recuperados.
CANDIDATE_MIN = 20
CANDIDATE_MAX = 100
CANDIDATE_MULTIPLIER = 5

# Nº máximo de linhas de detalhe a registar no trace (evita traces enormes).
# As **contagens** do trace abrangem sempre todos os candidatos.
MAX_TRACE_DETAIL_ROWS = 20


@dataclass(frozen=True)
class VariantTrace:
    """Orçamento e resultado de uma variante do plano."""

    strategy: str
    quota: int
    returned_count: int


@dataclass(frozen=True)
class RankedResultTrace:
    """Linha auditável de um resultado — apenas métricas, nunca conteúdo."""

    chunk_id: str
    document_id: str
    chunk_index: int
    strategy: str
    raw_score: float
    score: float
    coverage: float
    exact_phrase: float
    ordered: float
    proximity: float
    title_overlap: float
    section_overlap: float
    structure_type: str | None
    matched_terms: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class ExcludedCandidateTrace:
    """Linha auditável de um candidato excluído, com motivo tipado.

    ``score`` é ``None`` quando a exclusão ocorreu antes da pontuação
    (falha de elegibilidade): os sinais auxiliares nem chegam a existir.
    """

    chunk_id: str
    document_id: str
    chunk_index: int
    strategy: str
    reason: str
    coverage: float
    matched_terms: tuple[str, ...]
    score: float | None


@dataclass(frozen=True)
class LexicalRetrievalTrace(RetrievalTrace):
    """Trace do retrieval lexical: a base neutra mais o detalhe da estratégia.

    Não altera o comportamento da pesquisa, não é endpoint público, não
    contém documentos completos nem segredos: só metadados de ranking e as
    formas canónicas dos termos da consulta.

    Invariantes garantidas por construção::

        sum(quota)                 <= global_candidate_limit
        sum(returned_count)        == total_returned_before_dedup
        unique_after_dedup         <= total_returned_before_dedup
        unique_after_dedup         <= global_candidate_limit
        candidates_evaluated       == unique_after_dedup
        candidates_evaluated       == result_count_before_limit
                                      + excluded_no_content_match
                                      + excluded_insufficient_coverage
                                      + excluded_below_threshold

    ``candidates_evaluated`` e ``result_count_before_limit`` são herdados de
    :class:`~app.retrieval.base.RetrievalTrace` — é por eles que este trace
    satisfaz o contrato neutro. ``result_count_before_limit`` conta os
    candidatos que sobreviveram à elegibilidade e ao limiar, **antes** do corte
    por ``top_k``: o ``top_k`` é uma escolha de apresentação, nunca uma exclusão
    por relevância. ``results`` detalha apenas os que foram efetivamente
    devolvidos.

    Os campos abaixo são específicos da estratégia lexical e por isso vivem
    aqui, e não na base: um retriever denso não tem variantes de tsquery nem
    cobertura de termos.
    """

    fts_config: str
    informative_terms: tuple[str, ...]
    query_ordinals: tuple[int, ...]
    query_ranges: tuple[str, ...]
    planned_variants: tuple[str, ...]
    global_candidate_limit: int
    variants: tuple[VariantTrace, ...]
    total_returned_before_dedup: int
    unique_after_dedup: int
    excluded_no_content_match: int
    excluded_insufficient_coverage: int
    excluded_below_threshold: int
    results: tuple[RankedResultTrace, ...]
    excluded: tuple[ExcludedCandidateTrace, ...]


def global_candidate_limit(top_k: int) -> int:
    """Orçamento total de candidatos para uma pesquisa (antes das consultas)."""
    return min(CANDIDATE_MAX, max(CANDIDATE_MIN, top_k * CANDIDATE_MULTIPLIER))


def distribute_quotas(limit: int, variant_count: int) -> tuple[int, ...]:
    """Reparte o orçamento global pelas variantes, por ordem de prioridade.

    Divisão inteira com o resto distribuído um a um pelas variantes mais
    prioritárias (as variantes já chegam ordenadas por
    ``STRATEGY_PRIORITY``). A soma das quotas é exatamente ``min(limit,
    ...)`` e nunca a excede; com o orçamento mínimo (20) e no máximo quatro
    variantes, nenhuma variante válida recebe quota zero.
    """
    if variant_count <= 0 or limit <= 0:
        return ()
    quotient, remainder = divmod(limit, variant_count)
    return tuple(
        quotient + (1 if index < remainder else 0) for index in range(variant_count)
    )


def _better_strategy(
    left: LexicalQueryStrategy, right: LexicalQueryStrategy
) -> LexicalQueryStrategy:
    return left if STRATEGY_PRIORITY[left] >= STRATEGY_PRIORITY[right] else right


class PostgresLexicalRetriever:
    """Retriever substituível: candidate generation FTS + rerank lexical."""

    def search(
        self,
        db: Session,
        query: str,
        context: RetrievalContext,
        top_k: int,
        official_only: bool,
    ) -> RetrievalResult:
        """Executa a pesquisa uma única vez e devolve evidência **e** trace.

        O trace é um subproduto desta mesma execução, nunca uma segunda
        pesquisa. Antes existia um ``search_with_trace`` separado e ``search``
        descartava o trace que ele produzia; o resultado era que o único
        consumidor do trace tinha de o descobrir por introspeção. Agora
        atravessa o contrato.
        """
        fts_config = resolve_fts_config(context.language)
        plan = plan_lexical_query(query, context.language)

        # Orçamento decidido antes de qualquer consulta e repartido por
        # quotas: o teto do pool é uma propriedade das consultas, não um
        # corte posterior.
        budget = global_candidate_limit(top_k)
        quotas = distribute_quotas(budget, len(plan.variants))

        candidates: dict = {}
        variant_traces: list[VariantTrace] = []
        total_returned = 0
        for variant, quota in zip(plan.variants, quotas, strict=True):
            rows = (
                self._execute_variant(
                    db, variant, context, quota, official_only, fts_config.value
                )
                if quota > 0
                else []
            )
            variant_traces.append(VariantTrace(variant.strategy.value, quota, len(rows)))
            total_returned += len(rows)
            for row in rows:
                self._merge_candidate(candidates, row, variant.strategy)

        result = rerank(
            query,
            list(candidates.values()),
            context.language,
            min_relevance_score=settings.retrieval_min_relevance_score,
        )
        top_results = result.ranked[:top_k]
        evidence = tuple(_ranked_to_evidence(ranked) for ranked in top_results)

        trace = self._build_trace(
            query=query,
            language=context.language,
            fts_config=fts_config.value,
            plan_variants=tuple(variant.strategy.value for variant in plan.variants),
            variant_traces=tuple(variant_traces),
            budget=budget,
            total_returned=total_returned,
            unique_candidate_count=len(candidates),
            result=result,
            top_results=top_results,
        )

        # Apenas metadados operacionais: nunca a pergunta, os termos ou o
        # conteúdo documental.
        logger.info(
            "Lexical retrieval: fts=%s variants=%d budget=%d unique=%d results=%d "
            "no_match=%d low_coverage=%d below_threshold=%d institution=%s language=%s",
            fts_config.value,
            len(plan.variants),
            budget,
            len(candidates),
            len(evidence),
            trace.excluded_no_content_match,
            trace.excluded_insufficient_coverage,
            trace.excluded_below_threshold,
            context.institution_id,
            context.language,
        )
        return RetrievalResult(
            evidence=evidence,
            trace=trace,
            score_semantics=LEXICAL_SCORE_SEMANTICS,
        )

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
        quota: int,
        official_only: bool,
        fts_config_name: str,
    ) -> list:
        # O texto da variante e o nome da configuração são sempre parâmetros
        # (bind params) de websearch_to_tsquery, nunca SQL interpolado. O
        # nome da configuração provém de uma allowlist fechada.
        ts_query = func.websearch_to_tsquery(fts_config_name, variant.websearch_input)
        statement = self._build_statement(ts_query, context, quota, official_only)
        return list(db.execute(statement))

    def _retrievability_context(
        self, context: RetrievalContext, official_only: bool
    ) -> RetrievabilityContext:
        """Traduz o contexto de recuperação no contexto documental.

        Não acrescenta configuração nenhuma: os quatro valores já existem
        na chamada. ``official_only`` é parâmetro da pesquisa e não do
        ``RetrievalContext``, que descreve apenas quem pergunta, em que
        idioma e a que data.
        """
        return RetrievabilityContext(
            institution_id=context.institution_id,
            language=context.language,
            reference_date=context.reference_date,
            official_only=official_only,
        )

    def _build_statement(
        self,
        ts_query,
        context: RetrievalContext,
        quota: int,
        official_only: bool,
    ) -> Select:
        """Seleção base partilhada por todas as variantes.

        Traz numa única consulta (sem N+1) tudo o que o reranking e o
        diagnóstico precisam, incluindo os metadados estruturais usados só
        internamente. O LIMIT é a quota da variante, não o top_k final.

        A admissibilidade documental vem inteira de ``RetrievalEligibility``
        e continua a executar no PostgreSQL: C1–C4 e C6–C11 como predicados
        do ``WHERE``, C5 pela subquery canónica. O que fica aqui é o
        mecanismo de pesquisa — a correspondência lexical, a ordenação de
        desempate e a quota.

        O join a ``DocumentVersion`` existe porque a política referencia as
        colunas da versão (C3 e C4); é sobre a chave primária, pelo que não
        altera a cardinalidade. C3 e C4 já eram implicadas pela subquery de
        C5, que só considera versões ``processed`` da instituição: aplicá-las
        explicitamente não muda o conjunto devolvido.
        """
        retrievability = self._retrievability_context(context, official_only)
        latest_processed = latest_processed_version_subquery(retrievability)
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
                DocumentVersion,
                DocumentVersion.id == DocumentChunk.document_version_id,
            )
            .join(
                latest_processed,
                (latest_processed.c.version_id == DocumentChunk.document_version_id)
                & (latest_processed.c.document_id == DocumentChunk.document_id),
            )
            .where(
                *RetrievalEligibility.as_sql_filters(retrievability),
                latest_processed.c.rn == 1,
                DocumentChunk.search_vector.op("@@")(ts_query),
            )
            # Ordenação apenas para escolher deterministicamente os
            # candidatos dentro da quota; a ordenação final é do reranker.
            .order_by(
                score.desc(),
                Document.id.asc(),
                DocumentChunk.chunk_index.asc(),
                DocumentChunk.id.asc(),
            )
            .limit(quota)
        )
        return statement

    def _build_trace(
        self,
        *,
        query: str,
        language: str,
        fts_config: str,
        plan_variants: tuple[str, ...],
        variant_traces: tuple[VariantTrace, ...],
        budget: int,
        total_returned: int,
        unique_candidate_count: int,
        result: RerankResult,
        top_results: tuple[RankedCandidate, ...],
    ) -> LexicalRetrievalTrace:
        representation = build_lexical_representation(query, language)
        ordinals = tuple(
            token.ordinal for token in representation.tokens if token.ordinal is not None
        )
        ranges = tuple(numeric_range.canonical for numeric_range in representation.ranges)
        return LexicalRetrievalTrace(
            fts_config=fts_config,
            informative_terms=result.query_terms,
            query_ordinals=ordinals,
            query_ranges=ranges,
            planned_variants=plan_variants,
            global_candidate_limit=budget,
            variants=variant_traces,
            total_returned_before_dedup=total_returned,
            unique_after_dedup=unique_candidate_count,
            candidates_evaluated=len(result.ranked) + len(result.excluded),
            excluded_no_content_match=result.excluded_count(
                ExclusionReason.NO_CONTENT_MATCH
            ),
            excluded_insufficient_coverage=result.excluded_count(
                ExclusionReason.INSUFFICIENT_COVERAGE
            ),
            excluded_below_threshold=result.excluded_count(
                ExclusionReason.BELOW_THRESHOLD
            ),
            result_count_before_limit=len(result.ranked),
            results=tuple(_ranked_to_trace(ranked) for ranked in top_results),
            excluded=tuple(
                _excluded_to_trace(item)
                for item in result.excluded[:MAX_TRACE_DETAIL_ROWS]
            ),
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
        # Score público = relevância lexical composta em [0, 1].
        score=ranked.score,
        language=candidate.language,
        official_source=candidate.official_source,
        source_url=candidate.source_url,
        valid_from=candidate.valid_from,
        valid_until=candidate.valid_until,
    )


def _ranked_to_trace(ranked: RankedCandidate) -> RankedResultTrace:
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
        ordered=features.ordered,
        proximity=features.proximity,
        title_overlap=features.title_overlap,
        section_overlap=features.section_overlap,
        structure_type=candidate.structure_type,
        matched_terms=tuple(sorted(features.matched_terms)),
        reason=ranked.reason,
    )


def _excluded_to_trace(item: ExcludedCandidate) -> ExcludedCandidateTrace:
    candidate = item.candidate
    return ExcludedCandidateTrace(
        chunk_id=str(candidate.chunk_id),
        document_id=str(candidate.document_id),
        chunk_index=candidate.chunk_index,
        strategy=candidate.strategy.value,
        reason=item.reason.value,
        coverage=item.match.coverage,
        matched_terms=tuple(sorted(item.match.matched_terms)),
        score=item.score,
    )
