"""Reranking lexical determinístico dos candidatos recuperados.

Etapa B do retrieval do Momento 4: recebe um conjunto **já limitado** de
candidatos (gerados pela Etapa A com PostgreSQL FTS + índice GIN) e
reordena-os por uma política lexical explicável, usando apenas informação
já disponível — nunca embeddings, pesquisa semântica, LLM ou sinónimos.

Sinais considerados (todos normalizados para ``[0, 1]``):

- cobertura dos termos informativos da pergunta no conteúdo;
- correspondência de frase exata (sequência informativa contígua);
- ordem dos termos e proximidade entre eles;
- sobreposição com o título do documento e com o título da secção;
- benefício condicionado para ``table_row`` (curta, coberta e próxima);
- score FTS cru (``ts_rank_cd``) como sinal **auxiliar** e saturante;
- qualidade da estratégia que recuperou o candidato (exact > and > or);
- fator de comprimento (um parágrafo longo não vence por repetição).

O score final é a soma ponderada destes sinais, com a cobertura
dominante. Os pesos e limiares são constantes nomeadas (abaixo), cobertas
por testes. O resultado é determinístico: a mesma entrada produz sempre a
mesma ordenação e os mesmos scores.

A comparação de cobertura usa formas canónicas (``lexical_normalization``:
ordinais e intervalos), não stemming — o stemming linguístico do
PostgreSQL governa a **recuperação** (Etapa A); a cobertura governa a
**ordenação** (Etapa B). Um candidato recuperado só por stemming, sem
qualquer termo de superfície coberto, é dominado por um candidato com
cobertura real.
"""

from dataclasses import dataclass, field
from datetime import date
from uuid import UUID

from app.core.text_normalization import normalize_text
from app.retrieval.lexical_normalization import build_lexical_representation
from app.retrieval.query_planning import (
    MAX_INFORMATIVE_TERMS,
    LexicalQueryStrategy,
    functional_terms_for,
)

# --- Pesos do score composto (somam 1.0; score final fica em [0, 1]) --------
# A cobertura domina: uma table_row com todos os termos vence um parágrafo
# genérico que só repete um termo. Quando dois candidatos têm cobertura
# igual (ex.: uma linha curta e um parágrafo longo que ambos contêm
# "regime" e "avaliação"), a decisão passa para proximidade, estrutura e
# comprimento — nunca para a frequência: o score FTS é deliberadamente
# auxiliar (peso pequeno e saturante), para que a repetição de um termo
# genérico não ultrapasse a evidência direta.
W_COVERAGE = 0.38
W_EXACT_PHRASE = 0.15
W_PROXIMITY = 0.14
W_ORDER = 0.07
W_TITLE = 0.06
W_STRUCTURE = 0.06
W_LENGTH = 0.05
W_SECTION = 0.04
W_FTS = 0.03
W_STRATEGY = 0.02
_WEIGHT_SUM = (
    W_COVERAGE + W_EXACT_PHRASE + W_PROXIMITY + W_FTS + W_ORDER
    + W_TITLE + W_SECTION + W_LENGTH + W_STRUCTURE + W_STRATEGY
)

# --- Constantes de calibração (nomeadas e comentadas) -----------------------
# Saturação do score FTS cru: fts_norm = raw / (raw + FTS_SATURATION), o que
# o mantém em [0, 1) e impede que valores de ts_rank_cd elevados dominem.
FTS_SATURATION = 0.1
# Comprimento sem penalização: conteúdos até este tamanho recebem fator 1.0;
# acima, o fator decresce (uma table_row curta nunca perde para um parágrafo
# longo só por repetir termos).
LENGTH_SOFT_CAP_CHARS = 400
# Benefício de table_row só quando a cobertura e a proximidade são altas.
STRUCTURE_MIN_COVERAGE = 0.5
STRUCTURE_MIN_PROXIMITY = 0.5

# Qualidade da estratégia que recuperou o candidato (sinal explícito):
# exact > reduced_and > reduced_or. Usada como componente pequeno e como
# desempate na ordenação final.
_STRATEGY_QUALITY: dict[LexicalQueryStrategy, float] = {
    LexicalQueryStrategy.EXACT: 1.0,
    LexicalQueryStrategy.REDUCED_AND: 0.7,
    LexicalQueryStrategy.REDUCED_OR: 0.4,
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
    """Sinais lexicais calculados para um candidato (todos em [0, 1])."""

    coverage: float
    matched_terms: frozenset[str]
    exact_phrase: float
    ordered: float
    proximity: float
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
class RerankResult:
    """Resultado do reranking, com o que foi removido pelo limiar."""

    query_terms: tuple[str, ...]
    ranked: tuple[RankedCandidate, ...]
    removed_by_threshold: tuple[RankedCandidate, ...] = field(default_factory=tuple)


def informative_query_terms(normalized_query: str, language: str) -> tuple[str, ...]:
    """Termos informativos canónicos da pergunta, por ordem, sem duplicados.

    Igual em espírito a ``query_planning.extract_informative_terms`` (remove
    termos funcionais e tokens de uma só letra, limita o número), mas opera
    sobre formas **canónicas** para que ordinais como ``1.ª`` e ``primeira``
    contribuam para a cobertura como o mesmo ``ord:1``.
    """
    representation = build_lexical_representation(normalized_query, language)
    functional = functional_terms_for(language)
    terms: list[str] = []
    seen: set[str] = set()
    for token in representation.tokens:
        if len(token.surface) == 1 and token.surface.isalpha():
            continue
        if token.surface in functional:
            continue
        if token.canonical in seen:
            continue
        seen.add(token.canonical)
        terms.append(token.canonical)
        if len(terms) >= MAX_INFORMATIVE_TERMS:
            break
    return tuple(terms)


def _informative_stream(normalized_text: str, language: str) -> list[str]:
    """Sequência de formas canónicas informativas (funcionais removidos)."""
    representation = build_lexical_representation(normalized_text, language)
    functional = functional_terms_for(language)
    stream: list[str] = []
    for token in representation.tokens:
        if len(token.surface) == 1 and token.surface.isalpha():
            continue
        if token.surface in functional:
            continue
        stream.append(token.canonical)
    return stream


def _canonical_set(normalized_text: str, language: str) -> frozenset[str]:
    return build_lexical_representation(normalized_text, language).canonical_set()


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


def _proximity(matched: frozenset[str], positions: dict[str, int]) -> float:
    """Proximidade dos termos correspondentes: 1.0 quando adjacentes."""
    if len(matched) < 2:
        return 1.0
    matched_positions = sorted(positions[term] for term in matched)
    span = matched_positions[-1] - matched_positions[0] + 1
    return len(matched_positions) / span


def _overlap(query_terms: tuple[str, ...], canonical: frozenset[str]) -> float:
    if not query_terms:
        return 0.0
    hits = sum(1 for term in query_terms if term in canonical)
    return hits / len(query_terms)


def compute_features(
    query_terms: tuple[str, ...],
    candidate: LexicalCandidate,
) -> LexicalFeatures:
    """Calcula os sinais lexicais de um candidato (função pura)."""
    language = candidate.language
    content = build_lexical_representation(candidate.normalized_content, language)
    content_set = content.canonical_set()
    positions = content.first_positions()
    term_count = len(query_terms)

    matched = frozenset(term for term in query_terms if term in content_set)
    coverage = len(matched) / term_count if term_count else 0.0

    if term_count >= 2:
        content_stream = _informative_stream(candidate.normalized_content, language)
        exact_phrase = 1.0 if _is_contiguous_sublist(query_terms, content_stream) else 0.0
    else:
        exact_phrase = 1.0 if coverage > 0 else 0.0

    ordered = _ordered_fraction(query_terms, positions)
    proximity = _proximity(matched, positions)

    title_set = _canonical_set(normalize_text(candidate.document_title), language)
    title_overlap = _overlap(query_terms, title_set)
    if candidate.section_title:
        section_set = _canonical_set(normalize_text(candidate.section_title), language)
        section_overlap = _overlap(query_terms, section_set)
    else:
        section_overlap = 0.0

    table_row_bonus = (
        1.0
        if candidate.structure_type == "table_row"
        and coverage >= STRUCTURE_MIN_COVERAGE
        and proximity >= STRUCTURE_MIN_PROXIMITY
        else 0.0
    )

    raw = max(candidate.raw_score, 0.0)
    fts_norm = raw / (raw + FTS_SATURATION) if raw > 0 else 0.0

    length_factor = LENGTH_SOFT_CAP_CHARS / max(len(candidate.content), LENGTH_SOFT_CAP_CHARS)
    strategy_quality = _STRATEGY_QUALITY[candidate.strategy]

    return LexicalFeatures(
        coverage=coverage,
        matched_terms=matched,
        exact_phrase=exact_phrase,
        ordered=ordered,
        proximity=proximity,
        title_overlap=title_overlap,
        section_overlap=section_overlap,
        table_row_bonus=table_row_bonus,
        fts_norm=fts_norm,
        length_factor=length_factor,
        strategy_quality=strategy_quality,
    )


def compute_score(features: LexicalFeatures) -> float:
    """Score composto em [0, 1] a partir dos sinais (soma ponderada)."""
    score = (
        W_COVERAGE * features.coverage
        + W_EXACT_PHRASE * features.exact_phrase
        + W_PROXIMITY * features.proximity
        + W_FTS * features.fts_norm
        + W_ORDER * features.ordered
        + W_TITLE * features.title_overlap
        + W_SECTION * features.section_overlap
        + W_STRUCTURE * features.table_row_bonus
        + W_LENGTH * features.length_factor
        + W_STRATEGY * features.strategy_quality
    )
    # Defensivo: garante o intervalo mesmo perante erros de vírgula flutuante.
    return max(0.0, min(1.0, score))


def _ranking_key(ranked: RankedCandidate) -> tuple:
    """Chave de ordenação total e determinística (secção 26).

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


def _reason(features: LexicalFeatures, candidate: LexicalCandidate) -> str:
    """Razão resumida do ranking — apenas métricas, nunca conteúdo."""
    return (
        f"cov={features.coverage:.2f} exact={features.exact_phrase:.0f} "
        f"prox={features.proximity:.2f} fts={features.fts_norm:.2f} "
        f"strat={candidate.strategy.value} struct={candidate.structure_type or '-'}"
    )


def rerank(
    normalized_query: str,
    candidates: list[LexicalCandidate],
    language: str,
    *,
    min_relevance_score: float,
) -> RerankResult:
    """Reordena e filtra os candidatos de forma determinística.

    Política do limiar:

    - consultas de um único termo informativo mantêm todos os candidatos
      recuperados (o termo institucional casou por FTS) — nunca ficam
      vazias por limiar;
    - consultas multi-termo aplicam um piso de score mínimo (exceto para
      correspondências de frase exata, nunca eliminadas) e uma regra de
      dominância: um candidato cujos termos correspondidos são um
      subconjunto próprio dos de um candidato melhor é removido como
      redundante;
    - o melhor candidato sobrevive sempre (nunca se devolve lista vazia
      quando existem candidatos recuperados).
    """
    query_terms = informative_query_terms(normalized_query, language)
    scored: list[RankedCandidate] = []
    for candidate in candidates:
        features = compute_features(query_terms, candidate)
        scored.append(
            RankedCandidate(
                candidate=candidate,
                features=features,
                score=compute_score(features),
                reason=_reason(features, candidate),
            )
        )
    scored.sort(key=_ranking_key)

    if not scored:
        return RerankResult(query_terms=query_terms, ranked=(), removed_by_threshold=())

    # Consultas de um único termo: manter tudo (secção 25.1).
    if len(query_terms) <= 1:
        return RerankResult(query_terms=query_terms, ranked=tuple(scored))

    kept: list[RankedCandidate] = []
    removed: list[RankedCandidate] = []
    kept_matched_sets: list[frozenset[str]] = []
    for rank_index, ranked in enumerate(scored):
        matched = ranked.features.matched_terms
        is_best = rank_index == 0
        exact = ranked.features.exact_phrase >= 1.0
        full_coverage = ranked.features.coverage >= 1.0

        dominated = any(
            existing > matched  # superconjunto próprio
            for existing in kept_matched_sets
        )
        below_floor = ranked.score < min_relevance_score

        if is_best:
            kept.append(ranked)
            kept_matched_sets.append(matched)
            continue
        if dominated and not exact and not full_coverage:
            removed.append(ranked)
            continue
        if below_floor and not exact:
            removed.append(ranked)
            continue
        kept.append(ranked)
        kept_matched_sets.append(matched)

    return RerankResult(
        query_terms=query_terms,
        ranked=tuple(kept),
        removed_by_threshold=tuple(removed),
    )
