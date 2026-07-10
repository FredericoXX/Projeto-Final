import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.models.conversation import Conversation
from app.models.user import User
from app.schemas.conversation import ConversationCreate, ConversationUpdate


def create_conversation(
    db: Session,
    institution_id: uuid.UUID,
    user_id: uuid.UUID,
    data: ConversationCreate,
) -> Conversation:
    conversation = Conversation(
        institution_id=institution_id,
        user_id=user_id,
        title=data.title,
        language=data.language,
        status="active",
    )
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return conversation


def get_accessible_conversation(
    db: Session,
    current_user: User,
    conversation_id: uuid.UUID,
) -> Conversation:
    """Fetch a conversation, enforcing institution isolation and per-role
    ownership: an admin can access any conversation in their institution,
    a regular user only their own. Any other case (wrong institution,
    someone else's conversation) reports as 404, never revealing that the
    conversation exists elsewhere."""
    query = select(Conversation).where(
        Conversation.id == conversation_id,
        Conversation.institution_id == current_user.institution_id,
    )
    if current_user.role != "admin":
        query = query.where(Conversation.user_id == current_user.id)

    conversation = db.scalar(query)
    if conversation is None:
        msg = f"Conversation '{conversation_id}' not found."
        raise NotFoundError(msg)
    return conversation


def list_conversations(
    db: Session,
    current_user: User,
    *,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[Conversation], int]:
    query = select(Conversation).where(Conversation.institution_id == current_user.institution_id)
    count_query = (
        select(func.count())
        .select_from(Conversation)
        .where(Conversation.institution_id == current_user.institution_id)
    )

    if current_user.role != "admin":
        query = query.where(Conversation.user_id == current_user.id)
        count_query = count_query.where(Conversation.user_id == current_user.id)

    total = db.scalar(count_query) or 0
    items = list(
        db.scalars(
            query.order_by(Conversation.created_at.desc(), Conversation.id.desc())
            .limit(limit)
            .offset(offset)
        ).all()
    )
    return items, total


def update_conversation(
    db: Session,
    current_user: User,
    conversation_id: uuid.UUID,
    data: ConversationUpdate,
) -> Conversation:
    conversation = get_accessible_conversation(db, current_user, conversation_id)

    changes = data.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(conversation, field, value)

    db.commit()
    db.refresh(conversation)
    return conversation
