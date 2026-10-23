"""Métricas da avaliação da política v1, sobre a execução principal.

Definições explícitas no prompt da v1.7, implementadas com esses números:

- **M1** — ``ANSWER`` quando ``ANSWER`` não é aceitável. Numerador: casos em que
  a ação foi ``ANSWER`` e ``ANSWER`` não está no conjunto aceitável;
  denominador: casos sem falha técnica em que ``ANSWER`` não é aceitável.
- **M2** — só conta ação diferente de ``ANSWER`` **e** fora do conjunto
  aceitável, quando ``ANSWER`` é aceitável. Denominador: casos sem falha em
  que ``ANSWER`` é aceitável.

Os restantes identificadores vêm de
:data:`app.evaluation.policy_v1.config.METRIC_IDS`, onde está a origem de cada
um. M4, M5, M7 e M8 são provisórios, e M9 está por atribuir.

=====  =============================================================
ID     Métrica
=====  =============================================================
M3     matriz de confusão das quatro ações (linha: ação preferida
       adjudicada; coluna: ação da condição ou falha técnica), com
       acordo estrito e acordo aceitável (:func:`action_confusion`)
M4     encaminhamento excessivo e insuficiente (duas componentes)
M5     destino correto, com denominador condicional e total
M6     citações inadmissíveis, resolvidas no packet da própria
       condição (:func:`citation_admissibility`)
M7     qualidade da mensagem, só a partir de avaliações humanas
       identificadas (:class:`~app.evaluation.policy_v1.labels.MessageRatingSet`)
M8     erros de estimação de P-e2e por dimensão (:func:`estimation_errors`)
=====  =============================================================

A atribuição de erros, com causas múltiplas ou indeterminadas, vive em
:mod:`app.evaluation.policy_v1.attribution`.

Cada proporção leva numerador, denominador e IC de Wilson. As falhas técnicas
são contadas à parte e nunca entram como ação. Sem avaliações humanas, M7 é
reportada como **não medida**, nunca como zero.

Citações (M6)
-------------

Um identificador de evidência como ``E1`` só tem sentido dentro do packet que
a condição recebeu: o mesmo ``E1`` pode ser um documento vigente no packet de
P-e2e e um documento caducado no de A-sem-filtro. Cada citação é por isso
resolvida no packet da **própria** condição (pelo ``packet_digest`` do
resultado), até à identidade documental — documento, versão e segmento — e
essa passagem é verificada na data de referência do packet, com a semântica de
C9/C10 (limites inclusivos; ``None`` é sem limite). As restantes condições D0
(isolamento, idioma, estado, versão efetiva, oficialidade, papel) são
garantidas pela recuperação de todas as famílias de packet — nenhuma ablação as
desliga —, e o inventário documental congelado prova que a base é a mesma.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any, Final

from app.decision.contracts import DecisionOutcome
from app.evaluation.policy_v1.conditions import CaseOutcome, Condition
from app.evaluation.policy_v1.config import METRIC_IDS, PAIRED_COMPARISONS
from app.evaluation.policy_v1.labels import CaseLabels, MessageRatingSet
from app.evaluation.policy_v1.packets import EvidencePacket, PacketPassage
from app.evaluation.policy_v1.runs import CaseSummary
from app.evaluation.policy_v1.statistics import paired_difference_interval, wilson_interval

ANSWER: Final = DecisionOutcome.ANSWER.value
ESCALATE: Final = DecisionOutcome.ESCALATE.value
ACTIONS: Final = tuple(outcome.value for outcome in DecisionOutcome)
TECHNICAL_FAILURE: Final = "technical_failure"


_ID_BY_METRIC: Final = {name: metric_id for metric_id, name in METRIC_IDS["ids"].items() if name}

#: Componentes que partilham o identificador de uma métrica.
_COMPONENT_OF: Final = {
    "over_escalation": "escalation_errors",
    "under_escalation": "escalation_errors",
    "destination_correct_conditional": "destination_correct",
    "destination_correct_total": "destination_correct",
    "strict_agreement": "action_confusion_matrix",
    "acceptable_agreement": "action_confusion_matrix",
}


def metric_id(name: str) -> str | None:
    """Identificador v1.7 de uma métrica ou de uma das suas componentes."""
    return _ID_BY_METRIC.get(_COMPONENT_OF.get(name, name))


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
    MetricDefinition("strict_agreement", "action=preferred", "no failure"),
    MetricDefinition("acceptable_agreement", "action∈acceptable", "no failure"),
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
        "a citation outside the condition's own packet, or not in force on the reference date",
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


# ---------------------------------------------------------------------------
# M6 — citações resolvidas no packet da própria condição
# ---------------------------------------------------------------------------


def _in_force(passage: PacketPassage, reference_date: date) -> bool:
    """C9/C10 sobre a passagem: limites inclusivos; ``None`` é sem limite."""
    return (passage.valid_from is None or passage.valid_from <= reference_date) and (
        passage.valid_until is None or passage.valid_until >= reference_date
    )


def citation_admissibility(
    outcome: CaseOutcome, packets: Mapping[str, EvidencePacket]
) -> list[dict[str, Any]]:
    """Cada citação do resultado, resolvida no packet que a condição recebeu.

    ``status`` é ``admissible``, ``not_in_packet`` (o identificador não existe
    nesse packet) ou ``outside_validity`` (a passagem não está em vigor na data
    de referência). Um resultado com citações e sem o seu packet é um erro do
    executor, nunca uma citação admissível.
    """
    if not outcome.cited_evidence_ids:
        return []
    packet = packets.get(outcome.packet_digest) if outcome.packet_digest else None
    if packet is None:
        msg = (
            f"case {outcome.case_id} ({outcome.condition.value}, run {outcome.run_number}) "
            "has citations but its packet is not available"
        )
        raise ValueError(msg)
    passages = {passage.evidence_id: passage for passage in packet.passages}
    resolved: list[dict[str, Any]] = []
    for evidence_id in outcome.cited_evidence_ids:
        passage = passages.get(evidence_id)
        if passage is None:
            resolved.append({"evidence_id": evidence_id, "status": "not_in_packet"})
            continue
        resolved.append(
            {
                "evidence_id": evidence_id,
                "document_id": passage.document_id,
                "document_version_id": passage.document_version_id,
                "chunk_id": passage.chunk_id,
                "reference_date": packet.reference_date.isoformat(),
                "status": (
                    "admissible"
                    if _in_force(passage, packet.reference_date)
                    else "outside_validity"
                ),
            }
        )
    return resolved


def has_inadmissible_citation(outcome: CaseOutcome, packets: Mapping[str, EvidencePacket]) -> bool:
    return any(
        citation["status"] != "admissible" for citation in citation_admissibility(outcome, packets)
    )


# ---------------------------------------------------------------------------
# M3 — matriz de confusão
# ---------------------------------------------------------------------------


def action_confusion(
    summaries: Mapping[str, CaseSummary], gold: Mapping[str, CaseLabels]
) -> dict[str, Any]:
    """Ação preferida adjudicada (linha) contra a ação da condição (coluna).

    As falhas técnicas ficam numa coluna própria e fora dos denominadores dos
    acordos: não são uma quinta ação. O acordo estrito exige a ação preferida;
    o aceitável, qualquer ação do conjunto aceitável.
    """
    matrix = {row: dict.fromkeys((*ACTIONS, TECHNICAL_FAILURE), 0) for row in ACTIONS}
    for case_id, summary in sorted(summaries.items()):
        column = summary.primary.action if summary.primary.failure is None else None
        matrix[gold[case_id].preferred_action.value][column or TECHNICAL_FAILURE] += 1
    return {
        "v1_7_id": metric_id("action_confusion_matrix"),
        "rows": "preferred_action",
        "columns": "condition_action",
        "matrix": matrix,
        "strict_agreement": _rate(
            summaries,
            gold,
            lambda s, g: True,
            lambda s, g: s.primary.action == g.preferred_action.value,
        ),
        "acceptable_agreement": _rate(
            summaries, gold, lambda s, g: True, lambda s, g: s.primary.action in _acceptable(g)
        ),
    }


def compute_metrics(
    summaries: Mapping[str, CaseSummary],
    gold: Mapping[str, CaseLabels],
    packets: Mapping[str, EvidencePacket],
    ratings: MessageRatingSet | None = None,
) -> dict[str, Any]:
    """Métricas de uma condição sobre a execução principal de cada caso.

    ``packets`` são todos os packets da avaliação, por digest: cada resultado
    é lido no contexto do packet que recebeu.
    """
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
            lambda s, g: has_inadmissible_citation(s.primary, packets),
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
        "action_confusion": action_confusion(summaries, gold),
        "inadmissible_citation_details": {
            case_id: [
                citation
                for citation in citation_admissibility(summary.primary, packets)
                if citation["status"] != "admissible"
            ]
            for case_id, summary in sorted(summaries.items())
            if summary.primary.failure is None
            and has_inadmissible_citation(summary.primary, packets)
        },
        "message_quality": _message_quality(summaries, ratings),
        "unassigned_ids": [k for k, v in METRIC_IDS["ids"].items() if v is None],
        "metric_ids_status": METRIC_IDS["status"],
        "instability": wilson_interval(
            sum(1 for summary in summaries.values() if summary.unstable), total
        ).as_dict(),
        "action_distribution": _distribution(summaries),
    }


def _message_ratings_by_case(
    summaries: Mapping[str, CaseSummary], ratings: MessageRatingSet
) -> dict[str, bool]:
    conditions = {summary.condition.value for summary in summaries.values()}
    return {
        rating.case_id: rating.acceptable
        for rating in ratings.ratings
        if rating.condition in conditions
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
        key = summary.primary.action or TECHNICAL_FAILURE
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


# ---------------------------------------------------------------------------
# Comparações emparelhadas
# ---------------------------------------------------------------------------

#: Medidas por caso: ``None`` quando o caso não é medível nessa condição (sem
#: avaliação humana da mensagem, por exemplo).
_PairedMeasure = Callable[[CaseSummary, CaseLabels], bool | None]


def _paired_measures(
    packets: Mapping[str, EvidencePacket],
    first_ratings: Mapping[str, bool] | None,
    second_ratings: Mapping[str, bool] | None,
) -> dict[str, tuple[_PairedMeasure, _PairedMeasure]]:
    def acceptable(s: CaseSummary, g: CaseLabels) -> bool | None:
        return s.primary.action in _acceptable(g)

    def strict(s: CaseSummary, g: CaseLabels) -> bool | None:
        return s.primary.action == g.preferred_action.value

    def inadmissible(s: CaseSummary, g: CaseLabels) -> bool | None:
        return has_inadmissible_citation(s.primary, packets)

    def rated(by_case: Mapping[str, bool] | None) -> _PairedMeasure:
        return lambda s, g: None if by_case is None else by_case.get(s.case_id)

    return {
        "acceptable_action": (acceptable, acceptable),
        "strict_action": (strict, strict),
        "inadmissible_citation": (inadmissible, inadmissible),
        "message_acceptable": (rated(first_ratings), rated(second_ratings)),
    }


def paired_comparison(
    first: Mapping[str, CaseSummary],
    second: Mapping[str, CaseSummary],
    gold: Mapping[str, CaseLabels],
    *,
    measure: str = "acceptable_action",
    packets: Mapping[str, EvidencePacket] | None = None,
    ratings: MessageRatingSet | None = None,
) -> dict[str, Any]:
    """Diferença emparelhada de uma medida por caso (caso = unidade).

    Só entram casos sem falha técnica nas duas condições e medíveis nas duas;
    os excluídos são contados por motivo. Um IC que inclui zero não demonstra
    equivalência. Sem avaliações humanas, ``message_acceptable`` é
    ``not_measured``.
    """
    if measure == "message_acceptable" and ratings is None:
        return {"measure": measure, "status": "not_measured", "reason": "requires human rating"}
    measures = _paired_measures(
        packets or {},
        _message_ratings_by_case(first, ratings) if ratings is not None and first else None,
        _message_ratings_by_case(second, ratings) if ratings is not None and second else None,
    )
    if measure not in measures:
        msg = f"unknown paired measure {measure}"
        raise ValueError(msg)
    read_first, read_second = measures[measure]
    both = sorted(set(first) & set(second))
    without_failure = [
        case_id
        for case_id in both
        if first[case_id].primary.failure is None and second[case_id].primary.failure is None
    ]
    values = {
        case_id: (
            read_first(first[case_id], gold[case_id]),
            read_second(second[case_id], gold[case_id]),
        )
        for case_id in without_failure
    }
    shared = [case_id for case_id, (a, b) in values.items() if a is not None and b is not None]
    interval = paired_difference_interval(
        [bool(values[case_id][0]) for case_id in shared],
        [bool(values[case_id][1]) for case_id in shared],
    )
    return {
        "measure": measure,
        **interval.as_dict(),
        "excluded_for_failures": len(set(first) | set(second)) - len(without_failure),
        "excluded_unmeasured": len(without_failure) - len(shared),
    }


def configured_paired_comparisons(
    summaries: Mapping[Condition, Mapping[str, CaseSummary]],
    gold: Mapping[str, CaseLabels],
    *,
    packets: Mapping[str, EvidencePacket],
    ratings: MessageRatingSet | None = None,
) -> list[dict[str, Any]]:
    """Todas as comparações de :data:`~app.evaluation.policy_v1.config.PAIRED_COMPARISONS`.

    Cada resultado leva o efeito isolado, o desfecho, o denominador, a unidade
    estatística e o intervalo tal como congelados na configuração, para que o
    relatório se leia sem a configuração ao lado.
    """
    results: list[dict[str, Any]] = []
    for pair in PAIRED_COMPARISONS["pairs"]:
        first = summaries.get(Condition(pair["first"]), {})
        second = summaries.get(Condition(pair["second"]), {})
        for measure in pair["measures"]:
            definition = PAIRED_COMPARISONS["measures"][measure]
            results.append(
                {
                    "first": pair["first"],
                    "second": pair["second"],
                    "isolates": pair["isolates"],
                    "outcome": definition["outcome"],
                    "denominator": definition["denominator"],
                    "unit": PAIRED_COMPARISONS["unit"],
                    "interval": PAIRED_COMPARISONS["interval"],
                    **paired_comparison(
                        first, second, gold, measure=measure, packets=packets, ratings=ratings
                    ),
                }
            )
    return results
