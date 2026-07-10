from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, field_validator

FULL_NAME_MAX_LENGTH = 255
PASSWORD_MIN_LENGTH = 8

# Roles suportadas nesta fase; genérico e não específico de nenhuma instituição.
ALLOWED_ROLES = {"admin", "staff", "student", "user"}


def _normalize_full_name(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        msg = "full_name must not be empty or whitespace only"
        raise ValueError(msg)
    if len(normalized) > FULL_NAME_MAX_LENGTH:
        msg = f"full_name must be at most {FULL_NAME_MAX_LENGTH} characters long"
        raise ValueError(msg)
    return normalized


def _validate_role(value: str) -> str:
    if value not in ALLOWED_ROLES:
        msg = f"role must be one of {sorted(ALLOWED_ROLES)}"
        raise ValueError(msg)
    return value


class UserCreate(BaseModel):
    # institution_id não faz parte deste schema de propósito: é sempre
    # derivado do admin autenticado na rota, nunca aceite do payload.
    full_name: str
    email: EmailStr
    password: str
    role: str = "user"

    @field_validator("full_name")
    @classmethod
    def normalize_full_name(cls, value: str) -> str:
        return _normalize_full_name(value)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        if len(value) < PASSWORD_MIN_LENGTH:
            msg = f"password must be at least {PASSWORD_MIN_LENGTH} characters long"
            raise ValueError(msg)
        return value

    @field_validator("role")
    @classmethod
    def validate_role(cls, value: str) -> str:
        return _validate_role(value)


class UserUpdate(BaseModel):
    # Todos os campos são opcionais para suportar atualizações parciais (PATCH).
    # institution_id e password não são atualizáveis por esta rota.
    full_name: str | None = None
    email: EmailStr | None = None
    role: str | None = None
    is_active: bool | None = None

    @field_validator("full_name")
    @classmethod
    def normalize_full_name(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return _normalize_full_name(value)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return value.strip().lower()

    @field_validator("role")
    @classmethod
    def validate_role(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return _validate_role(value)


class UserRead(BaseModel):
    # password_hash nunca é exposto nesta resposta.
    id: UUID
    institution_id: UUID
    full_name: str
    email: str
    role: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class UserListResponse(BaseModel):
    items: list[UserRead]
    total: int
    limit: int
    offset: int
