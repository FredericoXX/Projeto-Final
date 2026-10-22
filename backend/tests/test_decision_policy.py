"""DecisionPolicy experimental v1.7 — R01–R12, precedência e obrigações.

Testes puros, sem PostgreSQL nem fornecedor. As entradas são construídas à mão:
são fixtures **técnicas e sintéticas**, não anotação científica — servem para
fixar o comportamento das regras, não para avaliar a política.
"""

import ast
import inspect
import sys
from dataclasses import replace
from datetime import date

import pytest

from app.decision import policy as policy_module
from app.decision.contracts import DecisionOutcome, RequestConstraint, ScopeClass
from app.decision.dimensions import (
    AdmissibilityAssessment,
    CompetentService,
    ConflictAssessment,
    DestinationResolution,
    EvidenceConflict,
    ExcludedByValidity,
    ItemSupport,
    PolicyInput,
    PolicyInputError,
    Reading,
    RuleId,
    Specificity,
    SpecificityAssessment,
    SupportAssessment,
    TemporalDiagnostic,
    policy_input_from_dict,
    policy_input_to_dict,
)
from app.decision.policy import POLICY_VERSION, decide

REFERENCE_DATE = date(2026, 10, 1)
SERVICE = CompetentService(
    service_id="academic-office",
    name="Serviços Académicos (sintético)",
    email="academicos@example.org",
    url=None,
)


def _admissibility(*evidence_ids: str) -> AdmissibilityAssessment:
    return AdmissibilityAssessment(
        evidence_ids=frozenset(evidence_ids),
        eligibility_policy="RetrievalEligibility",
        conditions=("c1",),
        requester_role="student",
        access_policy_version="document_role_access_v1",
        reference_date=REFERENCE_DATE,
    )


def _destination(*, competent: bool) -> DestinationResolution:
    return DestinationResolution(
        service=SERVICE if competent else None,
        topic="enrolment" if competent else None,
        catalog_version=1,
    )


def _specified() -> SpecificityAssessment:
    return SpecificityAssessment(specificity=Specificity.SPECIFIED)


def _items(*supported: bool) -> SupportAssessment:
    items = tuple(
        ItemSupport(
            item_id=f"I{index}",
            label=f"item {index}",
            supported=is_supported,
            evidence_ids=frozenset({"E1"}) if is_supported else frozenset(),
        )
        for index, is_supported in enumerate(supported, start=1)
    )
    partial = any(supported) and not all(supported)
    return SupportAssessment(items=items, partial_misleading=False if partial else None)


def _input(
    *,
    scope: ScopeClass = ScopeClass.IN_SCOPE,
    constraints: frozenset[RequestConstraint] = frozenset(),
    competent: bool = True,
    specificity: SpecificityAssessment | None = None,
    support: SupportAssessment | None = None,
    conflict: ConflictAssessment | None = None,
    diagnostic: TemporalDiagnostic | None = None,
    admissible: tuple[str, ...] = ("E1", "E2"),
) -> PolicyInput:
    return PolicyInput(
        scope=scope,
        constraints=constraints,
        admissibility=_admissibility(*admissible),
        destination=_destination(competent=competent),
        reference_date=REFERENCE_DATE,
        specificity=specificity,
        support=support,
        conflict=conflict,
        diagnostic=diagnostic or TemporalDiagnostic(),
    )


def _documentary(**overrides: object) -> PolicyInput:
    """Pedido documental nominal: especificado, sem conflito, suporte total."""
    values: dict[str, object] = {
        "specificity": _specified(),
        "support": _items(True),
        "conflict": ConflictAssessment(),
    }
    values.update(overrides)
    return _input(**values)  # type: ignore[arg-type]


def _ambiguous(
    *, distinguishable: bool = True, covered: tuple[bool, ...] = (True, True)
) -> SpecificityAssessment:
    readings = tuple(
        Reading(
            reading_id=f"L{index}",
            label=f"leitura {index}",
            supporting_evidence_ids=frozenset({f"E{index}"}) if is_covered else frozenset(),
        )
        for index, is_covered in enumerate(covered, start=1)
    )
    return SpecificityAssessment(
        specificity=Specificity.UNDERSPECIFIED,
        readings=readings,
        ambiguity_material=True,
        user_can_distinguish=distinguishable,
    )


# --- As doze regras ---------------------------------------------------------------


def test_r01_out_of_scope_abstains_without_any_other_dimension() -> None:
    decision = decide(_input(scope=ScopeClass.OUT_OF_SCOPE))

    assert (decision.action, decision.rule) == (DecisionOutcome.ABSTAIN, RuleId.R01)
    assert decision.destination is None


@pytest.mark.parametrize(
    ("constraint", "competent", "rule", "action"),
    [
        (
            RequestConstraint.ADMINISTRATIVE_ACTION_REQUIRED,
            True,
            RuleId.R02,
            DecisionOutcome.ESCALATE,
        ),
        (
            RequestConstraint.ADMINISTRATIVE_ACTION_REQUIRED,
            False,
            RuleId.R03,
            DecisionOutcome.ABSTAIN,
        ),
        (RequestConstraint.PERSONAL_DATA_REQUIRED, True, RuleId.R04, DecisionOutcome.ESCALATE),
        (RequestConstraint.PERSONAL_DATA_REQUIRED, False, RuleId.R05, DecisionOutcome.ABSTAIN),
    ],
)
def test_r02_to_r05_constraints_escalate_only_with_a_competent_service(
    constraint: RequestConstraint, competent: bool, rule: RuleId, action: DecisionOutcome
) -> None:
    decision = decide(_input(constraints=frozenset({constraint}), competent=competent))

    assert (decision.action, decision.rule) == (action, rule)
    assert (decision.destination is not None) is (action is DecisionOutcome.ESCALATE)


def test_r06_clarifies_when_material_distinguishable_and_fully_covered() -> None:
    decision = decide(_documentary(specificity=_ambiguous()))

    assert (decision.action, decision.rule) == (DecisionOutcome.CLARIFY, RuleId.R06)
    assert decision.clarify_reading_ids == ("L1", "L2")


@pytest.mark.parametrize(
    ("competent", "rule", "action"),
    [
        (True, RuleId.R07, DecisionOutcome.ESCALATE),
        (False, RuleId.R08, DecisionOutcome.ABSTAIN),
    ],
)
def test_r07_r08_unresolvable_conflict(
    competent: bool, rule: RuleId, action: DecisionOutcome
) -> None:
    conflict = ConflictAssessment(
        conflicts=(EvidenceConflict(item_id="I1", evidence_ids=("E1", "E2"), resolvable=False),)
    )
    decision = decide(_documentary(conflict=conflict, competent=competent))

    assert (decision.action, decision.rule) == (action, rule)
    # As duas orientações são citadas; nenhuma é escolhida.
    assert decision.conflict_evidence_ids == ("E1", "E2")


def test_resolvable_conflict_is_not_a_conflict_for_the_policy() -> None:
    """Uma regra geral e uma específica coerentes, ou populações diferentes."""
    conflict = ConflictAssessment(
        conflicts=(EvidenceConflict(item_id="I1", evidence_ids=("E1", "E2"), resolvable=True),)
    )
    decision = decide(_documentary(conflict=conflict))

    assert decision.rule is RuleId.R09


def test_r09_full_support_answers_every_item() -> None:
    decision = decide(_documentary(support=_items(True, True)))

    assert (decision.action, decision.rule) == (DecisionOutcome.ANSWER, RuleId.R09)
    assert decision.answer_item_ids == ("I1", "I2")
    assert decision.gap_item_ids == ()


def test_r10_partial_not_misleading_answers_with_explicit_gap() -> None:
    decision = decide(_documentary(support=_items(True, False)))

    assert (decision.action, decision.rule) == (DecisionOutcome.ANSWER, RuleId.R10)
    assert decision.answer_item_ids == ("I1",)
    assert decision.gap_item_ids == ("I2",)


@pytest.mark.parametrize(
    ("competent", "rule", "action"),
    [
        (True, RuleId.R11, DecisionOutcome.ESCALATE),
        (False, RuleId.R12, DecisionOutcome.ABSTAIN),
    ],
)
def test_r11_r12_no_sufficiency(competent: bool, rule: RuleId, action: DecisionOutcome) -> None:
    decision = decide(_documentary(support=_items(False), competent=competent))

    assert (decision.action, decision.rule) == (action, rule)


def test_r11_misleading_partial_answer_is_not_answered() -> None:
    support = replace(_items(True, False), partial_misleading=True)
    decision = decide(_documentary(support=support))

    assert decision.rule is RuleId.R11
    assert decision.action is DecisionOutcome.ESCALATE


def test_there_is_no_fifth_action_for_partial_answers() -> None:
    assert {outcome.value for outcome in DecisionOutcome} == {
        "answer",
        "clarify",
        "abstain",
        "escalate",
    }


# --- Precedência --------------------------------------------------------------------


def test_administrative_action_precedes_personal_data() -> None:
    both = frozenset(
        {RequestConstraint.PERSONAL_DATA_REQUIRED, RequestConstraint.ADMINISTRATIVE_ACTION_REQUIRED}
    )
    assert decide(_input(constraints=both)).rule is RuleId.R02
    assert decide(_input(constraints=both, competent=False)).rule is RuleId.R03


def test_out_of_scope_precedes_constraints() -> None:
    decision = decide(
        _input(
            scope=ScopeClass.OUT_OF_SCOPE,
            constraints=frozenset({RequestConstraint.PERSONAL_DATA_REQUIRED}),
        )
    )
    assert decision.rule is RuleId.R01


def test_clarify_precedes_conflict_and_answer() -> None:
    conflict = ConflictAssessment(
        conflicts=(EvidenceConflict(item_id="I1", evidence_ids=("E1", "E2"), resolvable=False),)
    )
    decision = decide(_documentary(specificity=_ambiguous(), conflict=conflict))
    assert decision.rule is RuleId.R06


def test_conflict_precedes_full_support() -> None:
    conflict = ConflictAssessment(
        conflicts=(EvidenceConflict(item_id="I1", evidence_ids=("E1", "E2"), resolvable=False),)
    )
    assert decide(_documentary(conflict=conflict)).rule is RuleId.R07


# --- D3: cobertura desigual e limites de CLARIFY --------------------------------------


def test_unequal_coverage_does_not_clarify_and_material_ambiguity_is_not_answered() -> None:
    """Hipótese de desenho revisável: uma leitura sem cobertura admissível impede
    CLARIFY; a ambiguidade material fica por resolver e vai para R11/R12, mesmo
    que o suporte da leitura coberta seja total."""
    decision = decide(_documentary(specificity=_ambiguous(covered=(True, False))))

    assert decision.action is not DecisionOutcome.CLARIFY
    assert decision.rule is RuleId.R11


def test_indistinguishable_readings_do_not_clarify() -> None:
    decision = decide(_documentary(specificity=_ambiguous(distinguishable=False)))
    assert decision.rule is RuleId.R11


def test_more_than_three_readings_cannot_be_a_closed_question() -> None:
    specificity = _ambiguous(covered=(True, True, True, True))
    decision = decide(_documentary(specificity=specificity, admissible=("E1", "E2", "E3", "E4")))
    assert decision.rule is RuleId.R11


def test_a_general_request_is_not_automatically_ambiguous() -> None:
    general = SpecificityAssessment(
        specificity=Specificity.UNDERSPECIFIED,
        readings=(
            Reading(
                reading_id="L1", label="leitura geral", supporting_evidence_ids=frozenset({"E1"})
            ),
        ),
        ambiguity_material=False,
    )
    assert decide(_documentary(specificity=general)).rule is RuleId.R09


def test_material_ambiguity_requires_two_readings() -> None:
    with pytest.raises(PolicyInputError):
        SpecificityAssessment(
            specificity=Specificity.UNDERSPECIFIED,
            readings=(Reading(reading_id="L1", label="única"),),
            ambiguity_material=True,
        )


# --- D0 antes de D3/D4/D5 ----------------------------------------------------------------


def test_coverage_with_inadmissible_evidence_is_rejected_before_the_policy() -> None:
    with pytest.raises(PolicyInputError, match="not admissible"):
        _documentary(specificity=_ambiguous(), admissible=("E1",))


def test_support_with_inadmissible_evidence_is_rejected() -> None:
    with pytest.raises(PolicyInputError, match="not admissible"):
        _documentary(admissible=("E2",))


def test_conflict_with_inadmissible_evidence_is_rejected() -> None:
    conflict = ConflictAssessment(
        conflicts=(EvidenceConflict(item_id="I1", evidence_ids=("E1", "E9"), resolvable=False),)
    )
    with pytest.raises(PolicyInputError):
        _documentary(conflict=conflict)


def test_conflict_must_refer_to_an_item() -> None:
    conflict = ConflictAssessment(
        conflicts=(EvidenceConflict(item_id="I9", evidence_ids=("E1", "E2"), resolvable=False),)
    )
    with pytest.raises(PolicyInputError, match="item"):
        _documentary(conflict=conflict)


def test_a_rule_needing_an_uncollected_dimension_is_an_input_error_not_an_action() -> None:
    with pytest.raises(PolicyInputError, match="D3"):
        decide(_input())


# --- Obrigações e invariantes ---------------------------------------------------------------


def test_temporal_diagnostic_never_changes_the_action() -> None:
    diagnostic = TemporalDiagnostic(
        excluded=(
            ExcludedByValidity(
                document_id="doc",
                document_title="Calendário 2025",
                valid_from=date(2025, 1, 1),
                valid_until=date(2025, 12, 31),
            ),
        )
    )
    for case in (
        _documentary(),
        _documentary(support=_items(False)),
        _documentary(support=_items(False), competent=False),
        _documentary(specificity=_ambiguous()),
    ):
        with_diagnostic = replace(case, diagnostic=diagnostic)
        assert decide(with_diagnostic).rule is decide(case).rule
        assert decide(with_diagnostic).action is decide(case).action


def test_destination_absent_never_escalates() -> None:
    for case in (
        _input(
            constraints=frozenset({RequestConstraint.ADMINISTRATIVE_ACTION_REQUIRED}),
            competent=False,
        ),
        _input(constraints=frozenset({RequestConstraint.PERSONAL_DATA_REQUIRED}), competent=False),
        _documentary(support=_items(False), competent=False),
    ):
        decision = decide(case)
        assert decision.action is DecisionOutcome.ABSTAIN
        assert decision.destination is None


def test_decision_is_deterministic_and_carries_a_reconstructible_reason() -> None:
    policy_input = _documentary(support=_items(True, False))
    first, second = decide(policy_input), decide(policy_input)

    assert first == second
    assert first.policy_version == POLICY_VERSION
    reason = first.reason.as_dict()
    assert reason["rule"] == "R10"
    assert {fact["dimension"] for fact in reason["facts"]} == {"D3", "D4"}


def test_replay_from_archived_inputs_reproduces_the_decision() -> None:
    conflict = ConflictAssessment(
        conflicts=(EvidenceConflict(item_id="I1", evidence_ids=("E1", "E2"), resolvable=False),)
    )
    for case in (
        _input(scope=ScopeClass.OUT_OF_SCOPE),
        _input(constraints=frozenset({RequestConstraint.PERSONAL_DATA_REQUIRED})),
        _documentary(specificity=_ambiguous()),
        _documentary(conflict=conflict, competent=False),
        _documentary(support=_items(True, False)),
    ):
        archived = policy_input_to_dict(case)
        assert policy_input_from_dict(archived) == case
        assert decide(policy_input_from_dict(archived)) == decide(case)


def test_policy_module_is_pure() -> None:
    """Sem SQL, sem modelos, sem efeitos externos: só stdlib e app.decision."""
    tree = ast.parse(inspect.getsource(policy_module))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.module is not None
            roots.add(node.module)
    for module in roots:
        assert module.split(".")[0] in sys.stdlib_module_names or module.startswith(
            "app.decision."
        ), module
