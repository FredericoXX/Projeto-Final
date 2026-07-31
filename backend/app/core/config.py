import math
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    app_name: str = "Agentic Institutional Assistant"
    environment: str = "development"
    database_url: str
    test_database_url: str | None = None

    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60

    # Segredo exclusivo de inicialização que protege a criação de instituições,
    # register-initial-admin e PATCH
    # /api/v1/bootstrap/institutions/{id}/status até existir um papel
    # platform_admin real. None (o padrão) desativa as operações em vez de as
    # deixar abertas; um token ausente falha de forma segura em qualquer ambiente.
    bootstrap_token: str | None = None

    # Raiz do armazenamento local. Um valor relativo é resolvido a partir da
    # raiz do repositório, mantendo o padrão dentro da diretoria storage/,
    # ignorada pelo Git.
    document_storage_path: str = "storage/documents"
    document_max_file_size_mb: int = 20

    # Segmentação do texto extraído em chunks, atualmente usada pela
    # baseline lexical e mantida neutra para permitir outras estratégias.
    document_chunk_size_chars: int = 1200
    document_chunk_overlap_chars: int = 150

    # Limiar mínimo de relevância lexical composta (ver
    # app.retrieval.reranking). Aplica-se **depois** da elegibilidade e a
    # todos os candidatos elegíveis, incluindo o melhor: não substitui o
    # gate de cobertura (app.retrieval.eligibility), apenas remove
    # candidatos já elegíveis cuja relevância composta é residual. Os pesos
    # do ranking não são configuráveis — são constantes versionadas no
    # módulo; só este limiar operacional é ajustável. O score composto está
    # em [0, 1]; 0.0 desativa o piso sem afetar a elegibilidade.
    retrieval_min_relevance_score: float = 0.05

    # OCR local (Tesseract) para páginas de PDF sem texto pesquisável.
    # O comando vazio usa a resolução normal do PATH do sistema; a
    # ausência do executável nunca impede o arranque nem o processamento
    # de documentos que não precisam de OCR — só falha, de forma
    # controlada, o processamento que exigir OCR.
    document_ocr_enabled: bool = True
    document_ocr_command: str | None = None
    document_ocr_languages: str = "por+eng"
    document_ocr_dpi: int = 300
    document_ocr_timeout_seconds: int = 60
    document_ocr_min_native_chars: int = 40
    document_ocr_min_confidence: int = 60
    document_ocr_max_pages: int = 200
    document_ocr_max_pixels_per_page: int = 25_000_000

    # Geração experimental de respostas fundamentadas. Nomes neutros: o
    # provider é substituível e a abordagem não é uma decisão definitiva.
    answer_generator_provider: str = "openai"
    answering_default_top_k: int = 5
    answering_max_top_k: int = 10
    answering_max_context_chars: int = 12000
    answering_max_answer_chars: int = 4000

    # Configuração específica do adapter OpenAI. A ausência da chave não
    # impede a aplicação de arrancar: só o endpoint de answering falha
    # (503) quando tenta usar o provider. Nunca escrever a chave em logs
    # nem devolvê-la em respostas.
    openai_api_key: str | None = None
    openai_model: str | None = None
    openai_timeout_seconds: int = 30

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @model_validator(mode="after")
    def check_chunking_configuration(self) -> "Settings":
        if self.document_chunk_size_chars <= 0:
            msg = "DOCUMENT_CHUNK_SIZE_CHARS must be greater than zero"
            raise ValueError(msg)
        if self.document_chunk_overlap_chars < 0:
            msg = "DOCUMENT_CHUNK_OVERLAP_CHARS must not be negative"
            raise ValueError(msg)
        if self.document_chunk_overlap_chars >= self.document_chunk_size_chars:
            msg = "DOCUMENT_CHUNK_OVERLAP_CHARS must be smaller than DOCUMENT_CHUNK_SIZE_CHARS"
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def check_retrieval_configuration(self) -> "Settings":
        score = self.retrieval_min_relevance_score
        # O score composto é finito e vive em [0, 1]; o limiar tem de o
        # respeitar para ser comparável. isfinite rejeita NaN e ±infinito.
        if not math.isfinite(score):
            msg = "RETRIEVAL_MIN_RELEVANCE_SCORE must be a finite number"
            raise ValueError(msg)
        if not (0.0 <= score <= 1.0):
            msg = "RETRIEVAL_MIN_RELEVANCE_SCORE must be between 0 and 1"
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def check_ocr_configuration(self) -> "Settings":
        if not (72 <= self.document_ocr_dpi <= 600):
            msg = "DOCUMENT_OCR_DPI must be between 72 and 600"
            raise ValueError(msg)
        if self.document_ocr_timeout_seconds <= 0:
            msg = "DOCUMENT_OCR_TIMEOUT_SECONDS must be greater than zero"
            raise ValueError(msg)
        if self.document_ocr_min_native_chars < 0:
            msg = "DOCUMENT_OCR_MIN_NATIVE_CHARS must not be negative"
            raise ValueError(msg)
        if not (0 <= self.document_ocr_min_confidence <= 100):
            msg = "DOCUMENT_OCR_MIN_CONFIDENCE must be between 0 and 100"
            raise ValueError(msg)
        if self.document_ocr_max_pages <= 0:
            msg = "DOCUMENT_OCR_MAX_PAGES must be greater than zero"
            raise ValueError(msg)
        if self.document_ocr_max_pixels_per_page < 1_000_000:
            msg = "DOCUMENT_OCR_MAX_PIXELS_PER_PAGE must be at least 1000000"
            raise ValueError(msg)
        if not self.document_ocr_languages.strip():
            msg = "DOCUMENT_OCR_LANGUAGES must not be empty"
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def check_answering_configuration(self) -> "Settings":
        if self.answering_default_top_k <= 0:
            msg = "ANSWERING_DEFAULT_TOP_K must be greater than zero"
            raise ValueError(msg)
        if self.answering_max_top_k <= 0:
            msg = "ANSWERING_MAX_TOP_K must be greater than zero"
            raise ValueError(msg)
        if self.answering_default_top_k > self.answering_max_top_k:
            msg = "ANSWERING_DEFAULT_TOP_K must not be greater than ANSWERING_MAX_TOP_K"
            raise ValueError(msg)
        if self.answering_max_context_chars <= 0:
            msg = "ANSWERING_MAX_CONTEXT_CHARS must be greater than zero"
            raise ValueError(msg)
        if self.answering_max_answer_chars <= 0:
            msg = "ANSWERING_MAX_ANSWER_CHARS must be greater than zero"
            raise ValueError(msg)
        if self.openai_timeout_seconds <= 0:
            msg = "OPENAI_TIMEOUT_SECONDS must be greater than zero"
            raise ValueError(msg)
        return self

    @property
    def resolved_document_storage_path(self) -> Path:
        path = Path(self.document_storage_path)
        return path if path.is_absolute() else PROJECT_ROOT / path

    @property
    def document_max_file_size_bytes(self) -> int:
        return self.document_max_file_size_mb * 1024 * 1024

    @property
    def resolved_test_database_url(self) -> str:
        """The database URL tests should run against.

        Falls back to `database_url` with the database name suffixed by
        `_test`, so a dedicated `TEST_DATABASE_URL` is optional locally
        but tests never touch the same database as the dev server.
        """
        if self.test_database_url:
            return self.test_database_url
        base, _, db_name = self.database_url.rpartition("/")
        return f"{base}/{db_name}_test"


# pydantic-settings preenche os campos obrigatórios (database_url, jwt_secret_key)
# a partir do ambiente/.env em runtime; o mypy vê apenas o __init__ gerado por
# BaseSettings e não consegue verificar isso, marcando-os como ausentes.
settings = Settings()  # type: ignore[call-arg]
