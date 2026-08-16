"""Repooling dirigido e decomposição dos sinais de ranking (D4.6).

Dois contratos, e a diferença entre eles importa:

- o **repooling** pode acrescentar julgamentos e não pode rever os existentes,
  porque uma revisão silenciosa tornaria a série D4.2–D4.5 incomparável sem que
  nada o assinalasse;
- a **decomposição** tem de reproduzir exatamente ``compute_score``, sinal a
  sinal. Um diagnóstico assente numa base que não é a do código diagnosticaria
  um ranking que não existe.

Testes puros: não tocam na base de dados. Os últimos leem os artefactos reais
versionados, porque a afirmação central da fase — *o conjunto novo estende o
antigo* — não vale nada se só for verdadeira sobre fixtures.
"""

import copy
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from app.core.text_normalization import normalize_text
from app.evaluation.ground_truth_identity import (
    GroundTruthIdentityError,
    ground_truth_digest,
)
from app.evaluation.repooling import (
    denominator_changes,
    judgment_coverage,
    relevant_target_count,
    verify_repooling,
)
from app.retrieval.query_planning import LexicalQueryStrategy
from app.retrieval.reranking import (
    LexicalCandidate,
    LexicalFeatures,
    compute_features,
    compute_score,
    informative_query_terms,
)
from scripts.diagnose_ranking_signals import (
    DIAGNOSIS_INSUFFICIENT,
    DIAGNOSIS_REWEIGHTABLE,
    SCORE_TERMS,
    common_signals_favouring_target,
    compare_signals,
    decompose,
    diagnose_pair,
    score_terms,
    structure_bonus_availability,
)

DOCS = Path(__file__).resolve().parents[2] / "docs" / "evaluation"
SEED_PATH = DOCS / "retrieval-ground-truth-p1-seed.json"
REPOOLED_PATH = DOCS / "retrieval-ground-truth-p1-repooled.json"
DIAGNOSTICS_PATH = DOCS / "ranking-diagnostics-p1-s1.json"


def _judgment(chunk_index: int, relevance: int, item: str = "P1-DOC-002") -> dict[str, Any]:
    return {
        "corpus_item_id": item,
        "chunk_index": chunk_index,
        "relevance": relevance,
        "note": "nota",
    }


def _question(
    question_id: str = "Q001",
    *,
    judgments: list[dict[str, Any]] | None = None,
    excluded: bool = False,
) -> dict[str, Any]:
    return {
        "question_id": question_id,
        "question": "Quando comecam as aulas?",
        "language": "pt",
        "question_origin": "constructed_from_public_documents",
        "temporal_scope": "2025/2026",
        "difficulty_types": ["date_deadline"],
        "no_relevant_evidence": False,
        "excluded_from_metrics": excluded,
        "exclusion_reason": None,
        "evidence_judgments": judgments
        if judgments is not None
        else [_judgment(14, 2), _judgment(89, 0)],
    }


def _ground_truth(questions: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "schema_version": "2",
        "contract": "retrieval_ground_truth",
        "corpus_id": "P1",
        "snapshot_id": "a" * 64,
        "corpus_digest": "b" * 64,
        "reference_date": "2026-08-15",
        "metric_protocol": {
            "k_values": [1, 3, 5],
            "primary_k": 5,
            "binary_relevance_threshold": 2,
            "ndcg_gain_mapping": {"0": 0, "1": 1, "2": 3},
            "unjudged_chunk_treatment": "ASSUMED_IRRELEVANT",
        },
        "questions": questions if questions is not None else [_question()],
    }


def _extended(**kwargs: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    """Par (histórico, repooled) com um julgamento acrescentado."""
    historical = _ground_truth()
    repooled = copy.deepcopy(historical)
    repooled["questions"][0]["evidence_judgments"].append(_judgment(12, kwargs.get("grade", 1)))
    return historical, repooled


# ---------------------------------------------------------------------------
# O repooling estende, não revê
# ---------------------------------------------------------------------------


def test_an_added_judgment_is_accepted() -> None:
    report = verify_repooling(*_extended())
    assert report.valid, report.problems
    assert report.added_total == 1
    assert report.added_by_grade == {1: 1}
    assert report.questions_touched == ("Q001",)


def test_a_revised_grade_is_rejected() -> None:
    """A regra que não é negociável.

    Rever um grau antigo tornaria a comparação "antes e depois do repooling"
    uma medida da mudança de opinião do anotador, e não da incompletude.
    """
    historical, repooled = _extended()
    repooled["questions"][0]["evidence_judgments"][1]["relevance"] = 2
    report = verify_repooling(historical, repooled)
    assert not report.valid
    assert any("was revised" in problem for problem in report.problems)


def test_a_removed_judgment_is_rejected() -> None:
    historical, repooled = _extended()
    repooled["questions"][0]["evidence_judgments"].pop(0)
    assert any("was removed" in p for p in verify_repooling(historical, repooled).problems)


def test_a_repooling_that_adds_nothing_is_rejected() -> None:
    historical = _ground_truth()
    assert any(
        "added no judgment" in p
        for p in verify_repooling(historical, copy.deepcopy(historical)).problems
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("question", "Outra pergunta?"),
        ("temporal_scope", "2023/2024"),
        ("excluded_from_metrics", True),
        ("no_relevant_evidence", True),
        ("language", "en"),
    ],
)
def test_changing_a_question_is_not_a_repooling(field: str, value: object) -> None:
    """Se as perguntas mudassem, isto seria um conjunto novo — o caso do D4.4."""
    historical, repooled = _extended()
    repooled["questions"][0][field] = value
    report = verify_repooling(historical, repooled)
    assert any(field in problem for problem in report.problems)


def test_dropping_a_question_is_rejected() -> None:
    historical = _ground_truth([_question("Q001"), _question("Q002")])
    repooled = copy.deepcopy(historical)
    repooled["questions"].pop()
    repooled["questions"][0]["evidence_judgments"].append(_judgment(12, 0))
    assert any("dropped" in p for p in verify_repooling(historical, repooled).problems)


def test_inventing_a_question_is_rejected() -> None:
    historical = _ground_truth()
    repooled = copy.deepcopy(historical)
    repooled["questions"].append(_question("Q999"))
    repooled["questions"][0]["evidence_judgments"].append(_judgment(12, 0))
    assert any("invented" in p for p in verify_repooling(historical, repooled).problems)


def test_disagreeing_on_the_corpus_is_rejected() -> None:
    historical, repooled = _extended()
    repooled["corpus_digest"] = "z" * 64
    assert any("corpus_digest" in p for p in verify_repooling(historical, repooled).problems)


def test_disagreeing_on_the_protocol_is_rejected() -> None:
    historical, repooled = _extended()
    repooled["metric_protocol"]["primary_k"] = 3
    assert any(
        "metric_protocol.primary_k" in p
        for p in verify_repooling(historical, repooled).problems
    )


def test_a_duplicate_judgment_fails_loudly() -> None:
    historical, repooled = _extended()
    repooled["questions"][0]["evidence_judgments"].append(_judgment(12, 0))
    with pytest.raises(GroundTruthIdentityError, match="duplicate judgment"):
        verify_repooling(historical, repooled)


def test_the_repooling_changes_the_digest() -> None:
    historical, repooled = _extended()
    assert ground_truth_digest(historical) != ground_truth_digest(repooled)


# ---------------------------------------------------------------------------
# Denominador e cobertura
# ---------------------------------------------------------------------------


def test_adding_a_grade_two_changes_the_recall_denominator() -> None:
    """Sem esta lista, uma variação de Recall seria indistinguível de
    comportamento do sistema."""
    historical, repooled = _extended(grade=2)
    assert denominator_changes(historical, repooled, 2) == [
        {"question_id": "Q001", "before": 1, "after": 2}
    ]


def test_adding_a_grade_zero_leaves_the_denominator_alone() -> None:
    historical, repooled = _extended(grade=0)
    assert denominator_changes(historical, repooled, 2) == []


def test_relevant_target_count_uses_the_threshold() -> None:
    question = _question(judgments=[_judgment(1, 2), _judgment(2, 1), _judgment(3, 0)])
    assert relevant_target_count(question, 2) == 1
    assert relevant_target_count(question, 1) == 2


def test_judgment_coverage_counts_what_was_returned() -> None:
    question = _question(judgments=[_judgment(14, 2)])
    coverage = judgment_coverage(question, [("P1-DOC-002", 14), ("P1-DOC-002", 99)])
    assert coverage == {"returned": 2, "judged": 1, "unjudged": 1}


def test_judgment_coverage_of_nothing_returned() -> None:
    assert judgment_coverage(_question(), []) == {
        "returned": 0,
        "judged": 0,
        "unjudged": 0,
    }


# ---------------------------------------------------------------------------
# A decomposição tem de ser a do código
# ---------------------------------------------------------------------------


def _candidate(text: str, *, structure: str | None = None) -> LexicalCandidate:
    return LexicalCandidate(
        chunk_id=uuid4(),
        document_id=uuid4(),
        document_version_id=uuid4(),
        document_title="Calendario academico",
        chunk_index=0,
        content=text,
        normalized_content=normalize_text(text),
        language="pt",
        official_source=True,
        source_url=None,
        valid_from=None,
        valid_until=None,
        page_number=None,
        section_title="1.o semestre",
        structure_type=structure,
        chunking_strategy=None,
        raw_score=0.05,
        strategy=LexicalQueryStrategy.REDUCED_OR,
    )


@pytest.mark.parametrize(
    "text",
    [
        "inicio do ano letivo 06 de outubro de 2025",
        "1.o semestre do ano letivo 2025/2026",
        "renovacao das matriculas no 1o semestre",
        "texto sem relacao nenhuma",
    ],
)
def test_the_weighted_terms_reproduce_compute_score(text: str) -> None:
    """A base linear declarada **é** a de ``compute_score``, sem folga.

    É a garantia que impede o diagnóstico de descrever um ranking que não
    existe: se um sinal fosse esquecido ou inventado, esta soma divergiria.
    """
    query = normalize_text("Quando comeca o ano letivo 2025/2026?")
    terms = informative_query_terms(query, "pt")
    features = compute_features(terms, _candidate(text, structure="table_row"))
    rebuilt = sum(weight * score_terms(features)[name] for name, weight in SCORE_TERMS)
    assert rebuilt == pytest.approx(compute_score(features), abs=1e-12)


def test_the_declared_basis_omits_signals_that_are_not_summands() -> None:
    """``compactness`` condiciona o bónus estrutural e ``length_factor``
    multiplica o FTS; nenhum é um termo do somatório, e listá-los inventaria
    sinais que o código não tem."""
    names = {name for name, _ in SCORE_TERMS}
    assert "compactness" not in names
    assert "length_factor" not in names
    assert "fts_component" in names


def test_decompose_reports_the_auxiliary_signals_separately() -> None:
    query = normalize_text("Quando comeca o ano letivo?")
    terms = informative_query_terms(query, "pt")
    features = compute_features(terms, _candidate("inicio do ano letivo"))
    entry = decompose(features, structure_type="table_row")
    assert set(entry) == {
        "score",
        "structure_type",
        "signals",
        "contributions",
        "auxiliary",
    }
    assert entry["structure_type"] == "table_row"
    assert set(entry["auxiliary"]) == {
        "compactness",
        "length_factor",
        "fts_norm",
        "matched_terms",
    }


# ---------------------------------------------------------------------------
# Dominância e invertibilidade
# ---------------------------------------------------------------------------


def _features(**overrides: float) -> LexicalFeatures:
    defaults: dict[str, float] = {
        "coverage": 0.5,
        "exact_phrase": 0.0,
        "ordered": 0.5,
        "proximity": 0.5,
        "compactness": 0.5,
        "title_overlap": 0.0,
        "section_overlap": 0.0,
        "table_row_bonus": 0.0,
        "fts_norm": 0.5,
        "length_factor": 1.0,
        "strategy_quality": 0.25,
    }
    return LexicalFeatures(matched_terms=frozenset({"a"}), **{**defaults, **overrides})


def test_a_dominated_target_cannot_be_saved_by_any_reweighting() -> None:
    """Com pesos não negativos, ``sᵢ_alvo ≤ sᵢ_conc`` para todo o ``i`` implica
    ``score_alvo ≤ score_conc``. Não há ponderação que inverta isto."""
    comparison = compare_signals(_features(coverage=0.4), _features(coverage=0.6))
    assert comparison["dominated"] is True
    assert comparison["favours_target"] == []
    assert diagnose_pair(comparison) == DIAGNOSIS_INSUFFICIENT


def test_a_target_ahead_on_one_signal_is_reweightable() -> None:
    comparison = compare_signals(
        _features(coverage=0.4, title_overlap=1.0), _features(coverage=0.6)
    )
    assert comparison["dominated"] is False
    assert comparison["favours_target"] == ["title_overlap"]
    assert diagnose_pair(comparison) == DIAGNOSIS_REWEIGHTABLE


def test_an_exact_tie_is_not_dominance() -> None:
    comparison = compare_signals(_features(), _features())
    assert comparison["favours_target"] == []
    assert comparison["favours_competitor"] == []
    assert comparison["dominated"] is True


def test_the_weighted_delta_carries_the_sign_of_the_advantage() -> None:
    comparison = compare_signals(_features(coverage=0.9), _features(coverage=0.4))
    assert comparison["per_signal"]["coverage"]["favours"] == "target"
    assert comparison["per_signal"]["coverage"]["weighted_delta"] > 0
    assert comparison["score_gap"] < 0


def _competitor(favours: list[str]) -> dict[str, Any]:
    return {"comparison": {"favours_target": favours}}


def test_a_signal_that_beats_every_competitor_proves_a_single_reweighting_works() -> None:
    common = common_signals_favouring_target(
        [_competitor(["coverage", "title_overlap"]), _competitor(["coverage"])]
    )
    assert common == ["coverage"]


def test_pairwise_invertibility_does_not_imply_a_common_signal() -> None:
    """Cada par é invertível isoladamente e mesmo assim nenhum sinal os bate a
    todos; a lista vazia é a resposta honesta, não uma falha."""
    common = common_signals_favouring_target(
        [_competitor(["coverage"]), _competitor(["title_overlap"])]
    )
    assert common == []


def test_no_competitors_means_no_common_signal() -> None:
    assert common_signals_favouring_target([]) == []


# ---------------------------------------------------------------------------
# Os artefactos versionados
# ---------------------------------------------------------------------------


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_the_versioned_repooling_extends_the_historical_ground_truth() -> None:
    report = verify_repooling(_load(SEED_PATH), _load(REPOOLED_PATH))
    assert report.valid, report.problems
    assert report.added_total == 34
    assert report.added_by_grade == {0: 27, 1: 6, 2: 1}


def test_the_versioned_ground_truths_have_different_digests() -> None:
    assert ground_truth_digest(_load(SEED_PATH)) != ground_truth_digest(
        _load(REPOOLED_PATH)
    )


def test_the_diagnostics_artefact_declares_the_digests_it_used() -> None:
    payload = _load(DIAGNOSTICS_PATH)
    assert payload["ground_truth_digest_before"] == ground_truth_digest(_load(SEED_PATH))
    assert payload["ground_truth_digest_after"] == ground_truth_digest(
        _load(REPOOLED_PATH)
    )
    assert payload["repooling"]["revisions"] == []


def test_the_artefact_records_the_structural_asymmetry() -> None:
    """A evidência do achado entre documentos tem de ser reproduzível.

    Enquanto a contagem vivesse só no relatório, ficava fora do ``result_digest``
    e ninguém a podia reconferir a partir dos artefactos versionados.
    """
    counts = _load(DIAGNOSTICS_PATH)["document_structure_counts"]
    assert set(counts) == {f"P1-DOC-00{n}" for n in range(2, 8)}
    assert counts["P1-DOC-002"]["table_row"] == 56
    assert "table_row" not in counts["P1-DOC-003"]


def test_the_structure_bonus_is_available_to_a_single_document() -> None:
    """``table_row_bonus`` vale 0,06 e cinco dos seis documentos nunca o podem
    receber — o sinal separa documentos por qualidade de extração."""
    availability = _load(DIAGNOSTICS_PATH)["structure_bonus_availability"]
    assert availability["requires_structure_type"] == "table_row"
    assert availability["documents_with_table_rows"] == ["P1-DOC-002"]
    assert "P1-DOC-003" in availability["documents_without_table_rows"]
    assert len(availability["documents_without_table_rows"]) == 5


def test_structure_bonus_availability_splits_on_the_table_row_count() -> None:
    availability = structure_bonus_availability(
        {"A": {"table_row": 3, "paragraph": 1}, "B": {"paragraph": 9}, "C": {}}
    )
    assert availability["documents_with_table_rows"] == ["A"]
    assert availability["documents_without_table_rows"] == ["B", "C"]


def test_every_diagnosed_candidate_carries_its_structure_type() -> None:
    """O bónus estrutural é concedido ou negado por causa dele; sem o registar,
    a linha diria que o sinal decidiu sem dizer o que o produziu."""
    for case in _load(DIAGNOSTICS_PATH)["ranking_cases"]:
        if case["target_rank"] is None:
            continue
        assert "target_structure_type" in case
        assert case["target_decomposition"]["structure_type"] == case[
            "target_structure_type"
        ]
        for competitor in case["competitors"]:
            assert "structure_type" in competitor
            assert competitor["decomposition"]["structure_type"] == competitor[
                "structure_type"
            ]


def test_the_cross_document_failure_pits_a_paragraph_against_a_table_row() -> None:
    """O caso Q011: o alvo está no documento OCR e o concorrente do ano errado
    é uma linha de tabela, e é daí que vem a maior contribuição contra o alvo."""
    payload = _load(DIAGNOSTICS_PATH)
    case = next(
        c
        for c in payload["ranking_cases"]
        if c["question_id"] == "Q011"
        and c["target"]["chunk_index"] == 37
        and c["budget_policy"] == "redistribute_unused"
    )
    assert case["target_structure_type"] == "paragraph"
    competitor = case["competitors"][0]
    assert competitor["structure_type"] == "table_row"
    assert competitor["same_document_as_target"] is False
    deltas = case["competitors"][0]["comparison"]["per_signal"]
    assert deltas["structure_table_row"]["favours"] == "competitor"
    worst = min(deltas.items(), key=lambda item: item[1]["weighted_delta"])
    assert worst[0] == "structure_table_row"


def test_the_repooling_leaves_no_returned_result_unjudged() -> None:
    """O que a fase existe para conseguir: medir o ranking sem depender de
    resultados por julgar."""
    payload = _load(DIAGNOSTICS_PATH)
    repooled_cells = [c for c in payload["cells"] if c["ground_truth"] == "repooled"]
    assert repooled_cells
    for cell in repooled_cells:
        unjudged = sum(
            result["judgment_coverage"]["unjudged"] for result in cell["question_results"]
        )
        assert unjudged == 0, cell["budget_policy"]
