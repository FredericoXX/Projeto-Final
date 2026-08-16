"""Comparação entre condições e controlos nulos do experimento D4.4.

O que estes testes protegem é a **atribuição de causa**. O desenho só permite
dizer "esta diferença deve-se ao diacrítico" porque duas coisas se verificam: as
perguntas sem acentos a restituir medem exatamente o mesmo nas duas condições, e
o sentido de cada mudança é lido de Recall, MRR e nDCG em conjunto, e não do
Recall sozinho. Ambas falhariam em silêncio se não estivessem fixadas.

Funções puras sobre dicionários: não tocam na base de dados.
"""

from typing import Any

import pytest

from scripts.evaluate_diacritics_experiment import (
    _direction,
    _ranking_signature,
    compare_conditions,
    verify_null_controls,
)

PAIR_INDEX = {"Q001": "Q001-diacritics"}


def _ranking(chunk_index: int = 24, grade: int = 2, judged: bool = True) -> list[dict[str, Any]]:
    return [
        {
            "position": 1,
            "corpus_item_id": "P1-DOC-002",
            "chunk_index": chunk_index,
            "grade": grade,
            "judged": judged,
        }
    ]


def _result(
    question_id: str,
    *,
    recall: float = 1.0,
    rr: float = 1.0,
    ndcg: float = 1.0,
    retrieved: int = 1,
    distractors: int = 0,
    unjudged: int = 0,
    ranking: list[dict[str, Any]] | None = None,
    measured: bool = True,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "question_id": question_id,
        "retrieved_count": retrieved,
        "judged_distractors_returned": distractors,
        "unjudged_returned": unjudged,
        "ranking": _ranking() if ranking is None else ranking,
    }
    if measured:
        record["recall"] = {"1": recall, "3": recall, "5": recall}
        record["ndcg"] = {"1": ndcg, "3": ndcg, "5": ndcg}
        record["reciprocal_rank"] = rr
    return record


def _cell(results: list[dict[str, Any]], *, variant: str = "stem_accented") -> dict[str, Any]:
    measured = [result for result in results if "recall" in result]
    return {
        "matching_variant": variant,
        "question_set": "original",
        "question_results": results,
        "aggregate": {
            "questions_measured": len(measured),
            "recall": {"1": 1.0, "3": 1.0, "5": 1.0},
            "ndcg": {"1": 1.0, "3": 1.0, "5": 1.0},
            "mrr": 1.0,
        },
    }


# ---------------------------------------------------------------------------
# Assinatura do ranking
# ---------------------------------------------------------------------------


def test_ranking_signature_separates_an_unjudged_result_from_a_grade_zero_distractor() -> None:
    """Ambos valem 0; sem a bandeira ``judged`` seriam indistinguíveis."""
    distractor = _ranking_signature(_ranking(grade=0, judged=True))
    unjudged = _ranking_signature(_ranking(grade=0, judged=False))
    assert distractor != unjudged


# ---------------------------------------------------------------------------
# Sentido da mudança
# ---------------------------------------------------------------------------


def test_direction_reads_the_three_metrics_together() -> None:
    before = _result("Q001", recall=0.0, rr=0.0, ndcg=0.0)
    after = _result("Q001", recall=1.0, rr=1.0, ndcg=1.0)
    assert _direction(before, after) == "improved"
    assert _direction(after, before) == "regressed"


def test_a_recall_gain_paid_for_with_a_worse_first_hit_is_not_an_improvement() -> None:
    """Chamar isto "melhoria" esconderia a perda de precisão no topo."""
    before = _result("Q001", recall=0.5, rr=1.0, ndcg=0.8)
    after = _result("Q001", recall=1.0, rr=0.5, ndcg=0.8)
    assert _direction(before, after) == "mixed"


def test_equal_metrics_are_reported_as_a_reordering() -> None:
    before = _result("Q001")
    after = _result("Q001")
    assert _direction(before, after) == "reordered_without_metric_change"


# ---------------------------------------------------------------------------
# Comparação entre condições
# ---------------------------------------------------------------------------


def test_identical_cells_report_no_change() -> None:
    cell = _cell([_result("Q001")])
    paired = _cell([_result("Q001-diacritics")])
    delta = compare_conditions(cell, paired, PAIR_INDEX)
    assert delta["conditions_identical"] is True
    assert delta["unchanged"] == ["Q001"]
    assert delta["questions_changed"] == []


def test_a_metric_change_is_reported_against_the_original_identifier() -> None:
    before = _cell([_result("Q001", recall=0.0, rr=0.0, ndcg=0.0, retrieved=0, ranking=[])])
    after = _cell([_result("Q001-diacritics")])
    delta = compare_conditions(before, after, PAIR_INDEX)
    assert delta["improved"] == ["Q001"]
    assert delta["conditions_identical"] is False
    changed = delta["questions_changed"][0]
    assert changed["question_id"] == "Q001"
    assert changed["paired_question_id"] == "Q001-diacritics"
    assert changed["metrics"]["reciprocal_rank"] == [0.0, 1.0]
    assert changed["retrieved_count"] == [0, 1]


def test_a_reordering_without_metric_change_is_still_reported() -> None:
    """Ruído que entra sem mexer nas métricas continua a ser um efeito."""
    before = _cell([_result("Q001")])
    after = _cell([_result("Q001-diacritics", ranking=_ranking(chunk_index=99))])
    delta = compare_conditions(before, after, PAIR_INDEX)
    assert delta["conditions_identical"] is False
    assert delta["improved"] == []
    assert delta["regressed"] == []
    assert delta["questions_changed"][0]["direction"] == "reordered_without_metric_change"


def test_a_question_without_metrics_is_compared_by_what_it_returned() -> None:
    """Q013 e Q014 não têm métrica, mas mudarem de resultado é observável."""
    before = _cell([_result("Q001", measured=False, retrieved=0, ranking=[])])
    after = _cell([_result("Q001-diacritics", measured=False)])
    delta = compare_conditions(before, after, PAIR_INDEX)
    changed = delta["questions_changed"][0]
    assert changed["direction"] == "observed_only"
    assert changed["measured"] is False
    assert "metrics" not in changed


def test_the_aggregate_delta_is_the_difference_between_the_conditions() -> None:
    before = _cell([_result("Q001")])
    after = _cell([_result("Q001-diacritics")])
    after["aggregate"]["mrr"] = 0.5
    after["aggregate"]["recall"]["5"] = 0.75
    delta = compare_conditions(before, after, PAIR_INDEX)
    assert delta["aggregate_delta"]["mrr"] == -0.5
    assert delta["aggregate_delta"]["recall"]["5"] == -0.25


# ---------------------------------------------------------------------------
# Controlos nulos
# ---------------------------------------------------------------------------


def test_an_identical_null_control_passes() -> None:
    before = _cell([_result("Q001")])
    after = _cell([_result("Q001-diacritics")])
    assert verify_null_controls(before, after, PAIR_INDEX, ["Q001"]) == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("retrieved_count", 4),
        ("judged_distractors_returned", 1),
        ("unjudged_returned", 2),
    ],
)
def test_a_null_control_that_returns_differently_is_rejected(
    field: str, value: int
) -> None:
    """Texto byte a byte igual não pode produzir resultados diferentes.

    Se produzisse, nenhum outro delta seria atribuível ao diacrítico.
    """
    before = _cell([_result("Q001")])
    after = _cell([_result("Q001-diacritics")])
    after["question_results"][0][field] = value
    problems = verify_null_controls(before, after, PAIR_INDEX, ["Q001"])
    assert any(field in problem for problem in problems)


def test_a_null_control_with_a_changed_ranking_is_rejected() -> None:
    before = _cell([_result("Q001")])
    after = _cell([_result("Q001-diacritics", ranking=_ranking(chunk_index=99))])
    problems = verify_null_controls(before, after, PAIR_INDEX, ["Q001"])
    assert any("ranking changed" in problem for problem in problems)


def test_a_null_control_with_changed_metrics_is_rejected() -> None:
    before = _cell([_result("Q001")])
    after = _cell([_result("Q001-diacritics", ndcg=0.5)])
    problems = verify_null_controls(before, after, PAIR_INDEX, ["Q001"])
    assert any("metrics changed" in problem for problem in problems)


def test_a_null_control_with_a_changed_reciprocal_rank_is_rejected() -> None:
    before = _cell([_result("Q001")])
    after = _cell([_result("Q001-diacritics", rr=0.5)])
    problems = verify_null_controls(before, after, PAIR_INDEX, ["Q001"])
    assert any("reciprocal_rank changed" in problem for problem in problems)


def test_a_null_control_that_stops_being_measurable_is_rejected() -> None:
    before = _cell([_result("Q001")])
    after = _cell([_result("Q001-diacritics", measured=False)])
    problems = verify_null_controls(before, after, PAIR_INDEX, ["Q001"])
    assert any("measurability changed" in problem for problem in problems)


def test_questions_outside_the_null_control_list_are_not_checked() -> None:
    before = _cell([_result("Q001")])
    after = _cell([_result("Q001-diacritics", rr=0.5)])
    assert verify_null_controls(before, after, PAIR_INDEX, []) == []
