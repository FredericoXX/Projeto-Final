from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.language import normalize_language_code

# Papéis previstos para uma mensagem nesta fase. Quem pode efetivamente
# usar cada role (ex.: "system" reservado a admins) é decidido no serviço,
# não aqui.
ALLOWED_ROLES = {"user", "assistant", "system"}


class MessageCreate(BaseModel):
    # conversation_id, institution_id e user_id não fazem parte deste
    # schema de propósito: vêm sempre do contexto da rota (conversa na
    # URL, utilizador autenticado), nunca do payload. extra="forbid"
    # torna o envio desses (ou de qualquer campo desconhecido) um 422.
    model_config = ConfigDict(extra="forbid")

    role: str = "user"
    content: str
    language: str | None = None

    @field_validator("role")
    @classmethod
    def validate_role(cls, value: str) -> str:
        if value not in ALLOWED_ROLES:
            msg = f"role must be one of {sorted(ALLOWED_ROLES)}"
            raise ValueError(msg)
        return value

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: str) -> str:
        if not value.strip():
            msg = "content must not be empty or whitespace only"
            raise ValueError(msg)
        return value

    @field_validator("language")
    @classmethod
    def normalize_language(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return normalize_language_code(value)


class MessageSourceRead(BaseModel):
    id: UUID
    evidence_id: str
    citation_index: int
    chunk_id: UUID
    document_id: UUID
    document_version_id: UUID
    document_title: str
    chunk_index: int
    source_url: str | None
    official_source: bool
    language: str
    valid_from: date | None
    valid_until: date | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MessageRead(BaseModel):
    id: UUID
    conversation_id: UUID
    institution_id: UUID
    user_id: UUID | None
    role: str
    content: str
    language: str | None
    reply_to_message_id: UUID | None = None
    extra_metadata: dict | None
    created_at: datetime
    sources: list[MessageSourceRead] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class MessageListResponse(BaseModel):
    items: list[MessageRead]
    total: int
    limit: int
    offset: int


class ConversationAskResponse(BaseModel):
    status: Literal["answered", "insufficient_evidence"]
    conversation_id: UUID
    user_message: MessageRead
    assistant_message: MessageRead
