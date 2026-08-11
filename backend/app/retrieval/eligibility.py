"""Fase 1 do retrieval lexical: **elegibilidade**, separada do ranking.

O score composto ordena candidatos; não decide se um candidato constitui
evidência. Esta separação é deliberada e é o cerne da correção: sinais
auxiliares (título, secção, ``table_row``, comprimento, estratégia, score
FTS cru) podem ajudar a **ordenar** candidatos elegíveis, mas nunca podem,
isoladamente, transformar um candidato sem correspondência suficiente no
conteúdo em evidência.

Colisão de vocabulário — leia antes de usar
-------------------------------------------

Existe também :mod:`app.documents.retrievability`, com ``RetrievalEligibility``
e ``CitationPersistenceEligibility``. Apesar do nome parecido, trata de um
conceito **diferente**: a admissibilidade documental de um ``DocumentChunk``
num dado contexto — instituição, idioma, data de referência e restrição a
fontes oficiais. Não olha para a pergunta.

Este módulo decide o oposto: dado que o chunk é admissível, se o seu
**conteúdo** corresponde suficientemente à pergunta para constituir evidência.
Não olha para instituição, idioma, validade nem estado do documento.

As duas decisões são independentes e ambas têm de se verificar. Nenhum dos
nomes deste módulo — ``decide_eligibility``, ``EligibilityDecision``,
``EligibilityBasis``, ``ExclusionReason`` — é alterado por essa política, e o
módulo novo nunca deve ser importado aqui com um alias chamado apenas
``eligibility``.

A decisão é pura, determinística e testável sem PostgreSQL: recebe os
termos canónicos da pergunta, os sinais que dependem **só do conteúdo**
(``ContentMatch``) e a estratégia que recuperou o candidato.

Política (conservadora e explícita):

- **sem termos informativos** — nenhum candidato é elegível;
- **um termo informativo** — elegível: ou há correspondência canónica/de
  superfície no conteúdo, ou o candidato foi recuperado pelo FTS através
  de stemming legítimo (``matrículas`` ⇄ ``matrícula``). Note-se que
  qualquer candidato que chegue aqui foi devolvido pelo índice GIN, logo
  a segunda alternativa é sempre verificável;
- **dois ou mais termos** — é preciso cumprir pelo menos uma condição
  forte: sintaxe explícita do utilizador; frase exata; estratégia
  conjuntiva (``exact``/``reduced_and``); relaxação canónica com todo o
  contexto e pelo menos um marcador canónico correspondidos; ou cobertura
  mínima (``required_matches`` termos e cobertura ≥ ``MIN_COVERAGE_RATIO``);
- **cobertura zero numa consulta multi-termo** — nunca elegível, mesmo
  com título, secção, ``table_row``, comprimento ou FTS favoráveis.

Uma nota sobre a estratégia ``exact``: ela é usada em dois papéis
diferentes. Numa consulta normal, prova que a tsquery **conjuntiva** casou
todos os termos exigidos. Numa consulta com sintaxe websearch explícita
(aspas, ``OR``, ``-termo``), o plano também usa apenas ``exact``, mas aí a
consulta pode ser deliberadamente **disjuntiva**: ``aulas OR exames``
corresponde a um dos lados por desenho. Tratar esse caso como prova
conjuntiva seria factualmente errado e tornaria o trace enganoso, por isso
existe uma base própria — ``EXPLICIT_SYNTAX`` — que regista o que realmente
justificou a decisão: o utilizador escreveu os operadores e o sistema honra
essa intenção em vez de a reavaliar por cobertura.

Não existem regras específicas para palavras (regime, avaliação, exames,
chamada, calendário...) nem para instituições: a política é puramente
estrutural.
"""

from dataclasses import dataclass
from enum import StrEnum
from math import ceil

from app.retrieval.lexical_normalization import is_canonical_marker
from app.retrieval.query_planning import LexicalQueryStrategy

# Fração mínima dos termos da pergunta que um candidato multi-termo tem de
# cobrir no conteúdo para ser evidência por cobertura.
MIN_COVERAGE_RATIO = 0.5

# Mínimo absoluto de termos correspondidos numa consulta multi-termo: uma
# única coincidência nunca é evidência, por muito curta que seja a
# pergunta.
MIN_MATCHED_TERMS = 2


class ExclusionReason(StrEnum):
    """Motivo estável e tipado pelo qual um candidato não chega ao resultado."""

    NO_CONTENT_MATCH = "no_content_match"
    INSUFFICIENT_COVERAGE = "insufficient_coverage"
    BELOW_THRESHOLD = "below_threshold"


class EligibilityBasis(StrEnum):
    """Condição que tornou o candidato elegível (auditoria do trace)."""

    SINGLE_TERM_SURFACE = "single_term_surface"
    SINGLE_TERM_FTS = "single_term_fts"
    EXPLICIT_SYNTAX = "explicit_syntax"
    EXACT_PHRASE = "exact_phrase"
    CONJUNCTIVE_STRATEGY = "conjunctive_strategy"
    CANONICAL_RELAXED = "canonical_relaxed"
    COVERAGE = "coverage"


@dataclass(frozen=True)
class ContentMatch:
    """Sinais que dependem **apenas** do conteúdo do candidato.

    Calculados antes da elegibilidade; nenhum deles usa título, secção,
    estrutura, comprimento, estratégia ou score FTS.
    """

    coverage: float
    matched_terms: frozenset[str]
    exact_phrase: float
    ordered: float
    proximity: float
    compactness: float


@dataclass(frozen=True)
class EligibilityDecision:
    """Resultado da fase de elegibilidade para um candidato."""

    eligible: bool
    basis: EligibilityBasis | None = None
    reason: ExclusionReason | None = None


def required_matches(term_count: int) -> int:
    """Nº mínimo de termos correspondidos para uma consulta com ``term_count``.

    Fórmula única e centralizada: ``max(2, ceil(term_count × 0.5))``. Com
    3 termos exige 2 (cobertura 0.67); com 4 exige 2 (cobertura 0.50); com
    5 exige 3 (0.60). Consultas de 0 ou 1 termo têm política própria e não
    passam por aqui.
    """
    if term_count <= 1:
        return 1
    return max(MIN_MATCHED_TERMS, ceil(term_count * MIN_COVERAGE_RATIO))


def _canonical_relaxed_is_satisfied(
    query_terms: tuple[str, ...], matched: frozenset[str]
) -> bool:
    """Todo o contexto correspondido **e** pelo menos um marcador canónico.

    O ordinal/intervalo é removido apenas da consulta FTS; aqui volta a ser
    obrigatório, para que "exames primeira chamada" não aceite como
    evidência uma linha da 2.ª chamada só por partilhar o contexto.
    """
    markers = [term for term in query_terms if is_canonical_marker(term)]
    context = [term for term in query_terms if not is_canonical_marker(term)]
    if not markers or not context:
        return False
    if not all(term in matched for term in context):
        return False
    return any(marker in matched for marker in markers)


def decide_eligibility(
    query_terms: tuple[str, ...],
    match: ContentMatch,
    strategy: LexicalQueryStrategy,
    *,
    explicit_syntax: bool = False,
) -> EligibilityDecision:
    """Decide se um candidato constitui evidência (função pura).

    ``explicit_syntax`` indica que a pergunta usa sintaxe websearch
    explícita (aspas, ``OR``, ``-termo``). Nesse caso a consulta ``exact``
    pode ser disjuntiva por desenho, pelo que **não** é prova conjuntiva.
    """
    term_count = len(query_terms)
    if term_count == 0:
        # Sem termos informativos não há nada que possa ser evidência.
        return EligibilityDecision(
            eligible=False, reason=ExclusionReason.NO_CONTENT_MATCH
        )

    matched_count = len(match.matched_terms)

    if term_count == 1:
        # O candidato chegou aqui porque o índice GIN o devolveu: ou tem
        # correspondência de superfície, ou casou por stemming legítimo.
        basis = (
            EligibilityBasis.SINGLE_TERM_SURFACE
            if matched_count > 0
            else EligibilityBasis.SINGLE_TERM_FTS
        )
        return EligibilityDecision(eligible=True, basis=basis)

    # Consultas multi-termo: cobertura zero nunca é evidência, seja qual
    # for o título, a secção, a estrutura, o comprimento ou o FTS.
    if matched_count == 0:
        return EligibilityDecision(
            eligible=False, reason=ExclusionReason.NO_CONTENT_MATCH
        )

    if explicit_syntax and strategy is LexicalQueryStrategy.EXACT:
        # O utilizador escreveu os operadores (aspas, OR, negação) e o
        # sistema honra essa intenção sem a reavaliar por cobertura. Não é
        # prova conjuntiva: "aulas OR exames" casa um dos lados por desenho.
        return EligibilityDecision(
            eligible=True, basis=EligibilityBasis.EXPLICIT_SYNTAX
        )

    if match.exact_phrase >= 1.0:
        return EligibilityDecision(
            eligible=True, basis=EligibilityBasis.EXACT_PHRASE
        )

    if strategy in (
        LexicalQueryStrategy.EXACT,
        LexicalQueryStrategy.REDUCED_AND,
    ):
        # A pesquisa FTS conjuntiva encontrou todos os termos exigidos
        # (eventualmente por stemming), o que é prova de correspondência
        # real no conteúdo.
        return EligibilityDecision(
            eligible=True, basis=EligibilityBasis.CONJUNCTIVE_STRATEGY
        )

    if strategy is LexicalQueryStrategy.CANONICAL_RELAXED_AND and (
        _canonical_relaxed_is_satisfied(query_terms, match.matched_terms)
    ):
        return EligibilityDecision(
            eligible=True, basis=EligibilityBasis.CANONICAL_RELAXED
        )

    if (
        matched_count >= required_matches(term_count)
        and match.coverage >= MIN_COVERAGE_RATIO
    ):
        return EligibilityDecision(eligible=True, basis=EligibilityBasis.COVERAGE)

    return EligibilityDecision(
        eligible=False, reason=ExclusionReason.INSUFFICIENT_COVERAGE
    )
