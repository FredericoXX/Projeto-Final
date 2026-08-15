"""Guardas do runner da baseline de recuperação.

Cobre as verificações que decidem se a execução é sequer legítima — protocolo,
binding, exclusões e digest — e não apenas a aritmética das métricas, que vive em
``test_retrieval_metrics.py``.

Dados **sintéticos**. Nenhum identificador do Pilot Corpus, nenhum excerto
documental e nenhum acesso à base: todas as funções aqui exercitadas são puras.
"""

import pytest

from scripts.evaluate_retrieval_baseline import (
    EXIT_PROTOCOL_MISMATCH,
    UNJUDGED_CHUNK_TREATMENT,
    BaselineError,
    add_metrics,
    aggregate,
    build_document_index,
    result_digest,
    verify_metric_protocol,
)


def valid_protocol() -> dict:
    return {
        "k_values": [1, 3, 5],
        "primary_k": 5,
        "binary_relevance_threshold": 2,
        "ndcg_gain_mapping": {"0": 0, "1": 1, "2": 3},
        "unjudged_chunk_treatment": UNJUDGED_CHUNK_TREATMENT,
    }


class TestVerifyMetricProtocol:
    def test_accepts_the_implemented_protocol(self) -> None:
        verify_metric_protocol({"metric_protocol": valid_protocol()})

    def test_rejects_missing_protocol(self) -> None:
        with pytest.raises(BaselineError) as error:
            verify_metric_protocol({})
        assert error.value.exit_code == EXIT_PROTOCOL_MISMATCH

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("k_values", [1, 2, 3]),
            ("primary_k", 10),
            ("binary_relevance_threshold", 1),
            ("ndcg_gain_mapping", {"0": 0, "1": 1, "2": 2}),
            # A convenção dos não julgados é a única implementada. Aceitar outra
            # produziria números cuja interpretação documentada não corresponde
            # ao que foi calculado — foi exatamente esta a lacuna encontrada em
            # revisão.
            ("unjudged_chunk_treatment", "IGNORED"),
        ],
    )
    def test_rejects_each_divergence(self, field: str, value: object) -> None:
        protocol = valid_protocol()
        protocol[field] = value
        with pytest.raises(BaselineError) as error:
            verify_metric_protocol({"metric_protocol": protocol})
        assert error.value.exit_code == EXIT_PROTOCOL_MISMATCH
        assert field in str(error.value)

    def test_reports_every_divergence_at_once(self) -> None:
        protocol = valid_protocol()
        protocol["primary_k"] = 10
        protocol["unjudged_chunk_treatment"] = "IGNORED"
        with pytest.raises(BaselineError) as error:
            verify_metric_protocol({"metric_protocol": protocol})
        message = str(error.value)
        assert "primary_k" in message
        assert "unjudged_chunk_treatment" in message


class TestBuildDocumentIndex:
    def test_only_items_in_the_corpus(self) -> None:
        # Um item que não entrou no corpus não tem versão processada e não pode
        # ser âncora de nenhum julgamento.
        binding = {
            "items": [
                {"corpus_item_id": "X-1", "document_id": "d1", "in_corpus": True},
                {"corpus_item_id": "X-2", "document_id": "d2", "in_corpus": False},
                {"corpus_item_id": "X-3", "document_id": "d3"},
            ]
        }
        assert build_document_index(binding) == {"X-1": "d1"}


class TestAddMetrics:
    def test_uses_judged_grades_as_denominator(self) -> None:
        record = {
            "ranking": [{"relevance": 2}, {"relevance": 0}],
            "judged_grades": [2, 2],
        }
        enriched = add_metrics(record)
        assert enriched["total_relevant_judged"] == 2
        assert enriched["recall"]["5"] == pytest.approx(0.5)
        assert enriched["reciprocal_rank"] == pytest.approx(1.0)

    def test_grade_one_does_not_count_as_recall(self) -> None:
        record = {"ranking": [{"relevance": 1}], "judged_grades": [2, 1]}
        enriched = add_metrics(record)
        assert enriched["recall"]["5"] == 0.0
        assert enriched["reciprocal_rank"] == 0.0
        # Mas conta para o nDCG, porque tem ganho positivo.
        assert enriched["ndcg"]["5"] > 0.0

    def test_empty_ranking_scores_zero_everywhere(self) -> None:
        enriched = add_metrics({"ranking": [], "judged_grades": [2]})
        assert enriched["recall"]["1"] == 0.0
        assert enriched["reciprocal_rank"] == 0.0
        assert enriched["ndcg"]["5"] == 0.0


class TestAggregate:
    def test_macro_average_weights_questions_equally(self) -> None:
        measured = [
            add_metrics({"ranking": [{"relevance": 2}], "judged_grades": [2]}),
            add_metrics({"ranking": [], "judged_grades": [2, 2, 2]}),
        ]
        result = aggregate(measured)
        assert result["questions_measured"] == 2
        # A segunda pergunta tem três relevantes e a primeira um; a macro-média
        # continua a dar-lhes o mesmo peso.
        assert result["recall"]["5"] == pytest.approx(0.5)
        assert result["mrr"] == pytest.approx(0.5)


class TestResultDigest:
    def test_ignores_the_timestamp(self) -> None:
        base = {"a": 1, "executed_at": "2026-01-01T00:00:00Z"}
        other = {"a": 1, "executed_at": "2030-12-31T23:59:59Z"}
        assert result_digest(base) == result_digest(other)

    def test_changes_with_content(self) -> None:
        assert result_digest({"a": 1}) != result_digest({"a": 2})

    def test_is_stable_across_key_order(self) -> None:
        # A canonicalização ordena as chaves; a ordem de inserção não participa.
        assert result_digest({"a": 1, "b": 2}) == result_digest({"b": 2, "a": 1})
