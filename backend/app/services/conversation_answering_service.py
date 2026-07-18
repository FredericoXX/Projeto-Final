"""Persistência transacional de um turno conversacional fundamentado."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.answering.base import AnswerGenerator, InvalidGeneratedAnswerError
from app.answering.validation import INVALID_ANSWER_MESSAGE
from app.core.conversation_title import derive_conversation_title
from app.core.exceptions import AuthenticationError, ConflictError
from app.models.institution import Institution
from app.models.message import Message
from app.models.user import User
from app.retrieval.base import Retriever
from app.schemas.answering import AnsweringRequest
from app.schemas.message import ConversationAskResponse, MessageRead
from app.services import answering_service, conversation_service, message_source_service


def _ensure_active(conversation_id: UUID, status: str) -> None:
    if status != "active":
        msg = f"Conversation '{conversation_id}' is {status} and does not accept new messages."
        raise ConflictError(msg)


def ask_in_conversation(
    db: Session,
    current_user: User,
    conversation_id: UUID,
    payload: AnsweringRequest,
    retriever: Retriever,
    generator: AnswerGenerator,
) -> ConversationAskResponse:
    """Gera primeiro e persiste depois as duas mensagens num único commit."""
    # Captura apenas escalares antes do rollback que separa a transação de
    # leitura/fornecedor da transação curta de persistência.
    user_id = current_user.id
    institution_id = current_user.institution_id
    user_role = current_user.role

    conversation = conversation_service.get_accessible_conversation_by_identity(
        db,
        user_id=user_id,
        institution_id=institution_id,
        user_role=user_role,
        conversation_id=conversation_id,
    )
    _ensure_active(conversation.id, conversation.status)
    fallback_language = conversation.language

    answer = answering_service.ask(
        db,
        current_user,
        payload,
        retriever,
        generator,
        fallback_language=fallback_language,
    )
    query = payload.query
    reference_date = datetime.now(UTC).date()

    # Nenhum write foi feito até aqui. O rollback termina a transação de
    # leitura e liberta qualquer snapshot antes dos SELECT FOR UPDATE.
    db.rollback()

    try:
        # Ordem compatível com as mutações administrativas: instituição,
        # utilizador e só depois conversa. Os locks permanecem até ao commit,
        # fechando a janela entre revalidar role/estado e autorizar o turno.
        persisted_institution = db.scalar(
            select(Institution)
            .where(
                Institution.id == institution_id,
                Institution.is_active.is_(True),
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if persisted_institution is None:
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

        locked_conversation = conversation_service.get_accessible_conversation_by_identity(
            db,
            user_id=user_id,
            institution_id=institution_id,
            user_role=persisted_user.role,
            conversation_id=conversation_id,
            for_update=True,
        )
        _ensure_active(locked_conversation.id, locked_conversation.status)

        # "Primeiro turno" é decidido pela existência de mensagens
        # persistidas (não apenas por title is null): uma conversa com
        # histórico nunca volta a ser titulada automaticamente, mesmo que
        # um cliente antigo tenha limpado o título entretanto. Avaliado
        # sob o lock da conversa, antes de qualquer insert deste turno.
        is_first_turn = (
            db.scalar(
                select(Message.id)
                .where(
                    Message.conversation_id == locked_conversation.id,
                    Message.institution_id == locked_conversation.institution_id,
                )
                .limit(1)
            )
            is None
        )

        if answer.status == "answered":
            snapshots = message_source_service.revalidate_and_lock_sources(
                db,
                institution_id=institution_id,
                cited_sources=answer.sources,
                language=answer.language,
                reference_date=reference_date,
                official_only=payload.official_only,
            )
        else:
            if answer.sources:
                raise InvalidGeneratedAnswerError(
                    INVALID_ANSWER_MESSAGE,
                    reason_code="fallback_with_sources",
                    invalid_count=len(answer.sources),
                )
            snapshots = ()

        user_created_at = datetime.now(UTC)
        user_message = Message(
            conversation_id=locked_conversation.id,
            institution_id=locked_conversation.institution_id,
            user_id=user_id,
            role="user",
            content=query,
            language=answer.language,
            reply_to_message_id=None,
            extra_metadata={"turn_type": "institutional_question"},
            created_at=user_created_at,
        )
        db.add(user_message)
        db.flush()

        assistant_created_at = max(
            datetime.now(UTC),
            user_created_at + timedelta(microseconds=1),
        )
        assistant_message = Message(
            conversation_id=locked_conversation.id,
            institution_id=locked_conversation.institution_id,
            user_id=None,
            role="assistant",
            content=answer.answer,
            language=answer.language,
            reply_to_message_id=user_message.id,
            extra_metadata={"answer_status": answer.status},
            created_at=assistant_created_at,
        )
        db.add(assistant_message)
        db.flush()

        if answer.status == "answered":
            message_source_service.create_message_sources(
                db,
                assistant_message=assistant_message,
                snapshots=snapshots,
            )

        # Título automático apenas no primeiro turno de uma conversa ainda
        # sem título: derivado localmente da pergunta original (sem LLM) e
        # persistido na MESMA transação das mensagens/fontes — qualquer
        # falha até ao commit faz rollback do título junto com o turno.
        # Título manual (na criação, renomeado ou já gerado) nunca é
        # substituído.
        if locked_conversation.title is None and is_first_turn:
            locked_conversation.title = derive_conversation_title(query)

        # Atividade recente: o horário do turno persistido, explícito
        # porque o onupdate implícito não dispara quando nenhuma coluna da
        # conversa muda (turnos seguintes sem alteração de título).
        locked_conversation.updated_at = assistant_created_at

        db.flush()
        db.commit()
    except Exception:
        db.rollback()
        raise

    # Refresh explícito e eager load numa única query para devolver as duas
    # mensagens com sources ordenadas sem N+1.
    db.refresh(user_message)
    db.refresh(assistant_message)
    persisted = list(
        db.scalars(
            select(Message)
            .options(selectinload(Message.sources))
            .where(
                Message.id.in_((user_message.id, assistant_message.id)),
                Message.institution_id == institution_id,
            )
            .execution_options(populate_existing=True)
        ).all()
    )
    by_id = {message.id: message for message in persisted}
    return ConversationAskResponse(
        status=answer.status,
        conversation_id=conversation_id,
        user_message=MessageRead.model_validate(by_id[user_message.id]),
        assistant_message=MessageRead.model_validate(by_id[assistant_message.id]),
    )
