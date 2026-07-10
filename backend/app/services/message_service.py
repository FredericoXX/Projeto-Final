import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import AuthorizationError
from app.models.message import Message
from app.models.user import User
from app.schemas.message import MessageCreate
from app.services.conversation_service import get_accessible_conversation

# Roles que cada tipo de utilizador pode usar ao criar uma mensagem por
# esta rota. "assistant" fica de fora de ambos os conjuntos: mensagens do
# assistente não são criadas manualmente nesta fase, apenas por um futuro
# agente/LLM.
ALLOWED_ROLES_FOR_USER = {"user"}
ALLOWED_ROLES_FOR_ADMIN = {"user", "system"}


def create_message(
    db: Session,
    current_user: User,
    conversation_id: uuid.UUID,
    data: MessageCreate,
) -> Message:
    # Garante isolamento institucional e de posse antes de sequer olhar
    # para o role pedido: uma conversa de outra instituição, ou de outro
    # utilizador, continua a devolver 404.
    conversation = get_accessible_conversation(db, current_user, conversation_id)

    allowed_roles = (
        ALLOWED_ROLES_FOR_ADMIN if current_user.role == "admin" else ALLOWED_ROLES_FOR_USER
    )
    if data.role not in allowed_roles:
        msg = f"role '{data.role}' is not allowed for this user."
        raise AuthorizationError(msg)

    message = Message(
        conversation_id=conversation.id,
        institution_id=conversation.institution_id,
        user_id=current_user.id,
        role=data.role,
        content=data.content,
        language=data.language,
    )
    db.add(message)
    db.commit()
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

    query = select(Message).where(Message.conversation_id == conversation.id)
    count_query = (
        select(func.count()).select_from(Message).where(Message.conversation_id == conversation.id)
    )

    total = db.scalar(count_query) or 0
    items = list(
        db.scalars(
            query.order_by(Message.created_at.asc(), Message.id.asc()).limit(limit).offset(offset)
        ).all()
    )
    return items, total
