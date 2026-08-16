"""Variantes de pesos do ranking lexical (D4.7).

O que estes testes protegem é a validade da comparação. Uma variante só mede
pesos se três coisas se verificarem: o controlo reproduz exatamente
``compute_score``, a renormalização mantém o limiar inerte, e nenhuma variante
pode alterar **quem** é devolvido — só a ordem. As três falhariam em silêncio se
não estivessem fixadas.

Testes puros: não tocam na base de dados. Os últimos leem o artefacto real
versionado.
"""

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from app.core.text_normalization import normalize_text
from app.evaluation.ranking_variants import (
    PRODUCTION_WEIGHTS,
    SIGNAL_NAMES,
    RankingVariant,
    RankingVariantError,
    normalise_weights,
    score_with,
    signal_values,
    with_weight,
)
from app.retrieval.query_planning import LexicalQueryStrategy
from app.retrieval.reranking import (
    LexicalCandidate,
    LexicalFeatures,
    compute_features,
    compute_score,
    informative_query_terms,
)
from scripts.evaluate_ranking_variants import (
    EXIT_BASELINE_MISMATCH,
    EXPECTED_GROUND_TRUTH_DIGEST,
    VARIANTS,
    rank_under_weights,
)
from scripts.evaluate_ranking_variants import (
    main as run_ranking_variants,
)
from scripts.evaluate_retrieval_experiment import (
    ExperimentError,
    verify_baseline_integrity,
)

ARTEFACT = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "evaluation"
    / "ranking-variants-p1-s1.json"
)


def _candidate(
    text: str, *, structure: str | None = None, raw_score: float = 0.05
) -> LexicalCandidate:
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
        raw_score=raw_score,
        strategy=LexicalQueryStrategy.REDUCED_OR,
    )


def _features(**overrides: float) -> LexicalFeatures:
    defaults: dict[str, float] = {
        "coverage": 0.5,
        "exact_phrase": 0.0,
        "ordered": 0.5,
        "proximity": 0.5,
        "compactness": 0.5,
        "title_overlap": 0.25,
        "section_overlap": 0.25,
        "table_row_bonus": 0.0,
        "fts_norm": 0.5,
        "length_factor": 1.0,
        "strategy_quality": 0.25,
    }
    return LexicalFeatures(matched_terms=frozenset({"a"}), **{**defaults, **overrides})


# ---------------------------------------------------------------------------
# O controlo é mesmo o ranking de produção
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "inicio do ano letivo 06 de outubro de 2025",
        "1.o semestre do ano letivo 2025/2026",
        "renovacao das matriculas no 1o semestre do ano letivo",
        "texto sem relacao nenhuma com o assunto",
    ],
)
@pytest.mark.parametrize("structure", ["table_row", "heading", None])
def test_production_weights_reproduce_compute_score(text: str, structure: str) -> None:
    """A propriedade sem a qual nenhum delta é interpretável.

    Se o controlo divergisse de ``compute_score``, todas as variantes estariam a
    ser comparadas contra uma reimplementação em vez do ranking real.
    """
    query = normalize_text("Quando comeca o ano letivo 2025/2026?")
    terms = informative_query_terms(query, "pt")
    features = compute_features(terms, _candidate(text, structure=structure))
    assert score_with(features, PRODUCTION_WEIGHTS) == pytest.approx(
        compute_score(features), abs=1e-12
    )


def test_the_production_vector_already_sums_to_one() -> None:
    assert sum(PRODUCTION_WEIGHTS.values()) == pytest.approx(1.0, abs=1e-9)
    assert set(PRODUCTION_WEIGHTS) == set(SIGNAL_NAMES)


def test_signal_values_folds_length_into_the_fts_term() -> None:
    """O comprimento não tem peso próprio em produção; dar-lho aqui inventaria
    um sinal."""
    values = signal_values(_features(fts_norm=0.8, length_factor=0.5))
    assert values["fts_component"] == pytest.approx(0.4)
    assert "length_factor" not in values
    assert "compactness" not in values


# ---------------------------------------------------------------------------
# Renormalização
# ---------------------------------------------------------------------------


def test_a_normalised_vector_sums_to_one() -> None:
    weights = normalise_weights(with_weight(PRODUCTION_WEIGHTS, structure_table_row=0.0))
    assert sum(weights.values()) == pytest.approx(1.0, abs=1e-9)


def test_removing_a_signal_raises_every_other_weight() -> None:
    """A contrapartida da renormalização, declarada e não escondida: uma ablação
    responde a "que peso relativo deve este sinal ter", não a "o que acontece se
    este termo desaparecer sem mais nada mudar"."""
    weights = normalise_weights(with_weight(PRODUCTION_WEIGHTS, structure_table_row=0.0))
    assert weights["structure_table_row"] == 0.0
    for name in SIGNAL_NAMES:
        if name == "structure_table_row":
            continue
        assert weights[name] > PRODUCTION_WEIGHTS[name]


def test_the_production_vector_is_its_own_normalisation() -> None:
    normalised = normalise_weights(PRODUCTION_WEIGHTS)
    for name in SIGNAL_NAMES:
        assert normalised[name] == pytest.approx(PRODUCTION_WEIGHTS[name], abs=1e-12)


def test_negative_weights_are_refused() -> None:
    """Um peso negativo transformaria um sinal de relevância num de penalização —
    outra hipótese, que esta fase não formula."""
    with pytest.raises(RankingVariantError, match="negative weights"):
        normalise_weights(with_weight(PRODUCTION_WEIGHTS, coverage=-0.1))


def test_an_unknown_signal_is_refused() -> None:
    with pytest.raises(RankingVariantError, match="unknown ranking signals"):
        normalise_weights({**PRODUCTION_WEIGHTS, "semantic_similarity": 0.5})


def test_with_weight_refuses_an_unknown_signal() -> None:
    with pytest.raises(RankingVariantError, match="unknown ranking signals"):
        with_weight(PRODUCTION_WEIGHTS, embedding_score=0.5)


def test_an_all_zero_vector_is_refused() -> None:
    with pytest.raises(RankingVariantError, match="sums to zero"):
        normalise_weights({name: 0.0 for name in SIGNAL_NAMES})


def test_a_partial_vector_fills_the_missing_signals_with_zero() -> None:
    weights = normalise_weights({"coverage": 1.0})
    assert weights["coverage"] == pytest.approx(1.0)
    assert weights["proximity"] == 0.0


# ---------------------------------------------------------------------------
# As variantes declaradas
# ---------------------------------------------------------------------------


def test_the_control_variant_is_production() -> None:
    control = next(v for v in VARIANTS if v.variant_id == "A0")
    assert control.deltas_from_production() == {}


def test_every_variant_has_a_distinct_identifier_and_a_hypothesis() -> None:
    identifiers = [variant.variant_id for variant in VARIANTS]
    assert len(identifiers) == len(set(identifiers))
    for variant in VARIANTS:
        assert variant.hypothesis.strip()
        assert sum(variant.normalised.values()) == pytest.approx(1.0, abs=1e-9)


def test_the_variant_set_stays_small() -> None:
    """Com doze perguntas medidas, muitas variantes seriam procura de pesos e
    não teste de hipóteses."""
    assert len(VARIANTS) <= 8


def test_deltas_are_reported_after_normalisation() -> None:
    """Comparar os pesos escritos à mão esconderia o efeito da renormalização
    sobre os sinais que a variante nem menciona."""
    variant = RankingVariant(
        variant_id="X",
        label="teste",
        hypothesis="h",
        weights=with_weight(PRODUCTION_WEIGHTS, structure_table_row=0.0),
    )
    deltas = variant.deltas_from_production()
    assert deltas["structure_table_row"] == pytest.approx(-0.06)
    assert deltas["coverage"] > 0


# ---------------------------------------------------------------------------
# Uma variante só reordena
# ---------------------------------------------------------------------------


def test_a_variant_cannot_change_which_candidates_survive_eligibility() -> None:
    """A elegibilidade decide antes de qualquer peso existir.

    Todas as variantes recebem o mesmo conjunto; a única fronteira que os pesos
    podem mover é o limiar mínimo, e é por isso que ele é contado.
    """
    query = normalize_text("Quando comeca o ano letivo 2025/2026?")
    terms = informative_query_terms(query, "pt")
    survivors = [
        (candidate, compute_features(terms, candidate))
        for candidate in (
            _candidate("inicio do ano letivo 2025/2026", structure="table_row"),
            _candidate("1.o semestre do ano letivo 2025/2026", structure="heading"),
            _candidate("recesso do natal e ano novo", structure="table_row"),
        )
    ]
    baseline, _ = rank_under_weights(survivors, normalise_weights(PRODUCTION_WEIGHTS))
    variant, _ = rank_under_weights(
        survivors, normalise_weights(with_weight(PRODUCTION_WEIGHTS, coverage=0.8))
    )
    assert {c.chunk_id for c in baseline} == {c.chunk_id for c in variant}


def test_ranking_is_deterministic_regardless_of_input_order() -> None:
    """Sem desempate total, duas variantes com scores iguais poderiam diferir
    pela ordem de chegada das linhas."""
    query = normalize_text("Quando comeca o ano letivo?")
    terms = informative_query_terms(query, "pt")
    candidates = [
        _candidate("inicio do ano letivo", raw_score=0.05),
        _candidate("inicio do ano letivo", raw_score=0.05),
        _candidate("inicio do ano letivo", raw_score=0.05),
    ]
    survivors = [(c, compute_features(terms, c)) for c in candidates]
    weights = normalise_weights(PRODUCTION_WEIGHTS)
    forward, _ = rank_under_weights(survivors, weights)
    backward, _ = rank_under_weights(list(reversed(survivors)), weights)
    assert [c.chunk_id for c in forward] == [c.chunk_id for c in backward]


# ---------------------------------------------------------------------------
# O artefacto versionado
# ---------------------------------------------------------------------------


def _load() -> dict[str, Any]:
    return json.loads(ARTEFACT.read_text(encoding="utf-8"))


def test_the_artefact_is_bound_to_the_repooled_ground_truth() -> None:
    payload = _load()
    assert payload["ground_truth_digest"] == EXPECTED_GROUND_TRUTH_DIGEST
    assert payload["control_reproduces_d46"] is True


def test_the_threshold_stays_inert_in_every_variant() -> None:
    """A razão de ser da renormalização: se um candidato caísse abaixo do limiar,
    a variante deixaria de medir ordenação e passaria a medir corte."""
    for cell in _load()["cells"]:
        below = sum(r["below_threshold"] for r in cell["question_results"])
        assert below == 0, (cell["budget_policy"], cell["variant_id"])


def test_every_variant_sees_the_same_eligible_set() -> None:
    payload = _load()
    for policy in payload["budget_policies"]:
        cells = [c for c in payload["cells"] if c["budget_policy"] == policy]
        signatures = {
            tuple(
                (r["question_id"], r["eligible_candidates"])
                for r in cell["question_results"]
            )
            for cell in cells
        }
        assert len(signatures) == 1, policy


def test_variants_promoting_unjudged_results_are_flagged() -> None:
    """O protocolo pontua não julgado como grau 0; aqui isso penalizaria uma
    variante por trazer à superfície algo que ninguém avaliou."""
    for cell in _load()["cells"]:
        expected = "REPOOLING_REQUIRED" if cell["unjudged_in_top_k_total"] else "COMPARABLE"
        assert cell["comparability"] == expected


def test_the_artefact_records_the_normalised_weights_of_every_variant() -> None:
    payload = _load()
    for variant in payload["variants"]:
        weights = variant["weights_normalised"]
        assert set(weights) == set(SIGNAL_NAMES)
        assert sum(weights.values()) == pytest.approx(1.0, abs=1e-5)


# ---------------------------------------------------------------------------
# Integridade do artefacto consumido
# ---------------------------------------------------------------------------

DIAGNOSTICS = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "evaluation"
    / "ranking-diagnostics-p1-s1.json"
)
GROUND_TRUTH = DIAGNOSTICS.with_name("retrieval-ground-truth-p1-repooled.json")


def _diagnostics() -> dict[str, Any]:
    return json.loads(DIAGNOSTICS.read_text(encoding="utf-8"))


def test_the_versioned_diagnostics_artefact_matches_its_own_digest() -> None:
    """O D4.7 copia o ``result_digest`` do D4.6 para o seu próprio artefacto; se
    o ficheiro não correspondesse ao digest, essa ligação seria falsa."""
    verify_baseline_integrity(_diagnostics())


def test_a_tampered_result_digest_is_refused() -> None:
    tampered = _diagnostics()
    tampered["result_digest"] = "0" * 64
    with pytest.raises(ExperimentError, match="does not match its own result_digest") as info:
        verify_baseline_integrity(tampered)
    assert info.value.exit_code == EXIT_BASELINE_MISMATCH


def test_runner_refuses_tampered_diagnostics_before_writing_output(
    tmp_path: Path,
) -> None:
    """Protege a ligação entre o runner D4.7 e a guarda de integridade."""
    tampered = _diagnostics()
    tampered["result_digest"] = "0" * 64
    diagnostics = tmp_path / "tampered-diagnostics.json"
    diagnostics.write_text(json.dumps(tampered), encoding="utf-8")
    binding = tmp_path / "binding.json"
    binding.write_text("{}", encoding="utf-8")
    output = tmp_path / "ranking-variants.json"

    exit_code = run_ranking_variants(
        [
            "--ground-truth",
            str(GROUND_TRUTH),
            "--binding",
            str(binding),
            "--diagnostics",
            str(diagnostics),
            "--output",
            str(output),
        ]
    )

    assert exit_code == EXIT_BASELINE_MISMATCH
    assert not output.exists()


def test_a_tampered_payload_field_is_refused() -> None:
    """Reproduzir as células não apanharia isto.

    As células do D4.7 são recalculadas a partir da base e continuariam a
    coincidir; o que muda é o conteúdo do artefacto consumido, e só o digest o
    deteta.
    """
    tampered = _diagnostics()
    tampered["ground_truth_digest_before"] = "f" * 64
    with pytest.raises(ExperimentError, match="does not match its own result_digest") as info:
        verify_baseline_integrity(tampered)
    assert info.value.exit_code == EXIT_BASELINE_MISMATCH


def test_a_diagnostics_artefact_without_a_digest_is_refused() -> None:
    tampered = _diagnostics()
    del tampered["result_digest"]
    with pytest.raises(ExperimentError, match="no result_digest") as info:
        verify_baseline_integrity(tampered)
    assert info.value.exit_code == EXIT_BASELINE_MISMATCH


def test_the_variants_artefact_declares_the_digest_it_consumed() -> None:
    assert _load()["d46_result_digest"] == _diagnostics()["result_digest"]
