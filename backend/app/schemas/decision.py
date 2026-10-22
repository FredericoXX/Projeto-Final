"""Contratos HTTP do modo experimental da política de decisão v1.7.

Contratos **próprios**, separados de ``AnsweringResponse`` e de
``ConversationAskResponse``: o B0 (``/ask``) continua a declarar exatamente
``answered`` / ``insufficient_evidence``. Aqui expõe-se apenas o que é público
e seguro — ação, regra, versões, opções de clarificação, destino recomendado e
itens não suportados. As dimensões estimadas, as evidências admissíveis não
citadas e o diagnóstico detalhado ficam no registo interno protegido
(``decision_records``), sem endpoint de leitura.
"""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.language import normalize_language_code
from app.schemas.message import MessageRead

DecisionAction = Literal["answer", "clarify", "abstain", "escalate"]
DecisionRule = Literal[
    "R01", "R02", "R03", "R04", "R05", "R06", "R07", "R08", "R09", "R10", "R11", "R12"
]


class ClarificationSelection(BaseModel):
    """Escolha de uma leitura apresentada num CLARIFY anterior da conversa."""

    model_config = ConfigDict(extra="forbid")

    message_id: UUID
    reading_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,32}$")]


class DecisionTurnRequest(BaseModel):
    """Exatamente um de ``query`` (pedido novo) ou ``clarification``.

    Como no B0, ``institution_id``, ``user_id`` e o papel nunca fazem parte do
    pedido: vêm da identidade autenticada e revalidada.
    """

    model_config = ConfigDict(extra="forbid")

    query: Annotated[str, Field(min_length=1, max_length=1000)] | None = None
    clarification: ClarificationSelection | None = None
    language: str | None = None
    official_only: bool = True

    @field_validator("query", mode="before")
    @classmethod
    def trim_query(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("language")
    @classmethod
    def normalize_language(cls, value: str | None) -> str | None:
        return None if value is None else normalize_language_code(value)

    @model_validator(mode="after")
    def exactly_one_input(self) -> "DecisionTurnRequest":
        if (self.query is None) == (self.clarification is None):
            msg = "provide exactly one of query or clarification"
            raise ValueError(msg)
        return self


class ClarificationOptionRead(BaseModel):
    reading_id: str
    label: str


class RecommendedDestinationRead(BaseModel):
    """Serviço competente do catálogo, como recomendação (E1)."""

    service_id: str
    name: str
    email: str | None
    url: str | None


class ConversationDecisionResponse(BaseModel):
    action: DecisionAction
    rule: DecisionRule
    policy_version: str
    message_version: str
    conversation_id: UUID
    user_message: MessageRead
    assistant_message: MessageRead
    clarification_options: list[ClarificationOptionRead]
    destination: RecommendedDestinationRead | None
    gap_items: list[str]
    temporal_notice: bool


class DecisionStatusRead(BaseModel):
    """Se o modo experimental pode ser usado por esta conta, agora."""

    enabled: bool
    policy_version: str
    catalog_configured: bool
