"""A guarda de replicação do experimento D4.3, e o mapa de acentuação.

Estes testes existem por uma razão concreta: a primeira versão da guarda
comparava apenas o Recall das perguntas que **ambos** os lados tivessem medido,
e o conjunto de comparação era ele próprio derivado do que a célula continha.
Uma célula vazia passava. Cada teste abaixo corresponde a um buraco real que
essa versão deixava aberto.

Não tocam na base de dados: a guarda é uma função pura sobre dois dicionários.
"""

import pytest

from scripts.evaluate_retrieval_experiment import (
    ExperimentError,
    accent_map_for_text,
    verify_baseline_integrity,
    verify_baseline_replication,
)


def _question(
    question_id: str,
    *,
    retrieved: int = 1,
    ranking: list | None = None,
    measured: bool = True,
) -> dict:
    record: dict = {
        "question_id": question_id,
        "retrieved_count": retrieved,
        "ranking": ranking
        if ranking is not None
        else [{"position": 1, "corpus_item_id": "P1-DOC-002", "chunk_index": 24}],
    }
    if measured:
        record["recall"] = {"1": 1.0, "3": 1.0, "5": 1.0}
        record["ndcg"] = {"1": 1.0, "3": 1.0, "5": 1.0}
        record["reciprocal_rank"] = 1.0
    return record


def _artefact(questions: list[dict], observed: list[dict] | None = None) -> dict:
    measured = [q for q in questions if "recall" in q]
    return {
        "question_results": questions,
        "observed_only": observed or [],
        "aggregate": {
            "questions_measured": len(measured),
            "recall": {"1": 1.0, "3": 1.0, "5": 1.0},
            "ndcg": {"1": 1.0, "3": 1.0, "5": 1.0},
            "mrr": 1.0,
        },
    }


def _cell(questions: list[dict]) -> dict:
    return _artefact(questions)


def test_identical_artefacts_report_no_problem() -> None:
    baseline = _artefact([_question("Q001")], observed=[_question("Q013", measured=False)])
    cell = _cell([_question("Q001"), _question("Q013", measured=False)])
    assert verify_baseline_replication(cell, baseline) == []


def test_empty_cell_is_rejected() -> None:
    """O buraco original: sem perguntas, não havia nada para comparar."""
    baseline = _artefact([_question("Q001")])
    problems = verify_baseline_replication(_cell([]), baseline)
    assert problems
    assert any("missing" in problem for problem in problems)


def test_extra_question_is_rejected() -> None:
    baseline = _artefact([_question("Q001")])
    problems = verify_baseline_replication(_cell([_question("Q001"), _question("Q099")]), baseline)
    assert any("absent from the baseline" in problem for problem in problems)


def test_altered_ranking_is_rejected() -> None:
    baseline = _artefact([_question("Q001")])
    moved = _question(
        "Q001",
        ranking=[{"position": 1, "corpus_item_id": "P1-DOC-003", "chunk_index": 7}],
    )
    problems = verify_baseline_replication(_cell([moved]), baseline)
    assert any("ranking" in problem for problem in problems)


def test_altered_mrr_is_rejected() -> None:
    baseline = _artefact([_question("Q001")])
    altered = _question("Q001")
    altered["reciprocal_rank"] = 0.5
    assert any(
        "reciprocal_rank" in problem
        for problem in verify_baseline_replication(_cell([altered]), baseline)
    )


def test_altered_ndcg_is_rejected() -> None:
    baseline = _artefact([_question("Q001")])
    altered = _question("Q001")
    altered["ndcg"]["5"] = 0.25
    problems = verify_baseline_replication(_cell([altered]), baseline)
    assert any("ndcg@5" in problem for problem in problems)


def test_altered_retrieved_count_is_rejected() -> None:
    baseline = _artefact([_question("Q001")])
    altered = _question("Q001", retrieved=9)
    assert any(
        "retrieved_count" in problem
        for problem in verify_baseline_replication(_cell([altered]), baseline)
    )


def test_altered_aggregate_is_rejected() -> None:
    baseline = _artefact([_question("Q001")])
    cell = _cell([_question("Q001")])
    cell["aggregate"]["mrr"] = 0.1
    problems = verify_baseline_replication(cell, baseline)
    assert any("aggregate mrr" in problem for problem in problems)


def test_observed_only_questions_are_compared() -> None:
    """Q013 e Q014 vivem noutra lista no artefacto do D4.2 e não podem escapar."""
    baseline = _artefact([_question("Q001")], observed=[_question("Q013", measured=False)])
    diverged = _question("Q013", measured=False, retrieved=4)
    problems = verify_baseline_replication(_cell([_question("Q001"), diverged]), baseline)
    assert any("Q013" in problem for problem in problems)


def test_question_measured_on_one_side_only_is_rejected() -> None:
    baseline = _artefact([_question("Q001", measured=False)])
    problems = verify_baseline_replication(_cell([_question("Q001")]), baseline)
    assert any("measured" in problem for problem in problems)


def test_baseline_integrity_rejects_a_tampered_artefact() -> None:
    tampered = {"a": 1, "result_digest": "0" * 64}
    with pytest.raises(ExperimentError, match="does not match its own result_digest"):
        verify_baseline_integrity(tampered)


def test_baseline_integrity_requires_a_digest() -> None:
    with pytest.raises(ExperimentError, match="no result_digest"):
        verify_baseline_integrity({"a": 1})


# ---------------------------------------------------------------------------
# Mapa de acentuação
# ---------------------------------------------------------------------------


def test_accent_map_only_sees_its_own_text() -> None:
    """A propriedade que a versão global violava."""
    assert accent_map_for_text("a residência estudantil") == {"residencia": "residência"}
    assert accent_map_for_text("a residencia estudantil") == {}


def test_accent_map_keeps_the_first_occurrence() -> None:
    accents = accent_map_for_text("período e periodo e perÍodo")
    assert accents["periodo"] == "período"


def test_accent_map_ignores_words_without_diacritics() -> None:
    assert accent_map_for_text("prazo de matricula") == {}


def test_accent_map_is_independent_of_row_order() -> None:
    """Sem ORDER BY, a base pode devolver linhas em qualquer ordem.

    O mapa é construído por texto, pelo que a ordem das linhas não pode
    influenciar o resultado — era essa a fonte de indeterminismo do índice
    global.
    """
    first = accent_map_for_text("cerimónia de outorga")
    second = accent_map_for_text("cerimónia de outorga")
    assert first == second == {"cerimonia": "cerimónia"}
