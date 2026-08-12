"""Fase 2 do retrieval lexical: **ranking** determinístico dos elegíveis.

Recebe um conjunto **já limitado** de candidatos (gerados pela fase A com
PostgreSQL FTS + índice GIN), decide a elegibilidade de cada um (ver
app.retrieval.eligibility) e ordena **apenas os elegíveis** por uma
política lexical explicável, usando informação já disponível — nunca
embeddings, pesquisa semântica, LLM ou sinónimos.

A ordem das operações é significativa:

1. sinais de conteúdo (``ContentMatch``): cobertura, frase exata, ordem,
   proximidade e compacidade — nada além do conteúdo do chunk;
2. elegibilidade, a partir desses sinais e da estratégia;
3. **só então** os sinais auxiliares (título, secção, ``table_row``,
   comprimento, FTS cru, qualidade da estratégia) e o score composto;
4. limiar mínimo de relevância, aplicado a todos os elegíveis — incluindo
   o melhor e incluindo correspondências de frase exata.

Assim, o título ou a secção nunca criam evidência: só desempatam entre
candidatos que já correspondem no conteúdo. Um resultado vazio é um
resultado legítimo.

A comparação de cobertura usa formas canónicas (``lexical_normalization``:
ordinais e intervalos), não stemming — o stemming linguístico do
PostgreSQL governa a **recuperação** (fase A); a cobertura governa a
**ordenação** (fase B). O score não é uma probabilidade.
"""

import math
from dataclasses import dataclass
from datetime import date
from uuid import UUID

from app.core.text_normalization import normalize_text
from app.retrieval.eligibility import (
    ContentMatch,
    EligibilityDecision,
    ExclusionReason,
    decide_eligibility,
)
from app.retrieval.lexical_normalization import (
    LexicalRepresentation,
    build_lexical_representation,
)
from app.retrieval.query_planning import (
    MAX_INFORMATIVE_TERMS,
    STRATEGY_PRIORITY,
    LexicalQueryStrategy,
    functional_terms_for,
    is_informative_surface,
    uses_advanced_syntax,
)

# --- Pesos do score composto (somam 1.0; score final fica em [0, 1]) --------
# A cobertura domina: uma table_row com todos os termos vence um parágrafo
# genérico que só repete um termo. Quando dois candidatos têm cobertura
# igual (ex.: uma linha curta e um parágrafo longo que ambos contêm
# "regime" e "avaliação"), a decisão passa para proximidade e estrutura —
# nunca para a frequência.
#
# Os sinais que NÃO dependem de correspondência real (score FTS e
# comprimento) são auxiliares e combinados num único termo pequeno
# (``fts_norm × length_factor``, peso ``W_FTS``): o comprimento amortece o
# FTS (um parágrafo longo não vence por repetição) sem dar pontos
# independentes a conteúdo que nada corresponde. Nenhum destes pesos pode
# criar evidência: essa decisão pertence inteiramente à elegibilidade.
# Identidade da configuração de scoring: pesos acima + limiar mínimo aplicado
# em ``rerank``. Alterar qualquer um deles muda o significado quantitativo de
# **todos** os scores, pelo que a versão tem de subir junto — é o que torna a
# incomparabilidade entre execuções declarável em vez de silenciosa. Viaja no
# contrato em ``ScoreSemantics.version`` (app.retrieval.base).
SCORING_VERSION = "lexical_composite_v1"

W_COVERAGE = 0.40
W_EXACT_PHRASE = 0.16
W_PROXIMITY = 0.14
W_ORDER = 0.08
W_TITLE = 0.07
W_STRUCTURE = 0.06
W_SECTION = 0.05
W_FTS = 0.02
W_STRATEGY = 0.02
_WEIGHT_SUM = (
    W_COVERAGE + W_EXACT_PHRASE + W_PROXIMITY + W_ORDER
    + W_TITLE + W_STRUCTURE + W_SECTION + W_FTS + W_STRATEGY
)
if not math.isclose(_WEIGHT_SUM, 1.0, rel_tol=1e-9):  # pragma: no cover - erro de programação
    msg = "os pesos do ranking devem somar 1.0"
    raise ValueError(msg)

# --- Constantes de calibração (nomeadas e comentadas) -----------------------
# Saturação do score FTS cru: fts_norm = raw / (raw + FTS_SATURATION), o que
# o mantém em [0, 1) e impede que valores de ts_rank_cd elevados dominem.
FTS_SATURATION = 0.1
# Comprimento sem penalização: conteúdos até este tamanho recebem fator 1.0;
# acima, o fator decresce (uma table_row curta nunca perde para um parágrafo
# longo só por repetir termos).
LENGTH_SOFT_CAP_CHARS = 400
# Benefício de table_row só quando a cobertura é alta e as correspondências
# são compactas. Usa a **compacidade** (correspondências por span), não a
# proximidade composta: a proximidade já penaliza os termos em falta, e
# penalizá-los outra vez aqui esvaziaria o sinal estrutural.
STRUCTURE_MIN_COVERAGE = 0.5
STRUCTURE_MIN_COMPACTNESS = 0.5

# Qualidade da estratégia que recuperou o candidato: derivada da prioridade
# única definida em query_planning, normalizada para [0, 1]. Componente
# pequeno do score e desempate na ordenação final.
_MAX_STRATEGY_PRIORITY = max(STRATEGY_PRIORITY.values())
_STRATEGY_QUALITY: dict[LexicalQueryStrategy, float] = {
    strategy: priority / _MAX_STRATEGY_PRIORITY
    for strategy, priority in STRATEGY_PRIORITY.items()
}


@dataclass(frozen=True)
class LexicalCandidate:
    """Candidato recuperado numa única consulta (sem N+1).

    Reúne os campos necessários ao ranking e à construção da Evidence,
    incluindo os metadados estruturais usados apenas internamente.
    ``strategy`` é a melhor estratégia que recuperou este chunk e
    ``raw_score`` o melhor ``ts_rank_cd`` observado entre as variantes.
    """

    chunk_id: UUID
    document_id: UUID
    document_version_id: UUID
    document_title: str
    chunk_index: int
    content: str
    normalized_content: str
    language: str
    official_source: bool
    source_url: str | None
    valid_from: date | None
    valid_until: date | None
    page_number: int | None
    section_title: str | None
    structure_type: str | None
    chunking_strategy: str | None
    raw_score: float
    strategy: LexicalQueryStrategy


@dataclass(frozen=True)
class LexicalFeatures:
    """Sinais lexicais completos de um candidato elegível (todos em [0, 1])."""

    coverage: float
    matched_terms: frozenset[str]
    exact_phrase: float
    ordered: float
    proximity: float
    compactness: float
    title_overlap: float
    section_overlap: float
    table_row_bonus: float
    fts_norm: float
    length_factor: float
    strategy_quality: float


@dataclass(frozen=True)
class RankedCandidate:
    """Candidato com os seus sinais, o score final e uma razão resumida."""

    candidate: LexicalCandidate
    features: LexicalFeatures
    score: float
    reason: str


@dataclass(frozen=True)
class ExcludedCandidate:
    """Candidato removido, com o motivo tipado e os sinais de conteúdo.

    ``score`` é ``None`` quando o candidato foi excluído **antes** de ser
    pontuado (falhou a elegibilidade): nesse caso os sinais auxiliares nem
    chegam a ser calculados.
    """

    candidate: LexicalCandidate
    reason: ExclusionReason
    match: ContentMatch
    score: float | None = None


@dataclass(frozen=True)
class RerankResult:
    """Resultado do reranking: os elegíveis ordenados e os excluídos.

    Os motivos de exclusão são tipados e mutuamente exclusivos, pelo que
    ``len(ranked) + len(excluded)`` é sempre o número de candidatos
    avaliados.
    """

    query_terms: tuple[str, ...]
    ranked: tuple[RankedCandidate, ...]
    excluded: tuple[ExcludedCandidate, ...] = ()

    def excluded_count(self, reason: ExclusionReason) -> int:
        return sum(1 for item in self.excluded if item.reason is reason)


def informative_query_terms(normalized_query: str, language: str) -> tuple[str, ...]:
    """Termos informativos canónicos da pergunta, por ordem, sem duplicados.

    Igual em espírito a ``query_planning.extract_informative_terms`` (remove
    termos funcionais e tokens de uma só letra, limita o número), mas opera
    sobre o **stream canónico** para que ``1.ª`` e ``primeira`` contribuam
    como o mesmo ``ord:1``, e para que ``01a12``, ``01-12`` e ``1 a 12``
    contribuam como o mesmo ``rng:1-12``, na posição correta.
    """
    representation = build_lexical_representation(normalized_query, language)
    functional = functional_terms_for(language)
    terms: list[str] = []
    seen: set[str] = set()
    for canonical in _informative_stream(representation, functional):
        if canonical in seen:
            continue
        seen.add(canonical)
        terms.append(canonical)
        if len(terms) >= MAX_INFORMATIVE_TERMS:
            break
    return tuple(terms)


def _informative_stream(
    representation: LexicalRepresentation, functional: frozenset[str]
) -> list[str]:
    """Sequência de formas canónicas informativas (funcionais removidos)."""
    return [
        token.canonical
        for token in representation.tokens
        if is_informative_surface(token.surface, functional)
    ]


def _is_contiguous_sublist(needle: tuple[str, ...], haystack: list[str]) -> bool:
    """A sequência ``needle`` aparece contígua e por ordem em ``haystack``?"""
    if not needle or len(needle) > len(haystack):
        return False
    limit = len(haystack) - len(needle)
    for start in range(limit + 1):
        if all(haystack[start + offset] == needle[offset] for offset in range(len(needle))):
            return True
    return False


def _ordered_fraction(query_terms: tuple[str, ...], positions: dict[str, int]) -> float:
    """Fração de pares consecutivos da pergunta presentes na ordem certa."""
    if len(query_terms) < 2:
        return 1.0
    total = len(query_terms) - 1
    in_order = 0
    for index in range(total):
        left = query_terms[index]
        right = query_terms[index + 1]
        if left in positions and right in positions and positions[left] < positions[right]:
            in_order += 1
    return in_order / total


def compute_proximity(
    query_terms: tuple[str, ...],
    matched: frozenset[str],
    positions: dict[str, int],
) -> tuple[float, float]:
    """Proximidade composta e compacidade das correspondências.

    A proximidade combina **quantos** dos termos da pergunta foram
    encontrados com **quão juntos** aparecem::

        positional_coverage = posições correspondidas / termos da pergunta
        compactness         = posições correspondidas / span
        proximity           = positional_coverage × compactness

    Consequências deliberadas: sem correspondências a proximidade é
    ``0.0``; numa consulta de um só termo, esse termo é trivialmente
    próximo de si mesmo (``1.0``); numa consulta multi-termo, uma única
    correspondência **nunca** chega a ``1.0`` (fica em ``1/n``). Ambos os
    valores ficam em ``[0, 1]``.

    A compacidade é devolvida à parte porque é ela — e não a proximidade
    composta — que descreve "as correspondências estão juntas", que é o
    que o benefício de ``table_row`` precisa de saber.
    """
    total = len(query_terms)
    matched_positions = sorted({positions[term] for term in matched if term in positions})
    if total == 0 or not matched_positions:
        return 0.0, 0.0
    if len(matched_positions) == 1:
        return 1.0 / total, 1.0
    span = matched_positions[-1] - matched_positions[0] + 1
    compactness = len(matched_positions) / span
    positional_coverage = len(matched_positions) / total
    return positional_coverage * compactness, compactness


def _overlap(query_terms: tuple[str, ...], canonical: frozenset[str]) -> float:
    if not query_terms:
        return 0.0
    hits = sum(1 for term in query_terms if term in canonical)
    return hits / len(query_terms)


def compute_content_match(
    query_terms: tuple[str, ...], candidate: LexicalCandidate
) -> ContentMatch:
    """Sinais que dependem apenas do conteúdo (função pura, fase 1).

    Nada aqui usa título, secção, estrutura, comprimento, estratégia ou
    score FTS: são exatamente estes os sinais em que a elegibilidade pode
    basear-se.
    """
    language = candidate.language
    functional = functional_terms_for(language)
    content = build_lexical_representation(candidate.normalized_content, language)
    content_set = content.canonical_set()
    positions = content.first_positions()
    term_count = len(query_terms)

    matched = frozenset(term for term in query_terms if term in content_set)
    coverage = len(matched) / term_count if term_count else 0.0

    if term_count >= 2:
        stream = _informative_stream(content, functional)
        exact_phrase = 1.0 if _is_contiguous_sublist(query_terms, stream) else 0.0
    else:
        exact_phrase = 1.0 if coverage > 0 else 0.0

    proximity, compactness = compute_proximity(query_terms, matched, positions)
    return ContentMatch(
        coverage=coverage,
        matched_terms=matched,
        exact_phrase=exact_phrase,
        ordered=_ordered_fraction(query_terms, positions),
        proximity=proximity,
        compactness=compactness,
    )


def build_features(
    query_terms: tuple[str, ...],
    candidate: LexicalCandidate,
    match: ContentMatch,
) -> LexicalFeatures:
    """Acrescenta os sinais auxiliares aos de conteúdo (função pura, fase 2).

    Só é chamada para candidatos **já elegíveis**: o título e a secção não
    chegam sequer a ser calculados para um candidato sem correspondência
    suficiente no conteúdo.
    """
    language = candidate.language
    title_set = build_lexical_representation(
        normalize_text(candidate.document_title), language
    ).canonical_set()
    title_overlap = _overlap(query_terms, title_set)
    if candidate.section_title:
        section_set = build_lexical_representation(
            normalize_text(candidate.section_title), language
        ).canonical_set()
        section_overlap = _overlap(query_terms, section_set)
    else:
        section_overlap = 0.0

    table_row_bonus = (
        1.0
        if candidate.structure_type == "table_row"
        and match.coverage >= STRUCTURE_MIN_COVERAGE
        and match.compactness >= STRUCTURE_MIN_COMPACTNESS
        else 0.0
    )

    raw = max(candidate.raw_score, 0.0)
    fts_norm = raw / (raw + FTS_SATURATION) if raw > 0 else 0.0
    length_factor = LENGTH_SOFT_CAP_CHARS / max(len(candidate.content), LENGTH_SOFT_CAP_CHARS)

    return LexicalFeatures(
        coverage=match.coverage,
        matched_terms=match.matched_terms,
        exact_phrase=match.exact_phrase,
        ordered=match.ordered,
        proximity=match.proximity,
        compactness=match.compactness,
        title_overlap=title_overlap,
        section_overlap=section_overlap,
        table_row_bonus=table_row_bonus,
        fts_norm=fts_norm,
        length_factor=length_factor,
        strategy_quality=_STRATEGY_QUALITY[candidate.strategy],
    )


def compute_features(
    query_terms: tuple[str, ...], candidate: LexicalCandidate
) -> LexicalFeatures:
    """Sinais completos de um candidato (conveniência: fase 1 + fase 2)."""
    return build_features(
        query_terms, candidate, compute_content_match(query_terms, candidate)
    )


def compute_score(features: LexicalFeatures) -> float:
    """Score composto em [0, 1] a partir dos sinais (soma ponderada).

    O sinal auxiliar combina FTS e comprimento (``fts_norm × length_factor``,
    peso ``W_FTS``): o comprimento amortece o FTS e nenhum destes sinais dá
    pontos independentes a conteúdo sem correspondência real. O resultado é
    uma medida de relevância lexical, não uma probabilidade.
    """
    fts_component = features.fts_norm * features.length_factor
    score = (
        W_COVERAGE * features.coverage
        + W_EXACT_PHRASE * features.exact_phrase
        + W_PROXIMITY * features.proximity
        + W_ORDER * features.ordered
        + W_TITLE * features.title_overlap
        + W_SECTION * features.section_overlap
        + W_STRUCTURE * features.table_row_bonus
        + W_FTS * fts_component
        + W_STRATEGY * features.strategy_quality
    )
    # Defensivo: garante o intervalo mesmo perante erros de vírgula flutuante.
    return max(0.0, min(1.0, score))


def _ranking_key(ranked: RankedCandidate) -> tuple:
    """Chave de ordenação total e determinística.

    score↓, cobertura↓, qualidade da estratégia↓, score FTS cru↓,
    document_id↑, chunk_index↑, chunk_id↑.
    """
    candidate = ranked.candidate
    return (
        -ranked.score,
        -ranked.features.coverage,
        -ranked.features.strategy_quality,
        -candidate.raw_score,
        str(candidate.document_id),
        candidate.chunk_index,
        str(candidate.chunk_id),
    )


def _reason(
    features: LexicalFeatures,
    candidate: LexicalCandidate,
    decision: EligibilityDecision,
) -> str:
    """Razão resumida do ranking — apenas métricas, nunca conteúdo."""
    basis = decision.basis.value if decision.basis is not None else "-"
    return (
        f"cov={features.coverage:.2f} exact={features.exact_phrase:.0f} "
        f"prox={features.proximity:.2f} fts={features.fts_norm:.2f} "
        f"strat={candidate.strategy.value} struct={candidate.structure_type or '-'} "
        f"elig={basis}"
    )


def rerank(
    normalized_query: str,
    candidates: list[LexicalCandidate],
    language: str,
    *,
    min_relevance_score: float,
) -> RerankResult:
    """Aplica elegibilidade e ordena os candidatos elegíveis.

    A deduplicação por ``chunk_id`` já ocorreu na fase A, por isso o mesmo
    chunk nunca chega aqui duas vezes. Candidatos **diferentes** nunca são
    removidos por serem "redundantes": evidência complementar (um chunk que
    corresponde a menos termos do que outro) é preservada e simplesmente
    ordenada abaixo — a decisão de quantos usar é do ``top_k``.

    O limiar mínimo aplica-se a **todos** os elegíveis, incluindo o melhor
    e incluindo correspondências de frase exata: se todos ficarem abaixo, o
    resultado é vazio (e o answering devolve ``insufficient_evidence`` em
    vez de gerar sobre uma coincidência fraca).
    """
    query_terms = informative_query_terms(normalized_query, language)
    # Uma consulta com operadores explícitos pode ser disjuntiva por
    # desenho; a elegibilidade precisa de o saber para não a classificar
    # como prova conjuntiva (ver app.retrieval.eligibility).
    explicit_syntax = uses_advanced_syntax(normalized_query)

    scored: list[tuple[RankedCandidate, ContentMatch]] = []
    excluded: list[ExcludedCandidate] = []
    for candidate in candidates:
        match = compute_content_match(query_terms, candidate)
        decision = decide_eligibility(
            query_terms, match, candidate.strategy, explicit_syntax=explicit_syntax
        )
        if not decision.eligible:
            excluded.append(
                ExcludedCandidate(
                    candidate=candidate,
                    # A política garante um motivo sempre que não é elegível;
                    # o fallback mantém o tipo total sem ramos silenciosos.
                    reason=decision.reason or ExclusionReason.NO_CONTENT_MATCH,
                    match=match,
                )
            )
            continue
        features = build_features(query_terms, candidate, match)
        scored.append(
            (
                RankedCandidate(
                    candidate=candidate,
                    features=features,
                    score=compute_score(features),
                    reason=_reason(features, candidate, decision),
                ),
                match,
            )
        )
    scored.sort(key=lambda item: _ranking_key(item[0]))

    kept: list[RankedCandidate] = []
    for ranked, match in scored:
        if ranked.score < min_relevance_score:
            excluded.append(
                ExcludedCandidate(
                    candidate=ranked.candidate,
                    reason=ExclusionReason.BELOW_THRESHOLD,
                    match=match,
                    score=ranked.score,
                )
            )
            continue
        kept.append(ranked)

    return RerankResult(
        query_terms=query_terms,
        ranked=tuple(kept),
        excluded=tuple(excluded),
    )
