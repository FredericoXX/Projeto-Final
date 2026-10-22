"""Núcleo sem base de dados do fluxo da política v1.7.

Partilhado pelo fluxo operacional (:mod:`app.services.decision_service`) e pelo
executor de avaliação (:mod:`app.evaluation.policy_v1`): as duas pontas usam
**a mesma** construção das entradas e **a mesma** composição das mensagens,
para que P-e2e offline e o modo experimental em operação não divirjam.

Não faz SQL nem recuperação: recebe passagens já admissíveis (D0) e um
diagnóstico já calculado.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Final

from app.answering.base import (
    AnswerGenerator,
    AnsweringContext,
    ContextEvidence,
    GeneratedAnswer,
    InvalidGeneratedAnswerError,
)
from app.answering.validation import INVALID_ANSWER_MESSAGE, validate_generated_answer
from app.core.exceptions import ServiceUnavailableError
from app.decision.contracts import DecisionOutcome
from app.decision.dimensions import (
    AdmissibilityAssessment,
    ConflictAssessment,
    DestinationResolution,
    EstimateOrigin,
    EvidenceConflict,
    ItemSupport,
    PolicyDecision,
    PolicyInput,
    Reading,
    RuleId,
    SpecificityAssessment,
    SupportAssessment,
    TemporalDiagnostic,
    only_outside_validity_found,
)
from app.decision.estimators.base import (
    EvidenceAssessment,
    ItemDraft,
    ItemSupportDraft,
    PassageView,
    ReadingDraft,
    RequestAnalysis,
)
from app.decision.messages import (
    CitedExcerpt,
    ConflictingSource,
    build_abstain_message,
    build_clarify_message,
    build_escalate_message,
    build_gap_statement,
    temporal_notice,
)

#: Código estável de uma resposta que não cita evidência de algum item.
REASON_MISSING_ITEM_CITATION: Final = "missing_item_citation"


#: Atributo com que uma exceção do gerador transporta a utilização da chamada.
GENERATOR_USAGE_ATTRIBUTE: Final = "generator_usage"


def generator_usage(usage: dict[str, int] | None, *, attempts: int = 1) -> dict[str, object]:
    """Uma chamada ao gerador (sem repetição), com os tokens quando houver.

    O custo monetário não é calculado: depende de tarifas externas que o
    projeto não configura. Fica ``None``, explicitamente.
    """
    return {
        "attempts": attempts,
        "input_tokens": None if usage is None else usage.get("input_tokens"),
        "output_tokens": None if usage is None else usage.get("output_tokens"),
        "cost": None,
    }


def failed_generator_usage(exc: BaseException) -> dict[str, object] | None:
    """Utilização do gerador anexada a uma falha; ``None`` se não foi chamado."""
    usage = getattr(exc, GENERATOR_USAGE_ATTRIBUTE, None)
    return usage if isinstance(usage, dict) else None


def generate_with_usage(generator: AnswerGenerator, context: AnsweringContext) -> GeneratedAnswer:
    """Chama o gerador e garante que uma falha leva a utilização consigo.

    Uma falha de configuração (o gerador não está disponível) não chegou ao
    fornecedor: zero tentativas. Qualquer outra falha conta como uma tentativa,
    sem tokens conhecidos.
    """
    try:
        return generator.generate(context)
    except Exception as exc:
        attempts = 0 if isinstance(exc, ServiceUnavailableError) else 1
        setattr(exc, GENERATOR_USAGE_ATTRIBUTE, generator_usage(None, attempts=attempts))
        raise


def passage_views(entries: Sequence[ContextEvidence]) -> tuple[PassageView, ...]:
    return tuple(
        PassageView(
            evidence_id=entry.evidence_id,
            document_title=entry.evidence.document_title,
            content=entry.evidence.content,
            official_source=entry.evidence.official_source,
            valid_from=entry.evidence.valid_from,
            valid_until=entry.evidence.valid_until,
        )
        for entry in entries
    )


def assessment_without_evidence(
    readings: Sequence[ReadingDraft], items: Sequence[ItemDraft]
) -> EvidenceAssessment:
    """Sem passagens admissíveis, nenhuma leitura é coberta e nenhum item
    suportado — consequência de D0, não uma estimativa. O estimador não é
    chamado: não há evidência sobre a qual estimar."""
    return EvidenceAssessment(
        reading_coverage={reading.reading_id: frozenset() for reading in readings},
        item_support=tuple(
            ItemSupportDraft(item_id=item.item_id, supported=False, evidence_ids=frozenset())
            for item in items
        ),
        partial_misleading=None,
        conflicts=(),
    )


@dataclass(frozen=True)
class EstimatedDimensions:
    """As estimativas de D1–D5 de uma execução, tal como a política as recebe.

    É este o objeto que a condição B1-composição recebe de P-e2e: as mesmas
    estimativas, na mesma execução.
    """

    analysis: RequestAnalysis
    assessment: EvidenceAssessment | None
    origin: EstimateOrigin


def build_policy_input(
    dimensions: EstimatedDimensions,
    *,
    entries: Sequence[ContextEvidence],
    destination: DestinationResolution,
    diagnostic: TemporalDiagnostic,
    reference_date: date,
    requester_role: str,
    eligibility_policy: str,
    conditions: tuple[str, ...],
    access_policy_version: str,
) -> PolicyInput:
    """Traduz estimativas validadas em entradas da política."""
    analysis = dimensions.analysis
    assessment = dimensions.assessment
    origin = dimensions.origin
    admissibility = AdmissibilityAssessment(
        evidence_ids=frozenset(entry.evidence_id for entry in entries),
        eligibility_policy=eligibility_policy,
        conditions=conditions,
        requester_role=requester_role,
        access_policy_version=access_policy_version,
        reference_date=reference_date,
    )
    specificity = support = conflict = None
    if assessment is not None and not analysis.constraints:
        specificity = SpecificityAssessment(
            specificity=analysis.specificity,
            readings=tuple(
                Reading(
                    reading_id=reading.reading_id,
                    label=reading.label,
                    supporting_evidence_ids=assessment.reading_coverage.get(
                        reading.reading_id, frozenset()
                    ),
                )
                for reading in analysis.readings
            ),
            ambiguity_material=analysis.ambiguity_material,
            user_can_distinguish=analysis.user_can_distinguish,
            origin=origin,
        )
        labels = {item.item_id: item.label for item in analysis.items}
        support = SupportAssessment(
            items=tuple(
                ItemSupport(
                    item_id=draft.item_id,
                    label=labels[draft.item_id],
                    supported=draft.supported,
                    evidence_ids=draft.evidence_ids,
                )
                for draft in assessment.item_support
            ),
            partial_misleading=assessment.partial_misleading,
            origin=origin,
        )
        conflict = ConflictAssessment(
            conflicts=tuple(
                EvidenceConflict(
                    item_id=draft.item_id,
                    evidence_ids=draft.evidence_ids,
                    resolvable=draft.resolvable,
                )
                for draft in assessment.conflicts
            ),
            origin=origin,
        )
    return PolicyInput(
        scope=analysis.scope,
        scope_origin=origin,
        constraints=analysis.constraints,
        constraints_origin=origin,
        admissibility=admissibility,
        destination=destination,
        reference_date=reference_date,
        specificity=specificity,
        support=support,
        conflict=conflict,
        diagnostic=diagnostic,
    )


@dataclass(frozen=True)
class ComposedTurn:
    """Texto do turno e as evidências que ele cita, por ordem de citação."""

    content: str
    cited_evidence_ids: tuple[str, ...]
    generator_called: bool
    temporal_notice_shown: bool
    #: Tentativas e tokens do gerador substantivo; ``None`` fora de ANSWER.
    generator_usage: dict[str, object] | None = None


def compose_turn(
    decision: PolicyDecision,
    policy_input: PolicyInput,
    *,
    analysis: RequestAnalysis,
    procedure_evidence_ids: Sequence[str],
    entries: Sequence[ContextEvidence],
    query: str,
    language: str,
    institution_name: str,
    generator: AnswerGenerator,
    max_context_chars: int,
    max_answer_chars: int,
    include_diagnostic: bool = True,
) -> ComposedTurn:
    """Executa a ação decidida. **Só ANSWER chama o gerador.**

    ``include_diagnostic=False`` é a ablação A-sem-diagnóstico: remove apenas a
    nota temporal da mensagem, nada mais.
    """
    by_id = {entry.evidence_id: entry for entry in entries}
    # O aviso só existe quando apenas foi encontrada informação fora de vigor.
    notice = (
        temporal_notice(language, policy_input.diagnostic.excluded, policy_input.reference_date)
        if include_diagnostic and only_outside_validity_found(policy_input)
        else None
    )

    if decision.action is DecisionOutcome.ANSWER:
        support = policy_input.support
        if support is None:
            msg = "ANSWER requires D4"
            raise ValueError(msg)
        answer_items = [item for item in support.items if item.item_id in decision.answer_item_ids]
        allowed = sorted(
            {evidence_id for item in answer_items for evidence_id in item.evidence_ids},
            key=lambda evidence_id: list(by_id).index(evidence_id),
        )
        context_entries = tuple(by_id[evidence_id] for evidence_id in allowed)
        generated = generate_with_usage(
            generator,
            AnsweringContext(
                query=query,
                language=language,
                institution_name=institution_name,
                evidence=context_entries,
                max_context_chars=max_context_chars,
            ),
        )
        try:
            cited = validate_generated_answer(
                generated,
                allowed_evidence_ids=set(allowed),
                max_answer_chars=max_answer_chars,
            )
            # Citações por item: cada item respondido tem de citar pelo menos
            # uma das evidências que o suportam.
            uncited = sum(1 for item in answer_items if not (item.evidence_ids & set(cited)))
            if uncited:
                raise InvalidGeneratedAnswerError(
                    INVALID_ANSWER_MESSAGE, REASON_MISSING_ITEM_CITATION, invalid_count=uncited
                )
        except InvalidGeneratedAnswerError as exc:
            # O fornecedor respondeu: a chamada e os tokens contam, mesmo rejeitada.
            setattr(exc, GENERATOR_USAGE_ATTRIBUTE, generator_usage(generated.usage))
            raise
        content = generated.answer
        if decision.gap_item_ids:
            labels = [item.label for item in support.items if item.item_id in decision.gap_item_ids]
            content = f"{content}\n\n{build_gap_statement(language, labels)}"
        return ComposedTurn(
            content=content,
            cited_evidence_ids=cited,
            generator_called=True,
            temporal_notice_shown=False,
            generator_usage=generator_usage(generated.usage),
        )

    if decision.action is DecisionOutcome.CLARIFY:
        specificity = policy_input.specificity
        if specificity is None:
            msg = "CLARIFY requires D3"
            raise ValueError(msg)
        labels = [
            reading.label
            for reading in specificity.readings
            if reading.reading_id in decision.clarify_reading_ids
        ]
        return ComposedTurn(
            content=build_clarify_message(language, labels),
            cited_evidence_ids=(),
            generator_called=False,
            temporal_notice_shown=False,
        )

    conflicting = [
        ConflictingSource(
            evidence_id=evidence_id, document_title=by_id[evidence_id].evidence.document_title
        )
        for evidence_id in decision.conflict_evidence_ids
    ]
    procedure: list[CitedExcerpt] = []
    if decision.rule in (RuleId.R02, RuleId.R04):
        procedure = [
            CitedExcerpt(
                evidence_id=evidence_id,
                document_title=by_id[evidence_id].evidence.document_title,
                content=by_id[evidence_id].evidence.content,
            )
            for evidence_id in procedure_evidence_ids
            if evidence_id in by_id
        ]
    cited = tuple(item.evidence_id for item in conflicting) + tuple(
        item.evidence_id for item in procedure
    )
    if decision.action is DecisionOutcome.ESCALATE:
        if decision.destination is None:
            msg = "ESCALATE requires a competent service"
            raise ValueError(msg)
        summary = [item.label for item in analysis.items]
        content = build_escalate_message(
            language,
            decision.rule,
            decision.destination,
            summary_items=summary,
            conflicting=conflicting,
            procedure=procedure,
            notice=notice,
        )
    else:
        content = build_abstain_message(
            language, decision.rule, conflicting=conflicting, notice=notice
        )
    return ComposedTurn(
        content=content,
        cited_evidence_ids=cited,
        generator_called=False,
        temporal_notice_shown=notice is not None,
    )
