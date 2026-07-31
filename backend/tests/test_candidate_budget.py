"""Testes puros do orçamento global de candidatos e das quotas por variante.

O teto do candidate pool é decidido **antes** das consultas e repartido
pelas variantes ativas por ordem de prioridade. Não existe qualquer corte
posterior: a soma das quotas é, por construção, o limite observado.
"""

import pytest

from app.retrieval.lexical import (
    CANDIDATE_MAX,
    CANDIDATE_MIN,
    CANDIDATE_MULTIPLIER,
    distribute_quotas,
    global_candidate_limit,
)
from app.retrieval.query_planning import MAX_QUERY_VARIANTS

# --- Limite global ------------------------------------------------------------


def test_limit_respects_the_minimum_for_small_top_k() -> None:
    assert global_candidate_limit(1) == CANDIDATE_MIN
    assert global_candidate_limit(2) == CANDIDATE_MIN


def test_limit_is_proportional_between_the_bounds() -> None:
    assert global_candidate_limit(5) == 5 * CANDIDATE_MULTIPLIER
    assert global_candidate_limit(10) == 10 * CANDIDATE_MULTIPLIER


def test_limit_never_exceeds_the_absolute_maximum() -> None:
    assert global_candidate_limit(1000) == CANDIDATE_MAX


def test_limit_is_deterministic() -> None:
    assert global_candidate_limit(7) == global_candidate_limit(7)


# --- Distribuição por quotas ---------------------------------------------------


@pytest.mark.parametrize("variant_count", [1, 2, 3, 4])
def test_quota_sum_never_exceeds_the_budget(variant_count: int) -> None:
    for top_k in (1, 5, 10):
        budget = global_candidate_limit(top_k)
        quotas = distribute_quotas(budget, variant_count)
        assert len(quotas) == variant_count
        assert sum(quotas) <= budget


def test_single_variant_receives_the_whole_budget() -> None:
    assert distribute_quotas(25, 1) == (25,)


def test_two_variants_split_the_budget() -> None:
    assert distribute_quotas(25, 2) == (13, 12)


def test_three_variants_distribute_the_remainder_by_priority() -> None:
    # 25 = 8 + 8 + 8, resto 1 para a variante mais prioritária.
    assert distribute_quotas(25, 3) == (9, 8, 8)


def test_four_variants_distribute_the_remainder_by_priority() -> None:
    # 25 = 6×4 + 1: o resto vai para exact, a primeira da ordem.
    assert distribute_quotas(25, 4) == (7, 6, 6, 6)
    # 22 = 5×4 + 2: os dois primeiros recebem o resto.
    assert distribute_quotas(22, 4) == (6, 6, 5, 5)


def test_remainder_is_never_given_to_a_lower_priority_variant() -> None:
    quotas = distribute_quotas(23, 4)
    assert quotas == tuple(sorted(quotas, reverse=True))


def test_no_variant_is_starved_with_the_minimum_budget() -> None:
    quotas = distribute_quotas(global_candidate_limit(1), MAX_QUERY_VARIANTS)
    assert all(quota > 0 for quota in quotas)


def test_no_quota_is_ever_negative() -> None:
    for budget in (0, 1, 3, 20, 25, 100):
        for variant_count in range(0, MAX_QUERY_VARIANTS + 1):
            quotas = distribute_quotas(budget, variant_count)
            assert all(quota >= 0 for quota in quotas)
            assert sum(quotas) <= budget


def test_degenerate_inputs_yield_no_quotas() -> None:
    assert distribute_quotas(25, 0) == ()
    assert distribute_quotas(0, 4) == ()


def test_distribution_is_deterministic() -> None:
    assert distribute_quotas(25, 3) == distribute_quotas(25, 3)
