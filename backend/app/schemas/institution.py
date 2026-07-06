from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator, model_validator


class InstitutionBase(BaseModel):
    name: str
    code: str
    domain: str | None = None
    default_language: str
    supported_languages: list[str]
    is_active: bool = True

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("default_language")
    @classmethod
    def normalize_default_language(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("supported_languages")
    @classmethod
    def normalize_supported_languages(cls, value: list[str]) -> list[str]:
        return [language.strip().lower() for language in value]


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

    @field_validator("code")
    @classmethod
    def normalize_code(cls, value: str | None) -> str | None:
        return value.strip().upper() if value is not None else value

    @field_validator("default_language")
    @classmethod
    def normalize_default_language(cls, value: str | None) -> str | None:
        return value.strip().lower() if value is not None else value

    @field_validator("supported_languages")
    @classmethod
    def normalize_supported_languages(
        cls, value: list[str] | None
    ) -> list[str] | None:
        if value is None:
            return value
        return [language.strip().lower() for language in value]


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
