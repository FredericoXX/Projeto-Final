"""Guardas de diagnóstico do runner da baseline: contrafactual e destino do alvo.

São exatamente as peças introduzidas para impedir a repetição de dois erros
causais reais cometidos durante o D4.2:

1. aproximar a elegibilidade por ``to_tsvector``/``plainto_tsquery``, que faz
   *stemming*, quando a cobertura real compara **formas canónicas exatas** — o
   que fez ``residencia`` parecer casar ``residencias``;
2. classificar como "nunca foi candidato" um segmento que o ``top_k`` podia ter
   truncado.

Dados **sintéticos** e sem base de dados: a leitura da linha é substituída por um
duplo, e o que fica exercitado é a lógica real de correspondência e de
classificação.
"""

from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest

from scripts.evaluate_retrieval_baseline import (
    EXIT_SNAPSHOT_MISMATCH,
    FATE_CANDIDATE_EXCLUDED,
    FATE_NEVER_A_CANDIDATE,
    FATE_NOT_RETURNED_INDETERMINATE,
    FATE_RETURNED,
    BaselineError,
    counterfactual_eligibility,
    describe_target_fate,
    verify_snapshot,
)

DOCUMENT_ID = "11111111-1111-4111-8111-111111111111"


@dataclass
class FakeRow:
    values: tuple

    def one(self) -> tuple:
        return self.values


class FakeDb:
    """Devolve sempre a mesma linha de segmento. Não é uma Session."""

    def __init__(self, normalized_content: str) -> None:
        self.normalized_content = normalized_content

    def execute(self, _statement: object) -> FakeRow:
        return FakeRow(
            (
                uuid4(),  # chunk_id
                uuid4(),  # document_version_id
                self.normalized_content,  # content
                self.normalized_content,  # normalized_content
                "pt",  # language
                None,  # page_number
                None,  # section_title
                "paragraph",  # structure_type
                None,  # chunking_strategy
            )
        )


class TestCounterfactualEligibility:
    def test_exact_forms_match(self) -> None:
        result = counterfactual_eligibility(
            FakeDb("o prazo de entrega do pedido termina em marco"),
            document_id=DOCUMENT_ID,
            chunk_index=0,
            query_terms=("prazo", "entrega"),
        )
        assert result["matched_terms"] == ["entrega", "prazo"]
        assert result["coverage"] == pytest.approx(1.0)
        assert result["would_be_eligible"] is True
        assert result["exclusion_reason"] is None

    def test_plural_does_not_match_singular(self) -> None:
        # O erro que motivou este teste: o FTS conflaria as duas formas, a
        # elegibilidade não. Um contrafactual que use stemming sobrestima a
        # correspondência e produz uma conclusão causal errada.
        result = counterfactual_eligibility(
            FakeDb("a candidatura as residencias estudantis e apresentada pelo candidato"),
            document_id=DOCUMENT_ID,
            chunk_index=0,
            query_terms=("candidato", "residencia", "universitaria", "prazo"),
        )
        assert "residencia" not in result["matched_terms"]
        assert result["matched_terms"] == ["candidato"]
        assert result["coverage"] == pytest.approx(0.25)
        assert result["would_be_eligible"] is False
        assert result["exclusion_reason"] is not None

    def test_below_coverage_threshold_is_ineligible(self) -> None:
        result = counterfactual_eligibility(
            FakeDb("apenas um termo casa aqui: prazo"),
            document_id=DOCUMENT_ID,
            chunk_index=0,
            query_terms=("prazo", "entrega", "documento", "servico"),
        )
        assert result["coverage"] == pytest.approx(0.25)
        assert result["would_be_eligible"] is False


@dataclass
class FakeExcluded:
    document_id: str
    chunk_index: int
    reason: str
    coverage: float
    matched_terms: tuple[str, ...]


@dataclass
class FakeTrace:
    result_count_before_limit: int
    excluded: tuple[FakeExcluded, ...] = ()


def question_with(chunk_index: int, relevance: int = 2) -> dict:
    return {
        "question_id": "Q001",
        "evidence_judgments": [
            {"corpus_item_id": "X-1", "chunk_index": chunk_index, "relevance": relevance}
        ],
    }


INDEX = {"X-1": DOCUMENT_ID}


class TestDescribeTargetFate:
    def test_returned(self) -> None:
        fates = describe_target_fate(
            FakeDb("irrelevante"),
            question_with(7),
            document_index=INDEX,
            returned_keys={(DOCUMENT_ID, 7)},
            trace=FakeTrace(result_count_before_limit=1),
            retrieved_count=1,
            query_terms=("prazo",),
        )
        assert fates[0]["fate"] == FATE_RETURNED
        # Um segmento devolvido não precisa de contrafactual: não há nada a
        # imaginar sobre ele.
        assert "counterfactual" not in fates[0]

    def test_candidate_excluded_carries_the_real_reason(self) -> None:
        fates = describe_target_fate(
            FakeDb("irrelevante"),
            question_with(7),
            document_index=INDEX,
            returned_keys=set(),
            trace=FakeTrace(
                result_count_before_limit=0,
                excluded=(
                    FakeExcluded(DOCUMENT_ID, 7, "insufficient_coverage", 0.25, ("prazo",)),
                ),
            ),
            retrieved_count=0,
            query_terms=("prazo", "entrega"),
        )
        assert fates[0]["fate"] == FATE_CANDIDATE_EXCLUDED
        assert fates[0]["exclusion_reason"] == "insufficient_coverage"
        assert fates[0]["coverage"] == pytest.approx(0.25)
        assert fates[0]["matched_terms"] == ["prazo"]
        assert "counterfactual" not in fates[0]

    def test_never_a_candidate_gets_a_counterfactual(self) -> None:
        fates = describe_target_fate(
            FakeDb("o prazo de entrega termina em marco"),
            question_with(7),
            document_index=INDEX,
            returned_keys=set(),
            # Sem truncagem: tudo o que sobreviveu foi devolvido.
            trace=FakeTrace(result_count_before_limit=0),
            retrieved_count=0,
            query_terms=("prazo", "entrega"),
        )
        assert fates[0]["fate"] == FATE_NEVER_A_CANDIDATE
        assert fates[0]["counterfactual"]["would_be_eligible"] is True

    def test_truncation_makes_the_fate_indeterminate(self) -> None:
        # Sobreviveram 9 e foram devolvidos 5: um alvo ausente pode ter
        # sobrevivido e ficado abaixo do corte. Afirmar "nunca foi candidato"
        # seria uma conclusão causal que os dados não sustentam.
        fates = describe_target_fate(
            FakeDb("o prazo de entrega termina em marco"),
            question_with(7),
            document_index=INDEX,
            returned_keys=set(),
            trace=FakeTrace(result_count_before_limit=9),
            retrieved_count=5,
            query_terms=("prazo", "entrega"),
        )
        assert fates[0]["fate"] == FATE_NOT_RETURNED_INDETERMINATE
        assert "counterfactual" in fates[0]

    def test_only_grade_two_targets_are_described(self) -> None:
        # Grau 1 e grau 0 não são alvos: o Recall não os conta, e descrevê-los
        # como falhas confundiria contexto e distractores com evidência perdida.
        fates = describe_target_fate(
            FakeDb("irrelevante"),
            question_with(7, relevance=1),
            document_index=INDEX,
            returned_keys=set(),
            trace=FakeTrace(result_count_before_limit=0),
            retrieved_count=0,
            query_terms=("prazo",),
        )
        assert fates == []


@dataclass
class FakeSnapshot:
    snapshot_id: str
    corpus_digest: str


GROUND_TRUTH = {
    "snapshot_id": "aaa",
    "corpus_digest": "bbb",
    "reference_date": "2026-08-15",
}
BINDING = {"institution_id": str(UUID(int=1))}
RETRIEVAL = {"language": "pt", "top_k": 5, "official_only": True}


class TestVerifySnapshot:
    def test_accepts_a_matching_snapshot(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "scripts.evaluate_retrieval_baseline.build_evaluation_snapshot",
            lambda *args, **kwargs: FakeSnapshot("aaa", "bbb"),
        )
        verify_snapshot(
            object(), ground_truth=GROUND_TRUTH, binding=BINDING, retrieval=RETRIEVAL
        )

    @pytest.mark.parametrize(
        ("snapshot_id", "corpus_digest", "expected"),
        [
            ("other", "bbb", "snapshot_id"),
            ("aaa", "other", "corpus_digest"),
            ("other", "other", "snapshot_id"),
        ],
    )
    def test_refuses_to_measure_against_another_corpus(
        self,
        monkeypatch: pytest.MonkeyPatch,
        snapshot_id: str,
        corpus_digest: str,
        expected: str,
    ) -> None:
        monkeypatch.setattr(
            "scripts.evaluate_retrieval_baseline.build_evaluation_snapshot",
            lambda *args, **kwargs: FakeSnapshot(snapshot_id, corpus_digest),
        )
        with pytest.raises(BaselineError) as error:
            verify_snapshot(
                object(), ground_truth=GROUND_TRUTH, binding=BINDING, retrieval=RETRIEVAL
            )
        assert error.value.exit_code == EXIT_SNAPSHOT_MISMATCH
        assert expected in str(error.value)
