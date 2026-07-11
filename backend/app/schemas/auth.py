from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, field_validator

FULL_NAME_MAX_LENGTH = 255
PASSWORD_MIN_LENGTH = 8


def _normalize_full_name(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        msg = "full_name must not be empty or whitespace only"
        raise ValueError(msg)
    if len(normalized) > FULL_NAME_MAX_LENGTH:
        msg = f"full_name must be at most {FULL_NAME_MAX_LENGTH} characters long"
        raise ValueError(msg)
    return normalized


class RegisterInitialAdminRequest(BaseModel):
    # extra="forbid" em todos os payloads de escrita: um campo desconhecido
    # (ou não atualizável por esta rota) devolve 422 em vez de ser ignorado
    # silenciosamente, evitando erros ocultos em clientes e integrações.
    model_config = ConfigDict(extra="forbid")

    institution_id: UUID
    full_name: str
    email: EmailStr
    password: str

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


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: str

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
