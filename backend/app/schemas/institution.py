from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

NAME_MAX_LENGTH = 255
CODE_MAX_LENGTH = 50
DOMAIN_MAX_LENGTH = 255
LANGUAGE_MIN_LENGTH = 2
LANGUAGE_MAX_LENGTH = 8
MAX_SUPPORTED_LANGUAGES = 20


def _normalize_language(value: str) -> str:
    normalized = value.strip().lower().replace("_", "-")
    if not (LANGUAGE_MIN_LENGTH <= len(normalized) <= LANGUAGE_MAX_LENGTH):
        msg = (
            f"language must be between {LANGUAGE_MIN_LENGTH} and "
            f"{LANGUAGE_MAX_LENGTH} characters long"
        )
        raise ValueError(msg)
    return normalized


def _normalize_language_list(value: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for language in value:
        candidate = _normalize_language(language)
        if candidate not in seen:
            seen.add(candidate)
            normalized.append(candidate)
    if not normalized:
        msg = "supported_languages must contain at least one language"
        raise ValueError(msg)
    if len(normalized) > MAX_SUPPORTED_LANGUAGES:
        msg = f"supported_languages must contain at most {MAX_SUPPORTED_LANGUAGES} languages"
        raise ValueError(msg)
    return normalized


class InstitutionBase(BaseModel):
    name: str
    code: str
    domain: str | None = None
    default_language: str
    supported_languages: list[str]
    is_active: bool = True

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            msg = "name must not be empty or whitespace only"
            raise ValueError(msg)
        if len(normalized) > NAME_MAX_LENGTH:
            msg = f"name must be at most {NAME_MAX_LENGTH} characters long"
            raise ValueError(msg)
        return normalized

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            msg = "code must not be empty or whitespace only"
            raise ValueError(msg)
        if len(normalized) > CODE_MAX_LENGTH:
            msg = f"code must be at most {CODE_MAX_LENGTH} characters long"
            raise ValueError(msg)
        return normalized

    @field_validator("domain")
    @classmethod
    def normalize_domain(cls, value: str | None) -> str | None:
        if value is None:
            return value
        normalized = value.strip()
        if not normalized:
            msg = "domain must not be empty or whitespace only"
            raise ValueError(msg)
        if len(normalized) > DOMAIN_MAX_LENGTH:
            msg = f"domain must be at most {DOMAIN_MAX_LENGTH} characters long"
            raise ValueError(msg)
        return normalized

    @field_validator("default_language")
    @classmethod
    def normalize_default_language(cls, value: str) -> str:
        return _normalize_language(value)

    @field_validator("supported_languages")
    @classmethod
    def normalize_supported_languages(cls, value: list[str]) -> list[str]:
        return _normalize_language_list(value)


class InstitutionCreate(InstitutionBase):
    @model_validator(mode="after")
    def check_default_language_is_supported(self) -> "InstitutionCreate":
        if self.default_language not in self.supported_languages:
            msg = "default_language must be one of supported_languages"
            raise ValueError(msg)
        return self


class InstitutionUpdate(BaseModel):
    name: str | None = None
    code: str | None = None
    domain: str | None = None
    default_language: str | None = None
    supported_languages: list[str] | None = None
    is_active: bool | None = None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        if value is None:
            return value
        normalized = value.strip()
        if not normalized:
            msg = "name must not be empty or whitespace only"
            raise ValueError(msg)
        if len(normalized) > NAME_MAX_LENGTH:
            msg = f"name must be at most {NAME_MAX_LENGTH} characters long"
            raise ValueError(msg)
        return normalized

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str | None) -> str | None:
        if value is None:
            return value
        normalized = value.strip().upper()
        if not normalized:
            msg = "code must not be empty or whitespace only"
            raise ValueError(msg)
        if len(normalized) > CODE_MAX_LENGTH:
            msg = f"code must be at most {CODE_MAX_LENGTH} characters long"
            raise ValueError(msg)
        return normalized

    @field_validator("domain")
    @classmethod
    def normalize_domain(cls, value: str | None) -> str | None:
        if value is None:
            return value
        normalized = value.strip()
        if not normalized:
            msg = "domain must not be empty or whitespace only"
            raise ValueError(msg)
        if len(normalized) > DOMAIN_MAX_LENGTH:
            msg = f"domain must be at most {DOMAIN_MAX_LENGTH} characters long"
            raise ValueError(msg)
        return normalized

    @field_validator("default_language")
    @classmethod
    def normalize_default_language(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return _normalize_language(value)

    @field_validator("supported_languages")
    @classmethod
    def normalize_supported_languages(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return value
        return _normalize_language_list(value)


class InstitutionRead(InstitutionBase):
    id: UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class InstitutionListResponse(BaseModel):
    items: list[InstitutionRead]
    total: int
    limit: int
    offset: int
