"""Contrato HTTP do encaminhamento humano E1.

Contrato **próprio**, deliberadamente separado de ``AnsweringResponse`` e de
``ConversationAskResponse``: ``/ask`` continua a declarar exatamente
``answered`` / ``insufficient_evidence``, e nada nesta fase acrescenta um
estado novo à API caracterizada no Momento 6.

Não existe schema de pedido. O corpo é vazio por desenho: o único parâmetro
concebível seria o destino ou o motivo, e ambos são decididos pelo backend a
partir do utilizador autenticado e da configuração da própria instituição.
"""

from typing import Final, Literal
from uuid import UUID

from pydantic import BaseModel

from app.schemas.message import MessageRead

# Ponto único onde o valor público do desfecho é escrito. O service constrói a
# resposta a partir daqui em vez de repetir a string, e um teste fixa a
# igualdade com ``DecisionOutcome.ESCALATE.value`` — que é o que impede os dois
# de divergirem sem que nada falhe.
HANDOFF_OUTCOME: Final[Literal["escalate"]] = "escalate"


class HumanHandoffDestinationRead(BaseModel):
    """Destino apresentado ao utilizador, em campos próprios.

    Existe para que o cliente não tenha de interpretar ``extra_metadata`` da
    mensagem para obter os contactos. O snapshot persistido continua a ser a
    fonte de verdade histórica; isto é a mesma informação na resposta imediata.
    """

    name: str
    email: str | None
    url: str | None


class ConversationHandoffResponse(BaseModel):
    # Literal em vez de importar DecisionOutcome: o padrão dos schemas
    # públicos deste projeto é o Literal, e o schema não deve depender do
    # módulo de contratos de decisão. A coerência entre os dois valores é
    # fixada por teste (tests/test_human_handoff.py).
    outcome: Literal["escalate"]
    conversation_id: UUID
    destination: HumanHandoffDestinationRead
    assistant_message: MessageRead
