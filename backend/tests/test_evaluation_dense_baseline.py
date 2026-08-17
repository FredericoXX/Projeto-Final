"""Comparação C0 × C1 e o artefacto do D4.8.

Três grupos:

- o **módulo puro** ``app.evaluation.dense_baseline`` — união, exclusivos,
  itens por julgar e classificação de comparabilidade;
- as **guardas do runner**, testadas como funções puras sobre payloads
  fabricados, sem base de dados nem fornecedor;
- o **artefacto versionado**, que tem de ser internamente coerente, coincidir
  com o seu próprio digest, declarar os digests que consumiu e não transportar
  texto documental.

Nenhum teste contacta a rede, o PostgreSQL ou o fornecedor de embeddings.
"""

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
    build_repooling_requests,
    classify_comparability,
    exclusive_to,
    overlap_count,
    ranked_pool,
    union_pool,
    unjudged_items,
)
from app.evaluation.results import canonical_json
from scripts.evaluate_dense_baseline import (
    EXIT_BASELINE_MISMATCH,
    EXIT_INDEX_INCOMPLETE,
    EXPECTED_GROUND_TRUTH_DIGEST,
    ExperimentError,
    aggregate_metrics,
    condition_metrics,
    judged_grades_by_anchor,
    verify_c0_reproduces_d42,
    verify_c0_reproduces_d47_control,
    verify_ground_truth_identity,
    verify_index_coverage,
)

DOCS = Path(__file__).resolve().parents[2] / "docs" / "evaluation"
ARTEFACT = DOCS / "dense-baseline-p1-s1.json"
REPOOLING = DOCS / "dense-repooling-requests-p1-s1.json"
D42_BASELINE = DOCS / "retrieval-baseline-p1-s1.json"
D47_VARIANTS = DOCS / "ranking-variants-p1-s1.json"
GROUND_TRUTH = DOCS / "retrieval-ground-truth-p1-repooled.json"


# --- Anulação das fixtures de base de dados do conftest -------------------------


@pytest.fixture(scope="session", autouse=True)
def _override_get_db() -> None:
    """Anula a fixture homónima do conftest: aqui não há dependência de DB."""


@pytest.fixture(autouse=True)
def _clean_tables() -> None:
    """Anula a fixture homónima do conftest: aqui não há tabelas a truncar."""


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


# --- Módulo puro -----------------------------------------------------------------


def test_the_union_is_a_set_ordered_by_anchor_and_not_by_position() -> None:
    """A união é o conjunto a julgar; ordená-la por posição faria depender de
    qual condição foi lida primeiro."""
    c0 = (PoolItem("P1-DOC-003", 7), PoolItem("P1-DOC-002", 14))
    c1 = (PoolItem("P1-DOC-002", 14), PoolItem("P1-DOC-002", 3))

    assert union_pool(c0, c1) == (
        PoolItem("P1-DOC-002", 3),
        PoolItem("P1-DOC-002", 14),
        PoolItem("P1-DOC-003", 7),
    )


def test_exclusives_and_overlap_partition_the_union() -> None:
    c0 = (PoolItem("A", 1), PoolItem("A", 2))
    c1 = (PoolItem("A", 2), PoolItem("B", 9))

    assert exclusive_to(c0, c1) == (PoolItem("A", 1),)
    assert exclusive_to(c1, c0) == (PoolItem("B", 9),)
    assert overlap_count(c0, c1) == 1
    assert len(union_pool(c0, c1)) == len(exclusive_to(c0, c1)) + len(
        exclusive_to(c1, c0)
    ) + overlap_count(c0, c1)


def test_unjudged_items_are_those_the_ground_truth_never_saw() -> None:
    pool = (PoolItem("A", 1), PoolItem("A", 2), PoolItem("B", 3))
    judged = (PoolItem("A", 2),)

    assert unjudged_items(pool, judged) == (PoolItem("A", 1), PoolItem("B", 3))


def test_comparability_has_no_tolerance() -> None:
    """Um limiar do género "poucos por julgar chega" transformaria uma
    propriedade verificável num juízo."""
    assert classify_comparability(0) == COMPARABLE
    assert classify_comparability(1) == REPOOLING_REQUIRED
    assert classify_comparability(31) == REPOOLING_REQUIRED
    with pytest.raises(ValueError, match="cannot be negative"):
        classify_comparability(-1)


def test_a_repooling_request_records_which_conditions_returned_the_segment() -> None:
    """Distinguir "só o denso o viu" de "ambos o viram" é o ponto da lista."""
    requests = build_repooling_requests(
        question_id="Q001",
        c0_ranking=(PoolItem("A", 1), PoolItem("A", 2)),
        c1_ranking=(PoolItem("A", 2), PoolItem("B", 5)),
        judged=(PoolItem("A", 2),),
    )

    by_anchor = {(r.corpus_item_id, r.chunk_index): r for r in requests}
    assert set(by_anchor) == {("A", 1), ("B", 5)}
    assert by_anchor[("A", 1)].retrieved_by == (CONDITION_LEXICAL,)
    assert by_anchor[("A", 1)].rank_c0 == 1
    assert by_anchor[("A", 1)].rank_c1 is None
    assert by_anchor[("B", 5)].retrieved_by == (CONDITION_DENSE,)
    assert by_anchor[("B", 5)].rank_c1 == 2


def test_a_fully_judged_union_produces_no_requests() -> None:
    requests = build_repooling_requests(
        question_id="Q001",
        c0_ranking=(PoolItem("A", 1),),
        c1_ranking=(PoolItem("A", 1),),
        judged=(PoolItem("A", 1),),
    )
    assert requests == ()


def test_a_ranking_entry_without_an_anchor_is_refused() -> None:
    with pytest.raises(ValueError, match="no usable anchor"):
        ranked_pool([{"corpus_item_id": None, "chunk_index": 3}])


def test_grades_are_indexed_by_the_protocol_anchor() -> None:
    question = {
        "evidence_judgments": [
            {"corpus_item_id": "P1-DOC-002", "chunk_index": 14, "relevance": 2},
            {"corpus_item_id": "P1-DOC-003", "chunk_index": 7, "relevance": 0},
        ]
    }
    assert judged_grades_by_anchor(question) == {
        ("P1-DOC-002", 14): 2,
        ("P1-DOC-003", 7): 0,
    }


# --- Métricas --------------------------------------------------------------------


def test_an_unjudged_result_counts_as_grade_zero() -> None:
    """``ASSUMED_IRRELEVANT`` é a convenção do protocolo, e é o que penaliza a
    condição nova por ser nova — a razão de existir a lista de repooling."""
    ranking = [{"grade": 0}, {"grade": 2}]
    metrics = condition_metrics(ranking, [2, 2])

    assert metrics["total_relevant_judged"] == 2
    assert metrics["recall"]["1"] == 0.0
    assert metrics["recall"]["5"] == 0.5
    assert metrics["reciprocal_rank"] == 0.5


def test_the_aggregate_is_a_macro_average() -> None:
    measured = [
        {"recall": {"1": 1.0, "3": 1.0, "5": 1.0}, "reciprocal_rank": 1.0,
         "ndcg": {"1": 1.0, "3": 1.0, "5": 1.0}},
        {"recall": {"1": 0.0, "3": 0.0, "5": 0.0}, "reciprocal_rank": 0.0,
         "ndcg": {"1": 0.0, "3": 0.0, "5": 0.0}},
    ]
    aggregate = aggregate_metrics(measured)

    assert aggregate["questions_measured"] == 2
    assert aggregate["recall"]["5"] == 0.5
    assert aggregate["mrr"] == 0.5


# --- Guardas do runner -----------------------------------------------------------


def _record(question_id: str, *, admissible: int, embedded: int) -> dict[str, Any]:
    return {
        "question_id": question_id,
        "conditions": {
            CONDITION_DENSE: {
                "admissible_chunks": admissible,
                "embedded_chunks": embedded,
            }
        },
    }


def test_an_incomplete_vector_index_is_refused() -> None:
    """C1 medida sobre um corpus menor que C0 não é comparável com C0."""
    with pytest.raises(ExperimentError) as info:
        verify_index_coverage([_record("Q001", admissible=1834, embedded=1830)])

    assert info.value.exit_code == EXIT_INDEX_INCOMPLETE
    assert "1830 of 1834" in str(info.value)


def test_a_complete_vector_index_passes() -> None:
    verify_index_coverage([_record("Q001", admissible=1834, embedded=1834)])


def test_the_expected_ground_truth_digest_is_the_repooled_set() -> None:
    """Declarado no código, não lido do ficheiro: ler o digest do próprio
    ficheiro em uso verificaria apenas que ele é consistente consigo mesmo."""
    from app.evaluation.ground_truth_identity import ground_truth_digest

    assert ground_truth_digest(_load(GROUND_TRUTH)) == EXPECTED_GROUND_TRUTH_DIGEST


def test_a_ground_truth_that_is_not_the_repooled_set_is_refused() -> None:
    ground_truth = _load(GROUND_TRUTH)
    ground_truth["questions"] = ground_truth["questions"][:3]

    with pytest.raises(ExperimentError) as info:
        verify_ground_truth_identity(ground_truth, _load(D47_VARIANTS))

    assert info.value.exit_code == EXIT_BASELINE_MISMATCH


def test_a_variants_artefact_bound_to_another_question_set_is_refused() -> None:
    variants = _load(D47_VARIANTS)
    variants["ground_truth_digest"] = "0" * 64

    with pytest.raises(ExperimentError) as info:
        verify_ground_truth_identity(_load(GROUND_TRUTH), variants)

    assert info.value.exit_code == EXIT_BASELINE_MISMATCH
    assert "D4.7 artefact declares" in str(info.value)


def _c0_records_from_artefact() -> list[dict[str, Any]]:
    return _load(ARTEFACT)["question_results"]


def test_a_c0_ranking_that_drifts_from_d42_is_refused() -> None:
    """Sem esta guarda, uma diferença entre C0 e C1 poderia ser uma diferença
    entre duas execuções de C0."""
    records = json.loads(json.dumps(_c0_records_from_artefact()))
    records[0]["conditions"][CONDITION_LEXICAL]["ranking"][0]["chunk_index"] = 9999

    with pytest.raises(ExperimentError) as info:
        verify_c0_reproduces_d42(records, _load(D42_BASELINE))

    assert info.value.exit_code == EXIT_BASELINE_MISMATCH
    assert "does not reproduce the D4.2" in str(info.value)


def test_a_c0_metric_that_drifts_from_the_d47_control_is_refused() -> None:
    artefact = _load(ARTEFACT)
    records = artefact["question_results"]
    aggregate = dict(artefact["aggregate"][CONDITION_LEXICAL])
    aggregate["mrr"] = aggregate["mrr"] + 0.01

    with pytest.raises(ExperimentError) as info:
        verify_c0_reproduces_d47_control(records, aggregate, _load(D47_VARIANTS))

    assert info.value.exit_code == EXIT_BASELINE_MISMATCH


def test_a_variants_artefact_without_the_control_cell_is_refused() -> None:
    variants = _load(D47_VARIANTS)
    variants["cells"] = [
        cell for cell in variants["cells"] if cell["variant_id"] != "A0"
    ]
    artefact = _load(ARTEFACT)

    with pytest.raises(ExperimentError) as info:
        verify_c0_reproduces_d47_control(
            artefact["question_results"],
            artefact["aggregate"][CONDITION_LEXICAL],
            variants,
        )

    assert info.value.exit_code == EXIT_BASELINE_MISMATCH


# --- Artefacto versionado --------------------------------------------------------


def test_the_artefact_matches_its_own_result_digest() -> None:
    payload = _load(ARTEFACT)
    declared = payload.pop("result_digest")
    payload.pop("executed_at")

    recomputed = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()

    assert recomputed == declared


def test_the_repooling_artefact_matches_its_own_result_digest() -> None:
    payload = _load(REPOOLING)
    declared = payload.pop("result_digest")

    recomputed = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()

    assert recomputed == declared


def test_the_artefact_declares_the_digests_it_consumed() -> None:
    """A ligação ao D4.2, ao D4.7 e ao conjunto de perguntas é explícita."""
    payload = _load(ARTEFACT)

    assert payload["d42_baseline_result_digest"] == _load(D42_BASELINE)["result_digest"]
    assert payload["d47_result_digest"] == _load(D47_VARIANTS)["result_digest"]
    assert payload["ground_truth_digest"] == EXPECTED_GROUND_TRUTH_DIGEST
    assert _load(REPOOLING)["ground_truth_digest"] == EXPECTED_GROUND_TRUTH_DIGEST


def test_c0_in_the_artefact_reproduces_both_references() -> None:
    """As duas guardas de replicação, aplicadas ao artefacto tal como ficou."""
    payload = _load(ARTEFACT)

    verify_c0_reproduces_d42(payload["question_results"], _load(D42_BASELINE))
    verify_c0_reproduces_d47_control(
        payload["question_results"],
        payload["aggregate"][CONDITION_LEXICAL],
        _load(D47_VARIANTS),
    )


def test_the_artefact_declares_repooling_and_lists_every_unjudged_result() -> None:
    """A classificação e a lista têm de contar a mesma história."""
    payload = _load(ARTEFACT)
    requests = _load(REPOOLING)["requests"]

    assert payload["comparability"] == REPOOLING_REQUIRED
    assert payload["unjudged_in_top_k_total"] == len(requests)
    assert payload["unjudged_in_top_k_total"] > 0

    listed = {
        (request["question_id"], request["corpus_item_id"], request["chunk_index"])
        for request in requests
    }
    observed = {
        (record["question_id"], anchor["corpus_item_id"], anchor["chunk_index"])
        for record in payload["question_results"]
        for condition in (CONDITION_LEXICAL, CONDITION_DENSE)
        for anchor in record["unjudged_in_top_k"][condition]
    }
    assert listed == observed
    assert sorted({request["question_id"] for request in requests}) == payload[
        "questions_with_unjudged"
    ]


def test_every_unjudged_result_is_really_absent_from_the_ground_truth() -> None:
    """A lista de repooling não pode pedir julgamento do que já está julgado."""
    judged = {
        (question["question_id"], judgment["corpus_item_id"], judgment["chunk_index"])
        for question in _load(GROUND_TRUTH)["questions"]
        for judgment in question["evidence_judgments"]
    }
    for request in _load(REPOOLING)["requests"]:
        key = (request["question_id"], request["corpus_item_id"], request["chunk_index"])
        assert key not in judged, key


def test_every_question_partitions_its_union_into_overlap_and_exclusives() -> None:
    for record in _load(ARTEFACT)["question_results"]:
        assert record["union_size"] == (
            record["overlap"]
            + len(record["exclusive_to_c0"])
            + len(record["exclusive_to_c1"])
        ), record["question_id"]


def test_both_conditions_answered_the_same_questions() -> None:
    payload = _load(ARTEFACT)
    for record in payload["question_results"]:
        assert set(record["conditions"]) == {CONDITION_LEXICAL, CONDITION_DENSE}
        measured = record["measured"]
        for condition in (CONDITION_LEXICAL, CONDITION_DENSE):
            assert ("metrics" in record["conditions"][condition]) is measured


def test_the_dense_condition_declares_its_own_score_family() -> None:
    """Um score denso registado como relevância lexical seria uma comparação
    entre escalas diferentes disfarçada de igualdade."""
    for record in _load(ARTEFACT)["question_results"]:
        assert record["conditions"][CONDITION_LEXICAL]["score_kind"] == "lexical_relevance"
        assert record["conditions"][CONDITION_DENSE]["score_kind"] == "dense_similarity"
        assert record["conditions"][CONDITION_DENSE]["comparable_across_queries"] is False


def test_the_artefact_records_the_embedding_configuration_in_full() -> None:
    """A identidade tem três campos e os três têm de estar no artefacto.

    Declarar menos do que se filtra — ou filtrar menos do que se declara — é o
    que permitiria a um índice misto sair rotulado com a configuração nova.
    """
    embedding = _load(ARTEFACT)["embedding"]

    assert embedding["provider"] and embedding["model"]
    assert embedding["configuration_version"]
    assert embedding["dimension"] > 0
    assert embedding["similarity_metric"] == "cosine"
    assert embedding["embedded_text_field"] == "content"
    # Índice exato: um índice aproximado tornaria o resultado dependente dos
    # parâmetros de recall do índice.
    assert embedding["approximate_index"] is False
    assert len(embedding["index_digest"]) == 64
    assert embedding["indexed_vectors"] > 0


def test_the_dense_condition_declares_that_it_applies_no_threshold() -> None:
    assert _load(ARTEFACT)["dense_relevance_threshold"] is None


def test_the_artefact_never_contains_document_text() -> None:
    """A âncora do protocolo chega para localizar um segmento; texto
    institucional não entra em ficheiros versionados.

    Verificado estruturalmente — nenhuma chave de conteúdo em lado nenhum — e
    não por procura de palavras, que só apanharia o que se lembrasse de
    procurar.
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
    walk(_load(REPOOLING), "repooling")
