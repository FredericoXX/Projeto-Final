"""Políticas de orçamento de candidatos e diagnóstico de destino (D4.5).

Testes puros: não tocam na base de dados. O que fixam é a propriedade que dá
sentido ao experimento — **B não compra orçamento**, gasta o mesmo teto sem o
desperdiçar — e a distinção entre "o alvo nunca foi avaliado" e "foi avaliado e
perdeu", que é a razão de ser da fase.
"""

import json
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from app.core.text_normalization import normalize_text
from app.evaluation.candidate_budget import (
    BUDGET_CURRENT_QUOTA,
    BUDGET_GLOBAL_LIMITED_POOL,
    BUDGET_REDISTRIBUTE_UNUSED,
    FATE_CANDIDATE_EXCLUDED,
    FATE_NEVER_A_CANDIDATE,
    FATE_RANKED_OUTSIDE_TOP_K,
    FATE_RETURNED,
    adaptive_quota,
    candidate_recall,
    classify_target_fate,
    merge_candidate,
    pool_order_key,
    quota_plan,
    summarise_target_position,
    truncate_pool,
)
from app.evaluation.lexical_variants import MATCHING_EXACT_CANONICAL, identity_projection
from app.retrieval.lexical import distribute_quotas, global_candidate_limit
from app.retrieval.query_planning import LexicalQueryStrategy
from app.retrieval.reranking import LexicalCandidate
from scripts.evaluate_candidate_budget_experiment import (
    _direction,
    compare_policies,
    rank_with_diagnostics,
    verify_positions_explain_fates,
)
from scripts.evaluate_retrieval_experiment import rank_with_variant

BUDGET = global_candidate_limit(5)


def _candidate(
    *,
    normalized_content: str = "texto",
    strategy: LexicalQueryStrategy = LexicalQueryStrategy.REDUCED_OR,
    raw_score: float = 0.05,
    chunk_index: int = 0,
    chunk_id: UUID | None = None,
    document_id: UUID | None = None,
) -> LexicalCandidate:
    return LexicalCandidate(
        chunk_id=chunk_id or uuid4(),
        document_id=document_id or uuid4(),
        document_version_id=uuid4(),
        document_title="Documento",
        chunk_index=chunk_index,
        content=normalized_content,
        normalized_content=normalize_text(normalized_content),
        language="pt",
        official_source=True,
        source_url=None,
        valid_from=None,
        valid_until=None,
        page_number=None,
        section_title=None,
        structure_type=None,
        chunking_strategy=None,
        raw_score=raw_score,
        strategy=strategy,
    )


# ---------------------------------------------------------------------------
# Repartição adaptativa
# ---------------------------------------------------------------------------


def test_the_first_adaptive_quota_equals_the_production_quota() -> None:
    """B começa exatamente onde A começa; só diverge depois de sobrar orçamento."""
    for variant_count in (1, 2, 3, 4):
        assert adaptive_quota(BUDGET, variant_count) == distribute_quotas(
            BUDGET, variant_count
        )[0]


def test_a_variant_that_returns_nothing_hands_its_quota_to_the_next() -> None:
    """O caso Q009: duas conjuntivas devolvem zero e a disjuntiva herda tudo."""
    remaining, granted = BUDGET, []
    for index, returned in enumerate((0, 0, None)):
        quota = adaptive_quota(remaining, 3 - index)
        granted.append(quota)
        if returned is not None:
            remaining -= returned
    assert granted == [9, 13, BUDGET]


def test_the_redistributed_budget_never_exceeds_the_global_budget() -> None:
    """A propriedade central: B não é mais orçamento, é o mesmo sem desperdício.

    Se esta afirmação caísse, a comparação com A deixaria de ser justa: B estaria
    a ganhar por gastar mais, não por gastar melhor.
    """
    for returns in ((0, 0, 0), (5, 5, 5), (9, 8, 8), (25, 0, 0), (3, 20, 40)):
        remaining, fetched = BUDGET, 0
        for index, available in enumerate(returns):
            quota = adaptive_quota(remaining, 3 - index)
            taken = min(quota, available)
            fetched += taken
            remaining -= taken
        assert fetched <= BUDGET


def test_an_exhausted_budget_grants_nothing() -> None:
    assert adaptive_quota(0, 3) == 0
    assert adaptive_quota(BUDGET, 0) == 0


@pytest.mark.parametrize(
    ("policy", "expected"),
    [
        (BUDGET_CURRENT_QUOTA, (9, 8, 8)),
        (BUDGET_REDISTRIBUTE_UNUSED, (9, None, None)),
        (BUDGET_GLOBAL_LIMITED_POOL, (None, None, None)),
    ],
)
def test_the_declared_quota_plan_says_what_is_known_before_any_query(
    policy: str, expected: tuple[int | None, ...]
) -> None:
    assert quota_plan(policy, BUDGET, 3) == expected


def test_an_unknown_policy_fails_loudly() -> None:
    with pytest.raises(ValueError, match="unknown candidate budget policy"):
        quota_plan("greedy", BUDGET, 3)


def test_a_plan_without_variants_grants_nothing() -> None:
    assert quota_plan(BUDGET_CURRENT_QUOTA, BUDGET, 0) == ()


# ---------------------------------------------------------------------------
# Truncatura do conjunto global
# ---------------------------------------------------------------------------


def test_strategy_priority_beats_raw_score() -> None:
    """``ts_rank_cd`` de variantes diferentes não é grandeza comparável.

    Um candidato encontrado pela consulta conjuntiva precede um da disjuntiva
    mesmo com score bruto muito inferior.
    """
    conjunctive = _candidate(strategy=LexicalQueryStrategy.EXACT, raw_score=0.01)
    disjunctive = _candidate(strategy=LexicalQueryStrategy.REDUCED_OR, raw_score=0.99)
    assert truncate_pool([disjunctive, conjunctive], 2) == [conjunctive, disjunctive]


def test_within_one_strategy_the_higher_score_wins() -> None:
    low = _candidate(raw_score=0.10)
    high = _candidate(raw_score=0.90)
    assert truncate_pool([low, high], 1) == [high]


def test_the_pool_order_is_total_and_independent_of_row_order() -> None:
    """Sem desempate completo, a condição deixaria de ser reprodutível."""
    document = uuid4()
    tied = [
        _candidate(document_id=document, chunk_index=index, raw_score=0.5)
        for index in (3, 1, 2)
    ]
    assert truncate_pool(tied, 3) == truncate_pool(list(reversed(tied)), 3)
    assert [c.chunk_index for c in truncate_pool(tied, 3)] == [1, 2, 3]


def test_truncation_keeps_at_most_the_budget() -> None:
    pool = [_candidate(raw_score=index / 100) for index in range(40)]
    assert len(truncate_pool(pool, BUDGET)) == BUDGET


def test_a_pool_smaller_than_the_budget_is_kept_whole() -> None:
    pool = [_candidate() for _ in range(3)]
    assert len(truncate_pool(pool, BUDGET)) == 3


def test_pool_order_key_is_a_plain_tuple_of_comparables() -> None:
    key = pool_order_key(_candidate())
    assert isinstance(key, tuple)
    assert len(key) == 5


# ---------------------------------------------------------------------------
# Deduplicação
# ---------------------------------------------------------------------------


def test_the_same_segment_seen_twice_keeps_the_better_strategy_and_the_higher_score() -> None:
    """Espelha ``_merge_candidate`` de produção.

    ``strategy`` alimenta ``strategy_quality``, que é um sinal do ranking:
    guardar a pior estratégia faria a experiência medir duas coisas ao mesmo
    tempo.
    """
    chunk_id = uuid4()
    weak = _candidate(
        chunk_id=chunk_id, strategy=LexicalQueryStrategy.REDUCED_OR, raw_score=0.9
    )
    strong = _candidate(
        chunk_id=chunk_id, strategy=LexicalQueryStrategy.EXACT, raw_score=0.2
    )
    pool: dict[object, LexicalCandidate] = {}
    merge_candidate(pool, weak)
    merge_candidate(pool, strong)
    merged = pool[chunk_id]
    assert merged.strategy is LexicalQueryStrategy.EXACT
    assert merged.raw_score == 0.9
    assert len(pool) == 1


def test_merging_is_independent_of_the_order_the_variants_run() -> None:
    chunk_id = uuid4()
    weak = _candidate(
        chunk_id=chunk_id, strategy=LexicalQueryStrategy.REDUCED_OR, raw_score=0.9
    )
    strong = _candidate(
        chunk_id=chunk_id, strategy=LexicalQueryStrategy.EXACT, raw_score=0.2
    )
    forward: dict[object, LexicalCandidate] = {}
    backward: dict[object, LexicalCandidate] = {}
    merge_candidate(forward, weak)
    merge_candidate(forward, strong)
    merge_candidate(backward, strong)
    merge_candidate(backward, weak)
    assert forward[chunk_id].strategy == backward[chunk_id].strategy
    assert forward[chunk_id].raw_score == backward[chunk_id].raw_score


# ---------------------------------------------------------------------------
# Destino de um alvo
# ---------------------------------------------------------------------------


def test_a_target_outside_the_pool_never_was_a_candidate() -> None:
    assert (
        classify_target_fate(in_pool=False, excluded_reason=None, rank=None, top_k=5)
        == FATE_NEVER_A_CANDIDATE
    )


def test_a_target_rejected_by_eligibility_is_reported_as_excluded() -> None:
    assert (
        classify_target_fate(
            in_pool=True, excluded_reason="insufficient_coverage", rank=None, top_k=5
        )
        == FATE_CANDIDATE_EXCLUDED
    )


def test_a_surviving_target_below_the_cut_is_not_confused_with_an_absent_one() -> None:
    """A distinção que o D4.2 não conseguia exprimir, e que dá nome à fase."""
    assert (
        classify_target_fate(in_pool=True, excluded_reason=None, rank=7, top_k=5)
        == FATE_RANKED_OUTSIDE_TOP_K
    )


def test_a_target_inside_the_cut_is_returned() -> None:
    assert (
        classify_target_fate(in_pool=True, excluded_reason=None, rank=5, top_k=5)
        == FATE_RETURNED
    )


def test_candidate_recall_counts_everything_that_reached_evaluation() -> None:
    assert candidate_recall([FATE_RETURNED, FATE_CANDIDATE_EXCLUDED]) == 1.0
    assert candidate_recall([FATE_RETURNED, FATE_NEVER_A_CANDIDATE]) == 0.5
    assert candidate_recall([FATE_NEVER_A_CANDIDATE]) == 0.0


def test_candidate_recall_is_undefined_without_targets() -> None:
    """Q013 não tem alvos; 0.0 diria "o sistema falhou" e seria falso."""
    assert candidate_recall([]) is None


# ---------------------------------------------------------------------------
# Posição do alvo na ordenação FTS
# ---------------------------------------------------------------------------

QUOTAS = {"exact": 7, "reduced_and": 6, "canonical_relaxed_and": 6, "reduced_or": 6}


def _match(strategy: str, position: int, total: int = 100) -> dict:
    return {"strategy": strategy, "position": position, "total": total}


def test_a_target_within_its_quota_is_reachable() -> None:
    summary = summarise_target_position([_match("reduced_or", 3)], QUOTAS)
    assert summary["reachable_under_current_quota"] is True
    assert summary["best_position"] == 3


def test_a_target_below_the_cut_is_unreachable() -> None:
    """O caso Q009: posição 13, quota 8."""
    summary = summarise_target_position([_match("reduced_or", 13, 87)], {"reduced_or": 8})
    assert summary["reachable_under_current_quota"] is False
    assert summary["best_total"] == 87


def test_reachability_considers_every_variant_not_only_the_best() -> None:
    """Basta uma variante o trazer dentro da quota.

    Olhar só para a de maior prioridade daria um falso negativo num alvo que a
    disjuntiva alcança e a conjuntiva não.
    """
    matches = [_match("exact", 99), _match("reduced_or", 2)]
    assert summarise_target_position(matches, QUOTAS)["reachable_under_current_quota"]


def test_the_reported_best_match_is_the_highest_priority_strategy() -> None:
    """O caso Q014, que casa duas variantes."""
    matches = [_match("reduced_or", 3, 147), _match("canonical_relaxed_and", 2, 3)]
    summary = summarise_target_position(matches, QUOTAS)
    assert summary["best_strategy"] == "canonical_relaxed_and"
    assert summary["best_position"] == 2
    assert [m["strategy"] for m in summary["matches"]] == [
        "canonical_relaxed_and",
        "reduced_or",
    ]


def test_a_target_no_variant_finds_is_reported_as_such() -> None:
    summary = summarise_target_position([], QUOTAS)
    assert summary["matched_by_any_variant"] is False
    assert summary["reachable_under_current_quota"] is False
    assert summary["best_position"] is None


def test_a_strategy_absent_from_the_plan_grants_no_quota() -> None:
    """Uma variante que o plano não produziu não pode admitir nada."""
    summary = summarise_target_position([_match("exact", 1)], {"reduced_or": 25})
    assert summary["reachable_under_current_quota"] is False


def _position(question_id: str, chunk_index: int, *, reachable: bool) -> dict:
    return {
        "question_id": question_id,
        "corpus_item_id": "P1-DOC-002",
        "chunk_index": chunk_index,
        "reachable_under_current_quota": reachable,
    }


def _control_cell(fates: dict[str, list[tuple[int, str]]]) -> dict:
    return {
        "matching_variant": MATCHING_EXACT_CANONICAL,
        "question_results": [
            {
                "question_id": question_id,
                "targets": [
                    {"corpus_item_id": "P1-DOC-002", "chunk_index": index, "fate": fate}
                    for index, fate in targets
                ],
            }
            for question_id, targets in fates.items()
        ],
    }


def test_positions_that_explain_the_observed_fates_pass() -> None:
    positions = [_position("Q001", 14, reachable=True), _position("Q009", 251, reachable=False)]
    cell = _control_cell(
        {"Q001": [(14, FATE_RETURNED)], "Q009": [(251, FATE_NEVER_A_CANDIDATE)]}
    )
    assert verify_positions_explain_fates(positions, [cell]) == []


def test_a_position_table_that_contradicts_the_run_is_rejected() -> None:
    """A tabela do relatório sai destes campos; se não explicasse os destinos
    observados seria uma segunda medição não verificada, e não evidência."""
    positions = [_position("Q009", 251, reachable=True)]
    cell = _control_cell({"Q009": [(251, FATE_NEVER_A_CANDIDATE)]})
    problems = verify_positions_explain_fates(positions, [cell])
    assert problems
    assert "NEVER_A_CANDIDATE" in problems[0]


def test_a_target_predicted_unreachable_but_returned_is_rejected() -> None:
    positions = [_position("Q009", 251, reachable=False)]
    cell = _control_cell({"Q009": [(251, FATE_RETURNED)]})
    assert verify_positions_explain_fates(positions, [cell])


# ---------------------------------------------------------------------------
# O artefacto versionado
# ---------------------------------------------------------------------------

ARTEFACT = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "evaluation"
    / "retrieval-experiment-candidate-budget-p1-s1.json"
)


def _artefact() -> dict:
    return json.loads(ARTEFACT.read_text(encoding="utf-8"))


def test_the_artefact_records_a_position_for_every_grade_two_target() -> None:
    """Uma tabela incompleta não permite recontar a afirmação que dela se extrai.

    Inclui os alvos das perguntas excluídas das métricas, que continuam a ser
    alvos do corpus.
    """
    payload = _artefact()
    positions = payload["target_candidate_positions"]
    recorded = {
        (r["question_id"], r["corpus_item_id"], r["chunk_index"]) for r in positions
    }
    ground_truth = json.loads(
        (
            Path(__file__).resolve().parents[2]
            / "docs"
            / "evaluation"
            / "retrieval-ground-truth-p1-seed.json"
        ).read_text(encoding="utf-8")
    )
    expected = {
        (question["question_id"], judgment["corpus_item_id"], judgment["chunk_index"])
        for question in ground_truth["questions"]
        for judgment in question["evidence_judgments"]
        if judgment["relevance"] >= 2
    }
    assert recorded == expected
    assert payload["target_position_summary"]["targets_total"] == len(expected)


def test_the_position_claim_in_the_report_is_recomputable_from_the_artefact() -> None:
    """A afirmação central do relatório não pode ser uma contagem à mão."""
    summary = _artefact()["target_position_summary"]
    best = summary["best_positions_sorted"]
    assert len(best) == summary["targets_total"] == 16
    assert sum(1 for position in best if position <= 13) == 15
    assert max(best) == 99


def test_the_artefact_positions_agree_with_the_observed_fates() -> None:
    payload = _artefact()
    control = [
        cell for cell in payload["cells"] if cell["budget_policy"] == BUDGET_CURRENT_QUOTA
    ]
    assert control
    assert verify_positions_explain_fates(payload["target_candidate_positions"], control) == []
    assert payload["positions_explain_observed_fates"] is True


# ---------------------------------------------------------------------------
# O ranking de diagnóstico não pode divergir do do D4.3
# ---------------------------------------------------------------------------


def test_the_diagnostic_ranking_matches_the_d43_ranking_on_its_prefix() -> None:
    """A única diferença permitida é o corte em ``top_k``.

    ``rank_with_diagnostics`` existe para devolver a lista inteira e os motivos
    de exclusão. Se divergisse de ``rank_with_variant`` em mais do que isso, os
    deltas do D4.5 mediriam a reimplementação e não a política de orçamento.
    """
    top_k = 2
    candidates = [
        _candidate(normalized_content="o prazo de matricula termina em outubro"),
        _candidate(normalized_content="prazo de matricula e inscricao no primeiro semestre"),
        _candidate(normalized_content="a renovacao da matricula tem prazo proprio"),
        _candidate(normalized_content="texto sem relacao nenhuma com o assunto"),
    ]
    query = normalize_text("Qual e o prazo de matricula?")

    diagnostic, excluded_detail, diagnostic_counts = rank_with_diagnostics(
        question_text="Qual e o prazo de matricula?",
        normalized_query=query,
        candidates=candidates,
        language="pt",
        variant=MATCHING_EXACT_CANONICAL,
        stems={},
    )
    reference, reference_counts = rank_with_variant(
        question_text="Qual e o prazo de matricula?",
        normalized_query=query,
        candidates=candidates,
        language="pt",
        variant=MATCHING_EXACT_CANONICAL,
        stems={},
        top_k=top_k,
    )
    assert diagnostic[:top_k] == reference
    assert diagnostic_counts == reference_counts
    assert len(diagnostic) >= len(reference)
    # Cada excluído tem motivo, e nenhum sobrevivente aparece na lista de exclusões.
    assert all(detail["reason"] for detail in excluded_detail.values())
    assert not {c.chunk_id for c in diagnostic} & set(excluded_detail)


def test_the_diagnostic_ranking_keeps_survivors_beyond_top_k() -> None:
    """Sem isto, ``RANKED_OUTSIDE_TOP_K`` seria inobservável."""
    candidates = [
        _candidate(normalized_content="prazo de matricula um"),
        _candidate(normalized_content="prazo de matricula dois"),
        _candidate(normalized_content="prazo de matricula tres"),
    ]
    query = normalize_text("Qual e o prazo de matricula?")
    diagnostic, _, _ = rank_with_diagnostics(
        question_text="Qual e o prazo de matricula?",
        normalized_query=query,
        candidates=candidates,
        language="pt",
        variant=MATCHING_EXACT_CANONICAL,
        stems={},
    )
    reference, _ = rank_with_variant(
        question_text="Qual e o prazo de matricula?",
        normalized_query=query,
        candidates=candidates,
        language="pt",
        variant=MATCHING_EXACT_CANONICAL,
        stems={},
        top_k=1,
    )
    assert len(diagnostic) > len(reference)
    assert identity_projection().name == MATCHING_EXACT_CANONICAL


# ---------------------------------------------------------------------------
# Comparação entre políticas
# ---------------------------------------------------------------------------


def _result(
    question_id: str,
    *,
    recall: float = 1.0,
    rr: float = 1.0,
    ndcg: float = 1.0,
    fate: str = FATE_RETURNED,
    ranking_chunk: int = 24,
    measured: bool = True,
) -> dict:
    record: dict = {
        "question_id": question_id,
        "candidates_evaluated": 8,
        "retrieved_count": 1,
        "judged_distractors_returned": 0,
        "unjudged_returned": 0,
        "targets": [{"corpus_item_id": "P1-DOC-002", "chunk_index": 24, "fate": fate}],
        "ranking": [
            {
                "position": 1,
                "corpus_item_id": "P1-DOC-002",
                "chunk_index": ranking_chunk,
                "grade": 2,
                "judged": True,
            }
        ],
    }
    if measured:
        record["recall"] = {"1": recall, "3": recall, "5": recall}
        record["ndcg"] = {"1": ndcg, "3": ndcg, "5": ndcg}
        record["reciprocal_rank"] = rr
    return record


def _cell(results: list[dict], policy: str) -> dict:
    return {
        "budget_policy": policy,
        "matching_variant": MATCHING_EXACT_CANONICAL,
        "question_results": results,
        "aggregate": {
            "questions_measured": len([r for r in results if "recall" in r]),
            "recall": {"1": 1.0, "3": 1.0, "5": 1.0},
            "ndcg": {"1": 1.0, "3": 1.0, "5": 1.0},
            "mrr": 1.0,
            "candidate_recall": 1.0,
        },
    }


def test_identical_policies_report_no_change() -> None:
    control = _cell([_result("Q001")], BUDGET_CURRENT_QUOTA)
    other = _cell([_result("Q001")], BUDGET_REDISTRIBUTE_UNUSED)
    delta = compare_policies(control, other)
    assert delta["policies_identical"] is True
    assert delta["unchanged_count"] == 1


def test_a_regression_is_reported_with_both_sides() -> None:
    control = _cell([_result("Q001")], BUDGET_CURRENT_QUOTA)
    other = _cell(
        [_result("Q001", recall=0.0, rr=0.0, ndcg=0.0, fate=FATE_RANKED_OUTSIDE_TOP_K)],
        BUDGET_REDISTRIBUTE_UNUSED,
    )
    delta = compare_policies(control, other)
    assert delta["regressed"] == ["Q001"]
    changed = delta["questions_changed"][0]
    assert changed["target_fates"] == [[FATE_RETURNED], [FATE_RANKED_OUTSIDE_TOP_K]]
    assert changed["metrics"]["reciprocal_rank"] == [1.0, 0.0]


def test_a_fate_change_without_a_metric_change_is_still_reported() -> None:
    """O caso central da fase: o alvo passa a ser avaliado e continua a perder.

    As métricas não mexem — era zero antes e é zero depois — mas o diagnóstico
    mudou, e é ele que distingue um problema de orçamento de um de elegibilidade.
    """
    control = _cell(
        [_result("Q009", recall=0.0, rr=0.0, ndcg=0.0, fate=FATE_NEVER_A_CANDIDATE)],
        BUDGET_CURRENT_QUOTA,
    )
    other = _cell(
        [_result("Q009", recall=0.0, rr=0.0, ndcg=0.0, fate=FATE_CANDIDATE_EXCLUDED)],
        BUDGET_REDISTRIBUTE_UNUSED,
    )
    delta = compare_policies(control, other)
    assert delta["policies_identical"] is False
    assert delta["improved"] == []
    assert delta["regressed"] == []
    assert delta["questions_changed"][0]["target_fates"] == [
        [FATE_NEVER_A_CANDIDATE],
        [FATE_CANDIDATE_EXCLUDED],
    ]


def test_the_aggregate_delta_includes_candidate_recall() -> None:
    control = _cell([_result("Q001")], BUDGET_CURRENT_QUOTA)
    other = _cell([_result("Q001")], BUDGET_REDISTRIBUTE_UNUSED)
    other["aggregate"]["candidate_recall"] = 0.5
    delta = compare_policies(control, other)
    assert delta["aggregate_delta"]["candidate_recall"] == -0.5


def test_a_recall_gain_paid_for_with_a_worse_first_hit_is_not_an_improvement() -> None:
    before = _result("Q001", recall=0.5, rr=1.0, ndcg=0.8)
    after = _result("Q001", recall=1.0, rr=0.5, ndcg=0.8)
    assert _direction(before, after) == "mixed"


def test_direction_reads_the_three_metrics_together() -> None:
    before = _result("Q001", recall=0.0, rr=0.0, ndcg=0.0)
    after = _result("Q001")
    assert _direction(before, after) == "improved"
    assert _direction(after, before) == "regressed"
    assert _direction(after, after) == "reordered_without_metric_change"
