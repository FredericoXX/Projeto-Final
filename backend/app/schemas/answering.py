"""Schemas públicos da geração experimental de respostas fundamentadas."""

from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, field_validator

from app.core.language import normalize_language_code


class AnsweringRequest(BaseModel):
    # institution_id e user_id nunca fazem parte deste schema: vêm sempre
    # do utilizador autenticado. extra="forbid" torna o envio desses (ou
    # de qualquer campo desconhecido) um 422 explícito.
    model_config = ConfigDict(extra="forbid")

    query: Annotated[str, Field(min_length=1, max_length=1000)]
    language: str | None = None
    # Limite estrutural de segurança; o máximo real (configurável,
    # ANSWERING_MAX_TOP_K) é validado no service, porque o schema não
    # deve depender dinamicamente de Settings.
    top_k: Annotated[int, Field(ge=1, le=100)] | None = None
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


class AnswerSourceRead(BaseModel):
    # Apenas metadados públicos da fonte citada. Nunca: institution_id,
    # normalized_content, search_vector, content_sha256, storage_path,
    # extracted_text, ids de quem criou/carregou, prompts ou resposta
    # bruta do fornecedor.
    evidence_id: str
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

    # O checksum acompanha a fonte apenas entre services. PrivateAttr não
    # integra model_dump, JSON schema, OpenAPI nem a resposta HTTP.
    _internal_content_sha256: str | None = PrivateAttr(default=None)

    @property
    def internal_content_sha256(self) -> str | None:
        return self._internal_content_sha256

    def set_internal_content_sha256(self, checksum: str) -> None:
        self._internal_content_sha256 = checksum


class AnsweringResponse(BaseModel):
    status: Literal["answered", "insufficient_evidence"]
    query: str
    language: str
    answer: str
    sources: list[AnswerSourceRead]
