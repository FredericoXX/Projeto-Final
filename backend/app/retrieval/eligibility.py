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
- **um termo informativo** — elegível quando há prova de correspondência
  no conteúdo: canónica/de superfície, ou morfológica confirmada pelo FTS
  (``matrículas`` ⇄ ``matrícula``). Sem qualquer das duas não é elegível —
  o caso existe e não é teórico: em ``-propinas`` o termo informativo é
  ``propinas`` e a consulta devolve de propósito os segmentos que **não**
  o contêm;
- **dois ou mais termos** — é preciso cumprir pelo menos uma condição
  forte: sintaxe explícita do utilizador; frase exata; estratégia
  conjuntiva (``exact``/``reduced_and``); relaxação canónica com todo o
  contexto e pelo menos um marcador canónico correspondidos; ou cobertura
  mínima (``required_matches`` termos e cobertura ≥ ``MIN_COVERAGE_RATIO``);
- **cobertura zero numa consulta multi-termo** — nunca elegível, mesmo
  com título, secção, ``table_row``, comprimento ou FTS cru favoráveis.

O que conta como correspondência no conteúdo
--------------------------------------------

``ContentMatch.matched_terms`` reúne três provas, todas sobre o **conteúdo**
do segmento: a igualdade de formas canónicas e duas correspondências
morfológicas que o PostgreSQL confirmou, sob a configuração FTS do idioma —
uma contra o ``search_vector`` indexado, outra contra
``to_tsvector(cfg, content)``, calculado sobre o texto original acentuado.

Nenhuma é uma flexibilização da política. A primeira das morfológicas é a
mesma prova que **já** tinha recuperado o candidato, agora disponível na
decisão em vez de descartada entre as duas fases: ``notas`` e ``nota`` são o
mesmo lexema para o índice, e não eram para a cobertura. A segunda existe
porque a normalização remove os diacríticos **antes** do *stemmer*, e o
*stemmer* português usa-os nas suas regras — ``classificações`` e
``classificação`` reduzem ambos a ``classific``, enquanto as formas
desacentuadas produzem radicais distintos. Sem ela, essa família de palavras
ficava fora de alcance de qualquer decisão de elegibilidade, porque o
segmento nem sequer chegava a candidato.

Nada disto toca nos limiares (``MIN_MATCHED_TERMS``, ``MIN_COVERAGE_RATIO``),
nem cria exceções por palavra ou por instituição, nem abre a porta ao título
e à secção: ambas as expressões FTS leem **apenas** o conteúdo do segmento
(``normalized_content`` e ``content``), nunca ``document_title`` nem
``section_title``, pelo que uma correspondência morfológica no título é
impossível por construção.

Os marcadores canónicos (``ord:N``, ``rng:N-M``) ficam **fora** desta
extensão: não são palavras, nunca são sondados contra o índice (ver
``reranking.fts_probe_terms``) e continuam a exigir correspondência canónica
real — a 1.ª chamada não passa a ser evidência da 2.ª.

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
    estrutura, comprimento, estratégia ou score FTS cru.

    ``matched_terms`` é a **união** de três provas de correspondência no
    conteúdo: a canónica/de superfície, a morfológica confirmada contra o
    ``search_vector`` indexado (``indexed_fts_matched_terms``) e a morfológica
    confirmada contra ``to_tsvector(cfg, content)``, calculado sobre o texto
    original acentuado (``content_fts_matched_terms``). As duas últimas são
    disjuntas da primeira, pelo que ``matched_terms - fts_matched_terms``
    devolve exatamente as correspondências literais.

    As origens FTS ficam separadas porque respondem a perguntas diferentes: a
    indexada diz que o radical existe no texto **desacentuado** que o índice
    guarda; a de conteúdo diz que existe no texto **como foi escrito**, e é a
    única que pode ligar ``classificações`` a ``classificação``.

    A separação importa para além do trace: os sinais posicionais
    (``exact_phrase``, ``ordered``, ``proximity``, ``compactness``) descrevem
    onde os termos estão no conteúdo, e uma correspondência por radical não
    observa posição nenhuma. Por isso contribui para a cobertura e nunca para
    eles.
    """

    coverage: float
    matched_terms: frozenset[str]
    exact_phrase: float
    ordered: float
    proximity: float
    compactness: float
    indexed_fts_matched_terms: frozenset[str] = frozenset()
    content_fts_matched_terms: frozenset[str] = frozenset()

    @property
    def fts_matched_terms(self) -> frozenset[str]:
        """Termos cuja única prova foi morfológica, de qualquer das origens.

        Derivada e não guardada: a elegibilidade só precisa da união, e um
        terceiro estado guardado poderia dessincronizar-se das parcelas.
        """
        return self.indexed_fts_matched_terms | self.content_fts_matched_terms

    def __post_init__(self) -> None:
        """A parcela morfológica é sempre parte do todo que declara.

        A invariante ``fts_matched_terms ⊆ matched_terms`` é o que dá sentido
        a ``matched_terms - fts_matched_terms`` como "correspondências
        literais" — expressão de que a elegibilidade depende para escolher
        entre ``SINGLE_TERM_SURFACE`` e ``SINGLE_TERM_FTS``, e que o trace
        publica. Se a parcela pudesse conter um termo ausente do todo, essa
        subtração devolveria um conjunto sem significado e ninguém daria por
        isso.

        Verificada na construção, e não por um teste: quem deriva um
        ``ContentMatch`` de outro com ``dataclasses.replace`` — é o que a
        avaliação offline faz — substitui ``matched_terms`` sem
        necessariamente se lembrar da parcela. Aqui isso falha de imediato,
        em vez de sobreviver como um conjunto incoerente.
        """
        if not self.fts_matched_terms <= self.matched_terms:
            orphans = sorted(self.fts_matched_terms - self.matched_terms)
            msg = (
                "fts_matched_terms tem de ser subconjunto de matched_terms; "
                f"termos sem correspondência declarada: {orphans}"
            )
            raise ValueError(msg)


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


def _canonical_relaxed_is_satisfied(query_terms: tuple[str, ...], matched: frozenset[str]) -> bool:
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
        return EligibilityDecision(eligible=False, reason=ExclusionReason.NO_CONTENT_MATCH)

    matched_count = len(match.matched_terms)

    if term_count == 1:
        if not match.matched_terms:
            # Antes, qualquer candidato de uma consulta de um termo era
            # elegível, e a justificação era que o índice GIN só o teria
            # devolvido se tivesse casado — logo a prova existia mesmo sem
            # estar à vista. O argumento deixou de valer em dois pontos.
            #
            # Primeiro, a prova **está** agora à vista: as correspondências
            # morfológicas são transportadas no candidato, pelo que a ausência
            # delas é uma observação e não uma incerteza.
            #
            # Segundo, o argumento nunca cobriu as consultas explicitamente
            # negativas. Em ``-propinas`` o termo informativo é ``propinas``,
            # e o que a tsquery devolve são precisamente os segmentos que
            # **não** o contêm. Todos chegavam aqui com cobertura zero e
            # saíam declarados ``SINGLE_TERM_FTS`` — uma base que afirma uma
            # correspondência por radical que nunca houve. O trace mentia, e
            # conteúdo sem relação nenhuma com a pergunta tornava-se
            # evidência.
            #
            # Cobertura zero não é evidência numa consulta de um termo pela
            # mesma razão que não o é numa de vários.
            return EligibilityDecision(eligible=False, reason=ExclusionReason.NO_CONTENT_MATCH)
        # A base distingue as duas provas pela **literal**, e não pela união:
        # um termo que só casa por radical continua a declarar-se
        # ``SINGLE_TERM_FTS``, que é o que de facto aconteceu.
        surface_matched = match.matched_terms - match.fts_matched_terms
        basis = (
            EligibilityBasis.SINGLE_TERM_SURFACE
            if surface_matched
            else EligibilityBasis.SINGLE_TERM_FTS
        )
        return EligibilityDecision(eligible=True, basis=basis)

    # Consultas multi-termo: cobertura zero nunca é evidência, seja qual
    # for o título, a secção, a estrutura, o comprimento ou o FTS.
    if matched_count == 0:
        return EligibilityDecision(eligible=False, reason=ExclusionReason.NO_CONTENT_MATCH)

    if explicit_syntax and strategy is LexicalQueryStrategy.EXACT:
        # O utilizador escreveu os operadores (aspas, OR, negação) e o
        # sistema honra essa intenção sem a reavaliar por cobertura. Não é
        # prova conjuntiva: "aulas OR exames" casa um dos lados por desenho.
        return EligibilityDecision(eligible=True, basis=EligibilityBasis.EXPLICIT_SYNTAX)

    if match.exact_phrase >= 1.0:
        return EligibilityDecision(eligible=True, basis=EligibilityBasis.EXACT_PHRASE)

    if strategy in (
        LexicalQueryStrategy.EXACT,
        LexicalQueryStrategy.REDUCED_AND,
    ):
        # A pesquisa FTS conjuntiva encontrou todos os termos exigidos
        # (eventualmente por stemming), o que é prova de correspondência
        # real no conteúdo.
        return EligibilityDecision(eligible=True, basis=EligibilityBasis.CONJUNCTIVE_STRATEGY)

    if strategy is LexicalQueryStrategy.CANONICAL_RELAXED_AND and (
        _canonical_relaxed_is_satisfied(query_terms, match.matched_terms)
    ):
        return EligibilityDecision(eligible=True, basis=EligibilityBasis.CANONICAL_RELAXED)

    if matched_count >= required_matches(term_count) and match.coverage >= MIN_COVERAGE_RATIO:
        return EligibilityDecision(eligible=True, basis=EligibilityBasis.COVERAGE)

    return EligibilityDecision(eligible=False, reason=ExclusionReason.INSUFFICIENT_COVERAGE)
