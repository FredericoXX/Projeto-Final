"""Métricas de recuperação: a interpretação fixada pelo protocolo do D4.1.

Dados **sintéticos**. Nenhum documento institucional real, nenhum excerto e
nenhum identificador do Pilot Corpus entra aqui: a baseline real é um artefacto
de demonstração separado, e a suite continua a correr sem depender dela.

Os casos fixam as decisões que distinguem este protocolo de uma implementação
"óbvia" — o limiar binário no grau 2, o ganho não linear do nDCG, o denominador
do Recall ser o número de relevantes **julgados**, e o *reciprocal rank* ser
truncado pela lista devolvida.
"""

import math

import pytest

from app.evaluation.retrieval_metrics import (
    BINARY_RELEVANCE_THRESHOLD,
    K_VALUES,
    NDCG_GAIN_BY_GRADE,
    PRIMARY_K,
    UNJUDGED_GRADE,
    dcg,
    gain,
    ideal_dcg,
    mean,
    ndcg_at_k,
    recall_at_k,
    reciprocal_rank,
)


class TestProtocolConstants:
    def test_binary_threshold_is_grade_two(self) -> None:
        # Grau 1 é contexto insuficiente por definição da rubrica; contá-lo como
        # acerto inflacionaria o Recall com evidência que não responde.
        assert BINARY_RELEVANCE_THRESHOLD == 2

    def test_ndcg_gain_is_non_linear(self) -> None:
        assert NDCG_GAIN_BY_GRADE == {0: 0, 1: 1, 2: 3}
        # A propriedade que interessa: dois grau 1 não valem um grau 2.
        assert NDCG_GAIN_BY_GRADE[1] * 2 < NDCG_GAIN_BY_GRADE[2] * 2
        assert NDCG_GAIN_BY_GRADE[2] > NDCG_GAIN_BY_GRADE[1] * 2

    def test_k_values_and_primary(self) -> None:
        assert K_VALUES == (1, 3, 5)
        assert PRIMARY_K == 5
        assert PRIMARY_K in K_VALUES

    def test_unjudged_counts_as_irrelevant(self) -> None:
        assert UNJUDGED_GRADE == 0


class TestGain:
    def test_known_grades(self) -> None:
        assert gain(0) == 0
        assert gain(1) == 1
        assert gain(2) == 3

    def test_unknown_grade_fails_loudly(self) -> None:
        # Um grau fora da rubrica é erro de anotação. Devolver 0 esconderia o
        # problema dentro de uma métrica plausível.
        with pytest.raises(ValueError, match="unknown relevance grade"):
            gain(3)


class TestRecallAtK:
    def test_counts_only_grade_two(self) -> None:
        # Um grau 1 na primeira posição não conta como evidência encontrada.
        assert recall_at_k([1, 1, 1], total_relevant=1, k=3) == 0.0

    def test_denominator_is_judged_relevants_not_retrieved(self) -> None:
        # Dois relevantes julgados, um recuperado -> 0.5, não 1.0.
        assert recall_at_k([2, 0, 0], total_relevant=2, k=3) == 0.5

    def test_truncates_at_k(self) -> None:
        grades = [0, 0, 0, 0, 2]
        assert recall_at_k(grades, total_relevant=1, k=1) == 0.0
        assert recall_at_k(grades, total_relevant=1, k=3) == 0.0
        assert recall_at_k(grades, total_relevant=1, k=5) == 1.0

    def test_shorter_list_than_k_is_not_an_error(self) -> None:
        # O retriever pode devolver menos do que top_k; isso é um resultado, não
        # uma condição de erro.
        assert recall_at_k([2], total_relevant=1, k=5) == 1.0

    def test_empty_result_is_zero(self) -> None:
        assert recall_at_k([], total_relevant=1, k=5) == 0.0

    def test_undefined_without_relevants(self) -> None:
        with pytest.raises(ValueError, match="undefined"):
            recall_at_k([2], total_relevant=0, k=5)

    def test_non_positive_k_rejected(self) -> None:
        with pytest.raises(ValueError, match="k must be positive"):
            recall_at_k([2], total_relevant=1, k=0)


class TestReciprocalRank:
    @pytest.mark.parametrize(
        ("grades", "expected"),
        [
            ([2, 0, 0], 1.0),
            ([0, 2, 0], 0.5),
            ([0, 0, 2], 1 / 3),
            ([0, 0, 0], 0.0),
            ([], 0.0),
        ],
    )
    def test_first_relevant_position(self, grades: list[int], expected: float) -> None:
        assert reciprocal_rank(grades) == pytest.approx(expected)

    def test_grade_one_does_not_open_the_rank(self) -> None:
        # O primeiro grau 2 está em terceiro; os grau 1 antes dele não contam.
        assert reciprocal_rank([1, 1, 2]) == pytest.approx(1 / 3)

    def test_is_truncated_by_the_returned_list(self) -> None:
        # Não há como distinguir "o relevante estava na posição 7" de "não
        # apareceu": a lista devolvida é o que o sistema real mostra.
        assert reciprocal_rank([0] * 5) == 0.0


class TestDcg:
    def test_discount_is_log2_of_position_plus_one(self) -> None:
        # Um único grau 2 na primeira posição: ganho 3, desconto log2(2) == 1.
        assert dcg([2], k=1) == pytest.approx(3.0)
        # Na segunda posição o mesmo ganho vale menos.
        assert dcg([0, 2], k=2) == pytest.approx(3.0 / math.log2(3))

    def test_truncates_at_k(self) -> None:
        assert dcg([0, 0, 2], k=2) == 0.0

    def test_ideal_sorts_by_gain(self) -> None:
        # A ordem de entrada não importa: o ideal é sempre o melhor arranjo.
        assert ideal_dcg([1, 2], k=2) == pytest.approx(ideal_dcg([2, 1], k=2))
        assert ideal_dcg([1, 2], k=2) == pytest.approx(3.0 + 1.0 / math.log2(3))


class TestNdcgAtK:
    def test_perfect_ranking_is_one(self) -> None:
        assert ndcg_at_k([2, 1], [2, 1], k=2) == pytest.approx(1.0)

    def test_inverted_ranking_is_below_one(self) -> None:
        assert ndcg_at_k([1, 2], [2, 1], k=2) < 1.0

    def test_ideal_uses_this_question_judgments(self) -> None:
        # O ideal não é sobre o corpus inteiro: é sobre os julgamentos desta
        # pergunta. É essa escolha que torna o enviesamento indeterminado sob
        # julgamentos incompletos.
        assert ndcg_at_k([2], [2], k=1) == pytest.approx(1.0)

    def test_empty_ranking_is_zero(self) -> None:
        assert ndcg_at_k([], [2], k=5) == 0.0

    def test_undefined_without_positive_gain(self) -> None:
        with pytest.raises(ValueError, match="undefined"):
            ndcg_at_k([0], [0], k=1)


class TestMean:
    def test_macro_average(self) -> None:
        assert mean([1.0, 0.0]) == pytest.approx(0.5)

    def test_empty_fails_loudly(self) -> None:
        with pytest.raises(ValueError, match="empty sequence"):
            mean([])
