"""``DecisionPolicy`` experimental da política v1.7 — R01–R12.

Função **pura e determinística** sobre entradas já validadas
(:class:`app.decision.dimensions.PolicyInput`): sem SQL, sem chamadas a modelos
e sem efeitos externos. Aplica a **primeira regra terminal satisfeita**, por
esta ordem, e devolve ação, regra e uma razão estruturada reconstruível.

======  ==============================================================  ========
Regra   Condição                                                        Ação
======  ==============================================================  ========
R01     D1 fora de âmbito                                               ABSTAIN
R02     D2 ato administrativo, com serviço competente (D6)              ESCALATE
R03     D2 ato administrativo, sem serviço competente                   ABSTAIN
R04     D2 dado pessoal, com serviço competente                         ESCALATE
R05     D2 dado pessoal, sem serviço competente                         ABSTAIN
R06     D3 ambiguidade material, distinguível, todas as leituras        CLARIFY
        cobertas por evidência admissível
R07     D5 conflito não resolúvel, com serviço competente               ESCALATE
R08     D5 conflito não resolúvel, sem serviço competente               ABSTAIN
R09     D4 suporte total (sem ambiguidade material por resolver)        ANSWER
R10     D4 suporte parcial, parte suportada não enganosa                ANSWER
        (com lacuna explícita)
R11     restantes: nenhuma suficiência, parcial enganosa, ou            ESCALATE
        ambiguidade material não resolúvel — com serviço competente
R12     idem, sem serviço competente                                    ABSTAIN
======  ==============================================================  ========

Quando coexistem as duas restrições de D2, o ato administrativo precede o dado
pessoal, para que a regra registada seja estável. Não existe uma quinta ação
para resposta parcial: R10 é ``ANSWER`` com os itens não suportados declarados.

O diagnóstico temporal faz parte das entradas mas **não** de nenhuma regra: na
v1.7 altera a mensagem, nunca a ação.

A precedência das regras não determina a ordem de recolha dos dados — essa
pertence ao orquestrador (:mod:`app.services.decision_service`).

Este módulo é experimental: a v1.7 é uma especificação de trabalho sujeita a
calibração, e nenhuma regra aqui foi avaliada.
"""

from typing import Final

from app.decision.contracts import (
    AnswerabilityClass,
    DecisionOutcome,
    RequestConstraint,
    ScopeClass,
)
from app.decision.dimensions import (
    ConflictAssessment,
    DecisionFact,
    DecisionReason,
    PolicyDecision,
    PolicyInput,
    PolicyInputError,
    RuleId,
    SpecificityAssessment,
    SupportAssessment,
)

#: Identidade da política executável. Participa nos registos de decisão e nos
#: packets de avaliação: uma alteração de regra muda esta versão.
POLICY_VERSION: Final = "decision_policy_v1.7-experimental.1"


def _fact(dimension: str, name: str, value: object) -> DecisionFact:
    return DecisionFact(dimension=dimension, name=name, value=value)


def _destination_facts(policy_input: PolicyInput) -> tuple[DecisionFact, ...]:
    destination = policy_input.destination
    return (
        _fact("D6", "has_competent_service", destination.has_competent_service),
        _fact("D6", "topic", destination.topic),
        _fact("D6", "catalog_version", destination.catalog_version),
    )


def _decision(
    policy_input: PolicyInput,
    action: DecisionOutcome,
    rule: RuleId,
    facts: tuple[DecisionFact, ...],
    **extra: object,
) -> PolicyDecision:
    escalates = action is DecisionOutcome.ESCALATE
    return PolicyDecision(
        action=action,
        rule=rule,
        reason=DecisionReason(rule=rule, facts=facts),
        policy_version=POLICY_VERSION,
        destination=policy_input.destination.service if escalates else None,
        **extra,  # type: ignore[arg-type]
    )


def _escalate_or_abstain(
    policy_input: PolicyInput,
    escalate_rule: RuleId,
    abstain_rule: RuleId,
    facts: tuple[DecisionFact, ...],
    **extra: object,
) -> PolicyDecision:
    """O padrão comum de R02/R03, R04/R05, R07/R08 e R11/R12: D6 decide."""
    facts = (*facts, *_destination_facts(policy_input))
    if policy_input.destination.has_competent_service:
        return _decision(policy_input, DecisionOutcome.ESCALATE, escalate_rule, facts, **extra)
    return _decision(policy_input, DecisionOutcome.ABSTAIN, abstain_rule, facts, **extra)


def _required[T](value: T | None, *, dimension: str, rule: RuleId) -> T:
    if value is None:
        msg = f"rule {rule.value} needs dimension {dimension}, which was not collected"
        raise PolicyInputError(msg)
    return value


def decide(policy_input: PolicyInput) -> PolicyDecision:
    """Aplica R01–R12 e devolve a primeira regra terminal satisfeita."""
    # R01 — D1.
    if policy_input.scope is ScopeClass.OUT_OF_SCOPE:
        return _decision(
            policy_input,
            DecisionOutcome.ABSTAIN,
            RuleId.R01,
            (_fact("D1", "scope", policy_input.scope.value),),
        )

    constraints = policy_input.constraints
    # R02/R03 — ato administrativo precede dado pessoal.
    if RequestConstraint.ADMINISTRATIVE_ACTION_REQUIRED in constraints:
        return _escalate_or_abstain(
            policy_input,
            RuleId.R02,
            RuleId.R03,
            (_fact("D2", "constraints", sorted(c.value for c in constraints)),),
        )
    # R04/R05.
    if RequestConstraint.PERSONAL_DATA_REQUIRED in constraints:
        return _escalate_or_abstain(
            policy_input,
            RuleId.R04,
            RuleId.R05,
            (_fact("D2", "constraints", sorted(c.value for c in constraints)),),
        )

    specificity: SpecificityAssessment = _required(
        policy_input.specificity, dimension="D3", rule=RuleId.R06
    )
    # R06 — só com as três condições: material, distinguível, todas cobertas.
    if specificity.clarifiable:
        return _decision(
            policy_input,
            DecisionOutcome.CLARIFY,
            RuleId.R06,
            (
                _fact("D3", "ambiguity_material", specificity.ambiguity_material),
                _fact("D3", "user_can_distinguish", specificity.user_can_distinguish),
                _fact("D3", "all_readings_covered", specificity.all_readings_covered),
                _fact("D3", "readings", len(specificity.readings)),
            ),
            clarify_reading_ids=tuple(r.reading_id for r in specificity.readings),
        )

    conflict: ConflictAssessment = _required(policy_input.conflict, dimension="D5", rule=RuleId.R07)
    # R07/R08 — conflito não resolúvel.
    if conflict.has_unresolvable_conflict:
        evidence_ids = tuple(
            dict.fromkeys(
                evidence_id for item in conflict.unresolvable for evidence_id in item.evidence_ids
            )
        )
        return _escalate_or_abstain(
            policy_input,
            RuleId.R07,
            RuleId.R08,
            (
                _fact("D5", "unresolvable_conflicts", len(conflict.unresolvable)),
                _fact("D5", "items", sorted({c.item_id for c in conflict.unresolvable})),
            ),
            conflict_evidence_ids=evidence_ids,
        )

    support: SupportAssessment = _required(policy_input.support, dimension="D4", rule=RuleId.R09)
    sufficiency = support.sufficiency
    ambiguity_unresolved = specificity.materially_ambiguous
    d4_facts = (
        _fact("D4", "sufficiency", sufficiency.value),
        _fact("D3", "material_ambiguity_unresolved", ambiguity_unresolved),
    )

    if not ambiguity_unresolved:
        # R09 — suporte total.
        if sufficiency is AnswerabilityClass.FULLY_ANSWERABLE:
            return _decision(
                policy_input,
                DecisionOutcome.ANSWER,
                RuleId.R09,
                d4_facts,
                answer_item_ids=tuple(item.item_id for item in support.items),
            )
        # R10 — parcial e não enganosa: ANSWER com lacuna explícita.
        if (
            sufficiency is AnswerabilityClass.PARTIALLY_ANSWERABLE
            and support.partial_misleading is False
        ):
            return _decision(
                policy_input,
                DecisionOutcome.ANSWER,
                RuleId.R10,
                (*d4_facts, _fact("D4", "partial_misleading", False)),
                answer_item_ids=tuple(item.item_id for item in support.supported_items),
                gap_item_ids=tuple(item.item_id for item in support.unsupported_items),
            )

    # R11/R12 — nenhuma suficiência, parcial enganosa ou ambiguidade material
    # não resolúvel.
    return _escalate_or_abstain(
        policy_input,
        RuleId.R11,
        RuleId.R12,
        (*d4_facts, _fact("D4", "partial_misleading", support.partial_misleading)),
    )
