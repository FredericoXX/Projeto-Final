"""Reciprocal Rank Fusion dos rankings lexical e denso (D4.9).

Módulo **puro** e determinístico: recebe rankings já ordenados, devolve um
ranking fundido. Não importa SQLAlchemy, Settings, FastAPI, SDK de fornecedor
nem toca na rede — a fusão desta fase consome os rankings **já versionados**
pela D4.8.1 e não volta a executar retrieval nenhum. Tal como
``retrieval_metrics`` e ``dense_baseline``, **não** é reexportado por
``app/evaluation/__init__.py``.

Porque é que a entrada são posições e não scores
------------------------------------------------

A assinatura de :func:`reciprocal_rank_fusion` aceita **sequências ordenadas de
identidades**. Não aceita scores, não os lê e não os pode ler: a garantia de que
``lexical_composite_v1`` e a similaridade do cosseno não são somados não depende
de disciplina nem de um teste, está na forma da função.

Isto não é purismo. As duas grandezas têm semânticas diferentes — uma é
relevância lexical composta em [0, 1], a outra é similaridade do cosseno — e
nenhuma é comparável entre consultas (``comparable_across_queries`` é ``False``
em ambas). Somá-las produziria um número sem unidade cuja variação entre
perguntas seria dominada pela que tivesse maior amplitude naquela pergunta. A
posição não tem esse problema: o primeiro lugar significa o mesmo nas duas.

Porque é que a soma é exata
---------------------------

Os termos ``1 / (k_rrf + rank)`` são somados em :class:`~fractions.Fraction` e só
depois arredondados para o artefacto. Com vírgula flutuante, dois empates
genuínos — o mesmo multiconjunto de posições somado por ordens diferentes —
podiam diferir no último bit e o desempate declarado nunca chegaria a correr. A
fração torna o empate detetável exatamente, que é o que faz do desempate uma
regra e não uma coincidência.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction
from typing import Final

from app.evaluation.dense_baseline import (
    CONDITION_DENSE,
    CONDITION_LEXICAL,
    PoolItem,
)

#: Identificador da condição fundida, ao lado de C0 (lexical) e C1 (densa).
CONDITION_HYBRID: Final = "C2"

#: Nome do método, gravado no artefacto.
FUSION_METHOD: Final = "reciprocal_rank_fusion"

#: O valor usado no artigo original — Cormack, Clarke & Buettcher (2009),
#: "Reciprocal Rank Fusion outperforms Condorcet and individual Rank Learning
#: Methods", SIGIR 2009 — onde o método foi introduzido.
#:
#: Não é "canónico" no sentido de derivado: os autores dizem que 60 foi fixado
#: durante uma investigação piloto, num corpus que não é este. É uma convenção
#: herdada, e a única propriedade que esta fase lhe reclama é **não ter sido
#: escolhido aqui**. Não houve grid search: procurar o ``k_rrf`` que maximiza
#: uma métrica sobre doze perguntas produziria um número ajustado a esta amostra
#: e apresentá-lo-ia como propriedade do método.
K_RRF: Final = 60

#: Profundidade lida de cada condição. É o ``top_k`` que a D4.8.1 registou, e
#: aumentá-la mudaria o universo de candidatos e exigiria novos julgamentos —
#: misturaria o efeito da fusão com o efeito de recuperar mais fundo.
SOURCE_DEPTH: Final = 5

#: Profundidade devolvida pela fusão, igual à das condições isoladas para que a
#: comparação seja entre rankings do mesmo tamanho.
FINAL_TOP_K: Final = 5

#: Ordem em que as condições são lidas. Só afeta ``contributing_conditions``; a
#: soma é comutativa e o desempate não olha para a condição.
FUSION_SOURCES: Final = (CONDITION_LEXICAL, CONDITION_DENSE)

#: Desempate declarado antes de medir, por ordem de aplicação. É **total** —
#: nenhum par de itens distintos sobrevive ao quarto critério, porque
#: ``(corpus_item_id, chunk_index)`` é único.
#:
#: Não existe um critério que prefira C0 ou C1. Seria fácil acrescentá-lo e
#: seria errado: a fusão é simétrica por construção, e um desempate que
#: favorecesse uma das condições estaria a decidir, dentro do mecanismo em
#: avaliação, parte daquilo que a experiência pergunta. A identidade do segmento
#: já basta para tornar a regra total, e não tem preferência nenhuma.
TIE_BREAK: Final = (
    "maior rrf_score, em aritmetica exata",
    "menor best_rank entre as condicoes que o devolveram",
    "menor corpus_item_id",
    "menor chunk_index",
)


@dataclass(frozen=True)
class FusedItem:
    """Um segmento no ranking fundido, com a origem preservada.

    ``rank_c0``/``rank_c1`` são ``None`` quando a condição não devolveu o
    segmento no seu top ``source_depth``. Ficam no resultado porque é deles que
    a análise de complementaridade vive: um item com ``rank_c0`` preenchido e
    ``rank_c1`` a ``None`` é exatamente a evidência que a condição densa perdia.
    """

    item: PoolItem
    rrf_score: Fraction
    rank_c0: int | None
    rank_c1: int | None

    @property
    def contributing_conditions(self) -> tuple[str, ...]:
        """As condições que contribuíram com um termo para a soma."""
        ranks = {CONDITION_LEXICAL: self.rank_c0, CONDITION_DENSE: self.rank_c1}
        return tuple(name for name in FUSION_SOURCES if ranks[name] is not None)

    @property
    def best_rank(self) -> int:
        """A melhor posição obtida em qualquer condição que o devolveu."""
        ranks = [rank for rank in (self.rank_c0, self.rank_c1) if rank is not None]
        if not ranks:
            msg = "a fused item must come from at least one ranking"
            raise ValueError(msg)
        return min(ranks)


def rrf_term(rank: int, k_rrf: int = K_RRF) -> Fraction:
    """``1 / (k_rrf + rank)`` para uma posição **1-based**.

    Um ``rank`` de zero ou negativo é erro de chamada, não um caso a tratar por
    omissão: as posições do protocolo começam em 1, e aceitar 0 produziria um
    termo silenciosamente maior do que o da primeira posição.
    """
    if rank < 1:
        msg = f"rank must be 1-based, got {rank!r}"
        raise ValueError(msg)
    return Fraction(1, k_rrf + rank)


def reciprocal_rank_fusion(
    rankings: Mapping[str, Sequence[PoolItem]],
    *,
    k_rrf: int = K_RRF,
    source_depth: int = SOURCE_DEPTH,
    final_top_k: int = FINAL_TOP_K,
) -> tuple[FusedItem, ...]:
    """Funde os rankings por posição e devolve os ``final_top_k`` primeiros.

    ``rankings`` mapeia o nome da condição para a sua sequência ordenada de
    segmentos. Cada sequência é truncada em ``source_depth`` antes de contribuir.

    **Um segmento ausente de um ranking não recebe posição nenhuma.** Não há
    rank sintético, nem penalização, nem ``1 / (k_rrf + 999)``: um retriever que
    não devolveu um segmento não se pronunciou sobre ele, e inventar-lhe uma
    posição transformaria silêncio em juízo negativo. A consequência é
    deliberada — um segmento exclusivo de uma condição soma um termo só e
    compete com essa desvantagem contra os que as duas condições viram.
    """
    unknown = set(rankings) - set(FUSION_SOURCES)
    if unknown:
        msg = f"unknown fusion sources: {sorted(unknown)}"
        raise ValueError(msg)

    scores: dict[PoolItem, Fraction] = {}
    ranks: dict[PoolItem, dict[str, int]] = {}
    for condition in FUSION_SOURCES:
        seen: set[PoolItem] = set()
        for position, item in enumerate(rankings.get(condition, ())[:source_depth], 1):
            if item in seen:
                msg = f"{condition} ranking repeats {item}"
                raise ValueError(msg)
            seen.add(item)
            scores[item] = scores.get(item, Fraction(0)) + rrf_term(position, k_rrf)
            ranks.setdefault(item, {})[condition] = position

    fused = [
        FusedItem(
            item=item,
            rrf_score=score,
            rank_c0=ranks[item].get(CONDITION_LEXICAL),
            rank_c1=ranks[item].get(CONDITION_DENSE),
        )
        for item, score in scores.items()
    ]
    fused.sort(
        key=lambda entry: (
            -entry.rrf_score,
            entry.best_rank,
            entry.item.corpus_item_id,
            entry.item.chunk_index,
        )
    )
    return tuple(fused[:final_top_k])


def fusion_configuration(
    *,
    k_rrf: int = K_RRF,
    source_depth: int = SOURCE_DEPTH,
    final_top_k: int = FINAL_TOP_K,
) -> dict[str, object]:
    """A configuração como fica gravada no artefacto, definida num sítio só."""
    return {
        "method": FUSION_METHOD,
        "formula": "sum over conditions of 1 / (k_rrf + rank), ranks 1-based",
        "k_rrf": k_rrf,
        "k_rrf_provenance": (
            "Valor usado no artigo original que introduziu o metodo - Cormack, "
            "Clarke & Buettcher (2009), SIGIR 2009 - onde e descrito como "
            "fixado durante uma investigacao piloto, noutro corpus. Convencao "
            "herdada, sem grid search e sem ajuste a P1/S1."
        ),
        "source_depth": source_depth,
        "final_top_k": final_top_k,
        "sources": list(FUSION_SOURCES),
        "absent_condition_contributes": False,
        "uses_original_scores": False,
        "arithmetic": "exact rational (fractions.Fraction), rounded only for output",
        "tie_break": list(TIE_BREAK),
    }
