"""Turno conversacional no modo experimental da política de decisão v1.7.

Única autoridade de escolha da ação neste fluxo: :func:`app.decision.policy.decide`.
A seleção da estratégia de recuperação (o retriever injetado) coexiste com a
política sem a substituir. O B0 (``conversation_answering_service``) não é
alterado por este módulo.

Ordem de recolha — não a precedência das regras
-----------------------------------------------

1. análise do pedido (D1, D2, leituras e itens de D3/D4, tema de D6), sem
   recuperação;
2. D1 fora de âmbito termina aqui, **sem recuperação**;
3. D2 com restrições termina a escolha; só se recupera, com limite, quando o
   pedido também pergunta pelo procedimento documentado — e o procedimento só
   entra na mensagem como excerto citado de evidência admissível;
4. caso contrário, recuperação **por leitura** quando a ambiguidade é material
   (uma consulta por leitura, até ``MAX_READINGS``), ou única; D0 aplica-se na
   própria recuperação (``RetrievalEligibility`` + C13), antes de qualquer
   verificação de cobertura (D3) ou de suporte e conflito (D4/D5);
5. diagnóstico temporal: a mesma pesquisa com C9/C10 relaxadas, de que só se
   retêm documentos excluídos **apenas** por validade — nunca o seu conteúdo;
6. avaliação das leituras e dos itens sobre as passagens admissíveis;
7. política; composição da ação (o gerador só em ANSWER); persistência.

"Não encontrei" é sempre relativo ao que este fluxo recuperou: ausência de
recuperação não é ausência de resposta no corpus.

Transações e locks
------------------

Nenhum lock é mantido durante as chamadas ao estimador ou ao gerador: a
transação de leitura termina antes delas. A persistência repete exatamente o
padrão do B0 — instituição → utilizador → conversa, sob ``FOR UPDATE`` — e as
fontes citadas são revalidadas com ``CitationPersistenceEligibility`` e o papel
persistido. Uma alteração do papel durante a decisão invalida o turno (409):
as evidências admissíveis foram recolhidas para o papel anterior.

Falhas técnicas — estimador ou gerador indisponível, timeout, saída inválida,
fontes alteradas — **não** são ``ABSTAIN``: o pedido falha com o erro próprio,
nenhuma mensagem é gravada, e fica um ``decision_records`` com
``status='technical_failure'``.
"""

import hashlib
import logging
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.answering.base import AnswerGenerator, ContextEvidence
from app.answering.context import select_evidence
from app.core.config import settings
from app.core.conversation_title import derive_conversation_title
from app.core.exceptions import (
    AuthenticationError,
    ConflictError,
    DomainError,
    NotFoundError,
    ServiceUnavailableError,
    ValidationError,
)
from app.core.language import resolve_language
from app.core.text_normalization import normalize_text
from app.decision.contracts import DecisionOutcome, ScopeClass
from app.decision.definitions import DEFINITIONS_VERSION, RULES_VERSION
from app.decision.dimensions import (
    MAX_CLARIFY_READINGS,
    ExcludedByValidity,
    PolicyDecision,
    PolicyInput,
    TemporalDiagnostic,
    policy_input_to_dict,
)
from app.decision.estimators.base import (
    AnalysisRequest,
    AssessmentRequest,
    CatalogTopicView,
    DimensionEstimator,
    EvidenceAssessment,
    ReadingDraft,
    RequestAnalysis,
    validate_analysis,
    validate_assessment,
)
from app.decision.messages import MESSAGE_VERSION
from app.decision.pipeline import (
    ComposedTurn,
    EstimatedDimensions,
    assessment_without_evidence,
    build_policy_input,
    compose_turn,
    failed_generator_usage,
    passage_views,
)
from app.decision.policy import POLICY_VERSION, decide
from app.documents.retrievability import (
    DOCUMENT_ACCESS_POLICY_VERSION,
    RELAXABLE_CONDITIONS,
    RetrievalEligibility,
    role_authorized_sql,
)
from app.models.decision_catalog import InstitutionDecisionCatalog
from app.models.decision_record import DecisionRecord
from app.models.document import Document
from app.models.institution import Institution
from app.models.message import Message
from app.models.user import User
from app.retrieval.base import Evidence, RetrievalContext, RetrievalQuery, Retriever
from app.schemas.answering import AnswerSourceRead
from app.schemas.decision import (
    ClarificationOptionRead,
    ConversationDecisionResponse,
    DecisionStatusRead,
    DecisionTurnRequest,
    RecommendedDestinationRead,
)
from app.schemas.message import MessageRead
from app.services import (
    conversation_service,
    decision_catalog_service,
    message_source_service,
)
from app.services.institution_service import get_institution

logger = logging.getLogger(__name__)

POLICY_NOT_ENABLED_MESSAGE: Final = "The experimental decision policy is not enabled."
CATALOG_NOT_CONFIGURED_MESSAGE: Final = (
    "The decision policy is not configured for this institution."
)
ROLE_CHANGED_MESSAGE: Final = (
    "The account changed while the request was being decided. Please retry."
)
TURN_TYPE_QUESTION: Final = "policy_question"
TURN_TYPE_DECISION: Final = "policy_decision"
#: Máximo de documentos referidos pelo diagnóstico temporal.
MAX_DIAGNOSTIC_DOCUMENTS: Final = 3


class DecisionPolicyNotEnabledError(ServiceUnavailableError):
    """O modo experimental está desativado nesta instalação (503)."""


class DecisionCatalogNotConfiguredError(ServiceUnavailableError):
    """A instituição não tem âmbito/catálogo configurado (503)."""


def ensure_enabled() -> None:
    if not settings.decision_policy_enabled:
        raise DecisionPolicyNotEnabledError(POLICY_NOT_ENABLED_MESSAGE)


def get_status(db: Session, current_user: User) -> DecisionStatusRead:
    catalog = decision_catalog_service.get_active_catalog(db, current_user.institution_id)
    return DecisionStatusRead(
        enabled=settings.decision_policy_enabled,
        policy_version=POLICY_VERSION,
        catalog_configured=catalog is not None,
    )


# ---------------------------------------------------------------------------
# Recuperação e diagnóstico (D0)
# ---------------------------------------------------------------------------


@dataclass
class _Gathered:
    entries: tuple[ContextEvidence, ...] = ()
    diagnostic: TemporalDiagnostic = field(default_factory=TemporalDiagnostic)
    queries: int = 0
    per_reading: bool = False


def _search(
    db: Session,
    retriever: Retriever,
    text: str,
    context: RetrievalContext,
    official_only: bool,
) -> tuple[Evidence, ...]:
    if not normalize_text(text):
        return ()
    result = retriever.search(
        db,
        RetrievalQuery.from_text(text),
        context,
        settings.decision_retrieval_top_k,
        official_only,
    )
    return result.evidence


def _outside_validity(evidence: Evidence, reference_date: date) -> bool:
    before = evidence.valid_from is not None and evidence.valid_from > reference_date
    after = evidence.valid_until is not None and evidence.valid_until < reference_date
    return before or after


def gather_evidence(
    db: Session,
    retriever: Retriever,
    *,
    analysis: RequestAnalysis,
    query: str,
    context: RetrievalContext,
    official_only: bool,
    language: str,
    institution_name: str,
    with_diagnostic: bool = True,
) -> _Gathered:
    """Recuperação limitada e diagnóstico temporal, sob D0."""
    per_reading = analysis.ambiguity_material and len(analysis.readings) >= 2
    texts = (
        [reading.search_query for reading in analysis.readings[: MAX_CLARIFY_READINGS + 1]]
        if per_reading
        else [query]
    )
    merged: list[Evidence] = []
    for text in texts:
        merged.extend(_search(db, retriever, text, context, official_only))
    entries = select_evidence(
        merged,
        settings.answering_max_context_chars,
        query=query,
        language=language,
        institution_name=institution_name,
    )
    diagnostic = TemporalDiagnostic()
    if with_diagnostic:
        relaxed = RetrievalContext(
            institution_id=context.institution_id,
            language=context.language,
            reference_date=context.reference_date,
            requester_role=context.requester_role,
            relaxed_conditions=RELAXABLE_CONDITIONS,
        )
        admissible_chunks = {entry.evidence.chunk_id for entry in entries}
        excluded: dict[uuid.UUID, ExcludedByValidity] = {}
        for evidence in _search(db, retriever, query, relaxed, official_only):
            if evidence.chunk_id in admissible_chunks:
                continue
            if not _outside_validity(evidence, context.reference_date):
                continue
            excluded.setdefault(
                evidence.document_id,
                ExcludedByValidity(
                    document_id=str(evidence.document_id),
                    document_title=evidence.document_title,
                    valid_from=evidence.valid_from,
                    valid_until=evidence.valid_until,
                ),
            )
        diagnostic = TemporalDiagnostic(
            excluded=tuple(excluded.values())[:MAX_DIAGNOSTIC_DOCUMENTS]
        )
    return _Gathered(
        entries=entries,
        diagnostic=diagnostic,
        queries=len(texts) + (1 if with_diagnostic else 0),
        per_reading=per_reading,
    )


def _assess(
    estimator: DimensionEstimator,
    *,
    query: str,
    language: str,
    reference_date: date,
    readings: Sequence[ReadingDraft],
    items: Sequence[Any],
    entries: Sequence[ContextEvidence],
) -> EvidenceAssessment:
    if not entries:
        return assessment_without_evidence(readings, items)
    request = AssessmentRequest(
        query=query,
        language=language,
        reference_date=reference_date,
        readings=tuple(readings),
        items=tuple(items),
        passages=passage_views(entries),
    )
    assessment = estimator.assess(request)
    validate_assessment(assessment, request)
    return assessment


# ---------------------------------------------------------------------------
# Continuação de clarificação
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Clarification:
    parent_message_id: uuid.UUID
    reading_id: str
    reading_label: str
    original_query: str


def _resolve_clarification(
    db: Session,
    *,
    conversation_id: uuid.UUID,
    institution_id: uuid.UUID,
    message_id: uuid.UUID,
    reading_id: str,
) -> _Clarification:
    """A leitura escolhida tem de existir num CLARIFY desta conversa.

    Não é memória conversacional: só se usam o pedido original e a leitura
    escolhida, e a nova decisão revalida toda a admissibilidade.
    """
    parent = db.scalar(
        select(Message).where(
            Message.id == message_id,
            Message.conversation_id == conversation_id,
            Message.institution_id == institution_id,
            Message.role == "assistant",
        )
    )
    metadata = (parent.extra_metadata or {}) if parent is not None else {}
    options = metadata.get("clarification_options") or []
    label = next(
        (
            option.get("label")
            for option in options
            if isinstance(option, dict) and option.get("reading_id") == reading_id
        ),
        None,
    )
    if (
        parent is None
        or metadata.get("turn_type") != TURN_TYPE_DECISION
        or metadata.get("decision_outcome") != DecisionOutcome.CLARIFY.value
        or not isinstance(label, str)
        or parent.reply_to_message_id is None
    ):
        msg = "Clarification option not found."
        raise NotFoundError(msg)
    original = db.scalar(
        select(Message.content).where(
            Message.id == parent.reply_to_message_id,
            Message.conversation_id == conversation_id,
            Message.institution_id == institution_id,
        )
    )
    if original is None:
        msg = "Clarification option not found."
        raise NotFoundError(msg)
    return _Clarification(
        parent_message_id=parent.id,
        reading_id=reading_id,
        reading_label=label,
        original_query=original,
    )


# ---------------------------------------------------------------------------
# Registo protegido
# ---------------------------------------------------------------------------


def _versions(
    estimator: DimensionEstimator, catalog: InstitutionDecisionCatalog | None
) -> dict[str, Any]:
    return {
        "policy": POLICY_VERSION,
        "definitions": DEFINITIONS_VERSION,
        "rules": RULES_VERSION,
        "messages": MESSAGE_VERSION,
        "document_access": DOCUMENT_ACCESS_POLICY_VERSION,
        "estimator": estimator.identity.as_dict(),
        "generator": {
            "provider": settings.answer_generator_provider,
            "model": settings.openai_model,
        },
        "catalog_version": None if catalog is None else catalog.version,
    }


def _record_failure(
    db: Session,
    *,
    run_id: uuid.UUID,
    started: float,
    institution_id: uuid.UUID,
    conversation_id: uuid.UUID,
    user_id: uuid.UUID,
    requester_role: str,
    reference_date: date,
    estimator: DimensionEstimator,
    catalog: InstitutionDecisionCatalog | None,
    failure_code: str,
    stage: str,
    generator_usage: dict[str, object] | None = None,
) -> None:
    """Grava a falha técnica numa transação própria; nunca a converte em ação."""
    db.rollback()
    try:
        db.add(
            DecisionRecord(
                institution_id=institution_id,
                conversation_id=conversation_id,
                user_id=user_id,
                run_id=run_id,
                status="technical_failure",
                failure_code=failure_code[:64],
                policy_version=POLICY_VERSION,
                reference_date=reference_date,
                requester_role=requester_role,
                attempts=max(estimator.usage.attempts, 1),
                duration_ms=int((time.perf_counter() - started) * 1000),
                record={
                    "stage": stage,
                    "versions": _versions(estimator, catalog),
                    "usage": {
                        "estimator": estimator.usage.as_dict(),
                        # Só quando o gerador chegou a ser chamado nesta execução.
                        "generator": generator_usage,
                        "cost_note": "monetary cost not computed: no tariff configured",
                    },
                },
            )
        )
        db.commit()
    except Exception:
        # O registo da falha nunca mascara a falha original.
        db.rollback()
        logger.warning("Could not record decision failure: run_id=%s", run_id)


# ---------------------------------------------------------------------------
# Turno
# ---------------------------------------------------------------------------


def _source_reads(
    entries: Sequence[ContextEvidence], cited_ids: Sequence[str], language: str
) -> list[AnswerSourceRead]:
    by_id = {entry.evidence_id: entry for entry in entries}
    sources = []
    for evidence_id in cited_ids:
        evidence = by_id[evidence_id].evidence
        source = AnswerSourceRead(
            evidence_id=evidence_id,
            chunk_id=evidence.chunk_id,
            document_id=evidence.document_id,
            document_version_id=evidence.document_version_id,
            document_title=evidence.document_title,
            chunk_index=evidence.chunk_index,
            source_url=evidence.source_url,
            official_source=evidence.official_source,
            language=evidence.language,
            valid_from=evidence.valid_from,
            valid_until=evidence.valid_until,
        )
        source.set_internal_content_sha256(
            hashlib.sha256(evidence.content.encode("utf-8")).hexdigest()
        )
        sources.append(source)
    return sources


def _public_metadata(
    decision: PolicyDecision,
    policy_input: PolicyInput,
    composed: ComposedTurn,
    reference_date: date,
) -> dict[str, Any]:
    specificity = policy_input.specificity
    options = (
        [
            {"reading_id": reading.reading_id, "label": reading.label}
            for reading in specificity.readings
            if reading.reading_id in decision.clarify_reading_ids
        ]
        if specificity is not None
        else []
    )
    gap_items = (
        [item.label for item in policy_input.support.items if item.item_id in decision.gap_item_ids]
        if policy_input.support is not None
        else []
    )
    metadata: dict[str, Any] = {
        "turn_type": TURN_TYPE_DECISION,
        "decision_outcome": decision.action.value,
        "decision_rule": decision.rule.value,
        "policy_version": decision.policy_version,
        "message_version": MESSAGE_VERSION,
        # Origem: decisão automática do backend, distinta do encaminhamento
        # pedido pelo utilizador (handoff_trigger="user_requested").
        "decision_trigger": "automatic",
        "reference_date": reference_date.isoformat(),
        "clarification_options": options,
        "gap_items": gap_items,
        "temporal_notice": composed.temporal_notice_shown,
        "recommended_destination": None,
    }
    if decision.destination is not None:
        metadata["recommended_destination"] = {
            "service_id": decision.destination.service_id,
            "name": decision.destination.name,
            "email": decision.destination.email,
            "url": decision.destination.url,
        }
        metadata["handoff_mode"] = "e1"
        metadata["handoff_trigger"] = "policy_decision"
    return metadata


def decide_in_conversation(
    db: Session,
    current_user: User,
    conversation_id: uuid.UUID,
    payload: DecisionTurnRequest,
    retriever: Retriever,
    generator: AnswerGenerator,
    estimator: DimensionEstimator,
) -> ConversationDecisionResponse:
    ensure_enabled()
    started = time.perf_counter()
    run_id = uuid.uuid4()
    user_id = current_user.id
    institution_id = current_user.institution_id
    requester_role = current_user.role
    # Uma única data por pedido, usada na recuperação, no diagnóstico, na
    # política, na revalidação das fontes e no registo.
    reference_date = datetime.now(UTC).date()

    conversation = conversation_service.get_accessible_conversation_by_identity(
        db, user_id=user_id, institution_id=institution_id, conversation_id=conversation_id
    )
    if conversation.status != "active":
        msg = (
            f"Conversation '{conversation_id}' is {conversation.status} "
            "and does not accept new messages."
        )
        raise ConflictError(msg)
    institution = get_institution(db, institution_id)
    language = resolve_language(
        payload.language,
        supported_languages=institution.supported_languages,
        fallback=conversation.language or institution.default_language,
    )
    catalog = decision_catalog_service.get_active_catalog(db, institution_id)
    if catalog is None:
        raise DecisionCatalogNotConfiguredError(CATALOG_NOT_CONFIGURED_MESSAGE)

    clarification: _Clarification | None = None
    if payload.clarification is not None:
        clarification = _resolve_clarification(
            db,
            conversation_id=conversation.id,
            institution_id=institution_id,
            message_id=payload.clarification.message_id,
            reading_id=payload.clarification.reading_id,
        )
        query = clarification.original_query
        user_content = clarification.reading_label
    else:
        query = payload.query or ""
        user_content = query
    if not normalize_text(query):
        msg = "query must contain searchable text"
        raise ValidationError(msg)

    institution_name = institution.name
    topics = tuple(
        CatalogTopicView(code=topic["code"], label=topic["label"]) for topic in catalog.topics
    )
    scope_description = catalog.scope_description
    context = RetrievalContext(
        institution_id=institution_id,
        language=language,
        reference_date=reference_date,
        requester_role=requester_role,
    )

    stage = "analysis"
    try:
        # Nenhum lock durante o estimador ou o gerador.
        db.rollback()
        analysis = estimator.analyze(
            AnalysisRequest(
                query=query,
                language=language,
                reference_date=reference_date,
                requester_role=requester_role,
                scope_description=scope_description,
                topics=topics,
                selected_reading=None if clarification is None else clarification.reading_label,
            )
        )
        validate_analysis(analysis, [topic.code for topic in topics])
        destination = decision_catalog_service.resolve_destination(catalog, analysis.topic)

        gathered = _Gathered()
        assessment: EvidenceAssessment | None = None
        procedure_evidence_ids: tuple[str, ...] = ()
        stage = "retrieval"
        if analysis.scope is ScopeClass.IN_SCOPE and analysis.constraints:
            if analysis.procedure_item is not None:
                gathered = gather_evidence(
                    db,
                    retriever,
                    analysis=analysis,
                    # Pesquisa-se o procedimento, não o ato pedido: o item
                    # de procedimento é o que o descreve.
                    query=analysis.procedure_item.label,
                    context=context,
                    official_only=payload.official_only,
                    language=language,
                    institution_name=institution_name,
                    with_diagnostic=False,
                )
                db.rollback()
                stage = "assessment"
                procedure_assessment = _assess(
                    estimator,
                    query=query,
                    language=language,
                    reference_date=reference_date,
                    readings=(),
                    items=(analysis.procedure_item,),
                    entries=gathered.entries,
                )
                procedure_evidence_ids = tuple(
                    evidence_id
                    for support in procedure_assessment.item_support
                    if support.supported
                    for evidence_id in sorted(support.evidence_ids)
                )
        elif analysis.scope is ScopeClass.IN_SCOPE:
            gathered = gather_evidence(
                db,
                retriever,
                analysis=analysis,
                query=query,
                context=context,
                official_only=payload.official_only,
                language=language,
                institution_name=institution_name,
            )
            db.rollback()
            stage = "assessment"
            assessment = _assess(
                estimator,
                query=query,
                language=language,
                reference_date=reference_date,
                readings=analysis.readings,
                items=analysis.items,
                entries=gathered.entries,
            )
        db.rollback()

        policy_input = build_policy_input(
            EstimatedDimensions(
                analysis=analysis, assessment=assessment, origin=estimator.identity.origin
            ),
            entries=gathered.entries,
            destination=destination,
            diagnostic=gathered.diagnostic,
            reference_date=reference_date,
            requester_role=requester_role,
            eligibility_policy=RetrievalEligibility.name,
            conditions=RetrievalEligibility.condition_names,
            access_policy_version=DOCUMENT_ACCESS_POLICY_VERSION,
        )
        decision = decide(policy_input)

        stage = "composition"
        composed = compose_turn(
            decision,
            policy_input,
            analysis=analysis,
            procedure_evidence_ids=procedure_evidence_ids,
            entries=gathered.entries,
            query=query,
            language=language,
            institution_name=institution_name,
            generator=generator,
            max_context_chars=settings.answering_max_context_chars,
            max_answer_chars=settings.answering_max_answer_chars,
        )
        cited_sources = _source_reads(gathered.entries, composed.cited_evidence_ids, language)

        stage = "persistence"
        response = _persist_turn(
            db,
            run_id=run_id,
            started=started,
            user_id=user_id,
            institution_id=institution_id,
            conversation_id=conversation_id,
            requester_role=requester_role,
            reference_date=reference_date,
            language=language,
            official_only=payload.official_only,
            query=query,
            user_content=user_content,
            clarification=clarification,
            policy_input=policy_input,
            decision=decision,
            composed=composed,
            cited_sources=cited_sources,
            gathered=gathered,
            procedure_evidence_ids=procedure_evidence_ids,
            estimator=estimator,
            catalog=catalog,
            retriever=retriever,
        )
    except AuthenticationError:
        db.rollback()
        raise
    except DomainError as exc:
        # Falhas técnicas e conflitos de concorrência ficam registados como
        # tal — nunca como ABSTAIN — e o erro original segue para o cliente.
        _record_failure(
            db,
            run_id=run_id,
            started=started,
            institution_id=institution_id,
            conversation_id=conversation_id,
            user_id=user_id,
            requester_role=requester_role,
            reference_date=reference_date,
            estimator=estimator,
            catalog=catalog,
            failure_code=getattr(exc, "reason_code", None) or type(exc).__name__,
            stage=stage,
            generator_usage=failed_generator_usage(exc),
        )
        raise
    return response


def _lock_relied_on_documents(
    db: Session,
    *,
    institution_id: uuid.UUID,
    requester_role: str,
    gathered: _Gathered,
    policy_input: PolicyInput,
) -> None:
    """Autorização por papel (C13) de **tudo** aquilo em que a decisão assentou.

    As fontes citadas são revalidadas por ``revalidate_and_lock_sources``. Mas a
    decisão também assenta em evidência admissível não citada — cobertura de
    leituras, suporte negativo, conflito — e o diagnóstico temporal nomeia
    documentos na mensagem e no registo. Todos são relidos aqui, sob
    ``FOR SHARE`` até ao commit, com o papel persistido: um documento entretanto
    eliminado ou vedado ao papel invalida o turno (409), em vez de ficar
    registado como fundamento de uma decisão que já não podia ver.

    Corre depois do lock da instituição, que serializa as persistências da
    instituição e as alterações administrativas de documentos.
    """
    relied_on = {entry.evidence.document_id for entry in gathered.entries} | {
        uuid.UUID(item.document_id) for item in policy_input.diagnostic.excluded
    }
    if not relied_on:
        return
    authorized = set(
        db.scalars(
            select(Document.id)
            .where(
                Document.id.in_(relied_on),
                Document.institution_id == institution_id,
                role_authorized_sql(requester_role),
            )
            .order_by(Document.id)
            .with_for_update(read=True)
        ).all()
    )
    if authorized != relied_on:
        raise ConflictError(message_source_service.SOURCES_CHANGED_MESSAGE)


def _persist_turn(
    db: Session,
    *,
    run_id: uuid.UUID,
    started: float,
    user_id: uuid.UUID,
    institution_id: uuid.UUID,
    conversation_id: uuid.UUID,
    requester_role: str,
    reference_date: date,
    language: str,
    official_only: bool,
    query: str,
    user_content: str,
    clarification: _Clarification | None,
    policy_input: PolicyInput,
    decision: PolicyDecision,
    composed: ComposedTurn,
    cited_sources: list[AnswerSourceRead],
    gathered: _Gathered,
    procedure_evidence_ids: tuple[str, ...],
    estimator: DimensionEstimator,
    catalog: InstitutionDecisionCatalog,
    retriever: Retriever,
) -> ConversationDecisionResponse:
    db.rollback()
    try:
        institution = db.scalar(
            select(Institution)
            .where(Institution.id == institution_id, Institution.is_active.is_(True))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if institution is None:
            raise AuthenticationError("Invalid authentication token.")
        persisted_user = db.scalar(
            select(User)
            .where(
                User.id == user_id,
                User.institution_id == institution_id,
                User.is_active.is_(True),
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if persisted_user is None:
            raise AuthenticationError("Invalid authentication token.")
        if persisted_user.role != requester_role:
            raise ConflictError(ROLE_CHANGED_MESSAGE)
        conversation = conversation_service.get_accessible_conversation_by_identity(
            db,
            user_id=user_id,
            institution_id=institution_id,
            conversation_id=conversation_id,
            for_update=True,
        )
        if conversation.status != "active":
            msg = (
                f"Conversation '{conversation_id}' is {conversation.status} "
                "and does not accept new messages."
            )
            raise ConflictError(msg)

        snapshots = (
            message_source_service.revalidate_and_lock_sources(
                db,
                institution_id=institution_id,
                cited_sources=cited_sources,
                language=language,
                reference_date=reference_date,
                official_only=official_only,
                requester_role=persisted_user.role,
            )
            if cited_sources
            else ()
        )
        _lock_relied_on_documents(
            db,
            institution_id=institution_id,
            requester_role=persisted_user.role,
            gathered=gathered,
            policy_input=policy_input,
        )
        is_first_turn = (
            db.scalar(
                select(Message.id)
                .where(
                    Message.conversation_id == conversation.id,
                    Message.institution_id == conversation.institution_id,
                )
                .limit(1)
            )
            is None
        )

        user_created_at = datetime.now(UTC)
        user_metadata: dict[str, Any] = {"turn_type": TURN_TYPE_QUESTION}
        if clarification is not None:
            user_metadata["clarification_of"] = str(clarification.parent_message_id)
            user_metadata["selected_reading_id"] = clarification.reading_id
        user_message = Message(
            conversation_id=conversation.id,
            institution_id=conversation.institution_id,
            user_id=user_id,
            role="user",
            content=user_content,
            language=language,
            reply_to_message_id=None,
            extra_metadata=user_metadata,
            created_at=user_created_at,
        )
        db.add(user_message)
        db.flush()

        assistant_created_at = max(datetime.now(UTC), user_created_at + timedelta(microseconds=1))
        assistant_message = Message(
            conversation_id=conversation.id,
            institution_id=conversation.institution_id,
            user_id=None,
            role="assistant",
            content=composed.content,
            language=language,
            reply_to_message_id=user_message.id,
            extra_metadata=_public_metadata(decision, policy_input, composed, reference_date),
            created_at=assistant_created_at,
        )
        db.add(assistant_message)
        db.flush()
        if snapshots:
            message_source_service.create_message_sources(
                db, assistant_message=assistant_message, snapshots=snapshots
            )

        db.add(
            DecisionRecord(
                institution_id=institution_id,
                conversation_id=conversation.id,
                user_id=user_id,
                user_message_id=user_message.id,
                assistant_message_id=assistant_message.id,
                run_id=run_id,
                status="decided",
                action=decision.action.value,
                rule=decision.rule.value,
                policy_version=decision.policy_version,
                reference_date=reference_date,
                requester_role=requester_role,
                attempts=max(estimator.usage.attempts, 1),
                duration_ms=int((time.perf_counter() - started) * 1000),
                record={
                    "policy_input": policy_input_to_dict(policy_input),
                    "decision": decision.as_dict(),
                    "versions": _versions(estimator, catalog),
                    "retrieval": {
                        "retriever": type(retriever).__name__,
                        "top_k": settings.decision_retrieval_top_k,
                        "official_only": official_only,
                        "queries": gathered.queries,
                        "per_reading": gathered.per_reading,
                        "max_context_chars": settings.answering_max_context_chars,
                    },
                    "admissible_evidence": [
                        {
                            "evidence_id": entry.evidence_id,
                            "chunk_id": str(entry.evidence.chunk_id),
                            "document_id": str(entry.evidence.document_id),
                            "document_version_id": str(entry.evidence.document_version_id),
                            "content_sha256": hashlib.sha256(
                                entry.evidence.content.encode("utf-8")
                            ).hexdigest(),
                        }
                        for entry in gathered.entries
                    ],
                    "procedure_evidence_ids": list(procedure_evidence_ids),
                    "cited_evidence_ids": list(composed.cited_evidence_ids),
                    "generator_called": composed.generator_called,
                    "temporal_notice_shown": composed.temporal_notice_shown,
                    "clarification_of": None
                    if clarification is None
                    else str(clarification.parent_message_id),
                    "usage": {
                        "estimator": estimator.usage.as_dict(),
                        "generator": composed.generator_usage,
                        "cost_note": "monetary cost not computed: no tariff configured",
                    },
                    # Em operação não se calcula o snapshot do corpus (custo);
                    # a avaliação offline regista-os nos packets.
                    "snapshot_id": None,
                    "corpus_digest": None,
                    "estimate_origin": estimator.identity.origin.value,
                },
            )
        )
        if conversation.title is None and is_first_turn:
            conversation.title = derive_conversation_title(query)
        conversation.updated_at = assistant_created_at
        db.flush()
        db.commit()
    except Exception:
        db.rollback()
        raise

    db.refresh(user_message)
    db.refresh(assistant_message)
    persisted = {
        message.id: message
        for message in db.scalars(
            select(Message)
            .options(selectinload(Message.sources))
            .where(
                Message.id.in_((user_message.id, assistant_message.id)),
                Message.institution_id == institution_id,
            )
            .execution_options(populate_existing=True)
        ).all()
    }
    metadata = persisted[assistant_message.id].extra_metadata or {}
    destination = metadata.get("recommended_destination")
    return ConversationDecisionResponse(
        action=decision.action.value,
        rule=decision.rule.value,
        policy_version=decision.policy_version,
        message_version=MESSAGE_VERSION,
        conversation_id=conversation_id,
        user_message=MessageRead.model_validate(persisted[user_message.id]),
        assistant_message=MessageRead.model_validate(persisted[assistant_message.id]),
        clarification_options=[
            ClarificationOptionRead(**option)
            for option in metadata.get("clarification_options", [])
        ],
        destination=None if destination is None else RecommendedDestinationRead(**destination),
        gap_items=list(metadata.get("gap_items", [])),
        temporal_notice=bool(metadata.get("temporal_notice")),
    )
