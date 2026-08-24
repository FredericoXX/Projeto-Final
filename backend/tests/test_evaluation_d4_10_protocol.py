"""D4.10a — o painel independente, os digests e a barreira de pré-registo.

Nenhum teste precisa de base de dados, rede ou fornecedor: esta fase não executa
a experiência. As fixtures de base de dados do ``conftest`` são anuladas por isso
mesmo.
"""

import copy
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

import app.evaluation.d4_10_statistics as d4_10_statistics
import scripts.seal_d4_10_protocol as d4_10_sealer
from app.evaluation.d4_10_protocol import (
    AMENDMENT_KIND,
    ANSWERABLE,
    EXCLUDE,
    HUMAN_CONFIRMED,
    INDEPENDENT,
    MACHINE_LOCATED,
    MACHINE_SEARCHED,
    NO_EVIDENCE,
    NO_TARGET_DOCUMENT,
    OVERLAP_REVIEW_FIELD,
    PENDING_HUMAN_REVIEW,
    RELATED_BUT_DISTINCT,
    REVIEW_STATUSES,
    ProtocolError,
    declared_identity,
    distribution,
    document_distribution,
    human_review_digest,
    human_review_summary,
    protocol_digest,
    question_set_digest,
    scenario_digest,
    scenario_distribution,
    validation_block_name,
    verify_declared_identity,
    verify_prior_observation_disclosure,
    verify_protocol_has_no_results,
    verify_question_set,
)
from app.evaluation.d4_10_statistics import (
    A_EVIDENCE_FOR_HYBRID,
    B_EVIDENCE_FOR_DENSE,
    C_INCONCLUSIVE,
    DEFAULT_REPLICATES,
    DEFAULT_SEED,
    ConfidenceInterval,
    DecisionInputs,
    StatisticsError,
    bootstrap_interval,
    bootstrap_replicates,
    build_decision_result,
    decide,
    eligible_scenario_deltas,
    quantile,
    scenario_macro_mean,
    sensitivity_scenario_deltas_without_sc_a16,
    validate_decision_result,
)
from scripts.seal_d4_10_protocol import (
    EXIT_HUMAN_REVIEW_REQUIRED,
    EXIT_OK,
    PROTOCOL_DRAFT,
    PROTOCOL_SEALED,
    build_protocol,
    load_json,
)
from scripts.seal_d4_10_protocol import main as seal_main

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = BACKEND_DIR.parent
QUESTION_SET_PATH = REPOSITORY_ROOT / "docs" / "evaluation" / "d4-10-question-set-v1.json"
PROTOCOL_PATH = REPOSITORY_ROOT / "docs" / "evaluation" / "d4-10-protocol-v1.json"

HISTORICAL_GROUND_TRUTH = (
    REPOSITORY_ROOT
    / "docs"
    / "evaluation"
    / "retrieval-ground-truth-p1-lexical-dense-repooled.json"
)
DENSE_ADMISSION_DATASET = (
    REPOSITORY_ROOT / "docs" / "evaluation" / "dense-admission-dataset-v1.json"
)


@pytest.fixture(scope="session", autouse=True)
def _override_get_db() -> None:
    """Anula a fixture homónima do conftest: aqui não há dependência de DB."""


@pytest.fixture(autouse=True)
def _clean_tables() -> None:
    """Anula a fixture homónima do conftest: aqui não há tabelas a truncar."""


@pytest.fixture(scope="module")
def question_set() -> dict[str, Any]:
    return load_json(QUESTION_SET_PATH)


@pytest.fixture(scope="module")
def protocol() -> dict[str, Any]:
    return load_json(PROTOCOL_PATH)


@pytest.fixture(scope="module")
def snapshot_binding(protocol: dict[str, Any]) -> dict[str, Any]:
    """Binding versionado de S1; o snapshot operacional não existe no CI."""
    return {
        field: protocol[field]
        for field in ("snapshot_id", "corpus_digest", "reference_date")
    }


# ---------------------------------------------------------------------------
# Digests
# ---------------------------------------------------------------------------


def test_the_digests_are_deterministic(question_set: dict[str, Any]) -> None:
    questions = question_set["questions"]
    assert question_set_digest(questions) == question_set_digest(questions)
    assert scenario_digest(question_set) == scenario_digest(question_set)
    assert human_review_digest(question_set) == human_review_digest(question_set)


def test_the_three_digests_are_distinct(question_set: dict[str, Any]) -> None:
    """Cobrem coisas diferentes; se coincidissem, um deles seria decorativo."""
    questions = question_set["questions"]
    digests = {
        question_set_digest(questions),
        scenario_digest(question_set),
        human_review_digest(question_set),
    }
    assert len(digests) == 3


def test_the_artefacts_declare_their_own_digests(
    question_set: dict[str, Any], protocol: dict[str, Any]
) -> None:
    questions = question_set["questions"]
    assert protocol["question_set_digest"] == question_set_digest(questions)
    assert protocol["scenario_digest"] == scenario_digest(question_set)
    assert protocol["human_review_digest"] == human_review_digest(question_set)
    assert protocol["protocol_digest"] == protocol_digest(protocol)


def test_the_amendment_requires_a_prior_observation_disclosure(
    protocol: dict[str, Any],
) -> None:
    tampered = copy.deepcopy(protocol)
    del tampered["prior_observation_disclosure"]
    with pytest.raises(ProtocolError, match="prior_observation_disclosure obrigatório"):
        verify_prior_observation_disclosure(tampered)


def test_mutating_only_the_disclosure_changes_the_protocol_digest(
    protocol: dict[str, Any],
) -> None:
    tampered = copy.deepcopy(protocol)
    before = protocol_digest(tampered)
    tampered["prior_observation_disclosure"]["observations"][0]["exposure_surface"][
        0
    ] = "different_observed_surface"
    verify_prior_observation_disclosure(tampered)
    assert protocol_digest(tampered) != before


def test_observer_belief_field_is_required_without_a_default(
    protocol: dict[str, Any],
) -> None:
    tampered = copy.deepcopy(protocol)
    del tampered["prior_observation_disclosure"]["observations"][0][
        "observer_formed_belief_about_label"
    ]
    with pytest.raises(ProtocolError, match="observer_formed_belief_about_label"):
        verify_prior_observation_disclosure(tampered)


@pytest.mark.parametrize("rationale", [None, "", "   "])
def test_false_observer_belief_requires_a_non_empty_rationale(
    protocol: dict[str, Any], rationale: str | None
) -> None:
    tampered = copy.deepcopy(protocol)
    observation = tampered["prior_observation_disclosure"]["observations"][0]
    observation["observer_formed_belief_about_label"] = False
    if rationale is None:
        observation.pop("observation_belief_rationale", None)
    else:
        observation["observation_belief_rationale"] = rationale
    with pytest.raises(ProtocolError, match="observation_belief_rationale"):
        verify_prior_observation_disclosure(tampered)


def test_the_seven_known_exposures_and_scenarios_are_disclosed(
    protocol: dict[str, Any],
) -> None:
    verify_prior_observation_disclosure(protocol)
    disclosure = protocol["prior_observation_disclosure"]
    observed = {
        item["question_id"]: (item["scenario_id"], item["answerability_intent"])
        for item in disclosure["observations"]
    }
    assert {
        "DX026": ("SC-A16", ANSWERABLE),
        "DX027": ("SC-A16", ANSWERABLE),
        "DX043": ("SC-N01", NO_EVIDENCE),
        "DX044": ("SC-N01", NO_EVIDENCE),
        "DX045": ("SC-N02", NO_EVIDENCE),
        "DX046": ("SC-N03", NO_EVIDENCE),
        "DX047": ("SC-N03", NO_EVIDENCE),
    }.items() <= observed.items()
    assert protocol["amendment_kind"] == AMENDMENT_KIND
    assert protocol["phase"] == "D4.10a.1"


def test_the_question_set_carries_its_own_identity(
    question_set: dict[str, Any], protocol: dict[str, Any]
) -> None:
    """O conjunto declara os digests e as distribuições, e são os do protocolo."""
    verify_declared_identity(question_set)
    for field in ("question_set_digest", "scenario_digest", "human_review_digest"):
        assert question_set[field] == protocol[field]
    assert question_set["scenario_distribution"] == protocol["scenario_distribution"]
    assert question_set["document_distribution"] == protocol["document_distribution"]


def test_a_question_set_whose_declared_identity_is_stale_is_refused(
    question_set: dict[str, Any],
) -> None:
    """Carimbo desatualizado é pior do que carimbo nenhum: descreve outro ficheiro."""
    tampered = copy.deepcopy(question_set)
    tampered["questions"][0]["question"] += " (editada)"
    with pytest.raises(ProtocolError, match="não corresponde ao conteúdo"):
        verify_declared_identity(tampered)


def test_a_question_set_without_declared_identity_is_refused(
    question_set: dict[str, Any],
) -> None:
    tampered = copy.deepcopy(question_set)
    del tampered["human_review_digest"]
    with pytest.raises(ProtocolError, match="identidade declarada em falta"):
        verify_declared_identity(tampered)


def test_the_sealing_refuses_a_question_set_that_is_not_stamped(
    question_set: dict[str, Any],
) -> None:
    """A selagem não carimba: verifica. Caso contrário concordaria consigo própria."""
    tampered = copy.deepcopy(question_set)
    tampered["questions"][0]["question"] += " (editada)"
    verify_question_set(tampered)  # continua internamente válido
    with pytest.raises(ProtocolError, match="não corresponde ao conteúdo"):
        verify_declared_identity(tampered)


def test_editing_a_question_changes_the_question_set_digest(
    question_set: dict[str, Any],
) -> None:
    tampered = copy.deepcopy(question_set["questions"])
    tampered[0]["question"] += " (editada)"
    assert question_set_digest(tampered) != question_set_digest(question_set["questions"])


def test_moving_a_question_between_scenarios_changes_both_digests(
    question_set: dict[str, Any],
) -> None:
    """Mover uma paráfrase de família é leakage, e tem de ser visível."""
    tampered = copy.deepcopy(question_set)
    questions = tampered["questions"]
    other = next(q for q in questions if q["scenario_id"] != questions[0]["scenario_id"])
    questions[0]["scenario_id"] = other["scenario_id"]
    assert question_set_digest(questions) != question_set_digest(
        question_set["questions"]
    )
    assert scenario_digest(tampered) != scenario_digest(question_set)


def test_changing_a_label_changes_the_question_set_digest(
    question_set: dict[str, Any],
) -> None:
    tampered = copy.deepcopy(question_set["questions"])
    tampered[0]["answerability_intent"] = (
        NO_EVIDENCE if tampered[0]["answerability_intent"] == ANSWERABLE else ANSWERABLE
    )
    assert question_set_digest(tampered) != question_set_digest(question_set["questions"])


def test_removing_a_question_changes_the_digest(question_set: dict[str, Any]) -> None:
    tampered = question_set["questions"][:-1]
    assert question_set_digest(tampered) != question_set_digest(question_set["questions"])


def test_confirming_a_review_does_not_change_the_question_set_digest(
    question_set: dict[str, Any],
) -> None:
    """Um humano assinar uma validação não altera nenhuma pergunta.

    Se o digest cobrisse o `review_status`, a revisão humana invalidaria o
    conjunto que ela própria valida — e ninguém a faria.
    """
    reviewed = copy.deepcopy(question_set)
    for question in reviewed["questions"]:
        question["review_status"] = HUMAN_CONFIRMED
    assert question_set_digest(reviewed["questions"]) == question_set_digest(
        question_set["questions"]
    )
    # Mas tem de ser visível em **algum** digest, senão a revisão não é selável.
    assert human_review_digest(reviewed) != human_review_digest(question_set)


def _confirm(
    question_set: dict[str, Any], question_id: str, annotator: str
) -> dict[str, Any]:
    """Uma variante em que um humano nomeado confirmou uma pergunta."""
    variant = copy.deepcopy(question_set)
    for question in variant["questions"]:
        if question["question_id"] != question_id:
            continue
        question["review_status"] = HUMAN_CONFIRMED
        block = validation_block_name(question)
        question[block]["annotator"] = annotator
        question[block]["validation_status"] = HUMAN_CONFIRMED
    verify_question_set(variant)
    return variant


def test_who_validated_and_what_they_validated_are_covered_by_a_digest(
    question_set: dict[str, Any],
    protocol: dict[str, Any],
    snapshot_binding: dict[str, Any],
) -> None:
    """Duas revisões diferentes não podem produzir a mesma selagem.

    Este é o teste que o contrato anterior não passava: como nenhum digest
    cobria a revisão, confirmar `DX001` com um anotador ou `DX002` com outro
    dava exatamente os mesmos ``question_set_digest``, ``scenario_digest`` e
    ``protocol_digest``. Depois das cinquenta confirmações seria possível
    reescrever quem validou o quê sem invalidar nada.
    """
    first = _confirm(question_set, "DX001", "revisor-A")
    second = _confirm(question_set, "DX002", "revisor-B")

    # O conteúdo das perguntas é o mesmo nas duas variantes, e deve sê-lo.
    assert question_set_digest(first["questions"]) == question_set_digest(
        second["questions"]
    )
    assert scenario_digest(first) == scenario_digest(second)

    # A revisão não é, e a selagem tem de o refletir.
    assert human_review_digest(first) != human_review_digest(second)
    for variant in (first, second):
        variant.update(declared_identity(variant))
    assert (
        build_protocol(first, snapshot_binding)["protocol_digest"]
        != build_protocol(second, snapshot_binding)["protocol_digest"]
    )
    assert build_protocol(first, snapshot_binding)["protocol_digest"] != protocol[
        "protocol_digest"
    ]


def test_rewriting_recorded_evidence_changes_the_human_review_digest(
    question_set: dict[str, Any],
) -> None:
    """Trocar a âncora registada é trocar a prova de que a etiqueta assenta."""
    tampered = copy.deepcopy(question_set)
    target = next(
        q for q in tampered["questions"] if q["answerability_intent"] == ANSWERABLE
    )
    target["answerable_validation"]["located_evidence"][0]["chunk_index"] += 1
    assert human_review_digest(tampered) != human_review_digest(question_set)
    # E não muda o digest do conteúdo: são perguntas iguais, prova diferente.
    assert question_set_digest(tampered["questions"]) == question_set_digest(
        question_set["questions"]
    )


def test_rewriting_the_rationale_changes_the_human_review_digest(
    question_set: dict[str, Any],
) -> None:
    tampered = copy.deepcopy(question_set)
    target = next(
        q for q in tampered["questions"] if q["answerability_intent"] == ANSWERABLE
    )
    target["answerable_validation"]["rationale"] = "outra justificação"
    assert human_review_digest(tampered) != human_review_digest(question_set)


def test_redefining_a_scenario_changes_the_scenario_digest(
    question_set: dict[str, Any],
) -> None:
    """Reetiquetar um cenário muda a leitura sem mudar uma única pergunta.

    Trocar `exact_institutional_terms` por `paraphrase_natural` mantém os
    identificadores e as contagens intactos: sem metadados no digest, a
    redefinição passaria despercebida à selagem.
    """
    for field, value in (
        ("scenario_type", "outro_tipo"),
        ("topic", "outro_topico"),
    ):
        tampered = copy.deepcopy(question_set)
        scenario = tampered["scenarios"][0]
        scenario[field] = value
        for question in tampered["questions"]:
            if question["scenario_id"] == scenario["scenario_id"]:
                question[field] = value
        verify_question_set(tampered)
        assert scenario_digest(tampered) != scenario_digest(question_set), field
        assert question_set_digest(tampered["questions"]) == question_set_digest(
            question_set["questions"]
        ), field


def test_a_question_that_contradicts_its_scenario_is_refused(
    question_set: dict[str, Any],
) -> None:
    """Metadados repetidos que não são verificados acabam por divergir."""
    tampered = copy.deepcopy(question_set)
    tampered["questions"][0]["scenario_type"] = "outro_tipo"
    with pytest.raises(ProtocolError, match="scenario_type diverge do cenário"):
        verify_question_set(tampered)

    tampered = copy.deepcopy(question_set)
    tampered["questions"][0]["target_document"] = "P1-DOC-999"
    with pytest.raises(ProtocolError, match="target_document diverge do cenário"):
        verify_question_set(tampered)


def test_changing_the_fusion_configuration_changes_the_protocol_digest(
    protocol: dict[str, Any],
) -> None:
    tampered = copy.deepcopy(protocol)
    tampered["conditions"]["C2"]["k_rrf"] = 10
    assert protocol_digest(tampered) != protocol_digest(protocol)


def test_changing_the_metric_protocol_changes_the_protocol_digest(
    protocol: dict[str, Any],
) -> None:
    tampered = copy.deepcopy(protocol)
    tampered["metric_protocol"]["primary_metric"] = "recall@5"
    assert protocol_digest(tampered) != protocol_digest(protocol)


def test_changing_the_bootstrap_seed_changes_the_protocol_digest(
    protocol: dict[str, Any],
) -> None:
    tampered = copy.deepcopy(protocol)
    tampered["bootstrap_protocol"]["seed"] = 1
    assert protocol_digest(tampered) != protocol_digest(protocol)


# ---------------------------------------------------------------------------
# Independência do painel
# ---------------------------------------------------------------------------


def test_no_historical_question_id_is_reused(question_set: dict[str, Any]) -> None:
    historical = {
        q["question_id"] for q in load_json(HISTORICAL_GROUND_TRUTH)["questions"]
    }
    historical |= {
        q["question_id"] for q in load_json(DENSE_ADMISSION_DATASET)["questions"]
    }
    new = {q["question_id"] for q in question_set["questions"]}
    assert new & historical == set()
    assert all(qid.startswith("DX") for qid in new)


def test_a_historical_identifier_is_refused(question_set: dict[str, Any]) -> None:
    tampered = copy.deepcopy(question_set)
    tampered["questions"][0]["question_id"] = "Q001"
    with pytest.raises(ProtocolError, match="identificador histórico"):
        verify_question_set(tampered)


def test_no_question_text_is_reused_verbatim(question_set: dict[str, Any]) -> None:
    """Reutilizar o texto de uma pergunta histórica seria leakage direto."""

    def normalise(text: str) -> str:
        return " ".join(text.lower().split())

    historical = {
        normalise(q["question"])
        for q in load_json(HISTORICAL_GROUND_TRUTH)["questions"]
    }
    historical |= {
        normalise(q["question"]) for q in load_json(DENSE_ADMISSION_DATASET)["questions"]
    }
    new = {normalise(q["question"]) for q in question_set["questions"]}
    assert new & historical == set()


# ---------------------------------------------------------------------------
# Estrutura do painel
# ---------------------------------------------------------------------------


def test_every_question_has_a_scenario_and_a_review_status(
    question_set: dict[str, Any],
) -> None:
    for question in question_set["questions"]:
        assert question["scenario_id"]
        assert question["review_status"] in REVIEW_STATUSES


def test_no_scenario_is_empty_and_counts_match(question_set: dict[str, Any]) -> None:
    verify_question_set(question_set)
    for scenario in question_set["scenarios"]:
        assert scenario["question_count"] >= 1


def test_a_scenario_may_not_mix_answerability_intents(
    question_set: dict[str, Any],
) -> None:
    tampered = copy.deepcopy(question_set)
    first = tampered["questions"][0]
    sibling = next(
        q
        for q in tampered["questions"]
        if q["scenario_id"] == first["scenario_id"] and q is not first
    )
    sibling["answerability_intent"] = NO_EVIDENCE
    sibling.pop("answerable_validation", None)
    sibling["no_evidence_validation"] = {
        "validation_method": "x",
        "terms_searched": ["x"],
        "search_result": "x",
        "validation_status": MACHINE_SEARCHED,
        "annotator": None,
    }
    with pytest.raises(ProtocolError, match="intenções mistas"):
        verify_question_set(tampered)


def test_an_answerable_question_needs_located_evidence(
    question_set: dict[str, Any],
) -> None:
    tampered = copy.deepcopy(question_set)
    target = next(
        q for q in tampered["questions"] if q["answerability_intent"] == ANSWERABLE
    )
    target["answerable_validation"]["located_evidence"] = []
    with pytest.raises(ProtocolError, match="sem evidência localizada"):
        verify_question_set(tampered)


def test_a_no_evidence_question_needs_the_search_that_was_run(
    question_set: dict[str, Any],
) -> None:
    tampered = copy.deepcopy(question_set)
    target = next(
        q for q in tampered["questions"] if q["answerability_intent"] == NO_EVIDENCE
    )
    target["no_evidence_validation"]["terms_searched"] = []
    with pytest.raises(ProtocolError, match="sem termos procurados"):
        verify_question_set(tampered)


def test_a_human_confirmation_needs_a_named_annotator(
    question_set: dict[str, Any],
) -> None:
    """A máquina localiza evidência; assinar por um humano é outra coisa."""
    tampered = copy.deepcopy(question_set)
    target = tampered["questions"][0]
    target["review_status"] = HUMAN_CONFIRMED
    target["answerable_validation"]["validation_status"] = HUMAN_CONFIRMED
    target["answerable_validation"]["annotator"] = None
    with pytest.raises(ProtocolError, match="sem annotator"):
        verify_question_set(tampered)


def test_every_located_anchor_points_at_a_real_corpus_document(
    question_set: dict[str, Any],
) -> None:
    usable = set(question_set["usable_documents"])
    for question in question_set["questions"]:
        for anchor in question.get("answerable_validation", {}).get(
            "located_evidence", []
        ):
            assert anchor["corpus_item_id"] in usable
            assert isinstance(anchor["chunk_index"], int)


def test_the_panel_is_materially_larger_than_the_d4_9_one(
    question_set: dict[str, Any],
) -> None:
    """A D4.9 mediu 12 perguntas e o efeito só era observável em sete."""
    counts = distribution(question_set)
    assert counts["question_count"] > 12
    assert counts["scenario_count"] > 12
    assert counts["by_answerability_intent"][NO_EVIDENCE] >= 1


def test_the_document_distribution_reports_volume_and_semantic_type(
    question_set: dict[str, Any],
) -> None:
    """Contagem sozinha não distingue cobertura de repetição.

    Cinco perguntas sobre um documento todas do mesmo tipo não testam o que
    cinco perguntas repartidas por termos exatos, paráfrase e formulação
    indireta testam. As duas leituras têm de estar no mesmo sítio.
    """
    coverage = document_distribution(question_set)
    total = sum(entry["question_count"] for entry in coverage.values())
    assert total == len(question_set["questions"])
    for name, entry in coverage.items():
        assert entry["question_count"] >= 1, name
        assert entry["by_scenario_type"], name
        assert sum(entry["by_scenario_type"].values()) == entry["question_count"], name
        assert entry["scenario_count"] == len(entry["scenario_ids"]), name


def test_every_indexed_document_appears_in_the_distribution(
    question_set: dict[str, Any],
) -> None:
    coverage = document_distribution(question_set)
    assert set(question_set["usable_documents"]) <= set(coverage)


def test_the_no_evidence_questions_are_not_hidden_from_the_distribution(
    question_set: dict[str, Any],
) -> None:
    """Sem chave explícita, as oito NO_EVIDENCE desapareciam da contagem."""
    coverage = document_distribution(question_set)
    absent = coverage[NO_TARGET_DOCUMENT]
    assert absent["by_answerability_intent"] == {
        NO_EVIDENCE: distribution(question_set)["by_answerability_intent"][NO_EVIDENCE]
    }


def test_the_scenario_distribution_matches_the_declared_scenarios(
    question_set: dict[str, Any],
) -> None:
    composition = scenario_distribution(question_set)
    assert set(composition) == {s["scenario_id"] for s in question_set["scenarios"]}
    for scenario in question_set["scenarios"]:
        entry = composition[scenario["scenario_id"]]
        assert entry["question_count"] == len(entry["question_ids"])
        assert entry["question_count"] == scenario["question_count"]
        assert entry["scenario_type"] == scenario["scenario_type"]
        assert entry["topic"] == scenario["topic"]
        assert entry["target_document"] == scenario["target_document"]


# ---------------------------------------------------------------------------
# O protocolo é pré-registo, não resultado
# ---------------------------------------------------------------------------


def test_the_protocol_contains_no_experimental_result(
    protocol: dict[str, Any],
) -> None:
    verify_protocol_has_no_results(protocol)


def test_a_protocol_carrying_metrics_is_refused(protocol: dict[str, Any]) -> None:
    tampered = copy.deepcopy(protocol)
    tampered["aggregate"] = {"C2": {"ndcg": {"5": 0.9}}}
    with pytest.raises(ProtocolError, match="campo de resultado"):
        verify_protocol_has_no_results(tampered)


def test_a_protocol_carrying_a_nested_ranking_is_refused(
    protocol: dict[str, Any],
) -> None:
    tampered = copy.deepcopy(protocol)
    tampered["conditions"]["C2"]["ranking"] = [{"position": 1}]
    with pytest.raises(ProtocolError, match="campo de resultado"):
        verify_protocol_has_no_results(tampered)


def test_the_operational_docstring_distinguishes_prior_diagnostics() -> None:
    docstring = d4_10_sealer.__doc__ or ""
    assert "antes de existir qualquer ranking" not in docstring
    assert "antes da execução formal da D4.10b" in docstring
    assert "prior_observation_disclosure" in docstring


def test_the_scope_note_distinguishes_formal_results_from_prior_diagnostics(
    protocol: dict[str, Any],
) -> None:
    scope_note = protocol["scope_note"]
    assert "nenhum ranking observado" not in scope_note.lower()
    assert "resultados formais D4.10b" in scope_note
    assert "observações diagnósticas" in scope_note
    assert "prior_observation_disclosure" in scope_note


def test_the_temporal_precondition_applies_to_formal_d4_10b_execution(
    protocol: dict[str, Any],
) -> None:
    note = protocol["d4_10b_preconditions_note"]
    assert "primeiro embedding ou ranking" not in note
    assert "primeira geração de embeddings congelados" in note
    assert "rankings produzidos pela execução formal da D4.10b" in note
    assert "prior_observation_disclosure" in note


def test_the_protocol_declares_no_magnitude_threshold(
    protocol: dict[str, Any],
) -> None:
    """A D4.9 criou um `MATERIAL_DELTA` contra a instrução da fase.

    Nenhum ramo da decisão pode depender de a magnitude ultrapassar um número:
    `A` exige que o intervalo de confiança não inclua zero, que é uma afirmação
    sobre o sinal e a incerteza, não sobre o tamanho do efeito.
    """
    decision = protocol["decision_protocol"]
    assert decision["magnitude_threshold"] is None
    assert "CI95_lower" in decision[A_EVIDENCE_FOR_HYBRID]
    assert "CI95_upper" in decision[B_EVIDENCE_FOR_DENSE]

    # A propriedade, e não a redação: se houvesse limiar de magnitude,
    # multiplicar todos os efeitos por um fator positivo mudaria o ramo.
    for factor in (0.01, 1.0, 100.0):
        scaled = _decision_inputs(
            lower=0.004 * factor, upper=0.012 * factor, delta_recall=0.0, delta_solved=0.0
        )
        assert decide(scaled) == A_EVIDENCE_FOR_HYBRID, factor


def test_the_frozen_conditions_match_the_phases_that_measured_them(
    protocol: dict[str, Any],
) -> None:
    from app.evaluation.hybrid_rrf import FINAL_TOP_K, K_RRF, SOURCE_DEPTH, TIE_BREAK

    c2 = protocol["conditions"]["C2"]
    assert c2["k_rrf"] == K_RRF
    assert c2["source_depth"] == SOURCE_DEPTH
    assert c2["final_top_k"] == FINAL_TOP_K
    assert c2["tie_break"] == list(TIE_BREAK)


def test_the_metric_protocol_matches_the_shared_constants(
    protocol: dict[str, Any],
) -> None:
    from app.evaluation.retrieval_metrics import (
        BINARY_RELEVANCE_THRESHOLD,
        K_VALUES,
        NDCG_GAIN_BY_GRADE,
        PRIMARY_K,
    )

    metric = protocol["metric_protocol"]
    assert metric["k_values"] == list(K_VALUES)
    assert metric["primary_k"] == PRIMARY_K
    assert metric["binary_relevance_threshold"] == BINARY_RELEVANCE_THRESHOLD
    assert metric["ndcg_gain_mapping"] == {
        str(k): v for k, v in NDCG_GAIN_BY_GRADE.items()
    }


def test_the_bootstrap_resamples_scenarios_not_questions(
    protocol: dict[str, Any],
) -> None:
    """Reamostrar paráfrases duplicaria evidência estatística inexistente."""
    bootstrap = protocol["bootstrap_protocol"]
    assert bootstrap["unit"] == "scenario_id"
    assert bootstrap["replicates"] == 10000
    assert bootstrap["confidence_interval"] == 0.95
    assert isinstance(bootstrap["seed"], int)


def test_the_decision_rule_is_declared_before_any_measurement(
    protocol: dict[str, Any],
) -> None:
    decision = protocol["decision_protocol"]
    for branch in ("A_EVIDENCE_FOR_HYBRID", "B_EVIDENCE_FOR_DENSE", "C_INCONCLUSIVE"):
        assert decision[branch]


def test_the_phase_is_not_frozen_while_human_review_is_pending(
    question_set: dict[str, Any], protocol: dict[str, Any]
) -> None:
    """O congelamento é uma afirmação sobre revisão humana, não sobre digests.

    Enquanto houver validações por confirmar, o que existe é uma proposta
    auditável. Declará-la congelada seria repetir, com outra roupagem, a
    afirmação que a D4.9 não podia provar.
    """
    summary = human_review_summary(question_set)
    assert summary == protocol["human_review"]
    overlap = summary["scenario_overlap_review"]
    assert summary["freeze_ready"] is (
        summary["pending_human_review"] == 0
        and overlap["pending_or_inadmissible"] == 0
        and overlap["marked_exclude_still_present"] == 0
    )
    assert protocol["protocol_status"] == "DRAFT"


def test_the_d4_10b_preconditions_include_the_review_digest(
    protocol: dict[str, Any],
) -> None:
    """A D4.10b tem de recusar correr contra outra revisão, não só outro texto."""
    preconditions = " ".join(protocol["d4_10b_preconditions"])
    for digest in ("question_set_digest", "scenario_digest", "human_review_digest"):
        assert digest in preconditions
    assert "freeze_ready" in preconditions
    assert set(protocol["digest_scope"]) == {
        "question_set_digest",
        "scenario_digest",
        "human_review_digest",
    }


# ---------------------------------------------------------------------------
# A fase não executa nada
# ---------------------------------------------------------------------------


_PURITY_SNIPPET = """
import sys

import app.evaluation.d4_10_protocol
import scripts.seal_d4_10_protocol

for forbidden in ("sqlalchemy", "openai", "fastapi"):
    assert forbidden not in sys.modules, forbidden
print("ok")
"""


def test_the_phase_touches_no_database_no_provider_and_no_application() -> None:
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


@pytest.mark.parametrize(
    "script", ["seal_d4_10_protocol.py", "stamp_d4_10_question_set.py"]
)
def test_the_phase_commands_import_nothing_that_could_execute_the_experiment(
    script: str,
) -> None:
    """A garantia é sobre o que o módulo pode fazer, não sobre as palavras que usa.

    Procurar a cadeia ``embed`` no ficheiro apanharia o bloco que *pré-regista*
    o congelamento de embeddings — que é exatamente o que esta fase deve
    conter. O que não pode existir é a capacidade: sem importar retrievers,
    modelos de embeddings ou a fusão, o comando não tem como executar coisa
    nenhuma.
    """
    import ast

    tree = ast.parse((BACKEND_DIR / "scripts" / script).read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    forbidden = (
        "app.retrieval",
        "app.embeddings",
        "app.evaluation.hybrid_rrf",
        "app.evaluation.dense_baseline",
        "app.database",
        "openai",
        "sqlalchemy",
    )
    for module in imported:
        assert not module.startswith(forbidden), module


def test_no_relevance_grade_exists_anywhere_in_the_question_set(
    question_set: dict[str, Any],
) -> None:
    """Os graus 0/1/2 só existem depois de haver rankings para julgar."""
    payload = json.dumps(question_set, ensure_ascii=False)
    assert '"relevance"' not in payload
    assert '"judgments"' not in payload
    assert '"grade"' not in payload


def test_rebuilding_the_protocol_reproduces_its_digest(
    question_set: dict[str, Any],
    protocol: dict[str, Any],
    snapshot_binding: dict[str, Any],
) -> None:
    rebuilt = build_protocol(question_set, snapshot_binding)
    assert rebuilt["protocol_digest"] == protocol["protocol_digest"]


def test_production_retrieval_is_untouched() -> None:
    source = (BACKEND_DIR / "app" / "retrieval" / "dependencies.py").read_text(
        encoding="utf-8"
    )
    assert "PostgresLexicalRetriever()" in source
    assert "Hybrid" not in source


# ---------------------------------------------------------------------------
# Confirmacao humana: os dois campos que a descrevem tem de concordar
# ---------------------------------------------------------------------------


def _question(payload: dict[str, Any], question_id: str) -> dict[str, Any]:
    return next(q for q in payload["questions"] if q["question_id"] == question_id)


def _confirm_question(question: dict[str, Any], annotator: str = "revisor-A") -> None:
    block = validation_block_name(question)
    question["review_status"] = HUMAN_CONFIRMED
    question[block]["validation_status"] = HUMAN_CONFIRMED
    question[block]["annotator"] = annotator


def _confirm_scenario(scenario: dict[str, Any], annotator: str = "revisor-A") -> None:
    scenario[OVERLAP_REVIEW_FIELD] = {
        "status": INDEPENDENT,
        "historical_refs": [],
        "rationale": "sem parentesco com o material historico",
        "annotator": annotator,
    }


def _fully_reviewed(question_set: dict[str, Any]) -> dict[str, Any]:
    """Uma variante hipotetica com toda a revisao humana feita.

    Existe apenas para exercitar as guardas: o artefacto versionado continua
    com as cinquenta validacoes por confirmar.
    """
    variant = copy.deepcopy(question_set)
    for question in variant["questions"]:
        _confirm_question(question)
    for scenario in variant["scenarios"]:
        _confirm_scenario(scenario)
    variant.update(declared_identity(variant))
    return variant


def test_a_confirmed_review_with_a_pending_validation_block_is_refused(
    question_set: dict[str, Any],
) -> None:
    """O achado que motivou esta correção.

    Bastava marcar `review_status = HUMAN_CONFIRMED` e pôr um nome: o bloco de
    validação continuava a dizer «pendente» e o resumo contava a pergunta como
    confirmada. Dois campos que descrevem o mesmo facto não podem discordar.
    """
    tampered = copy.deepcopy(question_set)
    target = _question(tampered, "DX001")
    target["review_status"] = HUMAN_CONFIRMED
    target["answerable_validation"]["annotator"] = "Carlos"
    assert target["answerable_validation"]["validation_status"] == MACHINE_LOCATED
    with pytest.raises(ProtocolError, match="confirmação incoerente"):
        verify_question_set(tampered)


def test_a_confirmed_validation_block_with_a_pending_review_is_refused(
    question_set: dict[str, Any],
) -> None:
    """A incoerência inversa é igualmente inaceitável."""
    tampered = copy.deepcopy(question_set)
    target = _question(tampered, "DX001")
    target["answerable_validation"]["validation_status"] = HUMAN_CONFIRMED
    target["answerable_validation"]["annotator"] = "Carlos"
    with pytest.raises(ProtocolError, match="confirmação incoerente"):
        verify_question_set(tampered)


@pytest.mark.parametrize("annotator", [None, "", "   "])
def test_a_confirmation_without_a_real_name_is_refused(
    question_set: dict[str, Any], annotator: str | None
) -> None:
    """Um nome em branco não é uma assinatura."""
    tampered = copy.deepcopy(question_set)
    target = _question(tampered, "DX001")
    _confirm_question(target)
    target["answerable_validation"]["annotator"] = annotator
    with pytest.raises(ProtocolError, match="sem annotator nomeado"):
        verify_question_set(tampered)


def test_a_confirmed_answerable_without_evidence_is_refused(
    question_set: dict[str, Any],
) -> None:
    tampered = copy.deepcopy(question_set)
    target = _question(tampered, "DX001")
    _confirm_question(target)
    target["answerable_validation"]["located_evidence"] = []
    with pytest.raises(ProtocolError, match="sem evidência localizada"):
        verify_question_set(tampered)


def test_a_confirmed_answerable_without_a_rationale_is_refused(
    question_set: dict[str, Any],
) -> None:
    tampered = copy.deepcopy(question_set)
    target = _question(tampered, "DX001")
    _confirm_question(target)
    target["answerable_validation"]["rationale"] = "  "
    with pytest.raises(ProtocolError, match="sem rationale"):
        verify_question_set(tampered)


def test_a_confirmed_no_evidence_without_the_search_it_ran_is_refused(
    question_set: dict[str, Any],
) -> None:
    """Uma ausência afirmada sem registo da procura é uma afirmação sem base."""
    tampered = copy.deepcopy(question_set)
    target = next(
        q for q in tampered["questions"] if q["answerability_intent"] == NO_EVIDENCE
    )
    _confirm_question(target)
    target["no_evidence_validation"]["search_result"] = ""
    with pytest.raises(ProtocolError, match="sem search_result"):
        verify_question_set(tampered)


def test_a_pending_question_may_not_borrow_another_blocks_pending_status(
    question_set: dict[str, Any],
) -> None:
    tampered = copy.deepcopy(question_set)
    _question(tampered, "DX001")["answerable_validation"]["validation_status"] = (
        MACHINE_SEARCHED
    )
    with pytest.raises(ProtocolError, match="não é o estado pendente"):
        verify_question_set(tampered)


def test_one_unconfirmed_question_is_enough_to_block_the_freeze(
    question_set: dict[str, Any],
) -> None:
    """49 de 50 não é 50 de 50."""
    variant = _fully_reviewed(question_set)
    assert human_review_summary(variant)["freeze_ready"] is True

    last = variant["questions"][-1]
    block = validation_block_name(last)
    last["review_status"] = REVIEW_STATUSES[0]
    last[block]["validation_status"] = (
        MACHINE_LOCATED if block == "answerable_validation" else MACHINE_SEARCHED
    )
    last[block]["annotator"] = None
    summary = human_review_summary(variant)
    assert summary["human_confirmed"] == len(variant["questions"]) - 1
    assert summary["pending_human_review"] == 1
    assert summary["freeze_ready"] is False


def test_the_summary_does_not_count_an_incoherent_confirmation(
    question_set: dict[str, Any],
) -> None:
    """O resumo lê os três campos, não só o `review_status`."""
    variant = _fully_reviewed(question_set)
    _question(variant, "DX001")["answerable_validation"]["validation_status"] = (
        MACHINE_LOCATED
    )
    summary = human_review_summary(variant)
    assert summary["by_status"][HUMAN_CONFIRMED] == len(variant["questions"])
    assert summary["human_confirmed"] == len(variant["questions"]) - 1
    assert summary["freeze_ready"] is False


def test_the_versioned_question_set_has_no_confirmation_at_all(
    question_set: dict[str, Any],
) -> None:
    """Nenhuma validação foi fabricada por máquina — nem uma."""
    for question in question_set["questions"]:
        validation = question[validation_block_name(question)]
        assert question["review_status"] != HUMAN_CONFIRMED
        assert validation["validation_status"] != HUMAN_CONFIRMED
        assert validation["annotator"] is None
    for scenario in question_set["scenarios"]:
        review = scenario[OVERLAP_REVIEW_FIELD]
        assert review["status"] == PENDING_HUMAN_REVIEW
        assert review["annotator"] is None


# ---------------------------------------------------------------------------
# Independência semântica: decidida por humano, cenário a cenário
# ---------------------------------------------------------------------------


def test_every_scenario_carries_an_independence_review(
    question_set: dict[str, Any],
) -> None:
    """Todos os 32, e não apenas o que a máquina achou suspeito."""
    assert len(question_set["scenarios"]) == 32
    for scenario in question_set["scenarios"]:
        assert OVERLAP_REVIEW_FIELD in scenario, scenario["scenario_id"]


def test_a_scenario_without_an_independence_review_is_refused(
    question_set: dict[str, Any],
) -> None:
    tampered = copy.deepcopy(question_set)
    del tampered["scenarios"][0][OVERLAP_REVIEW_FIELD]
    with pytest.raises(ProtocolError, match="ausente"):
        verify_question_set(tampered)


def test_an_unknown_independence_status_is_refused(
    question_set: dict[str, Any],
) -> None:
    tampered = copy.deepcopy(question_set)
    tampered["scenarios"][0][OVERLAP_REVIEW_FIELD]["status"] = "PROVAVELMENTE_OK"
    with pytest.raises(ProtocolError, match="status de sobreposição desconhecido"):
        verify_question_set(tampered)


@pytest.mark.parametrize("status", [INDEPENDENT, RELATED_BUT_DISTINCT, EXCLUDE])
def test_no_final_independence_decision_is_valid_without_an_annotator(
    question_set: dict[str, Any], status: str
) -> None:
    tampered = copy.deepcopy(question_set)
    tampered["scenarios"][0][OVERLAP_REVIEW_FIELD] = {
        "status": status,
        "historical_refs": ["DA036"],
        "rationale": "justificação",
        "annotator": None,
    }
    with pytest.raises(ProtocolError, match="sem annotator nomeado"):
        verify_question_set(tampered)


def test_a_related_decision_without_the_questions_it_relates_to_is_refused(
    question_set: dict[str, Any],
) -> None:
    """Dizer «relacionado mas distinto» sem dizer de quê não é uma decisão."""
    tampered = copy.deepcopy(question_set)
    tampered["scenarios"][0][OVERLAP_REVIEW_FIELD] = {
        "status": RELATED_BUT_DISTINCT,
        "historical_refs": [],
        "rationale": "justificação",
        "annotator": "revisor-A",
    }
    with pytest.raises(ProtocolError, match="sem historical_refs"):
        verify_question_set(tampered)


def test_a_related_decision_without_a_rationale_is_refused(
    question_set: dict[str, Any],
) -> None:
    tampered = copy.deepcopy(question_set)
    tampered["scenarios"][0][OVERLAP_REVIEW_FIELD] = {
        "status": RELATED_BUT_DISTINCT,
        "historical_refs": ["DA036"],
        "rationale": "   ",
        "annotator": "revisor-A",
    }
    with pytest.raises(ProtocolError, match="sem rationale"):
        verify_question_set(tampered)


def test_an_independence_reference_must_name_a_historical_question(
    question_set: dict[str, Any],
) -> None:
    tampered = copy.deepcopy(question_set)
    tampered["scenarios"][0][OVERLAP_REVIEW_FIELD] = {
        "status": RELATED_BUT_DISTINCT,
        "historical_refs": ["DX002"],
        "rationale": "justificação",
        "annotator": "revisor-A",
    }
    with pytest.raises(ProtocolError, match="fora do padrão"):
        verify_question_set(tampered)


def test_a_pending_scenario_blocks_the_freeze(question_set: dict[str, Any]) -> None:
    variant = _fully_reviewed(question_set)
    assert human_review_summary(variant)["freeze_ready"] is True
    variant["scenarios"][0][OVERLAP_REVIEW_FIELD]["status"] = PENDING_HUMAN_REVIEW
    summary = human_review_summary(variant)
    assert summary["scenario_overlap_review"]["pending_or_inadmissible"] == 1
    assert summary["freeze_ready"] is False


def test_a_scenario_marked_exclude_blocks_the_freeze_until_it_is_removed(
    question_set: dict[str, Any],
) -> None:
    """Um cenário excluído sai antes da execução, não depois de ver o que deu."""
    variant = _fully_reviewed(question_set)
    scenario = variant["scenarios"][0]
    scenario[OVERLAP_REVIEW_FIELD] = {
        "status": EXCLUDE,
        "historical_refs": ["Q001"],
        "rationale": "reutiliza o mesmo facto já medido",
        "annotator": "revisor-A",
    }
    verify_question_set(variant)  # é uma decisão válida
    summary = human_review_summary(variant)
    assert summary["scenario_overlap_review"]["marked_exclude_still_present"] == 1
    assert summary["freeze_ready"] is False

    # Removido o cenário e as suas perguntas, o congelamento volta a ser possível.
    excluded = scenario["scenario_id"]
    variant["scenarios"] = [
        s for s in variant["scenarios"] if s["scenario_id"] != excluded
    ]
    variant["questions"] = [
        q for q in variant["questions"] if q["scenario_id"] != excluded
    ]
    assert human_review_summary(variant)["freeze_ready"] is True


@pytest.mark.parametrize(
    "field, value",
    [
        ("status", INDEPENDENT),
        ("historical_refs", ["DA036"]),
        ("rationale", "outra justificação"),
        ("annotator", "revisor-B"),
    ],
)
def test_changing_the_independence_review_changes_the_digest(
    question_set: dict[str, Any], field: str, value: Any
) -> None:
    """A decisão de independência é um juízo humano, e fica selada como tal."""
    tampered = copy.deepcopy(question_set)
    tampered["scenarios"][0][OVERLAP_REVIEW_FIELD][field] = value
    assert human_review_digest(tampered) != human_review_digest(question_set)
    # E não toca no conteúdo nem na composição dos cenários.
    assert question_set_digest(tampered["questions"]) == question_set_digest(
        question_set["questions"]
    )
    assert scenario_digest(tampered) == scenario_digest(question_set)


def test_sc_n04_is_not_declared_independent_by_machine(
    question_set: dict[str, Any],
) -> None:
    """O cenário que o próprio projeto assinalou continua por decidir."""
    scenario = next(
        s for s in question_set["scenarios"] if s["scenario_id"] == "SC-N04"
    )
    assert scenario[OVERLAP_REVIEW_FIELD]["status"] == PENDING_HUMAN_REVIEW
    notes = " ".join(
        question.get("overlap_review_note", "")
        for question in question_set["questions"]
        if question["scenario_id"] == "SC-N04"
    )
    assert "DA036" in notes and "DA037" in notes


# ---------------------------------------------------------------------------
# DRAFT e SEALED
# ---------------------------------------------------------------------------


def _seal(
    tmp_path: Path,
    question_set: dict[str, Any],
    snapshot_binding: dict[str, Any],
    *,
    draft: bool,
) -> tuple[int, Path]:
    question_path = tmp_path / "question-set.json"
    snapshot_path = tmp_path / "snapshot.json"
    output_path = tmp_path / "protocol.json"
    question_path.write_text(
        json.dumps(question_set, ensure_ascii=False), encoding="utf-8"
    )
    snapshot_path.write_text(
        json.dumps(snapshot_binding, ensure_ascii=False), encoding="utf-8"
    )
    argv = [
        "--question-set", str(question_path),
        "--snapshot", str(snapshot_path),
        "--output", str(output_path),
    ]
    if draft:
        argv.append("--draft")
    return seal_main(argv), output_path


def test_the_sealing_refuses_to_seal_while_the_review_is_pending(
    tmp_path: Path, question_set: dict[str, Any], snapshot_binding: dict[str, Any]
) -> None:
    """Um comando chamado «seal» que sele o que não está revisto não sela nada."""
    code, output = _seal(tmp_path, question_set, snapshot_binding, draft=False)
    assert code == EXIT_HUMAN_REVIEW_REQUIRED
    assert not output.exists()


def test_a_draft_is_produced_only_when_asked_for_by_name(
    tmp_path: Path, question_set: dict[str, Any], snapshot_binding: dict[str, Any]
) -> None:
    code, output = _seal(tmp_path, question_set, snapshot_binding, draft=True)
    assert code == EXIT_OK
    assert json.loads(output.read_text(encoding="utf-8"))["protocol_status"] == (
        PROTOCOL_DRAFT
    )


def test_a_fully_reviewed_question_set_seals_without_the_draft_flag(
    tmp_path: Path, question_set: dict[str, Any], snapshot_binding: dict[str, Any]
) -> None:
    """A guarda é sobre o estado da revisão, não sobre a opção usada."""
    variant = _fully_reviewed(question_set)
    code, output = _seal(tmp_path, variant, snapshot_binding, draft=False)
    assert code == EXIT_OK
    sealed = json.loads(output.read_text(encoding="utf-8"))
    assert sealed["protocol_status"] == PROTOCOL_SEALED
    assert sealed["human_review"]["freeze_ready"] is True
    assert sealed["protocol_digest"] == protocol_digest(sealed)


def test_the_draft_flag_does_not_downgrade_a_completed_review(
    tmp_path: Path, question_set: dict[str, Any], snapshot_binding: dict[str, Any]
) -> None:
    """`--draft` autoriza produzir com revisão pendente; não escolhe o estado."""
    variant = _fully_reviewed(question_set)
    code, output = _seal(tmp_path, variant, snapshot_binding, draft=True)
    assert code == EXIT_OK
    assert json.loads(output.read_text(encoding="utf-8"))["protocol_status"] == (
        PROTOCOL_SEALED
    )


def test_the_versioned_protocol_is_a_draft(protocol: dict[str, Any]) -> None:
    assert protocol["protocol_status"] == PROTOCOL_DRAFT
    assert protocol["human_review"]["freeze_ready"] is False
    assert protocol["human_review"]["human_confirmed"] == 0
    assert protocol["human_review"]["pending_human_review"] == 50


def test_the_d4_10b_preconditions_require_a_sealed_protocol(
    protocol: dict[str, Any],
) -> None:
    preconditions = " ".join(protocol["d4_10b_preconditions"])
    assert PROTOCOL_SEALED in preconditions
    assert "EXCLUDE" in preconditions


# ---------------------------------------------------------------------------
# Bootstrap: a implementação é o pré-registo
# ---------------------------------------------------------------------------


def test_the_quantile_matches_the_declared_method() -> None:
    """Tipo 7 (linear), o mesmo de `numpy.quantile` por omissão."""
    values = [1.0, 2.0, 3.0, 4.0]
    assert quantile(values, 0.0) == 1.0
    assert quantile(values, 1.0) == 4.0
    assert quantile(values, 0.5) == 2.5
    assert quantile(values, 0.25) == pytest.approx(1.75)
    assert quantile(values, 0.75) == pytest.approx(3.25)


def test_a_scenario_weighs_the_same_whatever_its_number_of_questions() -> None:
    """Duas paráfrases não valem duas observações."""
    one_question = {"SC-A01": [1.0], "SC-A02": [0.0]}
    two_questions = {"SC-A01": [1.0, 1.0], "SC-A02": [0.0]}
    assert scenario_macro_mean(one_question) == 0.5
    assert scenario_macro_mean(two_questions) == 0.5

    # E o mesmo cenário com deltas diferentes agrega-se primeiro dentro dele.
    assert scenario_macro_mean({"SC-A01": [1.0, 0.0], "SC-A02": [0.0]}) == 0.25


def test_the_bootstrap_draws_scenarios_not_questions() -> None:
    """Um cenário com muitas perguntas não pode dominar as réplicas."""
    deltas = {"SC-A01": [1.0] * 9, "SC-A02": [0.0]}
    drawn = set(bootstrap_replicates(deltas, replicates=200, seed=1))
    # Com duas unidades, as médias possíveis são 0, 0.5 e 1 — e nada mais.
    assert drawn <= {0.0, 0.5, 1.0}


def test_the_same_seed_reproduces_the_same_replicates() -> None:
    deltas = {"SC-A01": [0.1], "SC-A02": [-0.2], "SC-A03": [0.3]}
    first = bootstrap_replicates(deltas, replicates=50, seed=DEFAULT_SEED)
    second = bootstrap_replicates(deltas, replicates=50, seed=DEFAULT_SEED)
    other = bootstrap_replicates(deltas, replicates=50, seed=DEFAULT_SEED + 1)
    assert first == second
    assert first != other


def test_the_replicate_count_and_interval_are_the_declared_ones() -> None:
    deltas = {f"SC-A{index:02d}": [index / 10] for index in range(1, 6)}
    interval = bootstrap_interval(deltas)
    assert interval.replicates == DEFAULT_REPLICATES
    assert interval.seed == DEFAULT_SEED
    assert interval.method == "PERCENTILE"
    assert interval.confidence == 0.95
    assert interval.units == 5
    assert interval.lower <= interval.point_estimate <= interval.upper


def test_the_bootstrap_ignores_the_iteration_order_of_its_input() -> None:
    """Sem ordem fixa, a mesma seed daria sequências diferentes."""
    forward = {"SC-A01": [0.1], "SC-A02": [0.2], "SC-A03": [0.3]}
    backward = {"SC-A03": [0.3], "SC-A02": [0.2], "SC-A01": [0.1]}
    assert bootstrap_replicates(forward, replicates=100) == bootstrap_replicates(
        backward, replicates=100
    )


def test_the_protocol_declares_the_statistics_that_the_code_implements(
    protocol: dict[str, Any],
) -> None:
    """A descrição e o cálculo saem da mesma fonte, e por isso não divergem."""
    bootstrap = protocol["bootstrap_protocol"]
    assert bootstrap["unit"] == "scenario_id"
    assert bootstrap["estimator"] == "scenario_macro_mean"
    assert bootstrap["replicates"] == DEFAULT_REPLICATES
    assert bootstrap["seed"] == DEFAULT_SEED
    assert bootstrap["ci_method"] == "PERCENTILE"
    assert bootstrap["quantiles"] == [0.025, 0.975]
    assert bootstrap["quantile_method"] == "linear_hyndman_fan_type_7"
    assert bootstrap["eligible_questions"] == "apenas ANSWERABLE"


# ---------------------------------------------------------------------------
# A regra de decisão, testada antes de existirem resultados
# ---------------------------------------------------------------------------


def _decision_inputs(
    *, lower: float, upper: float, delta_recall: float, delta_solved: float
) -> DecisionInputs:
    return DecisionInputs(
        interval=ConfidenceInterval(
            point_estimate=(lower + upper) / 2,
            lower=lower,
            upper=upper,
            method="PERCENTILE",
            confidence=0.95,
            replicates=DEFAULT_REPLICATES,
            seed=DEFAULT_SEED,
            units=32,
        ),
        recall_at_5_c1=0.5,
        recall_at_5_c2=0.5 + delta_recall,
        solved_question_rate_c1=0.5,
        solved_question_rate_c2=0.5 + delta_solved,
    )


@pytest.mark.parametrize(
    "lower, upper, delta_recall, delta_solved, expected",
    [
        (0.01, 0.05, 0.0, 0.0, A_EVIDENCE_FOR_HYBRID),
        (0.01, 0.05, 0.02, 0.02, A_EVIDENCE_FOR_HYBRID),
        (0.01, 0.05, -0.01, 0.0, C_INCONCLUSIVE),
        (0.01, 0.05, 0.0, -0.01, C_INCONCLUSIVE),
        (-0.05, -0.01, 0.0, 0.0, B_EVIDENCE_FOR_DENSE),
        (-0.02, 0.03, 0.0, 0.0, C_INCONCLUSIVE),
        (0.0, 0.03, 0.0, 0.0, C_INCONCLUSIVE),
        (-0.03, 0.0, 0.0, 0.0, C_INCONCLUSIVE),
    ],
)
def test_the_decision_rule_is_total_and_deterministic(
    lower: float, upper: float, delta_recall: float, delta_solved: float, expected: str
) -> None:
    """Os seis casos do enunciado, mais os dois que tocam exatamente zero.

    Um intervalo que toca zero não é evidência: `A` exige `lower > 0` e `B`
    exige `upper < 0`, ambos estritos. Tudo o resto é `C`, sem quarta leitura.
    """
    assert decide(
        _decision_inputs(
            lower=lower, upper=upper, delta_recall=delta_recall, delta_solved=delta_solved
        )
    ) == expected


def test_no_secondary_metric_can_reclassify_the_decision() -> None:
    """MRR e companhia são discussão; não mudam o ramo."""
    inputs = _decision_inputs(lower=0.01, upper=0.05, delta_recall=0.0, delta_solved=0.0)
    assert decide(inputs) == A_EVIDENCE_FOR_HYBRID
    # A regra só lê os campos que a compõem: não há por onde entrar mais nada.
    assert set(DecisionInputs.__dataclass_fields__) == {
        "interval",
        "recall_at_5_c1",
        "recall_at_5_c2",
        "solved_question_rate_c1",
        "solved_question_rate_c2",
    }


def test_the_decision_never_falls_outside_the_three_branches() -> None:
    for lower in (-0.2, -0.01, 0.0, 0.01, 0.2):
        for upper in (lower, lower + 0.01, lower + 0.5):
            for delta in (-0.1, 0.0, 0.1):
                verdict = decide(
                    _decision_inputs(
                        lower=lower, upper=upper, delta_recall=delta, delta_solved=delta
                    )
                )
                assert verdict in {
                    A_EVIDENCE_FOR_HYBRID,
                    B_EVIDENCE_FOR_DENSE,
                    C_INCONCLUSIVE,
                }


# ---------------------------------------------------------------------------
# A folha de revisão não é a revisão
# ---------------------------------------------------------------------------


def test_the_workbook_covers_every_scenario_and_every_question() -> None:
    from scripts.build_d4_10_review_workbook import historical_questions, render

    question_set = load_json(QUESTION_SET_PATH)
    historical = historical_questions(
        [HISTORICAL_GROUND_TRUTH, DENSE_ADMISSION_DATASET]
    )
    text = render(question_set, historical)
    for scenario in question_set["scenarios"]:
        assert f"## {scenario['scenario_id']} " in text
    for question in question_set["questions"]:
        assert question["question_id"] in text
        assert question["question"] in text


def test_the_workbook_never_fills_in_a_decision() -> None:
    """Preparar a folha não é assiná-la."""
    from scripts.build_d4_10_review_workbook import historical_questions, render

    question_set = load_json(QUESTION_SET_PATH)
    before = human_review_digest(question_set)
    render(question_set, historical_questions([HISTORICAL_GROUND_TRUTH]))
    assert human_review_digest(question_set) == before
    for question in question_set["questions"]:
        assert question[validation_block_name(question)]["annotator"] is None


def test_the_workbook_pins_references_the_record_already_names() -> None:
    """A ordenação por palavras é fraca, e sabe-se onde falha.

    Em SC-N04, DA036 e DA037 — as históricas que a nota já identifica — ficam
    abaixo de cinco perguntas menos aparentadas por sobreposição de palavras.
    Uma ferramenta que deixasse cair o que o registo assinala seria pior do que
    não existir.
    """
    from scripts.build_d4_10_review_workbook import candidates_for, historical_questions

    question_set = load_json(QUESTION_SET_PATH)
    historical = historical_questions(
        [HISTORICAL_GROUND_TRUTH, DENSE_ADMISSION_DATASET]
    )
    scenario_questions = [
        q for q in question_set["questions"] if q["scenario_id"] == "SC-N04"
    ]
    shown = candidates_for(scenario_questions, historical)
    identifiers = [qid for _, qid, _, _ in shown]
    assert "DA036" in identifiers
    assert "DA037" in identifiers

    ranked = sorted((score for score, *_ in shown), reverse=True)
    pinned_scores = [score for score, qid, _, pin in shown if pin]
    assert max(pinned_scores) < ranked[0], "o teste deixaria de provar o ponto"


def test_the_workbook_command_executes_nothing() -> None:
    import ast

    tree = ast.parse(
        (BACKEND_DIR / "scripts" / "build_d4_10_review_workbook.py").read_text(
            encoding="utf-8"
        )
    )
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    forbidden = (
        "app.retrieval",
        "app.embeddings",
        "app.evaluation.hybrid_rrf",
        "app.evaluation.dense_baseline",
        "app.database",
        "openai",
        "sqlalchemy",
    )
    for module in imported:
        assert not module.startswith(forbidden), module


# ---------------------------------------------------------------------------
# Os três buracos que a segunda auditoria abriu
# ---------------------------------------------------------------------------


def test_an_invalid_scenario_decision_does_not_count_as_reviewed(
    question_set: dict[str, Any],
) -> None:
    """O resumo não pode ser mais permissivo do que a guarda.

    Um cenário `INDEPENDENT` sem anotador era recusado por
    `verify_question_set` e, ao mesmo tempo, contado como revisto pelo resumo —
    que lia só o rótulo do estado. Bastava isso para `freeze_ready` ficar
    verdadeiro sobre um conjunto que a validação recusa.
    """
    variant = _fully_reviewed(question_set)
    assert human_review_summary(variant)["freeze_ready"] is True

    variant["scenarios"][0][OVERLAP_REVIEW_FIELD]["annotator"] = None
    with pytest.raises(ProtocolError, match="sem annotator nomeado"):
        verify_question_set(variant)
    summary = human_review_summary(variant)
    assert summary["scenario_overlap_review"]["pending_or_inadmissible"] == 1
    assert summary["freeze_ready"] is False


def test_an_incoherent_question_does_not_count_as_confirmed(
    question_set: dict[str, Any],
) -> None:
    """A mesma exigência do lado das perguntas: o resumo usa a guarda."""
    variant = _fully_reviewed(question_set)
    _question(variant, "DX001")["answerable_validation"]["rationale"] = "   "
    with pytest.raises(ProtocolError, match="sem rationale"):
        verify_question_set(variant)
    summary = human_review_summary(variant)
    assert summary["human_confirmed"] == len(variant["questions"]) - 1
    assert summary["freeze_ready"] is False


def test_building_a_protocol_validates_the_question_set_itself(
    question_set: dict[str, Any], snapshot_binding: dict[str, Any]
) -> None:
    """A garantia não pode depender de por onde se entra.

    O CLI validava antes de construir; quem chamasse `build_protocol`
    diretamente obtinha um protocolo `SEALED` a partir de um conjunto inválido.
    """
    variant = _fully_reviewed(question_set)
    variant["scenarios"][0][OVERLAP_REVIEW_FIELD]["annotator"] = ""
    with pytest.raises(ProtocolError):
        build_protocol(variant, snapshot_binding)


def test_a_protocol_is_never_sealed_from_an_invalid_question_set(
    question_set: dict[str, Any], snapshot_binding: dict[str, Any]
) -> None:
    """Nenhum caminho produz SEALED sem o conjunto passar na validação."""
    for break_it in (
        lambda v: v["scenarios"][0][OVERLAP_REVIEW_FIELD].__setitem__("annotator", None),
        lambda v: _question(v, "DX001")["answerable_validation"].__setitem__(
            "validation_status", MACHINE_LOCATED
        ),
        lambda v: _question(v, "DX001")["answerable_validation"].__setitem__(
            "located_evidence", []
        ),
    ):
        variant = _fully_reviewed(question_set)
        break_it(variant)
        with pytest.raises(ProtocolError):
            build_protocol(variant, snapshot_binding)


def test_the_manifest_enumerates_exactly_the_historical_identifiers(
    question_set: dict[str, Any],
) -> None:
    """A lista contra a qual se validam as referências tem de ser a verdadeira."""
    declared = set(question_set["independence_manifest"]["historical_question_ids"])
    actual: set[str] = set()
    for path in (HISTORICAL_GROUND_TRUTH, DENSE_ADMISSION_DATASET):
        payload = load_json(path)
        actual.update(question["question_id"] for question in payload["questions"])
    assert declared == actual
    assert len(declared) == 63


def test_a_reference_to_a_question_that_does_not_exist_is_refused(
    question_set: dict[str, Any],
) -> None:
    """`Q999` tem o formato certo e não existe.

    Validar só o padrão aceitava uma justificação que aponta para o nada — e uma
    referência inexistente não sustenta uma decisão de independência.
    """
    for missing in ("Q999", "DA999"):
        tampered = copy.deepcopy(question_set)
        tampered["scenarios"][0][OVERLAP_REVIEW_FIELD] = {
            "status": RELATED_BUT_DISTINCT,
            "historical_refs": [missing],
            "rationale": "justificação",
            "annotator": "revisor-A",
        }
        with pytest.raises(ProtocolError, match="historical_ref inexistente"):
            verify_question_set(tampered)


def test_a_real_historical_reference_is_accepted(question_set: dict[str, Any]) -> None:
    """A guarda tem de deixar passar o caso legítimo, senão não prova nada."""
    variant = _fully_reviewed(question_set)
    scenario = next(s for s in variant["scenarios"] if s["scenario_id"] == "SC-N04")
    scenario[OVERLAP_REVIEW_FIELD] = {
        "status": RELATED_BUT_DISTINCT,
        "historical_refs": ["DA036", "DA037"],
        "rationale": "mesma família, ano e direção temporal distintos",
        "annotator": "revisor-A",
    }
    verify_question_set(variant)
    assert human_review_summary(variant)["freeze_ready"] is True


def test_a_no_evidence_question_may_not_enter_the_bootstrap(
    question_set: dict[str, Any],
) -> None:
    """A elegibilidade deixou de ser uma frase no protocolo.

    O bootstrap recebe um mapa já agrupado por cenário e não tem como saber que
    intenções lhe deram origem. A seleção passa por uma função que recusa —
    porque nDCG, Recall e MRR não estão definidos sem alvo relevante, e o número
    que saísse daí não significaria nada.
    """
    absent = next(
        q["question_id"]
        for q in question_set["questions"]
        if q["answerability_intent"] == NO_EVIDENCE
    )
    present = next(
        q["question_id"]
        for q in question_set["questions"]
        if q["answerability_intent"] == ANSWERABLE
    )
    with pytest.raises(StatisticsError, match="NO_EVIDENCE"):
        eligible_scenario_deltas(question_set, {present: 0.1, absent: 0.1})


def test_the_eligible_selection_keeps_every_answerable_and_nothing_else(
    question_set: dict[str, Any],
) -> None:
    answerable = [
        q for q in question_set["questions"] if q["answerability_intent"] == ANSWERABLE
    ]
    grouped = eligible_scenario_deltas(
        question_set, {q["question_id"]: 0.0 for q in answerable}
    )
    assert sum(len(values) for values in grouped.values()) == len(answerable)
    assert set(grouped) == {q["scenario_id"] for q in answerable}
    # Nenhum cenário NO_EVIDENCE sobrevive à seleção.
    assert not [scenario for scenario in grouped if scenario.startswith("SC-N")]


def test_an_unknown_question_id_is_refused_by_the_selection(
    question_set: dict[str, Any],
) -> None:
    with pytest.raises(StatisticsError, match="fora do conjunto"):
        eligible_scenario_deltas(question_set, {"DX999": 0.1})


def test_the_protocol_names_what_enforces_the_eligibility(
    protocol: dict[str, Any],
) -> None:
    """Declarar «apenas ANSWERABLE» sem dizer quem o impõe é só uma intenção."""
    bootstrap = protocol["bootstrap_protocol"]
    assert "eligible_scenario_deltas" in bootstrap["eligibility_is_enforced_by"]


def test_the_primary_analysis_remains_intact_and_includes_sc_a16(
    question_set: dict[str, Any], protocol: dict[str, Any]
) -> None:
    answerable = [
        question
        for question in question_set["questions"]
        if question["answerability_intent"] == ANSWERABLE
    ]
    primary = eligible_scenario_deltas(
        question_set,
        {question["question_id"]: 0.0 for question in answerable},
    )
    assert len(answerable) == 42
    assert sum(map(len, primary.values())) == 42
    assert primary["SC-A16"] == [0.0, 0.0]
    assert protocol["bootstrap_protocol"]["primary_analysis"] == {
        "answerable_question_count": 42,
        "includes_scenario": "SC-A16",
        "official_scientific_decision": True,
    }


def test_the_sensitivity_excludes_only_sc_a16_and_keeps_no_evidence_out(
    question_set: dict[str, Any],
) -> None:
    answerable_deltas = {
        question["question_id"]: 0.0
        for question in question_set["questions"]
        if question["answerability_intent"] == ANSWERABLE
    }
    primary = eligible_scenario_deltas(question_set, answerable_deltas)
    sensitivity = sensitivity_scenario_deltas_without_sc_a16(
        question_set, answerable_deltas
    )
    assert sum(map(len, sensitivity.values())) == 40
    assert set(sensitivity) == set(primary) - {"SC-A16"}
    assert "SC-A16" not in sensitivity
    assert not [scenario for scenario in sensitivity if scenario.startswith("SC-N")]

    no_evidence_id = next(
        question["question_id"]
        for question in question_set["questions"]
        if question["answerability_intent"] == NO_EVIDENCE
    )
    with pytest.raises(StatisticsError, match="NO_EVIDENCE"):
        sensitivity_scenario_deltas_without_sc_a16(
            question_set, {**answerable_deltas, no_evidence_id: 0.0}
        )


def test_the_sensitivity_reuses_the_primary_statistical_contract(
    protocol: dict[str, Any],
) -> None:
    primary = protocol["bootstrap_protocol"]
    shadow = protocol["sensitivity_analysis_protocol"]
    assert shadow["answerable_question_count"] == 40
    assert shadow["metric_contract"] == "o mesmo da analise primaria"
    assert shadow["estimator"] == primary["estimator"]
    assert shadow["bootstrap"]["replicates"] == primary["replicates"]
    assert shadow["bootstrap"]["seed"] == primary["seed"]
    assert shadow["bootstrap"]["confidence_interval"] == primary["confidence_interval"]
    assert shadow["decision_implementation"].endswith("::decide")


def test_primary_and_shadow_call_the_same_decide_function(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    primary_inputs = _decision_inputs(
        lower=0.01, upper=0.05, delta_recall=0.0, delta_solved=0.0
    )
    sensitivity_inputs = _decision_inputs(
        lower=-0.01, upper=0.03, delta_recall=0.0, delta_solved=0.0
    )
    original_decide = d4_10_statistics.decide
    calls: list[DecisionInputs] = []

    def tracked_decide(inputs: DecisionInputs) -> str:
        calls.append(inputs)
        return original_decide(inputs)

    monkeypatch.setattr(d4_10_statistics, "decide", tracked_decide)
    result = build_decision_result(primary_inputs, sensitivity_inputs)
    assert calls == [primary_inputs, sensitivity_inputs]
    assert result == {
        "primary_decision": A_EVIDENCE_FOR_HYBRID,
        "sensitivity_shadow_decision": C_INCONCLUSIVE,
        "official_decision": A_EVIDENCE_FOR_HYBRID,
    }


@pytest.mark.parametrize("shadow", [None, "missing"])
def test_the_shadow_decision_is_mandatory(shadow: str | None) -> None:
    result: dict[str, Any] = {
        "primary_decision": A_EVIDENCE_FOR_HYBRID,
        "official_decision": A_EVIDENCE_FOR_HYBRID,
    }
    if shadow != "missing":
        result["sensitivity_shadow_decision"] = shadow
    with pytest.raises(StatisticsError, match="obrigatórias ausentes ou nulas"):
        validate_decision_result(result)
