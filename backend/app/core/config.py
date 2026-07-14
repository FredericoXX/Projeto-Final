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

    # Bootstrap-only secret that gates institution creation,
    # register-initial-admin and PATCH
    # /api/v1/bootstrap/institutions/{id}/status until a real platform_admin
    # role exists. None (the default) disables these operations rather than
    # leaving them open, so an unset token fails closed in any environment.
    bootstrap_token: str | None = None

    # Root of the local document storage. A relative value is resolved
    # against the repository root, keeping the default inside the
    # gitignored storage/ directory.
    document_storage_path: str = "storage/documents"
    document_max_file_size_mb: int = 20

    # Segmentação do texto extraído em chunks, atualmente usada pela
    # baseline lexical e mantida neutra para permitir outras estratégias.
    document_chunk_size_chars: int = 1200
    document_chunk_overlap_chars: int = 150

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


# pydantic-settings fills required fields (database_url, jwt_secret_key)
# from the environment/.env at runtime; mypy only sees BaseSettings'
# generated __init__ and can't verify that, so it flags them as missing.
settings = Settings()  # type: ignore[call-arg]
