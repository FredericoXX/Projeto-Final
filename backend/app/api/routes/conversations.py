import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_user
from app.database.session import get_db
from app.models.user import User
from app.schemas.conversation import (
    ConversationCreate,
    ConversationListResponse,
    ConversationRead,
    ConversationUpdate,
)
from app.schemas.message import MessageCreate, MessageListResponse, MessageRead
from app.services import conversation_service, message_service

# Todas as rotas exigem um utilizador autenticado (get_current_user). O
# isolamento multi-institucional e a regra de posse (utilizador comum vs.
# admin) são aplicados nos serviços, com base em current_user.
router = APIRouter(prefix="/conversations", tags=["Conversations"])


@router.post("", response_model=ConversationRead, status_code=status.HTTP_201_CREATED)
def create_conversation(
    payload: ConversationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ConversationRead:
    # institution_id e user_id vêm sempre do utilizador autenticado,
    # nunca do payload.
    conversation = conversation_service.create_conversation(
        db, current_user.institution_id, current_user.id, payload
    )
    return ConversationRead.model_validate(conversation)


@router.get("", response_model=ConversationListResponse)
def list_conversations(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ConversationListResponse:
    items, total = conversation_service.list_conversations(
        db, current_user, limit=limit, offset=offset
    )
    return ConversationListResponse(
        items=[ConversationRead.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{conversation_id}", response_model=ConversationRead)
def get_conversation(
    conversation_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ConversationRead:
    conversation = conversation_service.get_accessible_conversation(
        db, current_user, conversation_id
    )
    return ConversationRead.model_validate(conversation)


@router.patch("/{conversation_id}", response_model=ConversationRead)
def update_conversation(
    conversation_id: uuid.UUID,
    payload: ConversationUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ConversationRead:
    conversation = conversation_service.update_conversation(
        db, current_user, conversation_id, payload
    )
    return ConversationRead.model_validate(conversation)


@router.post(
    "/{conversation_id}/messages",
    response_model=MessageRead,
    status_code=status.HTTP_201_CREATED,
)
def create_message(
    conversation_id: uuid.UUID,
    payload: MessageCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MessageRead:
    message = message_service.create_message(db, current_user, conversation_id, payload)
    return MessageRead.model_validate(message)


@router.get("/{conversation_id}/messages", response_model=MessageListResponse)
def list_messages(
    conversation_id: uuid.UUID,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MessageListResponse:
    items, total = message_service.list_messages(
        db, current_user, conversation_id, limit=limit, offset=offset
    )
    return MessageListResponse(
        items=[MessageRead.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )
