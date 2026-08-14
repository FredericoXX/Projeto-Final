"""Encaminhamento humano E1 — capacidade de escalar, não política de escalar.

Este service torna ``DecisionOutcome.ESCALATE`` um desfecho operacional real:
regista o encaminhamento, o destino designado e apresenta-o ao utilizador
(nível E1 de A2.2, secção 7.6.1). O que **não** faz, e não deve passar a fazer
sem decisão própria:

- não decide *quando* escalar. A única origem implementada é
  ``user_requested``: o utilizador autenticado pede explicitamente atendimento
  humano. Não existe ``DecisionPolicy``, ``AnswerabilityEvaluator``, nem
  classificação da pergunta por palavras-chave;
- não cria caso, ticket, fila, atribuição, SLA nem notificação interna. Isso
  seria E2 e exige decisão institucional (A2.2, O6);
- não escolhe entre destinos. Existe um único destino default por instituição.

E1 é inteiramente determinístico: sem Retriever, sem AnswerGenerator, sem SDK
de fornecedor e sem qualquer chamada externa. Este módulo não importa nada de
``app.retrieval`` nem de ``app.answering``, e é essa ausência que o teste
``test_handoff_never_touches_retriever_or_generator`` fixa.
"""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import AuthenticationError, ConflictError
from app.core.handoff_message import (
    HANDOFF_MESSAGE_VERSION,
    HumanSupportDestination,
    build_handoff_message,
)
from app.decision.contracts import DecisionOutcome
from app.models.institution import Institution
from app.models.message import Message
from app.models.user import User
from app.schemas.handoff import (
    HANDOFF_OUTCOME,
    ConversationHandoffResponse,
    HumanHandoffDestinationRead,
)
from app.schemas.message import MessageRead
from app.services import conversation_service

# Única origem implementada nesta fase. Um valor como "system_decision" é
# deliberadamente reservado a uma DecisionPolicy futura e não tem produtor:
# o trigger é sempre determinado pelo backend a partir do endpoint usado,
# nunca aceite do cliente.
HANDOFF_TRIGGER_USER_REQUESTED = "user_requested"

# Nível de maturidade do encaminhamento (A2.2, 7.6.1). Persistido para que
# uma mensagem histórica continue interpretável se E2 vier a existir.
HANDOFF_MODE_E1 = "e1"

HUMAN_SUPPORT_NOT_CONFIGURED_MESSAGE = "Human support is not configured for this institution."


def _ensure_active(conversation_id: UUID, status: str) -> None:
    # Mesmo comportamento de conflito do turno conversacional: closed e
    # archived são estados finais e não recebem mensagens novas.
    if status != "active":
        msg = f"Conversation '{conversation_id}' is {status} and does not accept new messages."
        raise ConflictError(msg)


def _resolve_destination(institution: Institution) -> HumanSupportDestination:
    """Lê o destino da instituição já bloqueada, ou recusa a operação.

    Uma instituição sem atendimento humano configurado é um conflito com o
    estado atual do recurso (409), não um erro do pedido nem uma falha do
    servidor: o pedido é válido e a capacidade existe — falta a configuração
    institucional. A mensagem é pública e não revela nada além disso.
    """
    name = institution.human_support_name
    email = institution.human_support_email
    url = institution.human_support_url
    if name is None or (email is None and url is None):
        raise ConflictError(HUMAN_SUPPORT_NOT_CONFIGURED_MESSAGE)
    return HumanSupportDestination(name=name, email=email, url=url)


def request_human_handoff(
    db: Session,
    current_user: User,
    conversation_id: UUID,
) -> ConversationHandoffResponse:
    """Encaminha explicitamente a conversa para atendimento humano.

    Transação única e curta — não há chamada externa a isolar, ao contrário de
    ``ask_in_conversation``. A ordem dos locks é exatamente a mesma desse fluxo
    e das mutações administrativas — **instituição → utilizador → conversa** —,
    para que os caminhos não possam entrar em deadlock.

    Os três locks fecham janelas distintas, e nenhum é decorativo:

    - a **instituição** torna o snapshot do destino coerente: uma alteração
      administrativa concorrente fica serializada, e a mensagem regista o
      destino que foi efetivamente apresentado;
    - o **utilizador** é relido e bloqueado porque ``current_user`` foi lido na
      autenticação, num statement anterior. Em READ COMMITTED, uma desativação
      ou despromoção que faça commit entretanto não seria visível a esta
      transação, e o handoff completaria com identidade obsoleta. O papel usado
      a seguir é o **persistido**, não o que veio do token: um admin
      despromovido concorrentemente não deve continuar a alcançar conversas de
      outros utilizadores;
    - a **conversa** garante que um fecho concorrente não é ultrapassado.
    """
    user_id = current_user.id
    institution_id = current_user.institution_id

    try:
        institution = db.scalar(
            select(Institution)
            .where(
                Institution.id == institution_id,
                Institution.is_active.is_(True),
            )
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

        conversation = conversation_service.get_accessible_conversation_by_identity(
            db,
            user_id=user_id,
            institution_id=institution_id,
            user_role=persisted_user.role,
            conversation_id=conversation_id,
            for_update=True,
        )
        _ensure_active(conversation.id, conversation.status)

        # Validado só depois do acesso e do estado: uma conversa de outro
        # tenant continua a responder 404 independentemente de a instituição
        # do atacante ter — ou não — atendimento humano configurado.
        destination = _resolve_destination(institution)

        language = conversation.language or institution.default_language
        created_at = datetime.now(UTC)
        assistant_message = Message(
            conversation_id=conversation.id,
            institution_id=conversation.institution_id,
            # Mensagem automática sem autor humano, como as do fluxo de
            # respostas. O clique não fabrica uma mensagem de utilizador: o
            # pedido já está representado pela chamada ao endpoint.
            user_id=None,
            role="assistant",
            content=build_handoff_message(language, destination),
            language=language,
            # Não responde a uma mensagem concreta: o encaminhamento é sobre a
            # conversa, e apontar para a última pergunta afirmaria uma relação
            # causal que o utilizador não declarou.
            reply_to_message_id=None,
            extra_metadata={
                "turn_type": "human_handoff",
                "decision_outcome": DecisionOutcome.ESCALATE.value,
                "handoff_mode": HANDOFF_MODE_E1,
                "handoff_trigger": HANDOFF_TRIGGER_USER_REQUESTED,
                "message_version": HANDOFF_MESSAGE_VERSION,
                # Snapshot, não referência: alterar a configuração da
                # instituição depois disto não reescreve esta mensagem.
                "handoff_destination": {
                    "name": destination.name,
                    "email": destination.email,
                    "url": destination.url,
                },
            },
            created_at=created_at,
        )
        db.add(assistant_message)
        db.flush()

        # Mesma semântica de atividade recente dos turnos persistidos: a
        # conversa sobe na listagem por ter tido atividade.
        conversation.updated_at = created_at

        db.flush()
        db.commit()
    except Exception:
        db.rollback()
        raise

    # Uma única mensagem, sem fontes: o refresh chega e não há N+1 a evitar,
    # ao contrário do turno de /ask, que devolve duas mensagens com citações.
    db.refresh(assistant_message)

    return ConversationHandoffResponse(
        outcome=HANDOFF_OUTCOME,
        conversation_id=conversation_id,
        destination=HumanHandoffDestinationRead(
            name=destination.name,
            email=destination.email,
            url=destination.url,
        ),
        assistant_message=MessageRead.model_validate(assistant_message),
    )
