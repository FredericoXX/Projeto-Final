"""Synthetic regression tests; these fixtures are not human scientific labels."""

from copy import deepcopy
from dataclasses import replace
from datetime import date
from types import SimpleNamespace

import pytest

from app.evaluation.policy_v1.conditions import Condition
from app.evaluation.policy_v1.freeze import FreezeError
from app.evaluation.policy_v1.hypotheses import exact_mcnemar, holm_adjust, hypotheses_report
from app.evaluation.policy_v1.labels import CaseLabels, MessageRatingSet, oracle_policy_input
from app.evaluation.policy_v1.metrics import compute_metrics, paired_comparison
from app.evaluation.policy_v1.protocol import stratum, validate_formal_annotations
from app.evaluation.policy_v1.runs import summarize
from tests.test_policy_v1_evaluation import _case, _label_set
from tests.test_policy_v1_evaluation_audit import CORPUS_INVENTORY, _outcome

CHUNK = "00000000-0000-4000-8000-0000000000c1"


def _traced(case_id: str, *, family: str = "F01", **overrides):
    return _case(
        case_id,
        trace={
            "family": family,
            "source_kind": "synthetic",
            "snapshot_id": "synthetic-snapshot",
            "rationale": "Synthetic technical rationale used only by this regression test.",
            "items": [
                {"item_id": "I1", "label": "deadline", "supported": True, "evidence_ids": [CHUNK]}
            ],
        },
        **overrides,
    )


def test_m4_counts_preferred_escalation_even_when_abstention_is_acceptable():
    gold = CaseLabels.model_validate(
        _case("C1", preferred_action="escalate", acceptable_actions=["escalate", "abstain"])
    )
    result = compute_metrics({"C1": summarize([_outcome("C1", "abstain")])}, {"C1": gold}, {})
    assert result["rates"]["under_escalation"]["numerator"] == 1
    assert result["rates"]["under_escalation"]["denominator"] == 1
    assert result["action_confusion"]["acceptable_agreement"]["estimate"] == 1


def test_m5_does_not_reward_an_unacceptable_escalation():
    outcome = replace(_outcome("C1", "escalate"), destination_service_id="academic-office")
    result = compute_metrics(
        {"C1": summarize([outcome])}, {"C1": CaseLabels.model_validate(_case("C1"))}, {}
    )
    assert result["rates"]["destination_correct_conditional"]["denominator"] == 0


def test_m5_total_includes_missed_preferred_escalations():
    gold = CaseLabels.model_validate(
        _case("C1", preferred_action="escalate", acceptable_actions=["escalate", "abstain"])
    )
    result = compute_metrics({"C1": summarize([_outcome("C1", "abstain")])}, {"C1": gold}, {})
    assert result["rates"]["destination_correct_total"]["denominator"] == 1
    assert result["rates"]["destination_correct_total"]["numerator"] == 0


@pytest.mark.parametrize(("a", "b", "expected"), [(0, 0, 1), (0, 6, 0.03125), (3, 3, 1)])
def test_exact_mcnemar(a, b, expected):
    assert exact_mcnemar(a, b) == expected


def test_holm_restores_the_original_order_and_is_monotone():
    assert holm_adjust([0.03, 0.001, 0.02]) == pytest.approx([0.04, 0.003, 0.04])


def test_formal_annotations_refuse_missing_trace():
    case = SimpleNamespace(case_id="C1", family="F01", source_kind="synthetic")
    with pytest.raises(FreezeError, match="human trace"):
        validate_formal_annotations([case], _label_set("ADJ", [_case("C1")]), CORPUS_INVENTORY)


def test_formal_annotations_bind_to_the_same_snapshot_and_real_chunk():
    case = SimpleNamespace(
        case_id="C1",
        family="F01",
        source_kind="synthetic",
        expected_snapshot_id="synthetic-snapshot",
        language="pt",
        official_only=True,
        requester_role="student",
        reference_date=date(2026, 10, 1),
    )
    labels = _label_set("ADJ", [_traced("C1")])
    validate_formal_annotations([case], labels, CORPUS_INVENTORY)
    case.expected_snapshot_id = "a-different-snapshot"
    with pytest.raises(FreezeError, match="disagree"):
        validate_formal_annotations([case], labels, CORPUS_INVENTORY)


def test_f14_and_synthetic_cases_have_separate_strata():
    assert stratum(SimpleNamespace(family="F14", source_kind="synthetic")) == "F14_synthetic"
    assert stratum(SimpleNamespace(family="F06", source_kind="synthetic")) == "synthetic"
    assert stratum(SimpleNamespace(family="F01", source_kind="real")) == "real"


def test_formal_annotations_reject_evidence_for_a_different_role():
    case = SimpleNamespace(
        case_id="C1",
        family="F01",
        source_kind="synthetic",
        expected_snapshot_id="synthetic-snapshot",
        language="pt",
        official_only=True,
        requester_role="student",
        reference_date=date(2026, 10, 1),
    )
    inventory = deepcopy(CORPUS_INVENTORY)
    inventory["documents"][0]["access_roles"] = ["staff"]
    with pytest.raises(FreezeError, match="inadmissible"):
        validate_formal_annotations([case], _label_set("ADJ", [_traced("C1")]), inventory)


def test_oracle_preserves_the_annotated_item_and_corpus_evidence_identity():
    labels = CaseLabels.model_validate(
        _traced("C1", d6={"has_competent_service": False, "service_id": None})
    )
    inputs = oracle_policy_input(
        labels,
        services=[],
        catalog_version=1,
        reference_date=date(2026, 10, 1),
    )
    assert inputs.admissibility.evidence_ids == frozenset({CHUNK})
    assert inputs.support is not None
    assert inputs.support.items[0].label == "deadline"
    assert inputs.support.items[0].evidence_ids == frozenset({CHUNK})


def test_h1_uses_m1_denominator_instead_of_global_agreement():
    gold = {
        "C1": CaseLabels.model_validate(_case("C1", acceptable_actions=["abstain"])),
        "C2": CaseLabels.model_validate(_case("C2")),
    }
    proposed = {
        key: summarize([replace(_outcome(key, "abstain"), condition=Condition.P_E2E)])
        for key in gold
    }
    baseline = {key: summarize([_outcome(key, "answer")]) for key in gold}
    report = hypotheses_report({Condition.P_E2E: proposed, Condition.B0: baseline}, gold)
    contrast = report["H1_H1b"]["comparisons"][0]
    assert contrast["n_pairs"] == 1  # C2 is outside the M1 denominator.
    assert contrast["estimate"] == -1
    assert report["H2"]["status"] == "inconclusive_or_exploratory"


def test_h5b_records_presence_in_f02_and_does_not_infer_usefulness():
    gold = {"C1": CaseLabels.model_validate(_traced("C1", family="F02"))}
    first = summarize([replace(_outcome("C1", "abstain"), temporal_notice_shown=True)])
    second = summarize([replace(_outcome("C1", "abstain"), temporal_notice_shown=False)])
    report = paired_comparison({"C1": first}, {"C1": second}, gold, measure="outdated_notice")
    assert report["n_pairs"] == 1
    assert report["estimate"] == 1


def test_m7_reports_the_individual_human_criteria():
    outcome = _outcome("C1", "answer", message="Synthetic response")
    ratings = MessageRatingSet.model_validate(
        {
            "schema_version": "policy_v1_message_ratings_1",
            "set_id": "dev",
            "ratings": [
                {
                    "case_id": "C1",
                    "condition": outcome.condition.value,
                    "rater_id": "human-A1",
                    "acceptable": False,
                    "criteria": {
                        "supported_and_complete": False,
                        "gap_declared": None,
                        "clarification_material_and_covered": None,
                        "outdated_notice_present": None,
                        "escalation_without_transmission": None,
                    },
                }
            ],
        }
    )
    result = compute_metrics(
        {"C1": summarize([outcome])}, {"C1": CaseLabels.model_validate(_case("C1"))}, {}, ratings
    )
    assert result["message_quality"]["criteria"]["supported_and_complete"]["denominator"] == 1
    assert result["message_quality"]["criteria"]["gap_declared"]["denominator"] == 0
