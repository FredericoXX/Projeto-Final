"""Comparação definitiva C0 × C1 depois do repooling, e o artefacto do D4.8.1.

Quatro grupos:

- o **módulo puro** ``app.evaluation.lexical_dense_comparison`` — destino dos
  alvos, separação entre complementaridade e diferença de ranking, e a projeção
  independente do fornecedor;
- a **guarda de âmbito do repooling** ``verify_requests_satisfied``, que prova
  que se julgou exatamente o que a lista de pedidos declara;
- as **guardas do runner**, testadas como funções puras sobre payloads
  fabricados, sem base de dados nem fornecedor;
- os **artefactos versionados** — o ground truth repooled e o artefacto da
  comparação —, que têm de ser coerentes entre si, coincidir com os seus
  próprios digests e não transportar texto documental.

Nenhum teste contacta a rede, o PostgreSQL ou o fornecedor de embeddings.
"""

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from app.evaluation.dense_baseline import (
    COMPARABLE,
    CONDITION_DENSE,
    CONDITION_LEXICAL,
    REPOOLING_REQUIRED,
    PoolItem,
)
from app.evaluation.ground_truth_identity import ground_truth_digest
from app.evaluation.lexical_dense_comparison import (
    BOTH,
    C0_ONLY,
    C1_ONLY,
    EXECUTION_DIGEST_SCOPE,
    NEITHER,
    RESULT_DIGEST_SCOPE,
    SOLVED_BY_BOTH,
    SOLVED_BY_C0_ONLY,
    SOLVED_BY_C1_ONLY,
    SOLVED_BY_NEITHER,
    TargetOutcome,
    artefact_digests,
    classify_question,
    execution_projection,
    favoured_condition,
    grade_histogram,
    rank_of,
    result_projection,
    target_outcomes,
)
from app.evaluation.repooling import verify_repooling, verify_requests_satisfied
from app.evaluation.results import canonical_json
from app.evaluation.retrieval_metrics import BINARY_RELEVANCE_THRESHOLD
from scripts.evaluate_lexical_dense_comparison import (
    EXIT_BASELINE_MISMATCH,
    EXIT_NOT_COMPARABLE,
    HISTORICAL_GROUND_TRUTH_DIGEST,
    ExperimentError,
    verify_comparable,
    verify_reproduces_d48_rankings,
    verify_requests_integrity,
)

DOCS = Path(__file__).resolve().parents[2] / "docs" / "evaluation"
ARTEFACT = DOCS / "lexical-dense-comparison-p1-s1.json"
D48_ARTEFACT = DOCS / "dense-baseline-p1-s1.json"
REQUESTS = DOCS / "dense-repooling-requests-p1-s1.json"
HISTORICAL_GROUND_TRUTH = DOCS / "retrieval-ground-truth-p1-repooled.json"
GROUND_TRUTH = DOCS / "retrieval-ground-truth-p1-lexical-dense-repooled.json"


# --- Anulação das fixtures de base de dados do conftest -------------------------


@pytest.fixture(scope="session", autouse=True)
def _override_get_db() -> None:
    """Anula a fixture homónima do conftest: aqui não há dependência de DB."""


@pytest.fixture(autouse=True)
def _clean_tables() -> None:
    """Anula a fixture homónima do conftest: aqui não há tabelas a truncar."""


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


# --- Módulo puro: destino dos alvos ----------------------------------------------


def test_the_destination_derives_from_the_two_ranks() -> None:
    both = TargetOutcome("P1-DOC-002", 14, rank_c0=1, rank_c1=3)
    only_c0 = TargetOutcome("P1-DOC-002", 14, rank_c0=1, rank_c1=None)
    only_c1 = TargetOutcome("P1-DOC-002", 14, rank_c0=None, rank_c1=2)
    neither = TargetOutcome("P1-DOC-002", 14, rank_c0=None, rank_c1=None)
    assert both.destination == BOTH
    assert only_c0.destination == C0_ONLY
    assert only_c1.destination == C1_ONLY
    assert neither.destination == NEITHER


def test_complementarity_and_ranking_difference_are_mutually_exclusive() -> None:
    """Um alvo é exclusivo ou é comum; somar as duas contagens não pode
    contá-lo duas vezes."""
    outcomes = [
        TargetOutcome("P1-DOC-002", 14, rank_c0=1, rank_c1=3),
        TargetOutcome("P1-DOC-002", 16, rank_c0=2, rank_c1=2),
        TargetOutcome("P1-DOC-003", 37, rank_c0=1, rank_c1=None),
        TargetOutcome("P1-DOC-004", 60, rank_c0=None, rank_c1=1),
        TargetOutcome("P1-DOC-002", 78, rank_c0=None, rank_c1=None),
    ]
    for outcome in outcomes:
        assert not (outcome.is_real_complementarity and outcome.is_ranking_difference)


def test_the_same_position_in_both_is_not_a_ranking_difference() -> None:
    outcome = TargetOutcome("P1-DOC-002", 16, rank_c0=2, rank_c1=2)
    assert outcome.destination == BOTH
    assert not outcome.is_ranking_difference
    assert not outcome.is_real_complementarity


def test_an_exclusive_target_is_never_counted_as_a_ranking_difference() -> None:
    outcome = TargetOutcome("P1-DOC-003", 37, rank_c0=1, rank_c1=None)
    assert outcome.is_real_complementarity
    assert not outcome.is_ranking_difference


def test_rank_of_is_one_indexed_and_absent_is_none() -> None:
    pool = [PoolItem("P1-DOC-002", 14), PoolItem("P1-DOC-002", 16)]
    assert rank_of(PoolItem("P1-DOC-002", 14), pool) == 1
    assert rank_of(PoolItem("P1-DOC-002", 16), pool) == 2
    assert rank_of(PoolItem("P1-DOC-003", 37), pool) is None


def test_target_outcomes_are_ordered_by_anchor_and_not_by_rank() -> None:
    """A ordem tem de ser a do corpus, para que dois artefactos sejam
    diffáveis independentemente de quem ordenou os rankings."""
    targets = [PoolItem("P1-DOC-003", 37), PoolItem("P1-DOC-002", 14)]
    c0 = [PoolItem("P1-DOC-003", 37)]
    c1 = [PoolItem("P1-DOC-002", 14)]
    outcomes = target_outcomes(targets, c0, c1)
    assert [outcome.corpus_item_id for outcome in outcomes] == [
        "P1-DOC-002",
        "P1-DOC-003",
    ]


# --- Módulo puro: classificação das perguntas ------------------------------------


@pytest.mark.parametrize(
    ("rr_c0", "rr_c1", "expected"),
    [
        (1.0, 0.5, SOLVED_BY_BOTH),
        (1.0, 0.0, SOLVED_BY_C0_ONLY),
        (0.0, 0.2, SOLVED_BY_C1_ONLY),
        (0.0, 0.0, SOLVED_BY_NEITHER),
    ],
)
def test_a_question_is_solved_by_whoever_has_a_positive_reciprocal_rank(
    rr_c0: float, rr_c1: float, expected: str
) -> None:
    assert classify_question(rr_c0, rr_c1) == expected


def test_the_favoured_condition_is_decided_by_the_primary_ndcg() -> None:
    c0 = {"ndcg": {"1": 1.0, "3": 1.0, "5": 0.9}}
    c1 = {"ndcg": {"1": 0.0, "3": 0.0, "5": 0.7}}
    assert favoured_condition(c0, c1, 5) == CONDITION_LEXICAL
    assert favoured_condition(c1, c0, 5) == CONDITION_DENSE


def test_an_ndcg_tie_favours_nobody() -> None:
    metrics = {"ndcg": {"1": 0.5, "3": 0.5, "5": 0.5}}
    assert favoured_condition(metrics, copy.deepcopy(metrics), 5) is None


def test_the_grade_histogram_always_declares_the_three_grades() -> None:
    """Um histograma que omite o grau ausente confunde «zero» com «não medido»."""
    assert grade_histogram([]) == {"0": 0, "1": 0, "2": 0}
    assert grade_histogram([{"grade": 2}, {"grade": 2}, {"grade": 0}]) == {
        "0": 1,
        "1": 0,
        "2": 2,
    }


# --- Módulo puro: os dois digests -------------------------------------------------


def _payload(dense_scores: list[float], dense_positions: list[int]) -> dict[str, Any]:
    return {
        "experiment_version": "test",
        "question_results": [
            {
                "question_id": "Q001",
                "conditions": {
                    CONDITION_LEXICAL: {
                        "ranking": [
                            {
                                "position": 1,
                                "corpus_item_id": "P1-DOC-002",
                                "chunk_index": 14,
                                "score": 0.4137,
                                "grade": 2,
                            }
                        ]
                    },
                    CONDITION_DENSE: {
                        "ranking": [
                            {
                                "position": position,
                                "corpus_item_id": "P1-DOC-002",
                                "chunk_index": 14,
                                "score": score,
                                "grade": 2,
                            }
                            for position, score in zip(
                                dense_positions, dense_scores, strict=True
                            )
                        ]
                    },
                },
            }
        ],
        "no_evidence_questions": [
            {
                "question_id": "Q013",
                "similarity_top": 0.4718,
                "similarity_bottom": 0.4582,
                "other_questions_top_similarity_min": 0.6466,
                "other_questions_top_similarity_max": 0.8334,
                "relevant_results_found": False,
            }
        ],
        "executed_at": "2026-08-18T00:00:00+00:00",
        "execution_digest": "irrelevante",
    }


def test_the_result_digest_is_stable_under_provider_drift() -> None:
    """O gate de reprodutibilidade: duas execuções que só diferem na
    similaridade de C1 têm de ter o **mesmo** ``result_digest``."""
    first = _payload([0.688230], [1])
    second = _payload([0.688233], [1])
    assert first != second
    assert artefact_digests(first)[0] == artefact_digests(second)[0]


def test_the_execution_digest_records_the_drift_the_result_digest_absorbs() -> None:
    """A deriva fica preservada e visível, não arredondada para fora."""
    first = _payload([0.688230], [1])
    second = _payload([0.688233], [1])
    assert artefact_digests(first)[1] != artefact_digests(second)[1]


def test_the_two_digests_of_one_payload_differ() -> None:
    result, execution = artefact_digests(_payload([0.68], [1]))
    assert result != execution


def test_the_result_digest_does_not_absorb_a_change_of_position() -> None:
    """O que a projeção protege é o número, não o resultado."""
    first = artefact_digests(_payload([0.688230], [1]))[0]
    second = artefact_digests(_payload([0.688230], [2]))[0]
    assert first != second


def test_the_result_projection_keeps_the_lexical_score() -> None:
    """C0 corre local e é determinístico: uma alteração no seu score é sinal."""
    projection = result_projection(_payload([0.68], [1]))
    lexical = projection["question_results"][0]["conditions"][CONDITION_LEXICAL]
    assert "score" in lexical["ranking"][0]


def test_a_lexical_score_change_moves_the_result_digest() -> None:
    payload = _payload([0.68], [1])
    other = copy.deepcopy(payload)
    other["question_results"][0]["conditions"][CONDITION_LEXICAL]["ranking"][0][
        "score"
    ] = 0.9999
    assert artefact_digests(payload)[0] != artefact_digests(other)[0]


def test_the_result_projection_drops_the_run_fields_and_raw_similarities() -> None:
    projection = result_projection(_payload([0.68], [1]))
    assert "executed_at" not in projection
    assert "result_digest" not in projection
    assert "execution_digest" not in projection
    dense = projection["question_results"][0]["conditions"][CONDITION_DENSE]
    assert "score" not in dense["ranking"][0]
    assert "grade" in dense["ranking"][0]
    no_evidence = projection["no_evidence_questions"][0]
    assert "similarity_top" not in no_evidence
    assert no_evidence["relevant_results_found"] is False


def test_the_execution_projection_keeps_everything_but_the_run_instant() -> None:
    projection = execution_projection(_payload([0.68], [1]))
    assert "executed_at" not in projection
    assert "execution_digest" not in projection
    dense = projection["question_results"][0]["conditions"][CONDITION_DENSE]
    assert dense["ranking"][0]["score"] == 0.68
    assert projection["no_evidence_questions"][0]["similarity_top"] == 0.4718


def test_neither_projection_mutates_the_payload() -> None:
    payload = _payload([0.68], [1])
    before = copy.deepcopy(payload)
    result_projection(payload)
    execution_projection(payload)
    assert payload == before


# --- Guarda de âmbito do repooling ------------------------------------------------


def _minimal_ground_truth(judgments: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "questions": [
            {
                "question_id": "Q001",
                "question": "pergunta",
                "language": "pt",
                "no_relevant_evidence": False,
                "excluded_from_metrics": False,
                "evidence_judgments": judgments,
            }
        ]
    }


def _judgment(index: int, relevance: int) -> dict[str, Any]:
    return {
        "corpus_item_id": "P1-DOC-002",
        "chunk_index": index,
        "relevance": relevance,
    }


def _request(index: int) -> dict[str, Any]:
    return {
        "question_id": "Q001",
        "corpus_item_id": "P1-DOC-002",
        "chunk_index": index,
    }


def test_judging_exactly_the_requests_satisfies_the_guard() -> None:
    historical = _minimal_ground_truth([_judgment(14, 2)])
    repooled = _minimal_ground_truth([_judgment(14, 2), _judgment(16, 0)])
    assert verify_requests_satisfied([_request(16)], historical, repooled) == ()


def test_an_untreated_request_is_reported() -> None:
    historical = _minimal_ground_truth([_judgment(14, 2)])
    repooled = _minimal_ground_truth([_judgment(14, 2), _judgment(16, 0)])
    problems = verify_requests_satisfied(
        [_request(16), _request(18)], historical, repooled
    )
    assert any("18" in problem and "still unjudged" in problem for problem in problems)


def test_a_judgment_outside_the_requested_scope_is_reported() -> None:
    """Anotar mais do que o pedido não é ilegítimo, mas deixa de ser
    reproduzível a partir do artefacto que declara o âmbito."""
    historical = _minimal_ground_truth([_judgment(14, 2)])
    repooled = _minimal_ground_truth(
        [_judgment(14, 2), _judgment(16, 0), _judgment(20, 1)]
    )
    problems = verify_requests_satisfied([_request(16)], historical, repooled)
    assert any("20" in problem and "not requested" in problem for problem in problems)


def test_a_request_for_something_already_judged_is_reported() -> None:
    historical = _minimal_ground_truth([_judgment(14, 2), _judgment(16, 0)])
    repooled = _minimal_ground_truth(
        [_judgment(14, 2), _judgment(16, 0), _judgment(18, 0)]
    )
    problems = verify_requests_satisfied(
        [_request(16), _request(18)], historical, repooled
    )
    assert any("already judged" in problem for problem in problems)


def test_a_duplicate_request_is_reported() -> None:
    historical = _minimal_ground_truth([_judgment(14, 2)])
    repooled = _minimal_ground_truth([_judgment(14, 2), _judgment(16, 0)])
    problems = verify_requests_satisfied(
        [_request(16), _request(16)], historical, repooled
    )
    assert any("duplicate" in problem for problem in problems)


# --- Guardas do runner -------------------------------------------------------------


def test_a_tampered_request_list_is_refused() -> None:
    requests = _load(REQUESTS)
    requests["requests"] = requests["requests"][:-1]
    requests["requests_total"] = len(requests["requests"])
    with pytest.raises(ExperimentError) as error:
        verify_requests_integrity(requests)
    assert error.value.exit_code == EXIT_BASELINE_MISMATCH


def test_a_request_list_that_lies_about_its_total_is_refused() -> None:
    requests = _load(REQUESTS)
    requests["requests_total"] = 999
    payload = {
        key: value for key, value in requests.items() if key != "result_digest"
    }
    requests["result_digest"] = hashlib.sha256(
        canonical_json(payload).encode("utf-8")
    ).hexdigest()
    with pytest.raises(ExperimentError) as error:
        verify_requests_integrity(requests)
    assert error.value.exit_code == EXIT_BASELINE_MISMATCH


def test_the_intact_request_list_passes() -> None:
    verify_requests_integrity(_load(REQUESTS))


def _record(condition_rankings: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    return {
        "question_id": "Q001",
        "conditions": {
            condition: {"retrieved_count": len(ranking), "ranking": ranking}
            for condition, ranking in condition_rankings.items()
        },
    }


def test_a_dense_ranking_that_drifts_from_d48_is_refused() -> None:
    """A guarda central: se o ranking mudasse, a diferença de métricas deixaria
    de ser atribuível ao repooling."""
    entry = {"position": 1, "corpus_item_id": "P1-DOC-002", "chunk_index": 14}
    moved = {"position": 1, "corpus_item_id": "P1-DOC-002", "chunk_index": 16}
    reference = {
        "question_results": [
            _record({CONDITION_LEXICAL: [entry], CONDITION_DENSE: [entry]})
        ]
    }
    records = [_record({CONDITION_LEXICAL: [entry], CONDITION_DENSE: [moved]})]
    with pytest.raises(ExperimentError) as error:
        verify_reproduces_d48_rankings(records, reference)
    assert error.value.exit_code == EXIT_BASELINE_MISMATCH
    assert "C1" in str(error.value)


def test_identical_rankings_reproduce_d48() -> None:
    entry = {"position": 1, "corpus_item_id": "P1-DOC-002", "chunk_index": 14}
    records = [_record({CONDITION_LEXICAL: [entry], CONDITION_DENSE: [entry]})]
    verify_reproduces_d48_rankings(records, {"question_results": copy.deepcopy(records)})


def test_a_score_that_drifts_does_not_break_the_ranking_guard() -> None:
    """A guarda compara posições e âncoras, não similaridades: a deriva do
    fornecedor não pode fazer falhar uma execução legítima."""
    here = {
        "position": 1,
        "corpus_item_id": "P1-DOC-002",
        "chunk_index": 14,
        "score": 0.688233,
    }
    there = {
        "position": 1,
        "corpus_item_id": "P1-DOC-002",
        "chunk_index": 14,
        "score": 0.688230,
    }
    records = [_record({CONDITION_LEXICAL: [here], CONDITION_DENSE: [here]})]
    reference = {
        "question_results": [
            _record({CONDITION_LEXICAL: [there], CONDITION_DENSE: [there]})
        ]
    }
    verify_reproduces_d48_rankings(records, reference)


def test_an_unjudged_result_blocks_the_definitive_comparison() -> None:
    with pytest.raises(ExperimentError) as error:
        verify_comparable(
            REPOOLING_REQUIRED,
            [
                {
                    "question_id": "Q001",
                    "corpus_item_id": "P1-DOC-002",
                    "chunk_index": 44,
                }
            ],
        )
    assert error.value.exit_code == EXIT_NOT_COMPARABLE


def test_a_fully_judged_union_is_comparable() -> None:
    verify_comparable(COMPARABLE, [])


# --- Artefactos versionados: o ground truth --------------------------------------


def test_the_versioned_repooling_extends_the_set_d48_measured() -> None:
    report = verify_repooling(_load(HISTORICAL_GROUND_TRUTH), _load(GROUND_TRUTH))
    assert report.problems == ()
    assert report.added_total == _load(REQUESTS)["requests_total"]


def test_the_versioned_repooling_treated_exactly_the_requested_pairs() -> None:
    problems = verify_requests_satisfied(
        _load(REQUESTS)["requests"],
        _load(HISTORICAL_GROUND_TRUTH),
        _load(GROUND_TRUTH),
    )
    assert problems == ()


def test_the_historical_digest_declared_in_code_is_the_one_on_disk() -> None:
    assert ground_truth_digest(_load(HISTORICAL_GROUND_TRUTH)) == (
        HISTORICAL_GROUND_TRUTH_DIGEST
    )


def test_the_repooling_changes_the_digest() -> None:
    assert ground_truth_digest(_load(GROUND_TRUTH)) != HISTORICAL_GROUND_TRUTH_DIGEST


def test_the_questions_survived_the_repooling_letter_for_letter() -> None:
    before = {q["question_id"]: q for q in _load(HISTORICAL_GROUND_TRUTH)["questions"]}
    after = {q["question_id"]: q for q in _load(GROUND_TRUTH)["questions"]}
    assert sorted(before) == sorted(after)
    for question_id, question in before.items():
        assert after[question_id]["question"] == question["question"]
        assert after[question_id]["temporal_scope"] == question["temporal_scope"]
        assert (
            after[question_id]["excluded_from_metrics"]
            == question["excluded_from_metrics"]
        )
        assert (
            after[question_id]["no_relevant_evidence"]
            == question["no_relevant_evidence"]
        )


def test_the_snapshot_identity_survived_the_repooling() -> None:
    before = _load(HISTORICAL_GROUND_TRUTH)
    after = _load(GROUND_TRUTH)
    for field in ("corpus_id", "snapshot_id", "corpus_digest", "reference_date"):
        assert after[field] == before[field]


def test_every_judged_document_is_listed_at_document_level() -> None:
    """Invariante do ficheiro, mantida pelo repooling: nenhum documento ganha
    julgamentos sem aparecer em ``document_level_relevance``."""
    for question in _load(GROUND_TRUTH)["questions"]:
        judged = {j["corpus_item_id"] for j in question["evidence_judgments"]}
        listed = {d["corpus_item_id"] for d in question["document_level_relevance"]}
        assert judged <= listed, question["question_id"]


def test_the_question_without_evidence_received_no_relevant_judgment() -> None:
    """Q013 está anotada como sem evidência: julgar os resultados que C1
    devolveu não pode contradizer essa anotação sem que ela mude."""
    for question in _load(GROUND_TRUTH)["questions"]:
        if not question["no_relevant_evidence"]:
            continue
        grades = [j["relevance"] for j in question["evidence_judgments"]]
        assert grades, question["question_id"]
        assert max(grades) < BINARY_RELEVANCE_THRESHOLD


# --- Artefactos versionados: a comparação ----------------------------------------


def test_the_artefact_matches_both_of_its_own_digests() -> None:
    artefact = _load(ARTEFACT)
    result, execution = artefact_digests(artefact)
    assert result == artefact["result_digest"]
    assert execution == artefact["execution_digest"]
    assert artefact["result_digest"] != artefact["execution_digest"]


def test_the_artefact_declares_the_scope_of_each_digest() -> None:
    """Um digest cujo âmbito não está declarado convida ao erro que o D4.3
    apanhou no ``snapshot_id``."""
    artefact = _load(ARTEFACT)
    assert artefact["result_digest_scope"] == RESULT_DIGEST_SCOPE
    assert artefact["execution_digest_scope"] == EXECUTION_DIGEST_SCOPE


def test_the_canonical_digest_is_the_one_that_survives_provider_drift() -> None:
    """A propriedade que torna o ``result_digest`` citável por uma fase
    seguinte, verificada sobre o artefacto real e não sobre um payload
    fabricado."""
    artefact = _load(ARTEFACT)
    drifted = copy.deepcopy(artefact)
    for record in drifted["question_results"]:
        for entry in record["conditions"][CONDITION_DENSE]["ranking"]:
            entry["score"] = round(entry["score"] + 1e-5, 6)
    assert artefact_digests(drifted)[0] == artefact["result_digest"]
    assert artefact_digests(drifted)[1] != artefact["execution_digest"]


def test_the_artefact_declares_the_digests_it_consumed() -> None:
    artefact = _load(ARTEFACT)
    assert artefact["d48_result_digest"] == _load(D48_ARTEFACT)["result_digest"]
    assert (
        artefact["repooling_requests_result_digest"] == _load(REQUESTS)["result_digest"]
    )
    assert artefact["ground_truth_digest"] == ground_truth_digest(_load(GROUND_TRUTH))
    assert artefact["repooling"]["ground_truth_digest_before"] == (
        HISTORICAL_GROUND_TRUTH_DIGEST
    )


def test_the_artefact_is_comparable_and_says_so() -> None:
    artefact = _load(ARTEFACT)
    assert artefact["comparability"] == COMPARABLE
    assert artefact["unjudged_in_top_k_total"] == 0


def test_no_result_in_the_artefact_is_unjudged() -> None:
    """A afirmação central da fase, verificada sobre o artefacto e não sobre
    o seu resumo."""
    for record in _load(ARTEFACT)["question_results"]:
        for condition in (CONDITION_LEXICAL, CONDITION_DENSE):
            for entry in record["conditions"][condition]["ranking"]:
                assert entry["judged"] is True, record["question_id"]


def test_the_artefact_reproduces_the_d48_rankings() -> None:
    """A guarda corre no runner; aqui verifica-se o resultado que ela deixou."""
    verify_reproduces_d48_rankings(
        _load(ARTEFACT)["question_results"], _load(D48_ARTEFACT)
    )


def test_c0_metrics_are_the_ones_d48_measured() -> None:
    """O repooling julgou 31 resultados, todos de C1: nenhuma métrica de C0
    podia mudar, e o denominador que mudou em Q006 e Q007 era 0/1 e passou a
    0/2."""
    assert _load(ARTEFACT)["aggregate"][CONDITION_LEXICAL] == (
        _load(D48_ARTEFACT)["aggregate"][CONDITION_LEXICAL]
    )


def test_the_repooling_block_declares_no_revision() -> None:
    repooling = _load(ARTEFACT)["repooling"]
    assert repooling["historical_judgments_removed"] == 0
    assert repooling["historical_judgments_revised"] == 0
    assert repooling["judgments_added"] == repooling["requests_total"]
    assert sum(repooling["judgments_added_by_grade"].values()) == (
        repooling["judgments_added"]
    )


def test_the_complementarity_partitions_the_grade_two_targets() -> None:
    complementarity = _load(ARTEFACT)["complementarity"]
    destinations = complementarity["grade2_by_destination"]
    total = sum(entry["count"] for entry in destinations.values())
    assert total == complementarity["grade2_targets_total"]
    labels = [
        target for entry in destinations.values() for target in entry["targets"]
    ]
    assert len(labels) == len(set(labels))


def test_ranking_differences_are_a_subset_of_the_common_targets() -> None:
    """Uma diferença de ranking pressupõe que ambas recuperaram o alvo; contá-la
    como complementaridade inflacionaria o argumento a favor do híbrido."""
    complementarity = _load(ARTEFACT)["complementarity"]
    common = set(complementarity["grade2_by_destination"][BOTH]["targets"])
    differences = set(complementarity["grade2_ranking_differences"]["targets"])
    assert differences <= common


def test_the_dense_condition_still_declares_no_threshold() -> None:
    dense = _load(ARTEFACT)["conditions"][CONDITION_DENSE]
    assert dense["relevance_threshold"] is None
    assert dense["can_return_empty"] is False


def test_the_no_evidence_question_reports_what_each_condition_returned() -> None:
    questions = _load(ARTEFACT)["no_evidence_questions"]
    assert questions, "Q013 tem de aparecer no bloco da pergunta sem evidencia"
    for question in questions:
        assert question["relevant_results_found"] is False
        assert question["grade_histogram_c1"]["2"] == 0


def test_the_artefact_never_contains_document_text() -> None:
    """A âncora é ``corpus_item_id`` + ``chunk_index``; nenhum texto
    institucional é versionado.

    Verificado estruturalmente — nenhuma **chave** de conteúdo em lado nenhum —
    como no D4.8, e não por procura de palavras, que só apanharia o que se
    lembrasse de procurar. ``embedded_text_field`` fica de fora da regra porque
    o seu valor nomeia a coluna embebida; não é texto documental.
    """
    forbidden = {
        "content",
        "normalized_content",
        "text",
        "extracted_text",
        "section_title",
        "preview",
        "excerpt",
        "question",
    }

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                assert key not in forbidden, f"{path}.{key}"
                walk(value, f"{path}.{key}")
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, f"{path}[{index}]")

    walk(_load(ARTEFACT), "artefact")
