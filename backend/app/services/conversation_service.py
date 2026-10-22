import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError
from app.core.language import resolve_language
from app.models.conversation import Conversation
from app.models.user import User
from app.schemas.conversation import ConversationCreate, ConversationUpdate
from app.services import authorization_service
from app.services.institution_service import get_institution


def create_conversation(
    db: Session,
    institution_id: uuid.UUID,
    user_id: uuid.UUID,
    data: ConversationCreate,
) -> Conversation:
    # A conta é reconfirmada na transação que cria a conversa: uma desativação
    # concorrente já gravada é vista aqui, e uma posterior espera pelo commit.
    authorization_service.revalidate_actor(db, user_id=user_id, institution_id=institution_id)
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
    """Obtém uma conversa aplicando isolamento institucional e posse.

    Todas as contas — incluindo o admin institucional — acedem apenas às
    próprias conversas: nenhum papel lê conversas de terceiros (ver
    :mod:`app.core.permissions`). Uma conversa de outra instituição ou de
    outro utilizador responde como inexistente (404), sem revelar que existe.

    A conta é revalidada sob lock antes da procura, na mesma transação da
    leitura ou mutação que se segue. O fluxo de /ask e o handoff não passam por
    aqui: usam ``get_accessible_conversation_by_identity`` com a sua própria
    revalidação, para não manterem locks durante a geração.
    """
    authorization_service.revalidate_actor(
        db, user_id=current_user.id, institution_id=current_user.institution_id
    )
    return get_accessible_conversation_by_identity(
        db,
        user_id=current_user.id,
        institution_id=current_user.institution_id,
        conversation_id=conversation_id,
        for_update=for_update,
    )


def get_accessible_conversation_by_identity(
    db: Session,
    *,
    user_id: uuid.UUID,
    institution_id: uuid.UUID,
    conversation_id: uuid.UUID,
    for_update: bool = False,
) -> Conversation:
    """Aplica as regras de acesso usando apenas identidade escalar.

    O fluxo conversacional usa esta variante depois de terminar a transação
    de leitura do answering, evitando depender de objetos ORM expirados pelo
    rollback antes de bloquear novamente a conversa.
    """
    # A posse é incondicional: não depende do papel, e por isso uma alteração
    # concorrente de papel não pode alargar o conjunto de conversas visível.
    query = select(Conversation).where(
        Conversation.id == conversation_id,
        Conversation.institution_id == institution_id,
        Conversation.user_id == user_id,
    )
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
    authorization_service.revalidate_actor(
        db, user_id=current_user.id, institution_id=current_user.institution_id
    )
    # Listagem e contagem usam exatamente o mesmo filtro de instituição e
    # posse: o total nunca revela quantas conversas existem de outras contas.
    ownership = (
        Conversation.institution_id == current_user.institution_id,
        Conversation.user_id == current_user.id,
    )
    query = select(Conversation).where(*ownership)
    count_query = select(func.count()).select_from(Conversation).where(*ownership)

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
    # Lock da conversa: um fecho concorrente não é ultrapassado pela renomeação.
    conversation = get_accessible_conversation(db, current_user, conversation_id, for_update=True)

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
