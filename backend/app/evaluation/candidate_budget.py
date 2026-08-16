"""Políticas offline de repartição do orçamento de candidatos (D4.5).

Módulo de **avaliação**, não de produção. Existe para responder a uma pergunta
experimental — *existe uma repartição do orçamento de candidatos que aumenta a
probabilidade de a evidência relevante chegar ao ranking sem degradar o top 5?* —
sem tocar em ``PostgresLexicalRetriever``.

Tal como ``app.evaluation.lexical_variants`` e
``app.evaluation.ground_truth_identity``, **não** é reexportado por
``app/evaluation/__init__.py``.

O que varia, e o que não varia
------------------------------

Varia **apenas quantas linhas cada variante de consulta pode devolver**, e em que
momento o teto é aplicado. O plano de consulta, a elegibilidade, os pesos do
ranking, a ordenação, o limiar e o ``top_k`` são o código de produção, chamado
sem alteração. Nenhuma política aqui olha para o *ground truth*.

As três políticas
-----------------

``current_quota``
    Produção. ``distribute_quotas(25, n)`` é calculado **antes** de qualquer
    consulta e cada variante recebe ``LIMIT quota``. Uma variante que devolva
    menos do que a sua quota deixa o resto por usar, e o resto **não** volta ao
    orçamento.

``redistribute_unused``
    O mesmo orçamento, executado em cascata: a quota de cada variante é a
    fórmula de produção aplicada ao que **sobra**. Não é mais orçamento — é o
    mesmo teto de 25 linhas, sem desperdício. Ver :func:`adaptive_quota`.

``global_limited_pool``
    As variantes correm **sem** teto individual, a união é ordenada globalmente
    e truncada em 25 antes da elegibilidade. Move o corte de antes para depois
    da recolha. Custa mais SQL: o teto passa a limitar o que o ranking vê, não o
    que a base devolve — e isso é um facto a reportar, não um detalhe.

Porque é que a ordenação global não usa o score
------------------------------------------------

``ts_rank_cd`` é calculado contra a ``tsquery`` **daquela** variante. Duas
variantes são duas consultas diferentes, e os seus scores não são grandezas
comparáveis — é a mesma razão pela qual ``ScoreSemantics`` declara
``comparable_across_queries=False`` e pela qual produção nunca funde variantes
por score. :func:`pool_order_key` ordena primeiro por **prioridade de
estratégia**, que é o critério que produção já usa implicitamente ao repartir a
quota por ``STRATEGY_PRIORITY``, e só compara scores **dentro** da mesma
estratégia, onde a comparação é legítima.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import replace
from typing import Any, Final

from app.retrieval.lexical import distribute_quotas
from app.retrieval.query_planning import STRATEGY_PRIORITY, LexicalQueryStrategy
from app.retrieval.reranking import LexicalCandidate

#: Repartição de produção: quotas fixas decididas antes de qualquer consulta.
BUDGET_CURRENT_QUOTA: Final = "current_quota"

#: Mesmo orçamento, quota não utilizada devolvida às variantes seguintes.
BUDGET_REDISTRIBUTE_UNUSED: Final = "redistribute_unused"

#: Sem teto por variante; teto global aplicado depois da recolha.
BUDGET_GLOBAL_LIMITED_POOL: Final = "global_limited_pool"

BUDGET_POLICIES: Final = (
    BUDGET_CURRENT_QUOTA,
    BUDGET_REDISTRIBUTE_UNUSED,
    BUDGET_GLOBAL_LIMITED_POOL,
)


def adaptive_quota(remaining_budget: int, remaining_variants: int) -> int:
    """Quota da próxima variante, dado o que sobra do orçamento.

    É a **fórmula de produção aplicada ao remanescente**: ``redistribute_unused``
    não é uma política nova, é ``distribute_quotas`` repetida sobre o que ainda
    não foi gasto. Reimplementar a divisão aqui faria as duas condições
    divergirem por uma razão que nada tem a ver com o fator em estudo.

    Consequência que importa para a leitura dos resultados: a soma das linhas
    devolvidas continua limitada a ``budget``. B não compra orçamento; deixa de
    o desperdiçar.
    """
    if remaining_variants <= 0 or remaining_budget <= 0:
        return 0
    return distribute_quotas(remaining_budget, remaining_variants)[0]


def pool_order_key(candidate: LexicalCandidate) -> tuple[object, ...]:
    """Ordem de truncatura do conjunto global, determinística e total.

    Prioridade de estratégia primeiro — o critério que produção já aplica ao
    repartir a quota — e só depois ``raw_score``, comparado apenas entre
    candidatos da mesma estratégia. Os três últimos componentes existem para que
    a ordem seja total: sem eles, dois candidatos com o mesmo score dependeriam
    da ordem em que a base devolveu as linhas, e a condição deixaria de ser
    reprodutível.
    """
    return (
        -STRATEGY_PRIORITY[candidate.strategy],
        -candidate.raw_score,
        str(candidate.document_id),
        candidate.chunk_index,
        str(candidate.chunk_id),
    )


def truncate_pool(
    candidates: Iterable[LexicalCandidate], budget: int
) -> list[LexicalCandidate]:
    """Os ``budget`` melhores candidatos da união, por :func:`pool_order_key`."""
    return sorted(candidates, key=pool_order_key)[:budget]


def merge_candidate(
    candidates: dict[object, LexicalCandidate],
    candidate: LexicalCandidate,
) -> None:
    """Deduplicação por segmento, com a semântica de ``_merge_candidate``.

    O mesmo segmento pode ser devolvido por várias variantes. Produção guarda-o
    uma vez, com a **melhor** estratégia e o **maior** score bruto; qualquer
    outra escolha alteraria ``strategy_quality``, que é um sinal do ranking, e a
    experiência passaria a medir duas coisas ao mesmo tempo.
    """
    existing = candidates.get(candidate.chunk_id)
    if existing is None:
        candidates[candidate.chunk_id] = candidate
        return
    candidates[candidate.chunk_id] = replace(
        existing,
        strategy=_better_strategy(existing.strategy, candidate.strategy),
        raw_score=max(existing.raw_score, candidate.raw_score),
    )


def _better_strategy(
    left: LexicalQueryStrategy, right: LexicalQueryStrategy
) -> LexicalQueryStrategy:
    return left if STRATEGY_PRIORITY[left] >= STRATEGY_PRIORITY[right] else right


def quota_plan(policy: str, budget: int, variant_count: int) -> tuple[int | None, ...]:
    """Tetos **iniciais** por variante, antes de qualquer consulta.

    Só ``current_quota`` fica inteiramente determinado aqui.
    ``redistribute_unused`` devolve apenas a primeira quota, porque as seguintes
    dependem do que as anteriores devolverem; ``global_limited_pool`` não tem
    teto por variante e devolve ``None``. A função existe para que o artefacto
    possa registar o plano declarado ao lado do executado.
    """
    if variant_count <= 0:
        return ()
    if policy == BUDGET_CURRENT_QUOTA:
        return distribute_quotas(budget, variant_count)
    if policy == BUDGET_REDISTRIBUTE_UNUSED:
        first = adaptive_quota(budget, variant_count)
        return (first, *([None] * (variant_count - 1)))
    if policy == BUDGET_GLOBAL_LIMITED_POOL:
        return tuple([None] * variant_count)
    msg = f"unknown candidate budget policy: {policy!r}"
    raise ValueError(msg)


# ---------------------------------------------------------------------------
# Destino de um segmento-alvo
# ---------------------------------------------------------------------------

#: Vocabulário do D4.2 (``scripts.evaluate_retrieval_baseline``), preservado para
#: que as fases sejam comparáveis, mais um destino que o D4.2 não conseguia
#: exprimir.
FATE_RETURNED: Final = "RETURNED"
FATE_CANDIDATE_EXCLUDED: Final = "CANDIDATE_EXCLUDED"
FATE_NEVER_A_CANDIDATE: Final = "NEVER_A_CANDIDATE"

#: Elegível, pontuado acima do limiar, e ainda assim fora do ``top_k``.
#:
#: O D4.2 tinha de o classificar ``NOT_RETURNED_INDETERMINATE``, porque só via o
#: trace e não distinguia "nunca foi candidato" de "sobreviveu e ficou abaixo do
#: corte". Aqui o conjunto de candidatos é conhecido por inteiro, pelo que a
#: distinção deixa de ser indeterminada — e é exatamente ela que separa um
#: problema de **orçamento** de um problema de **ranking**.
FATE_RANKED_OUTSIDE_TOP_K: Final = "RANKED_OUTSIDE_TOP_K"

TARGET_FATES: Final = (
    FATE_RETURNED,
    FATE_RANKED_OUTSIDE_TOP_K,
    FATE_CANDIDATE_EXCLUDED,
    FATE_NEVER_A_CANDIDATE,
)


def classify_target_fate(
    *,
    in_pool: bool,
    excluded_reason: str | None,
    rank: int | None,
    top_k: int,
) -> str:
    """Destino de um segmento de grau 2, a partir de observações da execução.

    É uma **observação**, não um diagnóstico: diz onde o segmento parou, não
    porquê. A interpretação causal pertence ao relatório, onde pode ser
    argumentada e contestada.
    """
    if not in_pool:
        return FATE_NEVER_A_CANDIDATE
    if rank is None:
        return FATE_CANDIDATE_EXCLUDED if excluded_reason else FATE_NEVER_A_CANDIDATE
    return FATE_RETURNED if rank <= top_k else FATE_RANKED_OUTSIDE_TOP_K


def summarise_target_position(
    matches: Sequence[Mapping[str, Any]],
    quota_by_strategy: Mapping[str, int],
) -> dict[str, Any]:
    """Onde está o alvo na ordenação FTS, e se a quota atual lá chega.

    ``matches`` são as ocorrências do alvo nas consultas do plano, **sem teto**:
    uma por variante que o encontre, com ``strategy``, ``position`` e ``total``.

    A alcançabilidade é avaliada sobre **todas** as variantes, não só a melhor:
    basta que uma delas o traga dentro da sua quota para o alvo entrar no
    conjunto. Reduzir a verificação à variante de maior prioridade daria falsos
    negativos num alvo que a disjuntiva alcança e a conjuntiva não.

    ``best`` é a ocorrência sob a variante de **maior prioridade**, e serve para
    relatar: é a que descreve como o alvo é encontrado, não necessariamente a que
    o admite.
    """
    if not matches:
        return {
            "matches": [],
            "best_strategy": None,
            "best_position": None,
            "best_total": None,
            "matched_by_any_variant": False,
            "reachable_under_current_quota": False,
        }
    ranked = sorted(
        matches,
        key=lambda match: (
            -STRATEGY_PRIORITY[LexicalQueryStrategy(match["strategy"])],
            match["position"],
        ),
    )
    best = ranked[0]
    return {
        "matches": [dict(match) for match in ranked],
        "best_strategy": best["strategy"],
        "best_position": best["position"],
        "best_total": best["total"],
        "matched_by_any_variant": True,
        "reachable_under_current_quota": any(
            match["position"] <= quota_by_strategy.get(match["strategy"], 0)
            for match in matches
        ),
    }


def candidate_recall(fates: Sequence[str]) -> float | None:
    """Fração dos alvos que **chegaram ao conjunto de candidatos**.

    Métrica diagnóstica, acrescentada e não substituta: separa "o alvo nunca foi
    avaliado" de "foi avaliado e perdeu". Sem ela, uma política que aumente o
    Recall e outra que aumente a cobertura do conjunto seriam indistinguíveis
    pelas métricas do D4.2.

    ``None`` quando não há alvos — indefinida, e devolver 0.0 ou 1.0 seria uma
    afirmação falsa sobre uma pergunta que não tem evidência relevante.
    """
    if not fates:
        return None
    reached = sum(1 for fate in fates if fate != FATE_NEVER_A_CANDIDATE)
    return reached / len(fates)
