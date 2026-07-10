from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    app_name: str = "Agentic RAG Assistant"
    environment: str = "development"
    database_url: str
    test_database_url: str | None = None

    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

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


settings = Settings()
