from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator

LANGUAGE_MAX_LENGTH = 8

# Papéis previstos para uma mensagem nesta fase. Quem pode efetivamente
# usar cada role (ex.: "system" reservado a admins) é decidido no serviço,
# não aqui.
ALLOWED_ROLES = {"user", "assistant", "system"}


class MessageCreate(BaseModel):
    # conversation_id, institution_id e user_id não fazem parte deste
    # schema de propósito: vêm sempre do contexto da rota (conversa na
    # URL, utilizador autenticado), nunca do payload.
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
        normalized = value.strip().lower()
        if not normalized:
            msg = "language must not be empty or whitespace only"
            raise ValueError(msg)
        if len(normalized) > LANGUAGE_MAX_LENGTH:
            msg = f"language must be at most {LANGUAGE_MAX_LENGTH} characters long"
            raise ValueError(msg)
        return normalized


class MessageRead(BaseModel):
    id: UUID
    conversation_id: UUID
    institution_id: UUID
    user_id: UUID | None
    role: str
    content: str
    language: str | None
    extra_metadata: dict | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MessageListResponse(BaseModel):
    items: list[MessageRead]
    total: int
    limit: int
    offset: int
