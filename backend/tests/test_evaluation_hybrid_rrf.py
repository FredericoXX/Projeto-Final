"""D4.9 — a fusão por RRF, as suas guardas e o artefacto que produz.

Nenhum teste precisa de base de dados, de rede ou do fornecedor: a fase consome
rankings persistidos. As fixtures de base de dados do ``conftest`` são anuladas
por isso mesmo — exigir PostgreSQL para verificar aritmética de posições seria
esconder que a fase é pura.
"""

import copy
import json
import subprocess
import sys
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest

from app.evaluation.dense_baseline import (
    CONDITION_DENSE,
    CONDITION_LEXICAL,
    PoolItem,
)
from app.evaluation.hybrid_rrf import (
    CONDITION_HYBRID,
    FINAL_TOP_K,
    FUSION_SOURCES,
    K_RRF,
    SOURCE_DEPTH,
    TIE_BREAK,
    fusion_configuration,
    reciprocal_rank_fusion,
    rrf_term,
)
from scripts.evaluate_hybrid_rrf import (
    DECISION_A,
    DECISION_B,
    DECISION_C,
    DECISION_D,
    MATERIAL_DELTA,
    SOURCE_RESULT_DIGEST,
    GuardError,
    build_payload,
    decide,
    load_json,
    stamp_digests,
    verify_comparability,
    verify_ground_truth,
    verify_source_integrity,
)

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = BACKEND_DIR.parent
EVALUATION_DIR = REPOSITORY_ROOT / "docs" / "evaluation"
COMPARISON_PATH = EVALUATION_DIR / "lexical-dense-comparison-p1-s1.json"
GROUND_TRUTH_PATH = EVALUATION_DIR / "retrieval-ground-truth-p1-lexical-dense-repooled.json"
ARTEFACT_PATH = EVALUATION_DIR / "hybrid-rrf-p1-s1.json"


# --- Anulação das fixtures de base de dados do conftest -------------------------


@pytest.fixture(scope="session", autouse=True)
def _override_get_db() -> None:
    """Anula a fixture homónima do conftest: aqui não há dependência de DB."""


@pytest.fixture(autouse=True)
def _clean_tables() -> None:
    """Anula a fixture homónima do conftest: aqui não há tabelas a truncar."""


@pytest.fixture(scope="module")
def comparison() -> dict[str, Any]:
    return load_json(COMPARISON_PATH)


@pytest.fixture(scope="module")
def ground_truth() -> dict[str, Any]:
    return load_json(GROUND_TRUTH_PATH)


@pytest.fixture(scope="module")
def artefact() -> dict[str, Any]:
    return load_json(ARTEFACT_PATH)


def item(index: int, doc: str = "P1-DOC-001") -> PoolItem:
    return PoolItem(corpus_item_id=doc, chunk_index=index)


# ---------------------------------------------------------------------------
# A fórmula
# ---------------------------------------------------------------------------


def test_the_term_is_the_canonical_reciprocal() -> None:
    assert rrf_term(1) == Fraction(1, K_RRF + 1)
    assert rrf_term(5) == Fraction(1, K_RRF + 5)


def test_a_rank_below_one_is_a_call_error_not_a_case_to_absorb() -> None:
    """Aceitar rank 0 daria um termo maior do que o do primeiro lugar."""
    with pytest.raises(ValueError, match="1-based"):
        rrf_term(0)


def test_a_segment_in_both_rankings_sums_both_terms() -> None:
    shared = item(1)
    fused = reciprocal_rank_fusion(
        {CONDITION_LEXICAL: [shared], CONDITION_DENSE: [shared]}
    )
    assert len(fused) == 1
    assert fused[0].rrf_score == rrf_term(1) + rrf_term(1)
    assert fused[0].contributing_conditions == (CONDITION_LEXICAL, CONDITION_DENSE)


def test_a_segment_only_in_c0_sums_one_term_and_gets_no_synthetic_rank() -> None:
    """Ausência é silêncio, não juízo negativo.

    Se o retriever ausente contribuísse com ``1 / (k_rrf + 999)``, o segmento
    exclusivo receberia uma penalização que ninguém emitiu — e a fusão passaria
    a exprimir uma opinião que nenhuma das condições teve.
    """
    only_c0 = item(7)
    fused = reciprocal_rank_fusion(
        {CONDITION_LEXICAL: [only_c0], CONDITION_DENSE: []}
    )
    assert fused[0].rrf_score == rrf_term(1)
    assert fused[0].rank_c0 == 1
    assert fused[0].rank_c1 is None
    assert fused[0].contributing_conditions == (CONDITION_LEXICAL,)


def test_a_segment_only_in_c1_sums_one_term() -> None:
    only_c1 = item(9)
    fused = reciprocal_rank_fusion({CONDITION_LEXICAL: [], CONDITION_DENSE: [only_c1]})
    assert fused[0].rrf_score == rrf_term(1)
    assert fused[0].rank_c0 is None
    assert fused[0].rank_c1 == 1


def test_both_rankings_empty_produces_an_empty_fusion() -> None:
    assert reciprocal_rank_fusion({CONDITION_LEXICAL: [], CONDITION_DENSE: []}) == ()


def test_a_missing_condition_is_the_same_as_an_empty_one() -> None:
    fused = reciprocal_rank_fusion({CONDITION_DENSE: [item(3)]})
    assert len(fused) == 1
    assert fused[0].rank_c0 is None


def test_an_unknown_source_is_refused() -> None:
    with pytest.raises(ValueError, match="unknown fusion sources"):
        reciprocal_rank_fusion({"C9": [item(1)]})


def test_a_shared_segment_outranks_two_exclusive_ones() -> None:
    """O efeito central do RRF: concordância entre condições pesa mais."""
    shared, exclusive_c0, exclusive_c1 = item(1), item(2), item(3)
    fused = reciprocal_rank_fusion(
        {
            CONDITION_LEXICAL: [exclusive_c0, shared],
            CONDITION_DENSE: [exclusive_c1, shared],
        }
    )
    assert fused[0].item == shared


# ---------------------------------------------------------------------------
# Empate e desempate
# ---------------------------------------------------------------------------


def test_a_genuine_tie_is_broken_by_the_declared_rule() -> None:
    """Dois exclusivos no mesmo lugar empatam exatamente e caem na identidade."""
    left = PoolItem("P1-DOC-001", 5)
    right = PoolItem("P1-DOC-002", 1)
    fused = reciprocal_rank_fusion(
        {CONDITION_LEXICAL: [right], CONDITION_DENSE: [left]}
    )
    assert fused[0].rrf_score == fused[1].rrf_score
    assert (fused[0].item, fused[1].item) == (left, right)


def test_the_tie_break_does_not_depend_on_the_order_of_the_inputs() -> None:
    """Trocar qual condição viu qual item não pode mudar o resultado."""
    left = PoolItem("P1-DOC-001", 5)
    right = PoolItem("P1-DOC-002", 1)
    one = reciprocal_rank_fusion(
        {CONDITION_LEXICAL: [left], CONDITION_DENSE: [right]}
    )
    other = reciprocal_rank_fusion(
        {CONDITION_LEXICAL: [right], CONDITION_DENSE: [left]}
    )
    assert [entry.item for entry in one] == [entry.item for entry in other]


def test_best_rank_precedes_identity_in_the_tie_break() -> None:
    """Com scores iguais, decide primeiro a melhor posição obtida."""
    early = PoolItem("P1-DOC-009", 1)
    late = PoolItem("P1-DOC-001", 1)
    fused = reciprocal_rank_fusion(
        {CONDITION_LEXICAL: [early], CONDITION_DENSE: [late]}
    )
    assert fused[0].rrf_score == fused[1].rrf_score
    assert fused[0].best_rank == fused[1].best_rank == 1
    assert fused[0].item == late  # identidade decide: P1-DOC-001 < P1-DOC-009


def test_the_tie_break_is_declared_and_carries_no_condition_preference() -> None:
    """Um critério que preferisse C0 ou C1 decidiria parte do que se pergunta."""
    joined = " ".join(TIE_BREAK).lower()
    assert "c0" not in joined
    assert "c1" not in joined
    assert len(TIE_BREAK) == 4


# ---------------------------------------------------------------------------
# Profundidade
# ---------------------------------------------------------------------------


def test_only_the_first_source_depth_positions_contribute() -> None:
    beyond = item(99)
    ranking = [item(index) for index in range(1, SOURCE_DEPTH + 1)] + [beyond]
    fused = reciprocal_rank_fusion({CONDITION_LEXICAL: ranking}, final_top_k=99)
    assert beyond not in [entry.item for entry in fused]
    assert len(fused) == SOURCE_DEPTH


def test_the_fusion_returns_at_most_final_top_k() -> None:
    c0 = [item(index) for index in range(1, 6)]
    c1 = [item(index) for index in range(10, 15)]
    fused = reciprocal_rank_fusion({CONDITION_LEXICAL: c0, CONDITION_DENSE: c1})
    assert len(fused) == FINAL_TOP_K


def test_the_declared_configuration_is_the_one_the_code_uses() -> None:
    configuration = fusion_configuration()
    assert configuration["k_rrf"] == K_RRF == 60
    assert configuration["source_depth"] == SOURCE_DEPTH == 5
    assert configuration["final_top_k"] == FINAL_TOP_K == 5
    assert configuration["uses_original_scores"] is False
    assert configuration["absent_condition_contributes"] is False
    assert configuration["sources"] == list(FUSION_SOURCES)


# ---------------------------------------------------------------------------
# Os scores originais não participam
# ---------------------------------------------------------------------------


def test_the_fusion_signature_cannot_receive_a_score() -> None:
    """A garantia é estrutural: a função recebe identidades, não resultados.

    ``PoolItem`` tem dois campos e nenhum deles é um score. Não há por onde um
    ``lexical_composite_v1`` ou uma similaridade do cosseno entrar.
    """
    assert [field for field in PoolItem.__dataclass_fields__] == [
        "corpus_item_id",
        "chunk_index",
    ]


def test_changing_the_original_scores_does_not_change_the_fused_ranking(
    comparison: dict[str, Any], ground_truth: dict[str, Any]
) -> None:
    """Perturbar os scores mantendo as posições não pode mover nada.

    É a diferença entre rank fusion e score fusion, e é o que impede que a
    experiência esteja a somar relevância lexical composta com similaridade do
    cosseno sem dizer que o faz.
    """
    baseline = build_payload(comparison, ground_truth)

    perturbed = copy.deepcopy(comparison)
    for question in perturbed["question_results"]:
        for condition in (CONDITION_LEXICAL, CONDITION_DENSE):
            for entry in question["conditions"][condition]["ranking"]:
                if "score" in entry:
                    entry["score"] = round(1.0 - float(entry["score"]), 6)
    perturbed_payload = build_payload(perturbed, ground_truth)

    for before, after in zip(
        baseline["question_results"], perturbed_payload["question_results"], strict=True
    ):
        assert (
            before["conditions"][CONDITION_HYBRID]["ranking"]
            == after["conditions"][CONDITION_HYBRID]["ranking"]
        )
    assert baseline["aggregate"] == perturbed_payload["aggregate"]
    assert baseline["decision"] == perturbed_payload["decision"]


def test_the_fused_ranking_carries_no_original_score(artefact: dict[str, Any]) -> None:
    for question in artefact["question_results"]:
        for entry in question["conditions"][CONDITION_HYBRID]["ranking"]:
            assert "score" not in entry
            assert "similarity" not in entry


# ---------------------------------------------------------------------------
# Guardas do runner
# ---------------------------------------------------------------------------


def test_the_source_must_be_the_declared_d481_artefact(
    comparison: dict[str, Any]
) -> None:
    verify_source_integrity(comparison)
    assert comparison["result_digest"] == SOURCE_RESULT_DIGEST


def test_a_tampered_source_is_refused(comparison: dict[str, Any]) -> None:
    tampered = copy.deepcopy(comparison)
    assert tampered["question_results"][0]["conditions"][CONDITION_DENSE]["ranking"][0][
        "grade"
    ] == 2, "a adulteracao tem de mudar mesmo alguma coisa"
    tampered["question_results"][0]["conditions"][CONDITION_DENSE]["ranking"][0][
        "grade"
    ] = 0
    with pytest.raises(GuardError, match="result_digest nao confere"):
        verify_source_integrity(tampered)


def test_a_source_with_a_replaced_digest_is_still_refused(
    comparison: dict[str, Any]
) -> None:
    """Recalcular o digest depois de editar não faz do ficheiro a fonte certa."""
    from app.evaluation.lexical_dense_comparison import artefact_digests

    tampered = copy.deepcopy(comparison)
    assert tampered["question_results"][0]["conditions"][CONDITION_DENSE]["ranking"][0][
        "grade"
    ] == 2, "a adulteracao tem de mudar mesmo alguma coisa"
    tampered["question_results"][0]["conditions"][CONDITION_DENSE]["ranking"][0][
        "grade"
    ] = 0
    result, execution = artefact_digests(tampered)
    tampered["result_digest"] = result
    tampered["execution_digest"] = execution
    with pytest.raises(GuardError, match="nao e a D4.8.1 que esta fase declara"):
        verify_source_integrity(tampered)


def test_an_edited_ground_truth_is_refused(
    comparison: dict[str, Any], ground_truth: dict[str, Any]
) -> None:
    tampered = copy.deepcopy(ground_truth)
    tampered["questions"][0]["evidence_judgments"][0]["relevance"] = 1
    with pytest.raises(GuardError, match="ground_truth_digest divergente"):
        verify_ground_truth(comparison, tampered)


def test_a_divergent_metric_protocol_is_refused(
    comparison: dict[str, Any], ground_truth: dict[str, Any]
) -> None:
    """Se o ficheiro e o código discordarem do protocolo, não se mede.

    O ``metric_protocol`` está dentro do âmbito do ``ground_truth_digest``, pelo
    que editá-lo à bruta é apanhado pelo digest. Este teste vai um passo mais
    longe e constrói um par **internamente consistente** — ficheiro editado,
    digest recalculado, fonte a declarar esse digest novo — para que só a
    verificação do protocolo possa disparar. É a diferença entre «o ficheiro foi
    mexido» e «o ficheiro é coerente mas contradiz o código que o vai medir».
    """
    from app.evaluation.ground_truth_identity import ground_truth_digest

    tampered = copy.deepcopy(ground_truth)
    tampered["metric_protocol"]["binary_relevance_threshold"] = 1
    source = copy.deepcopy(comparison)
    source["ground_truth_digest"] = ground_truth_digest(tampered)

    with pytest.raises(GuardError, match="binary_relevance_threshold"):
        verify_ground_truth(source, tampered)


def test_an_incomparable_source_is_refused(comparison: dict[str, Any]) -> None:
    tampered = copy.deepcopy(comparison)
    tampered["comparability"] = "REPOOLING_REQUIRED"
    with pytest.raises(GuardError, match="nao e mensuravel"):
        verify_comparability(tampered)


def test_unjudged_results_in_the_source_are_refused(comparison: dict[str, Any]) -> None:
    tampered = copy.deepcopy(comparison)
    tampered["unjudged_in_top_k_total"] = 1
    with pytest.raises(GuardError, match="por julgar"):
        verify_comparability(tampered)


# ---------------------------------------------------------------------------
# O artefacto produzido
# ---------------------------------------------------------------------------


def test_c0_and_c1_are_reproduced_exactly(artefact: dict[str, Any]) -> None:
    """A reprodução é a prova de que C2 é medido pelo mesmo protocolo."""
    source = load_json(COMPARISON_PATH)
    for condition in (CONDITION_LEXICAL, CONDITION_DENSE):
        assert artefact["aggregate"][condition] == source["aggregate"][condition]
    assert artefact["conditions_reproduced"][CONDITION_LEXICAL] is True
    assert artefact["conditions_reproduced"][CONDITION_DENSE] is True


def test_c2_contains_only_segments_from_the_union(artefact: dict[str, Any]) -> None:
    for question in artefact["question_results"]:
        conditions = question["conditions"]
        union = {
            (entry["corpus_item_id"], entry["chunk_index"])
            for condition in (CONDITION_LEXICAL, CONDITION_DENSE)
            for entry in conditions[condition]["ranking"]
        }
        fused = {
            (entry["corpus_item_id"], entry["chunk_index"])
            for entry in conditions[CONDITION_HYBRID]["ranking"]
        }
        assert fused <= union


def test_no_result_is_unjudged(artefact: dict[str, Any]) -> None:
    assert artefact["unjudged_in_top_k_total"] == 0
    for question in artefact["question_results"]:
        for entry in question["conditions"][CONDITION_HYBRID]["ranking"]:
            assert entry["judged"] is True


def test_the_artefact_digests_match_its_own_content(artefact: dict[str, Any]) -> None:
    recomputed = stamp_digests(
        {k: v for k, v in artefact.items() if k != "execution_digest"}
    )
    assert recomputed["result_digest"] == artefact["result_digest"]
    assert recomputed["execution_digest"] == artefact["execution_digest"]


def test_the_admission_policy_of_d482_is_not_applied(artefact: dict[str, Any]) -> None:
    """Fundir e admitir são dois mecanismos; misturá-los tornaria o resultado
    inatribuível, e a D4.8.2 está fechada."""
    assert artefact["admission_policy_applied"] is False

    # Nenhuma chave, em nenhuma profundidade, pertence ao vocabulário da
    # admissão. Procurar o número 0,60 no ficheiro não serviria: valores de
    # nDCG e de Recall contêm-no legitimamente, e um teste que confunde os dois
    # não protege nada.
    forbidden = {
        "min_top1",
        "min_margin",
        "admitted",
        "abstained",
        "coverage",
        "correct_abstention_rate",
        "false_abstention_rate",
        "risk",
    }

    def keys_of(node: Any) -> set[str]:
        if isinstance(node, dict):
            return set(node) | {key for value in node.values() for key in keys_of(value)}
        if isinstance(node, list):
            return {key for value in node for key in keys_of(value)}
        return set()

    assert not keys_of(artefact) & forbidden

    # E a fusão não tem limiar nenhum na sua configuração.
    assert not {key for key in artefact["fusion"] if "threshold" in key}


def test_the_excluded_question_stays_excluded(artefact: dict[str, Any]) -> None:
    excluded = {entry["question_id"] for entry in artefact["excluded_questions"]}
    assert "Q014" in excluded
    measured = {
        question["question_id"]
        for question in artefact["question_results"]
        if question["measured"]
    }
    assert "Q014" not in measured
    assert "Q013" not in measured
    assert artefact["aggregate"][CONDITION_HYBRID]["questions_measured"] == 12


def test_the_no_evidence_question_is_reported_without_proposing_a_threshold(
    artefact: dict[str, Any],
) -> None:
    entry = artefact["no_evidence_questions"][0]
    assert entry["question_id"] == "Q013"
    for condition in (CONDITION_LEXICAL, CONDITION_DENSE, CONDITION_HYBRID):
        assert set(entry[condition]) == {
            "retrieved",
            "grade_histogram",
            "irrelevant_returned",
        }
    assert "threshold" not in json.dumps(entry).lower().replace("limiar", "")


# ---------------------------------------------------------------------------
# A decisão
# ---------------------------------------------------------------------------


def _analysis(**overrides: Any) -> dict[str, Any]:
    base = {
        "questions_solved_by_c1_and_lost_by_c2": [],
        "grade2_targets_c1_missed_and_c2_recovered": [],
        "questions_improved_over_c1": 0,
        "grade2_targets_exclusive_to_c0": 1,
        "grade2_targets_exclusive_to_c0_preserved_by_c2": 1,
    }
    base.update(overrides)
    return base


def _delta(ndcg5: float, recall5: float = 0.0) -> dict[str, Any]:
    return {"ndcg": {"5": ndcg5}, "recall": {"5": recall5}}


def test_losing_a_question_forces_b_whatever_the_aggregate_says() -> None:
    outcome = decide(_delta(0.5, 0.5), _analysis(questions_solved_by_c1_and_lost_by_c2=["Q003"]))
    assert outcome["decision"] == DECISION_B


def test_a_recall_drop_forces_b() -> None:
    assert decide(_delta(0.5, -0.01), _analysis())["decision"] == DECISION_B


def test_a_material_gain_without_regression_is_a() -> None:
    assert decide(_delta(MATERIAL_DELTA, 0.0), _analysis())["decision"] == DECISION_A


def test_a_gain_below_the_budget_with_concrete_benefit_is_d() -> None:
    outcome = decide(
        _delta(MATERIAL_DELTA / 2, 0.0),
        _analysis(grade2_targets_c1_missed_and_c2_recovered=["Q011:x"]),
    )
    assert outcome["decision"] == DECISION_D


def test_no_regression_no_benefit_and_no_material_gain_is_c() -> None:
    assert decide(_delta(0.0, 0.0), _analysis())["decision"] == DECISION_C


def test_a_lost_c0_exclusive_target_prevents_a() -> None:
    """Perder a evidência que só o lexical via anula a razão de existir da fusão."""
    outcome = decide(
        _delta(0.5, 0.5),
        _analysis(
            grade2_targets_exclusive_to_c0=1,
            grade2_targets_exclusive_to_c0_preserved_by_c2=0,
            questions_improved_over_c1=1,
        ),
    )
    assert outcome["decision"] == DECISION_D


def test_the_recorded_decision_follows_the_rule(artefact: dict[str, Any]) -> None:
    recomputed = decide(
        artefact["aggregate_delta_c2_minus_c1"], artefact["complementarity"]
    )
    assert recomputed == artefact["decision"]


# ---------------------------------------------------------------------------
# Pureza
# ---------------------------------------------------------------------------


_PURITY_SNIPPET = """
import sys

import app.evaluation.hybrid_rrf
import scripts.evaluate_hybrid_rrf

for forbidden in ("sqlalchemy", "openai", "fastapi"):
    assert forbidden not in sys.modules, forbidden
print("ok")
"""


def test_the_phase_needs_no_database_no_provider_and_no_application() -> None:
    """A fusão consome rankings persistidos: nada disto devia ser preciso."""
    result = subprocess.run(  # noqa: S603 - comando fixo, sem entrada externa
        [sys.executable, "-c", _PURITY_SNIPPET],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ok" in result.stdout


# ---------------------------------------------------------------------------
# Reprodutibilidade e produção
# ---------------------------------------------------------------------------


def test_two_builds_produce_the_same_result(
    comparison: dict[str, Any], ground_truth: dict[str, Any], artefact: dict[str, Any]
) -> None:
    rebuilt = stamp_digests(build_payload(comparison, ground_truth))
    assert rebuilt["result_digest"] == artefact["result_digest"]
    assert rebuilt["aggregate"] == artefact["aggregate"]
    assert rebuilt["decision"] == artefact["decision"]


def test_production_retrieval_is_untouched() -> None:
    """C2 é experiência. ``get_retriever`` continua a devolver o lexical."""
    source = (BACKEND_DIR / "app" / "retrieval" / "dependencies.py").read_text(
        encoding="utf-8"
    )
    assert "PostgresLexicalRetriever()" in source
    assert "Hybrid" not in source
    assert "hybrid_rrf" not in source


def test_the_fusion_module_is_not_reexported_by_the_package() -> None:
    """Manter ``hybrid_rrf`` fora do ``__init__`` é o que mantém estrutural a
    garantia de que importar ``app.evaluation.assets`` não puxa nada pesado."""
    import app.evaluation as evaluation_package

    assert "hybrid_rrf" not in getattr(evaluation_package, "__all__", [])
