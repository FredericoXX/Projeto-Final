"""Shared test fixtures: an isolated test database, truncated per test.

Tests must never run against the development database — that database
is shared with whatever the developer is doing manually (Swagger,
psql, the running dev server), and test runs would create/delete rows
in the middle of that. This fixture creates (if needed) and resets a
dedicated database, pointed to by settings.resolved_test_database_url,
and points both the FastAPI `get_db` dependency and any direct
`SessionLocal()` usage in tests at it for the duration of the run.

All tables are also truncated before every individual test, so tests
don't need to track and delete the rows they create.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.database.base import Base
from app.database.session import get_db
from app.main import app

# Importar todos os módulos de modelos para registar as tabelas em Base.metadata
# antes da execução de create_all.
from app.models import chunk_embedding as _chunk_embedding  # noqa: F401
from app.models import conversation as _conversation  # noqa: F401
from app.models import document as _document  # noqa: F401
from app.models import document_chunk as _document_chunk  # noqa: F401
from app.models import document_version as _document_version  # noqa: F401
from app.models import institution as _institution  # noqa: F401
from app.models import message as _message  # noqa: F401
from app.models import message_source as _message_source  # noqa: F401
from app.models import storage_cleanup_task as _storage_cleanup_task  # noqa: F401
from app.models import user as _user  # noqa: F401


def _maintenance_url(db_url: str) -> str:
    base, _, _ = db_url.rpartition("/")
    return f"{base}/postgres"


def _database_name(db_url: str) -> str:
    return db_url.rpartition("/")[2]


@pytest.fixture(scope="session")
def test_engine() -> Iterator[Engine]:
    test_url = settings.resolved_test_database_url
    db_name = _database_name(test_url)

    maintenance_engine = create_engine(_maintenance_url(test_url), isolation_level="AUTOCOMMIT")
    with maintenance_engine.connect() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :name"),
            {"name": db_name},
        ).scalar()
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    maintenance_engine.dispose()

    engine = create_engine(test_url, pool_pre_ping=True)

    # Necessário antes de create_all: colunas baseadas no tipo VECTOR do pgvector
    # falhariam ao ser criadas numa base de testes nova.
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))

    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)

    yield engine

    engine.dispose()


@pytest.fixture(scope="session")
def test_session_factory(test_engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=test_engine, autoflush=False, autocommit=False)

# Substitui a dependency get_db em todos os testes para que os pedidos
# feitos através do TestClient usem a base de dados de teste isolada,
# em vez da ligação apontada para a base de dados de desenvolvimento.
@pytest.fixture(scope="session", autouse=True)
def _override_get_db(test_session_factory: sessionmaker[Session]) -> Iterator[None]:
    def override_get_db() -> Iterator[Session]:
        db = test_session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    yield
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


# Redireciona o armazenamento de documentos para um diretório temporário
# por teste: a suite nunca escreve no storage de desenvolvimento, e cada
# teste começa com um armazenamento vazio.
@pytest.fixture(autouse=True)
def _document_storage_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "document_storage_path", str(tmp_path / "documents"))


@pytest.fixture(autouse=True)
def _clean_tables(test_engine: Engine) -> None:
    """Truncate every table before each test so tests never depend on
    manual per-test cleanup or on state left behind by earlier tests."""
    table_names = ", ".join(f'"{table.name}"' for table in reversed(Base.metadata.sorted_tables))
    if not table_names:
        return
    with test_engine.begin() as conn:
        conn.execute(text(f"TRUNCATE TABLE {table_names} RESTART IDENTITY CASCADE"))
