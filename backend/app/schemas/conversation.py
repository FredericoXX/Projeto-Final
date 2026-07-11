from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator

from app.core.language import normalize_language_code

TITLE_MAX_LENGTH = 255

# Estados previstos para uma conversa nesta fase. "closed" e "archived" são
# estados finais neste protótipo: não aceitam novas mensagens nem PATCH, e
# não existe (ainda) um endpoint para reabrir uma conversa.
ALLOWED_STATUSES = {"active", "closed", "archived"}


def _normalize_title(value: str | None) -> str | None:
    if value is None:
        return value
    normalized = value.strip()
    if not normalized:
        msg = "title must not be empty or whitespace only"
        raise ValueError(msg)
    if len(normalized) > TITLE_MAX_LENGTH:
        msg = f"title must be at most {TITLE_MAX_LENGTH} characters long"
        raise ValueError(msg)
    return normalized


def _normalize_language(value: str | None) -> str | None:
    if value is None:
        return value
    return normalize_language_code(value)


def _validate_status(value: str) -> str:
    if value not in ALLOWED_STATUSES:
        msg = f"status must be one of {sorted(ALLOWED_STATUSES)}"
        raise ValueError(msg)
    return value


class ConversationCreate(BaseModel):
    # institution_id e user_id não fazem parte deste schema de propósito:
    # são sempre derivados do utilizador autenticado na rota, nunca
    # aceites a partir do payload.
    title: str | None = None
    language: str | None = None

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str | None) -> str | None:
        return _normalize_title(value)

    @field_validator("language")
    @classmethod
    def normalize_language(cls, value: str | None) -> str | None:
        return _normalize_language(value)


class ConversationUpdate(BaseModel):
    # Todos os campos são opcionais para suportar atualizações parciais
    # (PATCH). institution_id e user_id nunca são atualizáveis por aqui.
    title: str | None = None
    status: str | None = None

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str | None) -> str | None:
        return _normalize_title(value)

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return _validate_status(value)


class ConversationRead(BaseModel):
    id: UUID
    institution_id: UUID
    user_id: UUID
    title: str | None
    language: str | None
    status: str
    extra_metadata: dict | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ConversationListResponse(BaseModel):
    items: list[ConversationRead]
    total: int
    limit: int
    offset: int
