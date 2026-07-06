"""Integration test for the real Alembic migration chain.

The endpoint tests build their schema from `Base.metadata.create_all()`,
which validates models but not the migration files themselves. This
test instead runs `alembic upgrade head` against a disposable database
created and dropped for this test alone (never the development
database, never the shared endpoint-test database), then checks that
the expected tables exist.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from alembic import command
from app.core.config import settings
from tests.conftest import _maintenance_url

BACKEND_DIR = Path(__file__).resolve().parents[1]


@pytest.fixture
def migrations_database_url() -> Iterator[str]:
    base_test_url = settings.resolved_test_database_url
    base, _, test_db_name = base_test_url.rpartition("/")
    db_name = f"{test_db_name}_migrations"
    migrations_url = f"{base}/{db_name}"

    maintenance_engine = create_engine(
        _maintenance_url(base_test_url), isolation_level="AUTOCOMMIT"
    )
    with maintenance_engine.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE "{db_name}"'))

    yield migrations_url

    with maintenance_engine.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)'))
    maintenance_engine.dispose()


def test_alembic_upgrade_head_creates_expected_tables(
    migrations_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # alembic/env.py always points itself at `settings.database_url`, so
    # this is how the migration run is redirected to the disposable
    # database instead of the development one.
    monkeypatch.setattr(settings, "database_url", migrations_database_url)

    alembic_cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    command.upgrade(alembic_cfg, "head")

    engine = create_engine(migrations_database_url)
    try:
        table_names = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()

    assert {"users", "institutions"} <= table_names
