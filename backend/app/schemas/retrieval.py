"""Schemas públicos da pesquisa de evidências documentais."""

from datetime import date
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.language import normalize_language_code


class RetrievalSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: Annotated[str, Field(min_length=1, max_length=1000)]
    language: str | None = None
    top_k: Annotated[int, Field(ge=1, le=20)] = 5
    official_only: bool = True

    @field_validator("query", mode="before")
    @classmethod
    def trim_query(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("language")
    @classmethod
    def normalize_language(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_language_code(value)


class RetrievalEvidenceRead(BaseModel):
    chunk_id: UUID
    document_id: UUID
    document_version_id: UUID
    document_title: str
    chunk_index: int
    content: str
    score: float
    language: str
    official_source: bool
    source_url: str | None
    valid_from: date | None
    valid_until: date | None


class RetrievalSearchResponse(BaseModel):
    query: str
    language: str
    items: list[RetrievalEvidenceRead]
