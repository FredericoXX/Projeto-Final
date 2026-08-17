"""Comparação C0 (lexical) × C1 (denso) sobre o mesmo protocolo (D4.8).

Módulo **puro**: recebe rankings já produzidos e julgamentos já resolvidos, e
devolve estruturas. Não importa SQLAlchemy, Settings, modelos, retrievers nem
o SDK de fornecedor nenhum — a execução contra a base vive em
``scripts.evaluate_dense_baseline``. Como ``retrieval_metrics``, ``results`` e
``ranking_variants``, **não** é reexportado por ``app/evaluation/__init__.py``.

O problema que este módulo existe para não deixar acontecer
-----------------------------------------------------------

O ground truth de P1 foi construído por inspeção dirigida a partir de execuções
**lexicais** (D4.1–D4.6). O seu próprio ``metric_protocol`` regista a
consequência: *«Antes de comparar lexical com denso ou hibrido, repoolar o
conjunto com os resultados de ambos e reanotar.»*

Uma estratégia densa recupera segmentos que nenhuma execução lexical alguma vez
devolveu. Sob a convenção ``ASSUMED_IRRELEVANT``, cada um desses segmentos conta
grau 0 — não porque tenha sido julgado irrelevante, mas porque nunca foi
julgado. Comparar as duas condições assim **penaliza a condição nova por ser
nova**, e o resultado teria a forma de uma medição sem o ser.

Por isso nada aqui declara vencedor. O que existe é:

- a **união** ``top5(C0) ∪ top5(C1)``, que é o conjunto que teria de estar
  julgado para a comparação ser legítima;
- a lista explícita dos pares pergunta/segmento por julgar;
- uma classificação de comparabilidade que obriga quem lê a saber em que caso
  está.

As métricas continuam a ser calculadas — são informação — mas quando há
resultados por julgar são **provisórias**, e a palavra faz parte do artefacto.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Final

#: Identificadores das duas condições. C2 (híbrido) não existe nesta fase e não
#: deve ser acrescentado aqui antes de ser medido.
CONDITION_LEXICAL: Final = "C0"
CONDITION_DENSE: Final = "C1"
CONDITIONS: Final = (CONDITION_LEXICAL, CONDITION_DENSE)

#: A união dos dois top 5 está inteiramente julgada: a comparação entre C0 e C1
#: é legítima sob o protocolo.
COMPARABLE: Final = "COMPARABLE"

#: Existe pelo menos um par pergunta/segmento no top 5 de alguma condição sem
#: julgamento. Nenhuma comparação definitiva pode ser feita antes do repooling.
REPOOLING_REQUIRED: Final = "REPOOLING_REQUIRED"


@dataclass(frozen=True, order=True)
class PoolItem:
    """Um segmento identificado pela âncora do protocolo.

    ``corpus_item_id`` + ``chunk_index``, e nada mais: os UUID locais de
    documento e versão identificam uma instalação concreta e não entram em
    artefactos versionados. ``order=True`` dá uma ordenação total determinística,
    que é o que torna a união reprodutível entre execuções.
    """

    corpus_item_id: str
    chunk_index: int


@dataclass(frozen=True)
class RepoolingRequest:
    """Um par pergunta/segmento que precisa de julgamento humano.

    ``retrieved_by`` regista **que condições** o devolveram. Não é decorativo: um
    segmento devolvido só por C1 é exatamente o caso que o ground truth atual não
    podia ter visto, e é sobre esses que a incompletude enviesa a comparação.

    ``rank_c0``/``rank_c1`` são ``None`` quando a condição não o devolveu. Não se
    inclui conteúdo documental — nem excerto, nem título de secção: a âncora é
    suficiente para localizar o segmento no documento original, e o artefacto
    versionado não transporta texto institucional.
    """

    question_id: str
    corpus_item_id: str
    chunk_index: int
    retrieved_by: tuple[str, ...]
    rank_c0: int | None
    rank_c1: int | None


def ranked_pool(ranking: Sequence[Mapping[str, object]]) -> tuple[PoolItem, ...]:
    """Extrai os itens de um ranking, pela ordem em que foram devolvidos."""
    items: list[PoolItem] = []
    for entry in ranking:
        corpus_item_id = entry["corpus_item_id"]
        chunk_index = entry["chunk_index"]
        if not isinstance(corpus_item_id, str) or not isinstance(chunk_index, int):
            msg = f"ranking entry has no usable anchor: {entry!r}"
            raise ValueError(msg)
        items.append(PoolItem(corpus_item_id, chunk_index))
    return tuple(items)


def union_pool(*pools: Iterable[PoolItem]) -> tuple[PoolItem, ...]:
    """União ordenada dos conjuntos devolvidos pelas condições.

    A ordenação é por âncora e não por posição: a união é um **conjunto** a
    julgar, e a posição em que cada condição o devolveu já está registada noutro
    lado. Ordenar por posição faria a lista depender de qual condição se leu
    primeiro.
    """
    seen: set[PoolItem] = set()
    for pool in pools:
        seen.update(pool)
    return tuple(sorted(seen))


def exclusive_to(pool: Iterable[PoolItem], other: Iterable[PoolItem]) -> tuple[PoolItem, ...]:
    """Itens de ``pool`` que ``other`` não devolveu, em ordem determinística."""
    return tuple(sorted(set(pool) - set(other)))


def unjudged_items(
    pool: Iterable[PoolItem], judged: Iterable[PoolItem]
) -> tuple[PoolItem, ...]:
    """Itens da união sem julgamento — o conjunto que o repooling tem de cobrir."""
    judged_set = set(judged)
    return tuple(sorted(item for item in pool if item not in judged_set))


def classify_comparability(unjudged_total: int) -> str:
    """``COMPARABLE`` apenas quando **nada** ficou por julgar.

    Deliberadamente sem tolerância. Um limiar do género "menos de N por julgar é
    aceitável" transformaria uma propriedade verificável — o conjunto está
    julgado ou não está — num juízo, e seria exatamente o tipo de folga que
    depois sustenta uma conclusão que os dados não suportam.
    """
    if unjudged_total < 0:
        msg = f"unjudged_total cannot be negative, got {unjudged_total}"
        raise ValueError(msg)
    return COMPARABLE if unjudged_total == 0 else REPOOLING_REQUIRED


def build_repooling_requests(
    *,
    question_id: str,
    c0_ranking: Sequence[PoolItem],
    c1_ranking: Sequence[PoolItem],
    judged: Iterable[PoolItem],
) -> tuple[RepoolingRequest, ...]:
    """Os pedidos de julgamento desta pergunta, um por segmento por julgar."""
    rank_c0 = {item: position for position, item in enumerate(c0_ranking, start=1)}
    rank_c1 = {item: position for position, item in enumerate(c1_ranking, start=1)}
    pool = union_pool(c0_ranking, c1_ranking)
    requests: list[RepoolingRequest] = []
    for item in unjudged_items(pool, judged):
        retrieved_by = tuple(
            condition
            for condition, ranks in (
                (CONDITION_LEXICAL, rank_c0),
                (CONDITION_DENSE, rank_c1),
            )
            if item in ranks
        )
        requests.append(
            RepoolingRequest(
                question_id=question_id,
                corpus_item_id=item.corpus_item_id,
                chunk_index=item.chunk_index,
                retrieved_by=retrieved_by,
                rank_c0=rank_c0.get(item),
                rank_c1=rank_c1.get(item),
            )
        )
    return tuple(requests)


def overlap_count(
    c0_ranking: Iterable[PoolItem], c1_ranking: Iterable[PoolItem]
) -> int:
    """Quantos segmentos as duas condições devolveram em comum.

    Sozinho não demonstra complementaridade: duas condições podem não se
    sobrepor e **ambas** falhar. A sobreposição só é informativa ao lado de que
    alvos de grau 2 cada uma recuperou, que é o que o runner regista.
    """
    return len(set(c0_ranking) & set(c1_ranking))
