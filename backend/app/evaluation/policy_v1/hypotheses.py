"""Predeclared paired contrasts of M1/M2; no claims from aggregate accuracy."""

import math
from collections.abc import Callable, Mapping
from typing import Any

from app.evaluation.policy_v1.conditions import Condition
from app.evaluation.policy_v1.labels import CaseLabels
from app.evaluation.policy_v1.runs import CaseSummary
from app.evaluation.policy_v1.statistics import paired_difference_interval, wilson_interval


def exact_mcnemar(only_first: int, only_second: int) -> float:
    """Two-sided exact McNemar test, including zero discordant pairs."""
    if only_first < 0 or only_second < 0:
        raise ValueError("discordant counts cannot be negative")
    n = only_first + only_second
    if n == 0:
        return 1.0
    tail = sum(math.comb(n, k) for k in range(min(only_first, only_second) + 1)) / 2**n
    return min(1.0, 2 * tail)


def holm_adjust(p_values: list[float]) -> list[float]:
    if any(not 0 <= p <= 1 for p in p_values):
        raise ValueError("invalid p-value")
    adjusted = [1.0] * len(p_values)
    previous = 0.0
    for rank, index in enumerate(sorted(range(len(p_values)), key=p_values.__getitem__)):
        previous = min(1.0, max(previous, (len(p_values) - rank) * p_values[index]))
        adjusted[index] = previous
    return adjusted


def _contrast(
    first: Mapping[str, CaseSummary],
    second: Mapping[str, CaseSummary],
    gold: Mapping[str, CaseLabels],
    eligible: Callable[[CaseLabels], bool],
    event: Callable[[CaseSummary, CaseLabels], bool | None],
) -> dict[str, Any]:
    ids = sorted(set(first) & set(second) & set(gold))
    target = [case_id for case_id in ids if eligible(gold[case_id])]
    nonfailed = [
        case_id
        for case_id in target
        if first[case_id].primary.failure is None and second[case_id].primary.failure is None
    ]
    paired = [
        case_id
        for case_id in nonfailed
        if event(first[case_id], gold[case_id]) is not None
        and event(second[case_id], gold[case_id]) is not None
    ]
    interval = paired_difference_interval(
        [bool(event(first[case_id], gold[case_id])) for case_id in paired],
        [bool(event(second[case_id], gold[case_id])) for case_id in paired],
    )
    return {
        **interval.as_dict(),
        "excluded_for_failures": len(target) - len(nonfailed),
        "excluded_unmeasured": len(nonfailed) - len(paired),
        "missing_in_one_condition": len(set(first) ^ set(second)),
        "exact_mcnemar_two_sided_p": exact_mcnemar(interval.only_a, interval.only_b),
    }


def hypotheses_report(
    summaries: Mapping[Condition, Mapping[str, CaseSummary]],
    gold: Mapping[str, CaseLabels],
    *,
    margin: float = 0.05,
    margin_justified: bool = False,
) -> dict[str, Any]:
    proposed = summaries.get(Condition.P_E2E, {})
    comparisons = []
    for baseline in (Condition.B0, Condition.B1_FULL, Condition.B1_COMPOSITION):
        result = _contrast(
            proposed,
            summaries.get(baseline, {}),
            gold,
            lambda g: "answer" not in {a.value for a in g.acceptable_actions},
            lambda s, g: s.primary.action == "answer",
        )
        comparisons.append({"first": "P-e2e", "second": baseline.value, "metric": "M1", **result})
    p_values = [float(c["exact_mcnemar_two_sided_p"]) for c in comparisons]
    for contrast, corrected in zip(comparisons, holm_adjust(p_values), strict=True):
        contrast["holm_adjusted_p"] = corrected
        contrast["improvement_after_holm"] = (
            contrast["estimate"] is not None and contrast["estimate"] < 0 and corrected < 0.05
        )

    refusal = _contrast(
        proposed,
        summaries.get(Condition.B1_FULL, {}),
        gold,
        lambda g: "answer" in {a.value for a in g.acceptable_actions},
        lambda s, g: (
            s.primary.action != "answer"
            and s.primary.action not in {a.value for a in g.acceptable_actions}
        ),
    )
    upper = refusal["upper"]
    h3: dict[str, list[int]] = {}
    for summary in summaries.get(Condition.P_ORACLE, {}).values():
        outcome = summary.primary
        if outcome.failure is None and outcome.rule is not None:
            counts = h3.setdefault(outcome.rule, [0, 0])
            counts[0] += outcome.action in {
                a.value for a in gold[summary.case_id].acceptable_actions
            }
            counts[1] += 1

    def family(g: CaseLabels) -> str | None:
        return None if g.trace is None else g.trace.family

    h4 = _contrast(
        proposed,
        summaries.get(Condition.B1_FULL, {}),
        gold,
        lambda g: family(g) in {"F04", "F08", "F09"},
        lambda s, g: s.primary.action == "clarify",
    )
    h5b = _contrast(
        proposed,
        summaries.get(Condition.A_NO_DIAGNOSTIC, {}),
        gold,
        lambda g: family(g) == "F02",
        lambda s, g: s.primary.temporal_notice_shown,
    )

    return {
        "unit": "case; pre-numbered first run",
        "H1_H1b": {"metric": "M1", "alpha": 0.05, "comparisons": comparisons},
        "H2": {
            "metric": "M2",
            "difference": "P-e2e minus B1-plena",
            **refusal,
            "margin": margin,
            "margin_justified": margin_justified,
            "status": (
                "non_inferiority_supported"
                if margin_justified and upper is not None and upper < margin
                else "inconclusive_or_exploratory"
            ),
        },
        "H3": {rule: wilson_interval(*counts).as_dict() for rule, counts in sorted(h3.items())},
        "H4": {"status": "exploratory", "negative_families": ["F04", "F08", "F09"], **h4},
        "H5": "descriptive M6 in F02/F03; not a novelty test",
        "H5b": {"outcome": "temporal notice presence in F02, not usefulness", **h5b},
        "H6": "descriptive M4 and over-escalation with confidence intervals",
    }
