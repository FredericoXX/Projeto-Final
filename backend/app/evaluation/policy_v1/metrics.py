"""Métricas da avaliação da política v1, sobre a execução principal.

Definições explícitas no prompt da v1.7, implementadas com esses números:

- **M1** — ``ANSWER`` quando ``ANSWER`` não é aceitável. Numerador: casos em que
  a ação foi ``ANSWER`` e ``ANSWER`` não está no conjunto aceitável;
  denominador: casos sem falha técnica em que ``ANSWER`` não é aceitável.
- **M2** — só conta ação diferente de ``ANSWER`` **e** fora do conjunto
  aceitável, quando ``ANSWER`` é aceitável. Denominador: casos sem falha em
  que ``ANSWER`` é aceitável.

As restantes métricas são descritas pelo prompt apenas por tema. Os seus
identificadores vêm de :data:`app.evaluation.policy_v1.config.METRIC_IDS`:

- M3–M8 são **provisórios**, pela ordem da enumeração no prompt;
- M9 está **por atribuir**, até haver o documento da v1.7.

=====  =============================================================
ID     Métrica
=====  =============================================================
M3     encaminhamento excessivo
M4     encaminhamento insuficiente
M5     destino correto, com denominador condicional e total
M6     citações inadmissíveis
M7     qualidade da mensagem, só a partir de avaliações humanas
       identificadas (:class:`~app.evaluation.policy_v1.labels.MessageRatingSet`)
M8     erros de estimação de P-e2e por dimensão (:func:`estimation_errors`)
=====  =============================================================

A atribuição de erros, com causas múltiplas ou indeterminadas, vive em
:mod:`app.evaluation.policy_v1.attribution`.

Cada proporção leva numerador, denominador e IC de Wilson. As falhas técnicas
são contadas à parte e nunca entram como ação. Sem avaliações humanas, M7 é
reportada como **não medida**, nunca como zero.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Final

from app.decision.contracts import DecisionOutcome
from app.evaluation.policy_v1.config import METRIC_IDS
from app.evaluation.policy_v1.labels import CaseLabels, MessageRatingSet
from app.evaluation.policy_v1.runs import CaseSummary
from app.evaluation.policy_v1.statistics import paired_difference_interval, wilson_interval

ANSWER: Final = DecisionOutcome.ANSWER.value
ESCALATE: Final = DecisionOutcome.ESCALATE.value


_ID_BY_METRIC: Final = {name: metric_id for metric_id, name in METRIC_IDS["ids"].items() if name}


def metric_id(name: str) -> str | None:
    """Identificador v1.7 de uma métrica (destino condicional e total são M5)."""
    return _ID_BY_METRIC.get(name.removesuffix("_conditional").removesuffix("_total"))


@dataclass(frozen=True)
class MetricDefinition:
    name: str
    numerator: str
    denominator: str

    @property
    def v1_7_id(self) -> str | None:
        return metric_id(self.name)


METRIC_DEFINITIONS: Final = (
    MetricDefinition(
        "answer_when_not_acceptable",
        "action=answer, answer∉acceptable",
        "no failure, answer∉acceptable",
    ),
    MetricDefinition(
        "non_answer_outside_acceptable",
        "action≠answer, action∉acceptable",
        "no failure, answer∈acceptable",
    ),
    MetricDefinition(
        "over_escalation",
        "action=escalate, escalate∉acceptable",
        "no failure, escalate∉acceptable",
    ),
    MetricDefinition("under_escalation", "action≠escalate", "no failure, acceptable={escalate}"),
    MetricDefinition(
        "destination_correct_conditional",
        "destination = adjudicated service",
        "no failure, action=escalate, adjudicated service exists",
    ),
    MetricDefinition(
        "destination_correct_total",
        "action=escalate and destination = adjudicated",
        "no failure, escalate∈acceptable, adjudicated service exists",
    ),
    MetricDefinition(
        "inadmissible_citations",
        "cited evidence outside the packet",
        "no failure, at least one citation",
    ),
)


def _rate(
    summaries: Mapping[str, CaseSummary],
    gold: Mapping[str, CaseLabels],
    in_denominator: Callable[[CaseSummary, CaseLabels], bool],
    in_numerator: Callable[[CaseSummary, CaseLabels], bool],
) -> dict[str, Any]:
    eligible = [
        case_id
        for case_id, summary in sorted(summaries.items())
        if summary.primary.failure is None and in_denominator(summary, gold[case_id])
    ]
    hits = sum(1 for case_id in eligible if in_numerator(summaries[case_id], gold[case_id]))
    return wilson_interval(hits, len(eligible)).as_dict()


def _acceptable(labels: CaseLabels) -> set[str]:
    return {action.value for action in labels.acceptable_actions}


def compute_metrics(
    summaries: Mapping[str, CaseSummary],
    gold: Mapping[str, CaseLabels],
    admissible_by_case: Mapping[str, frozenset[str]],
    ratings: MessageRatingSet | None = None,
) -> dict[str, Any]:
    """Métricas de uma condição sobre a execução principal de cada caso."""
    missing = set(summaries) - set(gold)
    if missing:
        msg = f"{len(missing)} case(s) have no adjudicated labels"
        raise ValueError(msg)

    def action(summary: CaseSummary) -> str | None:
        return summary.primary.action

    def service(labels: CaseLabels) -> bool:
        return bool(labels.d6.has_competent_service)

    rates = {
        "answer_when_not_acceptable": _rate(
            summaries,
            gold,
            lambda s, g: ANSWER not in _acceptable(g),
            lambda s, g: action(s) == ANSWER,
        ),
        "non_answer_outside_acceptable": _rate(
            summaries,
            gold,
            lambda s, g: ANSWER in _acceptable(g),
            lambda s, g: action(s) != ANSWER and action(s) not in _acceptable(g),
        ),
        "over_escalation": _rate(
            summaries,
            gold,
            lambda s, g: ESCALATE not in _acceptable(g),
            lambda s, g: action(s) == ESCALATE,
        ),
        "under_escalation": _rate(
            summaries,
            gold,
            lambda s, g: _acceptable(g) == {ESCALATE},
            lambda s, g: action(s) != ESCALATE,
        ),
        "destination_correct_conditional": _rate(
            summaries,
            gold,
            lambda s, g: action(s) == ESCALATE and service(g),
            lambda s, g: s.primary.destination_service_id == g.d6.service_id,
        ),
        "destination_correct_total": _rate(
            summaries,
            gold,
            lambda s, g: ESCALATE in _acceptable(g) and service(g),
            lambda s, g: (
                action(s) == ESCALATE and s.primary.destination_service_id == g.d6.service_id
            ),
        ),
        "inadmissible_citations": _rate(
            summaries,
            gold,
            lambda s, g: bool(s.primary.cited_evidence_ids),
            lambda s, g: (
                not set(s.primary.cited_evidence_ids)
                <= admissible_by_case.get(s.case_id, frozenset())
            ),
        ),
    }
    total = len(summaries)
    failures = sum(1 for summary in summaries.values() if summary.primary.failure is not None)
    return {
        "definitions": {
            d.name: {"v1_7_id": d.v1_7_id, "numerator": d.numerator, "denominator": d.denominator}
            for d in METRIC_DEFINITIONS
        },
        "cases": total,
        "technical_failures_primary_run": failures,
        "rates": rates,
        "message_quality": _message_quality(summaries, ratings),
        "unassigned_ids": [k for k, v in METRIC_IDS["ids"].items() if v is None],
        "metric_ids_status": METRIC_IDS["status"],
        "instability": wilson_interval(
            sum(1 for summary in summaries.values() if summary.unstable), total
        ).as_dict(),
        "action_distribution": _distribution(summaries),
    }


def _message_quality(
    summaries: Mapping[str, CaseSummary], ratings: MessageRatingSet | None
) -> dict[str, Any]:
    """M7: proporção de mensagens da execução principal julgadas aceitáveis.

    Só conta mensagens com avaliação humana; casos com mensagem e sem avaliação
    são reportados como ``unrated``, nunca presumidos. Sem avaliações, a
    métrica é ``not_measured``.
    """
    if ratings is None:
        return {"status": "not_measured", "reason": "requires human rating", "v1_7_id": "M7"}
    rated = {
        rating.case_id: rating
        for rating in ratings.ratings
        if rating.condition in {summary.condition.value for summary in summaries.values()}
    }
    with_message = [
        case_id
        for case_id, summary in sorted(summaries.items())
        if summary.primary.failure is None and summary.primary.message
    ]
    judged = [case_id for case_id in with_message if case_id in rated]
    acceptable = sum(1 for case_id in judged if rated[case_id].acceptable)
    return {
        "status": "measured",
        "v1_7_id": "M7",
        **wilson_interval(acceptable, len(judged)).as_dict(),
        "unrated": len(with_message) - len(judged),
        "raters": sorted({rated[case_id].rater_id for case_id in judged}),
    }


def _distribution(summaries: Mapping[str, CaseSummary]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for summary in summaries.values():
        key = summary.primary.action or "technical_failure"
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _sufficiency(estimates: Mapping[str, Any]) -> str | None:
    support = estimates.get("support")
    if support is None:
        return None
    supported = [item["supported"] for item in support["items"]]
    if all(supported):
        return "full"
    return "partial" if any(supported) else "none"


#: Erros de estimação por dimensão: estimativa de P-e2e contra a adjudicação,
#: só onde a dimensão foi adjudicada como aplicável e estimada.
_ESTIMATED_FIELDS: Final[
    Mapping[str, tuple[Callable[[CaseLabels], Any], Callable[[Mapping[str, Any]], Any]]]
] = {
    "d1.scope": (
        lambda g: None if g.d1.scope is None else g.d1.scope.value,
        lambda e: e["scope"]["value"],
    ),
    "d2.constraints": (
        lambda g: None if g.d2.constraints is None else sorted(c.value for c in g.d2.constraints),
        lambda e: sorted(e["constraints"]["value"]),
    ),
    "d3.materiality": (
        lambda g: g.d3.materiality,
        lambda e: None if e["specificity"] is None else e["specificity"]["ambiguity_material"],
    ),
    "d4.sufficiency": (lambda g: g.d4.sufficiency, _sufficiency),
    "d5.unresolvable_conflict": (
        lambda g: g.d5.unresolvable_conflict,
        lambda e: (
            None
            if e["conflict"] is None
            else any(not c["resolvable"] for c in e["conflict"]["conflicts"])
        ),
    ),
    "d6.has_competent_service": (
        lambda g: g.d6.has_competent_service,
        lambda e: e["destination"]["service"] is not None,
    ),
}


def estimation_errors(
    summaries: Mapping[str, CaseSummary], gold: Mapping[str, CaseLabels]
) -> dict[str, Any]:
    """Erros de estimação de P-e2e, por dimensão, contra a adjudicação."""
    result: dict[str, Any] = {"v1_7_id": metric_id("estimation_errors")}
    for name, (read_gold, read_estimate) in _ESTIMATED_FIELDS.items():
        errors = total = 0
        for case_id, summary in sorted(summaries.items()):
            estimates = summary.primary.estimates
            expected = read_gold(gold[case_id])
            if estimates is None or expected is None:
                continue
            observed = read_estimate(estimates)
            if observed is None:
                continue
            total += 1
            errors += observed != expected
        result[name] = wilson_interval(errors, total).as_dict()
    return result


def paired_comparison(
    first: Mapping[str, CaseSummary],
    second: Mapping[str, CaseSummary],
    gold: Mapping[str, CaseLabels],
) -> dict[str, Any]:
    """Diferença emparelhada da proporção de ações aceitáveis (caso = unidade).

    Só entram casos sem falha técnica nas duas condições; os excluídos são
    contados. Um IC que inclui zero não demonstra equivalência.
    """
    shared = sorted(
        case_id
        for case_id in set(first) & set(second)
        if first[case_id].primary.failure is None and second[case_id].primary.failure is None
    )

    def acceptable(summary: CaseSummary, case_id: str) -> bool:
        return summary.primary.action in _acceptable(gold[case_id])

    interval = paired_difference_interval(
        [acceptable(first[case_id], case_id) for case_id in shared],
        [acceptable(second[case_id], case_id) for case_id in shared],
    )
    return {
        **interval.as_dict(),
        "excluded_for_failures": len(set(first) | set(second)) - len(shared),
    }
