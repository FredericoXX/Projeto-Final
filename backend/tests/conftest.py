"""Shared test fixtures: an isolated test database.

Tests must never run against the development database — that database
is shared with whatever the developer is doing manually (Swagger,
psql, the running dev server), and test runs would create/delete rows
in the middle of that. This fixture creates (if needed) and resets a
dedicated database, pointed to by settings.resolved_test_database_url,
and points both the FastAPI `get_db` dependency and any direct
`SessionLocal()` usage in tests at it for the duration of the run.
"""

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.database.base import Base
from app.database.session import get_db
from app.main import app

# Import every model module so its table is registered on Base.metadata
# before create_all runs.
from app.models import institution as _institution  # noqa: F401
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

    maintenance_engine = create_engine(
        _maintenance_url(test_url), isolation_level="AUTOCOMMIT"
    )
    with maintenance_engine.connect() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :name"),
            {"name": db_name},
        ).scalar()
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    maintenance_engine.dispose()

    engine = create_engine(test_url, pool_pre_ping=True)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)

    yield engine

    engine.dispose()


@pytest.fixture(scope="session")
def test_session_factory(test_engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=test_engine, autoflush=False, autocommit=False)


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
