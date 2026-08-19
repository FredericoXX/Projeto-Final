"""Admissão e abstenção da condição densa: módulo puro, barreira e artefactos (D4.8.2).

Cinco grupos:

- as **regras de decisão** — o que cada regra admite, o que faz com uma
  recuperação vazia e o que faz com uma margem indefinida;
- as **métricas** de admissão e de qualidade pós-admissão, incluindo a
  distinção entre taxa indefinida e taxa zero;
- a **barreira de leakage** — a projeção DEV, o manifesto selado e a prova de
  que apontar a calibração ao dataset completo levanta erro em vez de calibrar;
- os **vetores congelados** e os digests, que têm de fechar sobre os ficheiros
  realmente escritos;
- os **artefactos versionados** — dataset, split, projeção DEV, protocolo,
  calibração e held-out —, que têm de ser coerentes entre si e não transportar
  texto documental.

Nenhum teste contacta a rede, o PostgreSQL ou o fornecedor de embeddings.
"""

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from app.embeddings.base import EmbeddingError, EmbeddingIdentity
from app.evaluation.dense_admission import (
    ABSTAIN,
    ADMIT,
    ANSWERABLE,
    DEV,
    DEV_PROJECTION_CONTRACT,
    EXECUTION_DIGEST_SCOPE,
    HELD_OUT,
    NO_EVIDENCE,
    RESULT_DIGEST_SCOPE,
    RULE_R0,
    RULE_R1,
    RULE_R2,
    AdmissionPolicy,
    AdmissionSignals,
    LeakageError,
    admission_metrics,
    alternating_split_assignments,
    artefact_digests,
    candidate_policies,
    candidate_rules_digest,
    decide,
    evaluate_policy,
    execution_projection,
    frozen_vectors_digest,
    heldout_labels_digest,
    heldout_manifest,
    heldout_manifest_digest,
    load_calibration_questions,
    parameter_space_digest,
    protocol_digest,
    question_dataset_digest,
    questions_of_split,
    result_projection,
    select_policy,
    selection_policy_digest,
    split_digest,
    verify_dev_projection,
    verify_split_by_scenario,
)
from app.evaluation.dense_admission_vectors import (
    FrozenQuestionEmbeddings,
    content_sha256,
    vector_digest,
    verify_frozen_vector_artefact,
    verify_frozen_vectors,
)
from scripts.evaluate_retrieval_experiment import ExperimentError

DOCS = Path(__file__).resolve().parents[2] / "docs" / "evaluation"
DATASET_PATH = DOCS / "dense-admission-dataset-v1.json"
SPLIT_PATH = DOCS / "dense-admission-split-v1.json"
DEV_PATH = DOCS / "dense-admission-dev-v1.json"
DEV_VECTORS_PATH = DOCS / "dense-admission-dev-vectors-v1.json"
PROTOCOL_PATH = DOCS / "dense-admission-protocol-v1.json"
VECTORS_PATH = DOCS / "dense-admission-frozen-vectors-v1.json"
CALIBRATION_PATH = DOCS / "dense-admission-calibration-v1.json"
HELDOUT_PATH = DOCS / "dense-admission-heldout-v1.json"


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def dataset() -> dict[str, Any]:
    return _load(DATASET_PATH)


@pytest.fixture(scope="module")
def split() -> dict[str, Any]:
    return _load(SPLIT_PATH)


@pytest.fixture(scope="module")
def dev_projection() -> dict[str, Any]:
    return _load(DEV_PATH)


@pytest.fixture(scope="module")
def protocol() -> dict[str, Any]:
    return _load(PROTOCOL_PATH)


@pytest.fixture(scope="module")
def vectors() -> dict[str, Any]:
    return _load(VECTORS_PATH)


@pytest.fixture(scope="module")
def dev_vectors() -> dict[str, Any]:
    return _load(DEV_VECTORS_PATH)


@pytest.fixture(scope="module")
def calibration() -> dict[str, Any]:
    return _load(CALIBRATION_PATH)


@pytest.fixture(scope="module")
def heldout() -> dict[str, Any]:
    return _load(HELDOUT_PATH)


# ---------------------------------------------------------------------------
# Regras de decisão
# ---------------------------------------------------------------------------


def test_r0_admits_whenever_there_is_anything_to_admit() -> None:
    policy = AdmissionPolicy(rule=RULE_R0)
    assert decide(policy, AdmissionSignals(top1=0.1, top2=0.09, returned=5)) == ADMIT


def test_an_empty_retrieval_abstains_under_every_rule() -> None:
    signals = AdmissionSignals(top1=None, top2=None, returned=0)
    for policy in (
        AdmissionPolicy(rule=RULE_R0),
        AdmissionPolicy(rule=RULE_R1, min_top1=0.6),
        AdmissionPolicy(rule=RULE_R2, min_top1=0.6, min_margin=0.05),
    ):
        assert decide(policy, signals) == ABSTAIN


def test_r1_compares_only_the_top_score() -> None:
    policy = AdmissionPolicy(rule=RULE_R1, min_top1=0.6)
    assert decide(policy, AdmissionSignals(top1=0.6, top2=0.6, returned=5)) == ADMIT
    assert decide(policy, AdmissionSignals(top1=0.599, top2=0.1, returned=5)) == ABSTAIN


def test_r2_requires_both_the_threshold_and_the_margin() -> None:
    policy = AdmissionPolicy(rule=RULE_R2, min_top1=0.6, min_margin=0.05)
    assert decide(policy, AdmissionSignals(top1=0.7, top2=0.6, returned=5)) == ADMIT
    assert decide(policy, AdmissionSignals(top1=0.7, top2=0.68, returned=5)) == ABSTAIN


def test_an_undefined_margin_does_not_satisfy_r2() -> None:
    """Um único resultado não é uma margem infinita: é a ausência de margem."""
    policy = AdmissionPolicy(rule=RULE_R2, min_top1=0.6, min_margin=0.05)
    assert decide(policy, AdmissionSignals(top1=0.9, top2=None, returned=1)) == ABSTAIN


def test_a_policy_cannot_carry_parameters_its_rule_does_not_use() -> None:
    with pytest.raises(ValueError):
        AdmissionPolicy(rule=RULE_R0, min_top1=0.6)
    with pytest.raises(ValueError):
        AdmissionPolicy(rule=RULE_R1, min_top1=0.6, min_margin=0.05)
    with pytest.raises(ValueError):
        AdmissionPolicy(rule=RULE_R2, min_top1=0.6)


# ---------------------------------------------------------------------------
# Métricas
# ---------------------------------------------------------------------------


def _signal(
    question_id: str,
    label: str,
    top1: float | None,
    top2: float | None,
    grades: tuple[int, ...],
) -> dict[str, Any]:
    return {
        "question_id": question_id,
        "scenario_id": f"SC-{question_id}",
        "label": label,
        "returned": 0 if top1 is None else len(grades),
        "top1": top1,
        "top2": top2,
        "grades": list(grades),
        "judged_grades": sorted(grades, reverse=True),
    }


def test_abstention_is_correct_or_false_according_to_the_label() -> None:
    signals = [
        _signal("Q1", ANSWERABLE, 0.4, 0.3, (2, 0, 0)),
        _signal("Q2", NO_EVIDENCE, 0.4, 0.3, (0, 0, 0)),
    ]
    _, metrics = evaluate_policy(AdmissionPolicy(rule=RULE_R1, min_top1=0.5), signals)
    admission = metrics["admission"]
    assert admission["false_abstention_rate"] == 1.0
    assert admission["correct_abstention_rate"] == 1.0
    assert admission["coverage"] == 0.0


def test_a_rate_over_zero_cases_is_undefined_and_not_zero() -> None:
    """Escrever 0.0 convidaria a ler «nunca aconteceu» onde não houve casos."""
    metrics = admission_metrics(
        evaluate_policy(
            AdmissionPolicy(rule=RULE_R0),
            [_signal("Q1", ANSWERABLE, 0.9, 0.1, (2,))],
        )[0]
    )
    assert metrics["correct_abstention_rate"] is None
    assert metrics["false_abstention_rate"] == 0.0


def test_ranking_metrics_are_measured_only_on_admitted_answerable() -> None:
    signals = [
        _signal("Q1", ANSWERABLE, 0.9, 0.1, (2, 0, 0)),
        _signal("Q2", NO_EVIDENCE, 0.9, 0.1, (0, 0, 0)),
        _signal("Q3", ANSWERABLE, 0.1, 0.05, (2, 0, 0)),
    ]
    _, metrics = evaluate_policy(AdmissionPolicy(rule=RULE_R1, min_top1=0.5), signals)
    assert metrics["retrieval"]["measured_questions"] == 1
    assert metrics["retrieval"]["mrr"] == 1.0
    # Q2 é admitida e conta para o ruído, mas não para recall nem nDCG.
    assert metrics["retrieval"]["returned_total"] == 6


def test_an_abstained_question_returns_nothing_and_contributes_no_grades() -> None:
    signals = [_signal("Q1", ANSWERABLE, 0.1, 0.05, (2, 2, 2))]
    outcomes, metrics = evaluate_policy(
        AdmissionPolicy(rule=RULE_R1, min_top1=0.5), signals
    )
    assert outcomes[0].grades == ()
    assert metrics["retrieval"]["returned_total"] == 0


# ---------------------------------------------------------------------------
# Seleção pré-registada
# ---------------------------------------------------------------------------


def _entry(rule: str, top1: float | None, margin: float | None, correct: float, false: float):
    return {
        "policy": {"rule": rule, "min_top1": top1, "min_margin": margin},
        "admission": {
            "correct_abstention_rate": correct,
            "false_abstention_rate": false,
        },
    }


def test_selection_excludes_everything_over_the_budget() -> None:
    entries = [
        _entry(RULE_R0, None, None, 0.0, 0.0),
        _entry(RULE_R1, 0.9, None, 1.0, 0.9),
    ]
    selection = select_policy(entries, 0.2)
    assert selection["eligible"] == 1
    assert selection["selected_policy"]["rule"] == RULE_R0


def test_ties_are_broken_towards_the_simpler_rule() -> None:
    entries = [
        _entry(RULE_R2, 0.6, 0.05, 0.5, 0.1),
        _entry(RULE_R1, 0.6, None, 0.5, 0.1),
    ]
    selection = select_policy(entries, 0.2)
    assert selection["selected_policy"]["rule"] == RULE_R1


def test_the_candidate_set_is_derived_from_the_parameter_space(
    protocol: dict[str, Any],
) -> None:
    policies = candidate_policies(protocol["parameter_space"])
    assert len(policies) == protocol["candidate_policies"]["total"]
    assert sum(1 for p in policies if p.rule == RULE_R0) == protocol["candidate_policies"]["R0"]
    assert sum(1 for p in policies if p.rule == RULE_R1) == protocol["candidate_policies"]["R1"]
    assert sum(1 for p in policies if p.rule == RULE_R2) == protocol["candidate_policies"]["R2"]


# ---------------------------------------------------------------------------
# Barreira de leakage
# ---------------------------------------------------------------------------


def test_the_split_never_puts_a_scenario_on_both_sides(dataset: dict[str, Any]) -> None:
    assignments = dataset["split_rule"]["assignments"]
    assert verify_split_by_scenario(dataset["questions"], assignments) == ()


def test_paraphrases_of_the_same_scenario_stay_together(dataset: dict[str, Any]) -> None:
    """É a forma de leakage que mais facilmente passaria despercebida."""
    assignments = dataset["split_rule"]["assignments"]
    dev = {q["scenario_id"] for q in questions_of_split(dataset["questions"], assignments, DEV)}
    held = {
        q["scenario_id"]
        for q in questions_of_split(dataset["questions"], assignments, HELD_OUT)
    }
    assert dev & held == set()


def test_the_calibration_refuses_the_full_dataset(
    dataset: dict[str, Any], split: dict[str, Any]
) -> None:
    """A promessa da fase, como comportamento e não como intenção."""
    with pytest.raises(LeakageError):
        load_calibration_questions(dataset, split["heldout_manifest"])


def test_the_calibration_refuses_a_projection_carrying_a_sealed_question(
    dev_projection: dict[str, Any], split: dict[str, Any], dataset: dict[str, Any]
) -> None:
    manifest = split["heldout_manifest"]
    sealed_id = manifest["question_ids"][0]
    sealed = next(q for q in dataset["questions"] if q["question_id"] == sealed_id)
    tampered = copy.deepcopy(dev_projection)
    tampered["questions"].append(sealed)
    with pytest.raises(LeakageError):
        load_calibration_questions(tampered, manifest)


def test_the_dev_projection_file_does_not_contain_a_single_sealed_identifier(
    split: dict[str, Any],
) -> None:
    """Lido como texto: nem o identificador da pergunta, nem o do cenário."""
    raw = DEV_PATH.read_text(encoding="utf-8")
    for question_id in split["heldout_manifest"]["question_ids"]:
        assert question_id not in raw
    for scenario_id in split["heldout_manifest"]["scenario_ids"]:
        assert scenario_id not in raw


def test_the_dev_projection_does_not_carry_the_split_assignments(
    dev_projection: dict[str, Any], split: dict[str, Any]
) -> None:
    assert "split_rule" not in dev_projection
    assert "scenarios" not in dev_projection
    assert verify_dev_projection(dev_projection, split["heldout_manifest"]) == ()


def test_the_calibration_command_has_no_dataset_argument() -> None:
    from scripts.calibrate_dense_admission import build_parser

    options = {action.dest for action in build_parser()._actions}
    assert "dataset" not in options
    assert "dev" in options
    assert "frozen_vectors" not in options
    assert "dev_vectors" in options


def test_the_manifest_identifies_the_sealed_set_without_revealing_it(
    split: dict[str, Any],
) -> None:
    manifest = split["heldout_manifest"]
    assert set(manifest) == {
        "manifest_version",
        "question_count",
        "question_ids",
        "scenario_ids",
        "labels_digest",
    }
    assert ANSWERABLE not in json.dumps(manifest)
    assert NO_EVIDENCE not in json.dumps(manifest)


# ---------------------------------------------------------------------------
# Vetores congelados
# ---------------------------------------------------------------------------


def test_the_frozen_vectors_cover_every_question(
    dataset: dict[str, Any], vectors: dict[str, Any]
) -> None:
    identity = EmbeddingIdentity(**vectors["embedding"])
    assert verify_frozen_vectors(vectors["vectors"], dataset["questions"], identity) == ()


def test_an_edited_question_invalidates_its_frozen_vector(
    dataset: dict[str, Any], vectors: dict[str, Any]
) -> None:
    """O caso em que tudo parece consistente e o vetor descreve outro texto."""
    identity = EmbeddingIdentity(**vectors["embedding"])
    questions = copy.deepcopy(dataset["questions"])
    questions[0]["question"] = questions[0]["question"] + "?"
    problems = verify_frozen_vectors(vectors["vectors"], questions, identity)
    assert any("content_sha256" in problem for problem in problems)


def test_a_tampered_vector_is_detected(vectors: dict[str, Any]) -> None:
    identity = EmbeddingIdentity(**vectors["embedding"])
    entries = copy.deepcopy(vectors["vectors"])
    entries[0]["vector"][0] = entries[0]["vector"][0] + 1.0
    problems = verify_frozen_vectors(entries, [], identity)
    assert any("vector_digest" in problem for problem in problems)


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        (lambda entries: entries[0].pop("dimension"), "missing 'dimension'"),
        (lambda entries: entries[0]["vector"].pop(), "declared dimension"),
        (lambda entries: entries.pop(), "no frozen vector"),
        (lambda entries: entries[0].__setitem__("model", "mixed-model"), "mix"),
    ],
)
def test_frozen_vector_guards_cover_required_mutations(
    dataset: dict[str, Any],
    vectors: dict[str, Any],
    mutation: Any,
    expected: str,
) -> None:
    identity = EmbeddingIdentity(**vectors["embedding"])
    entries = copy.deepcopy(vectors["vectors"])
    mutation(entries)
    problems = verify_frozen_vectors(entries, dataset["questions"], identity)
    assert any(expected in problem for problem in problems)


def test_recomputed_per_vector_digest_cannot_bypass_the_global_digest(
    dataset: dict[str, Any], vectors: dict[str, Any]
) -> None:
    identity = EmbeddingIdentity(**vectors["embedding"])
    tampered = copy.deepcopy(vectors)
    tampered["vectors"][0]["vector"][0] += 1.0
    tampered["vectors"][0]["vector_digest"] = vector_digest(
        tampered["vectors"][0]["vector"]
    )
    assert verify_frozen_vectors(
        tampered["vectors"], dataset["questions"], identity
    ) == ()
    problems = verify_frozen_vector_artefact(
        tampered,
        dataset["questions"],
        identity,
        expected_digest=vectors["frozen_vectors_digest"],
    )
    assert any("frozen_vectors_digest" in problem for problem in problems)


def test_dev_vector_projection_contains_only_dev_and_has_its_own_digest(
    dataset: dict[str, Any],
    split: dict[str, Any],
    dev_projection: dict[str, Any],
    dev_vectors: dict[str, Any],
) -> None:
    identity = EmbeddingIdentity(**dev_vectors["embedding"])
    dev_ids = {str(question["question_id"]) for question in dev_projection["questions"]}
    vector_ids = {str(vector["question_id"]) for vector in dev_vectors["vectors"]}
    held_ids = set(split["heldout_manifest"]["question_ids"])
    assert vector_ids == dev_ids
    assert vector_ids.isdisjoint(held_ids)
    assert verify_frozen_vector_artefact(
        dev_vectors,
        dev_projection["questions"],
        identity,
        digest_field="dev_vectors_digest",
        expected_digest=split["dev"]["vectors_digest"],
    ) == ()


def test_frozen_embeddings_refuse_a_text_they_do_not_know(
    vectors: dict[str, Any],
) -> None:
    identity = EmbeddingIdentity(**vectors["embedding"])
    model = FrozenQuestionEmbeddings(vectors["vectors"], identity)
    with pytest.raises(EmbeddingError):
        model.embed(["uma pergunta que nunca foi congelada"])


def test_frozen_embeddings_look_the_vector_up_by_the_text(
    dataset: dict[str, Any], vectors: dict[str, Any]
) -> None:
    identity = EmbeddingIdentity(**vectors["embedding"])
    model = FrozenQuestionEmbeddings(vectors["vectors"], identity)
    question = dataset["questions"][0]
    entry = next(
        v for v in vectors["vectors"] if v["question_id"] == question["question_id"]
    )
    assert entry["content_sha256"] == content_sha256(question["question"])
    assert model.embed([question["question"]])[0] == tuple(entry["vector"])


def test_the_vector_digest_matches_the_stored_components(vectors: dict[str, Any]) -> None:
    entry = vectors["vectors"][0]
    assert vector_digest(entry["vector"]) == entry["vector_digest"]


# ---------------------------------------------------------------------------
# Artefactos versionados
# ---------------------------------------------------------------------------


def test_the_dataset_labels_are_consistent_with_the_judgments(
    dataset: dict[str, Any],
) -> None:
    """Duas contradições que invalidariam a experiência inteira."""
    for question in dataset["questions"]:
        grades = [j["relevance"] for j in question["judgments"]]
        if question["label"] == ANSWERABLE:
            assert 2 in grades, question["question_id"]
        else:
            assert 2 not in grades, question["question_id"]
            assert question["no_evidence_validation"]["validation_status"] == (
                "CONFIRMED_ABSENT"
            )


def test_every_no_evidence_question_records_how_absence_was_verified(
    dataset: dict[str, Any],
) -> None:
    for question in dataset["questions"]:
        if question["label"] != NO_EVIDENCE:
            continue
        validation = question["no_evidence_validation"]
        assert validation["validation_method"] == (
            "normalised_full_corpus_term_search_and_reading"
        )
        assert validation["note"].strip()


def test_the_split_artefact_matches_the_dataset(
    dataset: dict[str, Any], split: dict[str, Any]
) -> None:
    assignments = dataset["split_rule"]["assignments"]
    assert split["assignments"] == assignments
    assert split["split_digest"] == split_digest(
        assignments, dataset["split_rule"]["split_version"]
    )
    assert split["dataset_questions_digest"] == question_dataset_digest(
        dataset["questions"]
    )
    assert split["frozen_vectors_digest"] == frozen_vectors_digest(
        _load(VECTORS_PATH)["vectors"]
    )


def test_the_split_matches_the_declared_alternating_algorithm(
    dataset: dict[str, Any], split: dict[str, Any]
) -> None:
    assert dataset["split_rule"]["rule"] == (
        "stratified_alternating_over_sorted_scenario_id"
    )
    assert alternating_split_assignments(dataset["scenarios"]) == split["assignments"]


def test_the_sealed_manifest_matches_its_digests(
    dataset: dict[str, Any], split: dict[str, Any]
) -> None:
    assignments = dataset["split_rule"]["assignments"]
    manifest = heldout_manifest(
        dataset["questions"], assignments, split["heldout_manifest"]["manifest_version"]
    )
    assert manifest == split["heldout_manifest"]
    assert heldout_manifest_digest(manifest) == split["heldout_manifest_digest"]
    held = questions_of_split(dataset["questions"], assignments, HELD_OUT)
    assert heldout_labels_digest(held) == manifest["labels_digest"]


def test_the_dev_projection_matches_the_dataset(
    dataset: dict[str, Any], dev_projection: dict[str, Any], split: dict[str, Any]
) -> None:
    assignments = dataset["split_rule"]["assignments"]
    dev = questions_of_split(dataset["questions"], assignments, DEV)
    assert dev_projection["contract"] == DEV_PROJECTION_CONTRACT
    assert dev_projection["split_scope"] == DEV
    assert [q["question_id"] for q in dev_projection["questions"]] == [
        q["question_id"] for q in dev
    ]
    assert dev_projection["dev_questions_digest"] == question_dataset_digest(dev)
    assert dev_projection["dev_questions_digest"] == split["dev"]["questions_digest"]


def test_the_protocol_matches_its_own_digests(protocol: dict[str, Any]) -> None:
    rules = [rule["rule"] for rule in protocol["candidate_rules"]]
    assert protocol["candidate_rules_digest"] == candidate_rules_digest(rules)
    assert protocol["parameter_space_digest"] == parameter_space_digest(
        protocol["parameter_space"]
    )
    assert protocol["selection_policy_digest"] == selection_policy_digest(
        protocol["selection"]
    )
    assert protocol["protocol_digest"] == protocol_digest(protocol)


def test_protocol_binds_the_complete_sealed_identity(
    protocol: dict[str, Any], split: dict[str, Any]
) -> None:
    expected = {
        "dataset_version": split["dataset_version"],
        "dataset_questions_digest": split["dataset_questions_digest"],
        "scenario_digest": split["scenario_digest"],
        "split_version": split["split_version"],
        "split_digest": split["split_digest"],
        "dev_questions_digest": split["dev"]["questions_digest"],
        "dev_vectors_digest": split["dev"]["vectors_digest"],
        "heldout_manifest_digest": split["heldout_manifest_digest"],
        "frozen_vectors_digest": split["frozen_vectors_digest"],
    }
    assert {field: protocol[field] for field in expected} == expected


def test_split_guard_rejects_tampered_assignments_even_with_replaced_digest(
    protocol: dict[str, Any], split: dict[str, Any]
) -> None:
    from scripts.calibrate_dense_admission import verify_split_integrity

    tampered = copy.deepcopy(split)
    scenario_id = next(iter(tampered["assignments"]))
    tampered["assignments"][scenario_id] = HELD_OUT
    tampered["split_digest"] = "0" * 64
    with pytest.raises(ExperimentError):
        verify_split_integrity(tampered, protocol)


def test_split_guard_rejects_a_recomputed_but_unregistered_split(
    protocol: dict[str, Any], split: dict[str, Any]
) -> None:
    from scripts.calibrate_dense_admission import verify_split_integrity

    tampered = copy.deepcopy(split)
    scenario_id = next(iter(tampered["assignments"]))
    tampered["assignments"][scenario_id] = HELD_OUT
    tampered["split_digest"] = split_digest(
        tampered["assignments"], tampered["split_version"]
    )
    with pytest.raises(ExperimentError):
        verify_split_integrity(tampered, protocol)


def test_heldout_manifest_commitment_mutation_is_rejected(
    split: dict[str, Any]
) -> None:
    from scripts.evaluate_dense_admission_heldout import verify_sealed_set

    manifest = copy.deepcopy(split["heldout_manifest"])
    manifest["labels_digest"] = "0" * 64
    held_questions = [
        question
        for question in _load(DATASET_PATH)["questions"]
        if question["question_id"] in manifest["question_ids"]
    ]
    with pytest.raises(ExperimentError):
        verify_sealed_set(held_questions, manifest)


def test_heldout_dataset_guard_rejects_assignment_tampering(
    dataset: dict[str, Any], split: dict[str, Any], protocol: dict[str, Any]
) -> None:
    from scripts.evaluate_dense_admission_heldout import verify_dataset_integrity

    tampered = copy.deepcopy(dataset)
    scenario_id = next(iter(tampered["split_rule"]["assignments"]))
    tampered["split_rule"]["assignments"][scenario_id] = HELD_OUT
    with pytest.raises(ExperimentError):
        verify_dataset_integrity(tampered, split, protocol)


def test_editing_the_protocol_changes_its_digest(protocol: dict[str, Any]) -> None:
    tampered = copy.deepcopy(protocol)
    tampered["selection"]["max_false_abstention_rate"] = 0.9
    assert protocol_digest(tampered) != protocol["protocol_digest"]


def test_the_calibration_matches_its_own_digests(calibration: dict[str, Any]) -> None:
    result, execution = artefact_digests(calibration)
    assert result == calibration["result_digest"]
    assert execution == calibration["execution_digest"]
    assert calibration["result_digest_scope"] == RESULT_DIGEST_SCOPE
    assert calibration["execution_digest_scope"] == EXECUTION_DIGEST_SCOPE


def test_the_heldout_artefact_matches_its_own_digests(heldout: dict[str, Any]) -> None:
    result, execution = artefact_digests(heldout)
    assert result == heldout["result_digest"]
    assert execution == heldout["execution_digest"]


def test_similarity_drift_alone_does_not_change_the_result_digest(
    heldout: dict[str, Any],
) -> None:
    """A correção da D4.8.1: o digest canónico descreve o resultado, não a execução."""
    drifted = copy.deepcopy(heldout)
    for signal in drifted["question_signals"]:
        if signal["top1"] is not None:
            signal["top1"] = round(signal["top1"] + 1e-6, 9)
    assert result_projection(drifted) == result_projection(heldout)
    assert artefact_digests(drifted)[0] == heldout["result_digest"]
    assert artefact_digests(drifted)[1] != heldout["execution_digest"]


def test_a_flipped_decision_does_change_the_result_digest(
    heldout: dict[str, Any],
) -> None:
    flipped = copy.deepcopy(heldout)
    question_id = next(iter(flipped["decisions"]))
    flipped["decisions"][question_id] = (
        ABSTAIN if flipped["decisions"][question_id] == ADMIT else ADMIT
    )
    assert artefact_digests(flipped)[0] != heldout["result_digest"]


def test_the_execution_projection_only_drops_the_timestamp(
    calibration: dict[str, Any],
) -> None:
    projection = execution_projection(calibration)
    assert "executed_at" not in projection
    assert "execution_digest" not in projection
    assert "result_digest" in projection


def test_the_calibration_never_measured_the_held_out_set(
    calibration: dict[str, Any], split: dict[str, Any]
) -> None:
    measured = {signal["question_id"] for signal in calibration["question_signals"]}
    sealed = set(split["heldout_manifest"]["question_ids"])
    assert measured & sealed == set()
    assert calibration["split_scope"] == DEV
    assert calibration["questions_evaluated"] == split["counts"]["questions"][DEV]["total"]


def test_the_heldout_evaluation_used_the_frozen_policy_unchanged(
    calibration: dict[str, Any], heldout: dict[str, Any]
) -> None:
    assert calibration["policy_frozen"] is True
    assert heldout["frozen_policy"] == calibration["selected_policy"]
    assert heldout["calibration_result_digest"] == calibration["result_digest"]


def test_the_heldout_evaluation_measured_exactly_the_sealed_set(
    heldout: dict[str, Any], split: dict[str, Any]
) -> None:
    measured = {signal["question_id"] for signal in heldout["question_signals"]}
    assert measured == set(split["heldout_manifest"]["question_ids"])
    assert heldout["heldout_labels_digest"] == split["heldout_manifest"]["labels_digest"]


def test_the_heldout_command_has_no_parameter_space() -> None:
    """Não recalibra porque não tem com que recalibrar."""
    import scripts.evaluate_dense_admission_heldout as runner

    source = Path(runner.__file__).read_text(encoding="utf-8")
    assert "candidate_policies" not in source
    assert "select_policy" not in source
    assert "parameter_space" not in source


def test_the_decision_follows_the_pre_registered_rule(
    heldout: dict[str, Any], protocol: dict[str, Any]
) -> None:
    decision = heldout["decision"]
    rule = protocol["heldout_decision_rule"]
    assert decision["generalisation_retention_floor"] == (
        rule["generalisation_retention_floor"]
    )
    assert decision["max_false_abstention_rate"] == (
        protocol["selection"]["max_false_abstention_rate"]
    )
    if decision["decision"] == "A_GENERALISED":
        assert decision["heldout_false_abstention_rate"] <= (
            decision["max_false_abstention_rate"]
        )
        assert decision["retained_fraction"] >= decision["generalisation_retention_floor"]


def test_the_control_comparison_is_present_whatever_the_decision(
    heldout: dict[str, Any],
) -> None:
    comparison = heldout["control_comparison"]["admission"]
    assert comparison["coverage"]["R0"] == 1.0
    assert comparison["risk"]["R0"] >= comparison["risk"]["selected"]


@pytest.mark.parametrize(
    "path",
    [DATASET_PATH, SPLIT_PATH, DEV_PATH, PROTOCOL_PATH, CALIBRATION_PATH, HELDOUT_PATH],
)
def test_the_artefacts_never_contain_document_text(path: Path) -> None:
    """Âncoras e graus, nunca o texto dos documentos do corpus."""
    forbidden = {"content", "chunk_content", "text", "document_text"}
    payload = _load(path)

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                assert key not in forbidden, f"{path.name}: {key}"
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(payload)
