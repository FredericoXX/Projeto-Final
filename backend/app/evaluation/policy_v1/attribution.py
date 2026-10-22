"""Atribuição de erros de P-e2e, com causas múltiplas ou indeterminadas.

A v1.7 pede uma atribuição de erro que "admite causas múltiplas e
indeterminadas, apoiada em replay e inspeção". Aqui:

**Replay contrafactual.** Para cada caso em que a execução principal de P-e2e
errou — ação fora do conjunto aceitável, ou destino diferente do adjudicado —
as entradas arquivadas da política são relidas, e cada grupo de dimensões
(D1, D2, D3, D4, D5, D6) é substituído, um de cada vez, pela versão adjudicada.
A **mesma** política volta a decidir. Um grupo que, sozinho, corrige o erro é
uma causa candidata.

**Resultado de cada caso:**

- ``single`` — exatamente um grupo corrige o erro;
- ``multiple`` — vários grupos o corrigem isoladamente, ou nenhum o corrige
  sozinho mas a substituição de todos (as dimensões adjudicadas do P-oráculo)
  corrige;
- ``indeterminate`` — o replay não isola a causa: com as dimensões
  adjudicadas a política continua a errar (regra ou adjudicação em causa), ou
  nenhuma dimensão difere e o erro está fora do que o resumo das dimensões
  capta (por exemplo, a ligação de evidências concretas a leituras).

**Inspeção.** Cada atribuição tem um campo ``inspection`` com estado
``pending``: o replay **propõe** causas, não as confirma. A confirmação é
humana, e nenhum modelo a faz.

Só P-e2e (e A-sem-diagnóstico, que tem as mesmas estimativas) é atribuível por
replay: as condições B1 não passam pela política.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date
from typing import Any, Final, Literal

from app.decision.dimensions import (
    PolicyDecision,
    PolicyInput,
    PolicyInputError,
    policy_input_from_dict,
)
from app.decision.policy import decide
from app.evaluation.policy_v1.labels import CaseLabels, oracle_policy_input
from app.evaluation.policy_v1.runs import CaseSummary

#: Grupos de dimensões substituídos no replay e os campos de PolicyInput.
DIMENSION_GROUPS: Final[Mapping[str, tuple[str, ...]]] = {
    "d1_scope": ("scope", "scope_origin"),
    "d2_constraints": ("constraints", "constraints_origin"),
    "d3_specificity": ("specificity",),
    "d4_support": ("support",),
    "d5_conflict": ("conflict",),
    "d6_destination": ("destination",),
}

Determinacy = Literal["single", "multiple", "indeterminate"]


@dataclass(frozen=True)
class ErrorAttribution:
    case_id: str
    error_kind: str
    action: str | None
    acceptable_actions: tuple[str, ...]
    causes: tuple[str, ...]
    determinacy: Determinacy
    replay: Mapping[str, str]
    oracle_action: str | None
    oracle_corrects: bool | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "error_kind": self.error_kind,
            "action": self.action,
            "acceptable_actions": list(self.acceptable_actions),
            "causes": list(self.causes),
            "determinacy": self.determinacy,
            "replay": dict(self.replay),
            "oracle_action": self.oracle_action,
            "oracle_corrects": self.oracle_corrects,
            # O replay propõe; a inspeção humana confirma ou corrige.
            "inspection": {"status": "pending", "confirmed_causes": None, "notes": None},
        }


def _correct(decision: PolicyDecision, labels: CaseLabels) -> bool:
    acceptable = {action.value for action in labels.acceptable_actions}
    if decision.action.value not in acceptable:
        return False
    if decision.action.value == "escalate" and labels.d6.has_competent_service:
        return decision.destination is not None and (
            decision.destination.service_id == labels.d6.service_id
        )
    return True


def _substitute(estimated: PolicyInput, oracle: PolicyInput, group: str) -> PolicyInput:
    """Entradas estimadas com um grupo substituído pelo adjudicado.

    O conjunto admissível passa a ser a união dos dois, para que as referências
    abstratas do oráculo e as reais da execução coexistam na validação D0.
    """
    admissibility = replace(
        estimated.admissibility,
        evidence_ids=estimated.admissibility.evidence_ids | oracle.admissibility.evidence_ids,
    )
    changes = {name: getattr(oracle, name) for name in DIMENSION_GROUPS[group]}
    return replace(estimated, admissibility=admissibility, **changes)


def _differs(estimated: PolicyInput, oracle: PolicyInput, group: str) -> bool:
    """O grupo difere entre estimativa e adjudicação, no que a política usa."""
    if group == "d1_scope":
        return estimated.scope is not oracle.scope
    if group == "d2_constraints":
        return estimated.constraints != oracle.constraints
    if group == "d3_specificity":
        spec_a, spec_b = estimated.specificity, oracle.specificity
        if spec_a is None or spec_b is None:
            return (spec_a is None) != (spec_b is None)
        return (spec_a.materially_ambiguous, spec_a.clarifiable) != (
            spec_b.materially_ambiguous,
            spec_b.clarifiable,
        )
    if group == "d4_support":
        sup_a, sup_b = estimated.support, oracle.support
        if sup_a is None or sup_b is None:
            return (sup_a is None) != (sup_b is None)
        return (sup_a.sufficiency, sup_a.partial_misleading) != (
            sup_b.sufficiency,
            sup_b.partial_misleading,
        )
    if group == "d5_conflict":
        con_a, con_b = estimated.conflict, oracle.conflict
        if con_a is None or con_b is None:
            return (con_a is None) != (con_b is None)
        return con_a.has_unresolvable_conflict != con_b.has_unresolvable_conflict
    service_a = estimated.destination.service
    service_b = oracle.destination.service
    return (None if service_a is None else service_a.service_id) != (
        None if service_b is None else service_b.service_id
    )


def attribute_errors(
    summaries: Mapping[str, CaseSummary],
    gold: Mapping[str, CaseLabels],
    *,
    services: Sequence[Mapping[str, Any]],
    catalog_version: int,
    reference_dates: Mapping[str, date],
) -> list[ErrorAttribution]:
    """Atribuição dos erros da execução principal de P-e2e (ou A-sem-diagnóstico)."""
    attributions: list[ErrorAttribution] = []
    for case_id, summary in sorted(summaries.items()):
        outcome = summary.primary
        labels = gold[case_id]
        if outcome.failure is not None or outcome.estimates is None:
            continue
        acceptable = tuple(sorted(action.value for action in labels.acceptable_actions))
        wrong_action = outcome.action not in acceptable
        wrong_destination = (
            not wrong_action
            and outcome.action == "escalate"
            and bool(labels.d6.has_competent_service)
            and outcome.destination_service_id != labels.d6.service_id
        )
        if not (wrong_action or wrong_destination):
            continue
        estimated = policy_input_from_dict(outcome.estimates)
        oracle = oracle_policy_input(
            labels,
            services=services,
            catalog_version=catalog_version,
            reference_date=reference_dates[case_id],
        )
        oracle_decision = decide(oracle)
        oracle_corrects = _correct(oracle_decision, labels)
        replay: dict[str, str] = {}
        fixing: list[str] = []
        differing: list[str] = []
        for group in DIMENSION_GROUPS:
            if not _differs(estimated, oracle, group):
                replay[group] = "no_difference"
                continue
            differing.append(group)
            try:
                corrected = _correct(decide(_substitute(estimated, oracle, group)), labels)
            except PolicyInputError:
                # A substituição isolada deixa as entradas incoerentes (por
                # exemplo, um conflito sobre um item que deixou de existir).
                replay[group] = "not_evaluable"
                continue
            replay[group] = "corrects" if corrected else "does_not_correct"
            if corrected:
                fixing.append(group)

        causes: tuple[str, ...]
        determinacy: Determinacy
        if len(fixing) == 1:
            causes, determinacy = (fixing[0],), "single"
        elif fixing:
            causes, determinacy = tuple(fixing), "multiple"
        elif differing and oracle_corrects:
            causes, determinacy = tuple(differing), "multiple"
        elif not oracle_corrects:
            causes, determinacy = ("policy_rule", "adjudication"), "indeterminate"
        else:
            causes, determinacy = ("evidence_linking", "retrieval_d0"), "indeterminate"
        attributions.append(
            ErrorAttribution(
                case_id=case_id,
                error_kind="wrong_action" if wrong_action else "wrong_destination",
                action=outcome.action,
                acceptable_actions=acceptable,
                causes=causes,
                determinacy=determinacy,
                replay=replay,
                oracle_action=oracle_decision.action.value,
                oracle_corrects=oracle_corrects,
            )
        )
    return attributions
