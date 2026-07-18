import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError
from app.core.language import resolve_language
from app.models.conversation import Conversation
from app.models.user import User
from app.schemas.conversation import ConversationCreate, ConversationUpdate
from app.services.institution_service import get_institution


def create_conversation(
    db: Session,
    institution_id: uuid.UUID,
    user_id: uuid.UUID,
    data: ConversationCreate,
) -> Conversation:
    institution = get_institution(db, institution_id)
    language = resolve_language(
        data.language,
        supported_languages=institution.supported_languages,
        fallback=institution.default_language,
    )

    conversation = Conversation(
        institution_id=institution_id,
        user_id=user_id,
        title=data.title,
        language=language,
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
    *,
    for_update: bool = False,
) -> Conversation:
    """Fetch a conversation, enforcing institution isolation and per-role
    ownership: an admin can access any conversation in their institution,
    a regular user only their own. Any other case (wrong institution,
    someone else's conversation) reports as 404, never revealing that the
    conversation exists elsewhere."""
    return get_accessible_conversation_by_identity(
        db,
        user_id=current_user.id,
        institution_id=current_user.institution_id,
        user_role=current_user.role,
        conversation_id=conversation_id,
        for_update=for_update,
    )


def get_accessible_conversation_by_identity(
    db: Session,
    *,
    user_id: uuid.UUID,
    institution_id: uuid.UUID,
    user_role: str,
    conversation_id: uuid.UUID,
    for_update: bool = False,
) -> Conversation:
    """Aplica as regras de acesso usando apenas identidade escalar.

    O fluxo conversacional usa esta variante depois de terminar a transação
    de leitura do answering, evitando depender de objetos ORM expirados pelo
    rollback antes de bloquear novamente a conversa.
    """
    query = select(Conversation).where(
        Conversation.id == conversation_id,
        Conversation.institution_id == institution_id,
    )
    if user_role != "admin":
        query = query.where(Conversation.user_id == user_id)
    if for_update:
        query = query.with_for_update()

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
    # Ordenação por atividade recente (comportamento de chat): updated_at
    # é atualizado explicitamente em cada turno persistido, por isso a
    # conversa usada há menos tempo sobe para o topo; id desc desempata
    # deterministicamente.
    items = list(
        db.scalars(
            query.order_by(Conversation.updated_at.desc(), Conversation.id.desc())
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

    # closed e archived são estados finais neste protótipo: nunca voltam
    # a active nem aceitam novas mensagens. A única alteração permitida
    # nesses estados é renomear (payload apenas com title); qualquer
    # payload que toque no status é recusado por inteiro — um pedido com
    # title e status não altera nada, nem sequer o título.
    if conversation.status != "active" and "status" in changes:
        msg = f"Conversation '{conversation_id}' is {conversation.status} and cannot be updated."
        raise ConflictError(msg)

    for field, value in changes.items():
        setattr(conversation, field, value)

    db.commit()
    db.refresh(conversation)
    return conversation
