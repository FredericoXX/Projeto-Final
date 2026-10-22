import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.exceptions import AuthenticationError, AuthorizationError, ConflictError
from app.core.language import resolve_language
from app.core.permissions import Permission, has_permission
from app.models.institution import Institution
from app.models.message import Message
from app.models.user import User
from app.schemas.message import MessageCreate
from app.services.conversation_service import (
    get_accessible_conversation,
    get_accessible_conversation_by_identity,
)

# Roles de mensagem que uma conta pode usar ao criar uma mensagem por esta
# rota. "assistant" nunca é aceite: mensagens do assistente pertencem
# exclusivamente ao fluxo interno de answering. "system" exige a permissão
# CONVERSATION_SYSTEM_MESSAGES da matriz central.
ALLOWED_ROLES_FOR_USER = {"user"}
ALLOWED_ROLES_WITH_SYSTEM_MESSAGES = {"user", "system"}


def _allowed_message_roles(account_role: str) -> set[str]:
    if has_permission(account_role, Permission.CONVERSATION_SYSTEM_MESSAGES):
        return ALLOWED_ROLES_WITH_SYSTEM_MESSAGES
    return ALLOWED_ROLES_FOR_USER


def create_message(
    db: Session,
    current_user: User,
    conversation_id: uuid.UUID,
    data: MessageCreate,
) -> Message:
    user_id = current_user.id
    institution_id = current_user.institution_id

    try:
        # Mesma ordem de locks do turno conversacional e do handoff —
        # instituição → utilizador → conversa. current_user foi lido na
        # autenticação, num statement anterior: sem reler a linha, uma
        # desativação ou alteração de papel concorrente não seria visível, e
        # uma conta despromovida ainda conseguiria escrever role="system".
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

        # Garante isolamento institucional e de posse antes de sequer olhar
        # para o role pedido: uma conversa de outra instituição, ou de outro
        # utilizador, continua a devolver 404.
        conversation = get_accessible_conversation_by_identity(
            db,
            user_id=user_id,
            institution_id=institution_id,
            conversation_id=conversation_id,
            for_update=True,
        )

        # closed e archived são estados finais neste protótipo: não aceitam
        # novas mensagens.
        if conversation.status != "active":
            msg = (
                f"Conversation '{conversation_id}' is {conversation.status} "
                "and does not accept new messages."
            )
            raise ConflictError(msg)

        if data.role not in _allowed_message_roles(persisted_user.role):
            msg = f"role '{data.role}' is not allowed for this user."
            raise AuthorizationError(msg)

        language = resolve_language(
            data.language,
            supported_languages=institution.supported_languages,
            fallback=conversation.language or institution.default_language,
        )

        message = Message(
            conversation_id=conversation.id,
            institution_id=conversation.institution_id,
            user_id=user_id,
            role=data.role,
            content=data.content,
            language=language,
        )
        db.add(message)
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(message)
    return message


def list_messages(
    db: Session,
    current_user: User,
    conversation_id: uuid.UUID,
    *,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[Message], int]:
    conversation = get_accessible_conversation(db, current_user, conversation_id)

    query = (
        select(Message)
        .options(selectinload(Message.sources))
        .where(
            Message.conversation_id == conversation.id,
            Message.institution_id == conversation.institution_id,
        )
    )
    count_query = (
        select(func.count())
        .select_from(Message)
        .where(
            Message.conversation_id == conversation.id,
            Message.institution_id == conversation.institution_id,
        )
    )

    total = db.scalar(count_query) or 0
    items = list(
        db.scalars(
            query.order_by(Message.created_at.asc(), Message.id.asc()).limit(limit).offset(offset)
        ).all()
    )
    return items, total
