"""Variantes offline da política de correspondência lexical (D4.3).

Módulo de **avaliação**, não de produção. Existe para responder a uma pergunta
experimental — *qual alteração mínima na correspondência lexical melhora a
recuperação da evidência relevante sem aumentar injustificadamente o ruído?* —
sem tocar em ``PostgresLexicalRetriever`` nem em ``decide_eligibility``.

O que varia, e o que não varia
------------------------------

Varia **apenas o predicado de correspondência de termos**: em que condições um
termo da pergunta conta como presente no conteúdo de um segmento. Tudo o resto —
a política de elegibilidade, os pesos do ranking, a ordenação, o limiar, o
``top_k`` — é o código de produção, chamado sem alteração.

A variante não é implementada como um predicado solto mas como uma **projeção
do espaço de termos**: os termos da pergunta e as formas canónicas do conteúdo
são projetados para o mesmo espaço, e a comparação continua a ser igualdade.
Assim a cobertura, os termos correspondidos e as posições permanecem mutuamente
coerentes, o que não aconteceria se só o lado da pergunta fosse transformado.

Os dois lados têm mapas **separados** — ver :class:`TermProjection`. Projetam
para o mesmo espaço, mas cada um é construído a partir do seu próprio texto: a
pergunta a partir da pergunta, o conteúdo a partir do conteúdo daquele segmento.
Um mapa único e global faria um segmento herdar informação de outro.

Marcadores canónicos (``ord:``, ``rng:``) **não** são projetados: identificam
ordinais e intervalos já normalizados, e passá-los por um *stemmer* destruiria a
distinção entre "1.ª chamada" e "2.ª chamada" que a política existe para
preservar.

Sinais mantidos constantes
--------------------------

``exact_phrase`` e ``ordered`` são lidos do cálculo de produção e **não** são
recalculados no espaço projetado. É a escolha conservadora: recalculá-los faria
uma variante ganhar por dois mecanismos ao mesmo tempo, e o objetivo é atribuir
o efeito a um só. ``proximity`` e ``compactness`` *são* recalculados, porque
dependem por definição do conjunto correspondido — mantê-los seria incoerente
com a cobertura que os acompanha.

O *stemmer* não vive aqui
-------------------------

Este módulo é puro e não fala com o PostgreSQL. A projeção é injetada como um
``Mapping`` já resolvido pelo chamador, que o obtém de ``ts_lexize`` — o mesmo
*stemmer* que o índice FTS usa. Uma segunda implementação de *stemming* em
Python divergiria da do índice e mediria um sistema que não existe.
"""

from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Final

from app.retrieval.eligibility import ContentMatch
from app.retrieval.lexical_normalization import (
    LexicalRepresentation,
    is_canonical_marker,
)
from app.retrieval.reranking import compute_proximity

#: Correspondência de produção: igualdade entre formas canónicas exatas.
MATCHING_EXACT_CANONICAL: Final = "exact_canonical"

#: Correspondência por radical, calculado sobre as formas **sem acentos** que o
#: sistema já persiste em ``normalized_content``. É a alteração mínima: nada no
#: pipeline documental muda, apenas a comparação.
MATCHING_STEM_NORMALIZED: Final = "stem_normalized"

#: Correspondência por radical calculado sobre as formas **com acentos**,
#: recuperadas do ``content`` original. Isola BUG-D4.2-01: se esta variante
#: superar a anterior, a remoção de diacríticos antes do *stemming* está a
#: custar correspondências reais.
MATCHING_STEM_ACCENTED: Final = "stem_accented"

MATCHING_VARIANTS: Final = (
    MATCHING_EXACT_CANONICAL,
    MATCHING_STEM_NORMALIZED,
    MATCHING_STEM_ACCENTED,
)

#: Conjunto de candidatos tal como produção o constrói: uma quota por variante
#: de consulta, somando o orçamento global.
POOL_PRODUCTION_QUOTA: Final = "production_quota"

#: O mesmo conjunto de consultas **sem quota**. Não é uma proposta de sistema:
#: existe para separar "a política de correspondência rejeitou o segmento" de "o
#: segmento nunca chegou a ser avaliado", que a métrica sozinha confunde.
POOL_UNBOUNDED: Final = "unbounded"

POOL_CONDITIONS: Final = (POOL_PRODUCTION_QUOTA, POOL_UNBOUNDED)


@dataclass(frozen=True)
class TermProjection:
    """Projeção do espaço de termos usada por uma variante.

    Há **duas** aplicações, e não uma: ``query_mapping`` projeta os termos da
    pergunta, ``content_mapping`` projeta as formas canónicas do conteúdo. A
    separação não é cosmética — é o que permite que cada lado seja construído a
    partir do **seu próprio texto**.

    Isso importa na variante que restitui acentos. Um mapa global
    ``sem acentos -> com acentos`` faria um segmento herdar o acento de outro
    segmento onde a palavra por acaso aparecesse acentuada, e faria os termos da
    pergunta serem reacentuados com informação do corpus. Nenhuma das duas
    coisas descreve o sistema que se quer medir: mediria um corpus fundido em
    vez do segmento corrente.

    Formas ausentes do mapa projetam-se em si mesmas: um termo que o *stemmer*
    não reconheça continua a poder corresponder por igualdade exata, pelo que
    nenhuma variante pode perder uma correspondência que a baseline tinha.
    """

    name: str
    query_mapping: Mapping[str, str]
    content_mapping: Mapping[str, str]

    def project_query(self, term: str) -> str:
        """Radical de um termo **da pergunta**, ou o próprio termo."""
        if is_canonical_marker(term):
            return term
        return self.query_mapping.get(term, term)

    def project_content(self, term: str) -> str:
        """Radical de uma forma canónica **do conteúdo**, ou a própria forma.

        Marcadores canónicos passam intactos: ``ord:2`` identifica um ordinal já
        normalizado e não é uma palavra a radicalizar.
        """
        if is_canonical_marker(term):
            return term
        return self.content_mapping.get(term, term)


def identity_projection() -> TermProjection:
    """A baseline: cada termo projeta-se em si mesmo."""
    return TermProjection(
        name=MATCHING_EXACT_CANONICAL, query_mapping={}, content_mapping={}
    )


def project_terms(terms: tuple[str, ...], projection: TermProjection) -> tuple[str, ...]:
    """Projeta termos **da pergunta**."""
    return tuple(projection.project_query(term) for term in terms)


def projected_positions(
    representation: LexicalRepresentation, projection: TermProjection
) -> dict[str, int]:
    """Primeira posição de cada forma **projetada** do conteúdo.

    Reproduz a semântica de ``LexicalRepresentation.first_positions`` no espaço
    projetado: a primeira ocorrência vence, e os endpoints de um intervalo
    herdam a posição do seu marcador em vez de acrescentarem posições próprias.
    """
    positions: dict[str, int] = {}
    for token in representation.tokens:
        positions.setdefault(projection.project_content(token.canonical), token.position)
        if token.numeric_range is not None:
            for endpoint in token.numeric_range.endpoint_canonicals:
                positions.setdefault(
                    projection.project_content(endpoint), token.position
                )
    return positions


def projected_content_set(
    representation: LexicalRepresentation, projection: TermProjection
) -> frozenset[str]:
    values = {
        projection.project_content(token.canonical) for token in representation.tokens
    }
    for token in representation.tokens:
        if token.numeric_range is not None:
            values.update(
                projection.project_content(endpoint)
                for endpoint in token.numeric_range.endpoint_canonicals
            )
    return frozenset(values)


def variant_content_match(
    *,
    base: ContentMatch,
    query_terms: tuple[str, ...],
    representation: LexicalRepresentation,
    projection: TermProjection,
) -> ContentMatch:
    """``ContentMatch`` da variante, derivado do de produção.

    ``matched_terms`` é devolvido no espaço **original** dos termos da pergunta,
    e não no projetado: o consumidor a jusante — ``decide_eligibility``, através
    de ``_canonical_relaxed_is_satisfied`` — compara-o com ``query_terms``, e um
    conjunto em radicais falharia silenciosamente essa comparação.
    """
    if not query_terms:
        return base

    content_set = projected_content_set(representation, projection)
    matched = frozenset(
        term for term in query_terms if projection.project_query(term) in content_set
    )
    coverage = len(matched) / len(query_terms)

    positions = projected_positions(representation, projection)
    projected_matched = frozenset(projection.project_query(term) for term in matched)
    proximity, compactness = compute_proximity(
        project_terms(query_terms, projection), projected_matched, positions
    )

    return replace(
        base,
        coverage=coverage,
        matched_terms=matched,
        proximity=proximity,
        compactness=compactness,
    )
