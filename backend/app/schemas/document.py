from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from app.core.language import normalize_language_code

TITLE_MAX_LENGTH = 255
SOURCE_URL_MAX_LENGTH = 2048


def _normalize_title(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        msg = "title must not be empty or whitespace only"
        raise ValueError(msg)
    if len(normalized) > TITLE_MAX_LENGTH:
        msg = f"title must be at most {TITLE_MAX_LENGTH} characters long"
        raise ValueError(msg)
    return normalized


def _normalize_description(value: str | None) -> str | None:
    if value is None:
        return value
    normalized = value.strip()
    if not normalized:
        msg = "description must not be empty or whitespace only"
        raise ValueError(msg)
    return normalized


def _normalize_source_url(value: str | None) -> str | None:
    if value is None:
        return value
    normalized = value.strip()
    if not normalized.lower().startswith(("http://", "https://")):
        msg = "source_url must be an HTTP or HTTPS URL"
        raise ValueError(msg)
    if len(normalized) > SOURCE_URL_MAX_LENGTH:
        msg = f"source_url must be at most {SOURCE_URL_MAX_LENGTH} characters long"
        raise ValueError(msg)
    return normalized


def _validate_validity_range(valid_from: date | None, valid_until: date | None) -> None:
    if valid_from is not None and valid_until is not None and valid_from > valid_until:
        msg = "valid_from must not be after valid_until"
        raise ValueError(msg)


class DocumentCreate(BaseModel):
    # institution_id e created_by_user_id não fazem parte deste schema de
    # propósito: vêm sempre do admin autenticado na rota, nunca do payload.
    # extra="forbid" torna o envio desses (ou de qualquer campo
    # desconhecido) um 422 explícito.
    model_config = ConfigDict(extra="forbid")

    title: str
    description: str | None = None
    # Omitido herda institution.default_language; fornecido é validado
    # contra institution.supported_languages no service (resolve_language).
    language: str | None = None
    source_url: str | None = None
    official_source: bool = False
    valid_from: date | None = None
    valid_until: date | None = None

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        return _normalize_title(value)

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        return _normalize_description(value)

    @field_validator("language")
    @classmethod
    def normalize_language(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return normalize_language_code(value)

    @field_validator("source_url")
    @classmethod
    def normalize_source_url(cls, value: str | None) -> str | None:
        return _normalize_source_url(value)

    @model_validator(mode="after")
    def check_validity_range(self) -> "DocumentCreate":
        _validate_validity_range(self.valid_from, self.valid_until)
        return self


class DocumentUpdate(BaseModel):
    # Todos os campos são opcionais (PATCH). O intervalo de validade e a
    # regra de idioma (imutável depois de existir uma versão) dependem do
    # estado atual do documento, por isso são validados no service, sobre
    # o estado final resultante.
    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    description: str | None = None
    language: str | None = None
    source_url: str | None = None
    official_source: bool | None = None
    is_active: bool | None = None
    valid_from: date | None = None
    valid_until: date | None = None

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return _normalize_title(value)

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        return _normalize_description(value)

    @field_validator("language")
    @classmethod
    def normalize_language(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return normalize_language_code(value)

    @field_validator("source_url")
    @classmethod
    def normalize_source_url(cls, value: str | None) -> str | None:
        return _normalize_source_url(value)


class DocumentRead(BaseModel):
    id: UUID
    institution_id: UUID
    created_by_user_id: UUID
    title: str
    description: str | None
    language: str
    source_url: str | None
    official_source: bool
    is_active: bool
    valid_from: date | None
    valid_until: date | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DocumentListResponse(BaseModel):
    items: list[DocumentRead]
    total: int
    limit: int
    offset: int


class ExtractionPageDetail(BaseModel):
    """Metadados de extração de uma página — calculados pelo servidor.

    Nunca contêm texto integral, imagens ou caminhos; `extra="ignore"`
    tolera a evolução futura dos metadados persistidos em JSONB.
    """

    page_number: int
    method: str
    native_characters: int
    extracted_characters: int
    ocr_confidence: float | None = None
    quality: str
    warning: str | None = None

    model_config = ConfigDict(extra="ignore")


class DocumentVersionRead(BaseModel):
    # storage_path e extracted_text nunca são expostos aqui: o caminho é
    # um detalhe interno do armazenamento e o texto tem um endpoint
    # próprio, paginado (GET .../content).
    id: UUID
    document_id: UUID
    institution_id: UUID
    uploaded_by_user_id: UUID
    version_number: int
    original_filename: str
    mime_type: str
    size_bytes: int
    checksum_sha256: str
    processing_status: str
    processing_error: str | None
    page_count: int | None
    # Metadados de extração calculados pelo servidor; NULL em versões
    # históricas anteriores ao suporte OCR. Nunca são aceites em payloads
    # de criação/atualização.
    extraction_method: str | None
    extraction_quality: str | None
    extraction_warning: str | None
    extraction_details: list[ExtractionPageDetail] | None
    created_at: datetime
    updated_at: datetime
    processed_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class DocumentVersionListResponse(BaseModel):
    items: list[DocumentVersionRead]
    total: int
    limit: int
    offset: int


class DocumentContentRead(BaseModel):
    text: str
    total_characters: int
    offset: int
    limit: int
