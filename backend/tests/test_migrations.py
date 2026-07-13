"""Integration test for the real Alembic migration chain.

The endpoint tests build their schema from `Base.metadata.create_all()`,
which validates models but not the migration files themselves. This
test instead runs `alembic upgrade head` against a disposable database
created and dropped for this test alone (never the development
database, never the shared endpoint-test database), then checks that
the expected schema — tables, columns, foreign key, index, pgvector,
and the resulting Alembic head — is exactly what the migration chain
is supposed to produce.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine

from alembic import command
from app.core.config import settings
from tests.conftest import _maintenance_url

BACKEND_DIR = Path(__file__).resolve().parents[1]

EXPECTED_USER_COLUMNS = {
    "id",
    "institution_id",
    "full_name",
    "email",
    "password_hash",
    "role",
    "is_active",
    "created_at",
    "updated_at",
}

EXPECTED_CONVERSATION_COLUMNS = {
    "id",
    "institution_id",
    "user_id",
    "title",
    "language",
    "status",
    "metadata",
    "created_at",
    "updated_at",
}

EXPECTED_MESSAGE_COLUMNS = {
    "id",
    "conversation_id",
    "institution_id",
    "user_id",
    "role",
    "content",
    "language",
    "metadata",
    "created_at",
}


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


# Confirma que a cadeia real de migrations produz o esquema esperado,
# em vez de apenas validar os modelos SQLAlchemy (o que create_all faria).
def test_alembic_upgrade_head_creates_expected_schema(
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
        inspector = inspect(engine)
        table_names = set(inspector.get_table_names())
        assert {
            "users",
            "institutions",
            "conversations",
            "messages",
            "documents",
            "document_versions",
        } <= table_names

        user_columns = {column["name"] for column in inspector.get_columns("users")}
        assert EXPECTED_USER_COLUMNS <= user_columns

        foreign_keys = inspector.get_foreign_keys("users")
        assert any(
            fk["referred_table"] == "institutions"
            and fk["constrained_columns"] == ["institution_id"]
            for fk in foreign_keys
        )

        indexes = inspector.get_indexes("users")
        assert any(index["column_names"] == ["institution_id"] for index in indexes)

        user_unique_constraints = inspector.get_unique_constraints("users")
        assert any(
            set(uc["column_names"]) == {"id", "institution_id"}
            for uc in user_unique_constraints
        )

        conversation_columns = {
            column["name"] for column in inspector.get_columns("conversations")
        }
        assert EXPECTED_CONVERSATION_COLUMNS <= conversation_columns

        conversation_fks = inspector.get_foreign_keys("conversations")
        assert any(
            fk["referred_table"] == "institutions"
            and fk["constrained_columns"] == ["institution_id"]
            for fk in conversation_fks
        )
        # user_id's foreign key is composite (migration 3ed4bcad52c8):
        # (user_id, institution_id) -> users(id, institution_id), so a
        # conversation can never reference a user from another institution.
        assert any(
            fk["referred_table"] == "users"
            and set(fk["constrained_columns"]) == {"user_id", "institution_id"}
            for fk in conversation_fks
        )

        conversation_unique_constraints = inspector.get_unique_constraints("conversations")
        assert any(
            set(uc["column_names"]) == {"id", "institution_id"}
            for uc in conversation_unique_constraints
        )

        conversation_indexes = inspector.get_indexes("conversations")
        assert any(
            index["column_names"] == ["institution_id"] for index in conversation_indexes
        )
        assert any(index["column_names"] == ["user_id"] for index in conversation_indexes)

        message_columns = {column["name"] for column in inspector.get_columns("messages")}
        assert EXPECTED_MESSAGE_COLUMNS <= message_columns

        # conversation_id's and user_id's foreign keys are composite
        # (migration 3ed4bcad52c8): a message can never reference a
        # conversation or a user from another institution.
        message_fks = inspector.get_foreign_keys("messages")
        assert any(
            fk["referred_table"] == "conversations"
            and set(fk["constrained_columns"]) == {"conversation_id", "institution_id"}
            for fk in message_fks
        )
        assert any(
            fk["referred_table"] == "institutions"
            and fk["constrained_columns"] == ["institution_id"]
            for fk in message_fks
        )
        assert any(
            fk["referred_table"] == "users"
            and set(fk["constrained_columns"]) == {"user_id", "institution_id"}
            for fk in message_fks
        )

        message_indexes = inspector.get_indexes("messages")
        assert any(index["column_names"] == ["conversation_id"] for index in message_indexes)
        assert any(index["column_names"] == ["institution_id"] for index in message_indexes)

        # Constraints de valores de domínio (migration 5f638cb2d2c3).
        check_constraint_names = {
            cc["name"]
            for table in ("users", "conversations", "messages")
            for cc in inspector.get_check_constraints(table)
        }
        assert "ck_users_role_allowed" in check_constraint_names
        assert "ck_conversations_status_allowed" in check_constraint_names
        assert "ck_messages_role_allowed" in check_constraint_names

        # Tabelas documentais (migration 1482b165c943): FKs compostas,
        # uniques, checks e índices principais.
        document_fks = inspector.get_foreign_keys("documents")
        assert any(
            fk["referred_table"] == "users"
            and set(fk["constrained_columns"]) == {"created_by_user_id", "institution_id"}
            for fk in document_fks
        )
        document_uniques = inspector.get_unique_constraints("documents")
        assert any(
            set(uc["column_names"]) == {"id", "institution_id"} for uc in document_uniques
        )
        document_checks = {cc["name"] for cc in inspector.get_check_constraints("documents")}
        assert "ck_documents_validity_range" in document_checks
        document_indexes = {index["name"] for index in inspector.get_indexes("documents")}
        assert "ix_documents_institution_id_is_active" in document_indexes
        assert "ix_documents_institution_id_official_source" in document_indexes

        version_fks = inspector.get_foreign_keys("document_versions")
        assert any(
            fk["referred_table"] == "documents"
            and set(fk["constrained_columns"]) == {"document_id", "institution_id"}
            for fk in version_fks
        )
        assert any(
            fk["referred_table"] == "users"
            and set(fk["constrained_columns"]) == {"uploaded_by_user_id", "institution_id"}
            for fk in version_fks
        )
        version_uniques = {
            uc["name"] for uc in inspector.get_unique_constraints("document_versions")
        }
        assert "uq_document_versions_document_id_version_number" in version_uniques
        assert "uq_document_versions_institution_id_checksum" in version_uniques
        version_checks = {
            cc["name"] for cc in inspector.get_check_constraints("document_versions")
        }
        assert "ck_document_versions_version_number_positive" in version_checks
        assert "ck_document_versions_size_bytes_positive" in version_checks
        assert "ck_document_versions_processing_status_allowed" in version_checks
        assert "ck_document_versions_page_count_non_negative" in version_checks

        with engine.connect() as conn:
            vector_extension = conn.execute(
                text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
            ).scalar()
            assert vector_extension == 1

            current_revision = conn.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar()
    finally:
        engine.dispose()

    script = ScriptDirectory.from_config(alembic_cfg)
    assert current_revision == script.get_current_head()


# Verifica especificamente a migration 3ed4bcad52c8 (constraints compostas
# multi-institucionais): upgrade -> downgrade -> upgrade outra vez, para
# confirmar que tanto o upgrade como o downgrade estão corretos e são
# repetíveis, não apenas que "upgrade head" funciona uma vez.
def test_composite_constraints_migration_upgrade_downgrade_upgrade(
    migrations_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "database_url", migrations_database_url)
    alembic_cfg = Config(str(BACKEND_DIR / "alembic.ini"))

    def unique_constraint_names(engine: Engine, table: str) -> set[str]:
        return {
            uc["name"]
            for uc in inspect(engine).get_unique_constraints(table)
            if uc["name"] is not None
        }

    def foreign_key_names(engine: Engine, table: str) -> set[str]:
        return {
            fk["name"] for fk in inspect(engine).get_foreign_keys(table) if fk["name"] is not None
        }

    # Upgrade até à própria migration em teste (não "head"): garante que o
    # "downgrade -1" abaixo reverte exatamente esta migration, mesmo que
    # existam migrations posteriores na cadeia.
    command.upgrade(alembic_cfg, "3ed4bcad52c8")
    engine = create_engine(migrations_database_url)
    try:
        assert "uq_users_id_institution_id" in unique_constraint_names(engine, "users")
        assert "uq_conversations_id_institution_id" in unique_constraint_names(
            engine, "conversations"
        )
        conversation_fks = foreign_key_names(engine, "conversations")
        assert "fk_conversations_user_id_institution_id_users" in conversation_fks
        assert "fk_conversations_user_id_users" not in conversation_fks

        message_fks = foreign_key_names(engine, "messages")
        assert "fk_messages_conversation_id_institution_id_conversations" in message_fks
        assert "fk_messages_user_id_institution_id_users" in message_fks
        assert "fk_messages_conversation_id_conversations" not in message_fks
        assert "fk_messages_user_id_users" not in message_fks
    finally:
        engine.dispose()

    command.downgrade(alembic_cfg, "-1")
    engine = create_engine(migrations_database_url)
    try:
        assert "uq_users_id_institution_id" not in unique_constraint_names(engine, "users")
        assert "uq_conversations_id_institution_id" not in unique_constraint_names(
            engine, "conversations"
        )
        conversation_fks = foreign_key_names(engine, "conversations")
        assert "fk_conversations_user_id_institution_id_users" not in conversation_fks
        assert "fk_conversations_user_id_users" in conversation_fks

        message_fks = foreign_key_names(engine, "messages")
        assert "fk_messages_conversation_id_institution_id_conversations" not in message_fks
        assert "fk_messages_user_id_institution_id_users" not in message_fks
        assert "fk_messages_conversation_id_conversations" in message_fks
        assert "fk_messages_user_id_users" in message_fks
    finally:
        engine.dispose()

    command.upgrade(alembic_cfg, "head")
    engine = create_engine(migrations_database_url)
    try:
        assert "uq_users_id_institution_id" in unique_constraint_names(engine, "users")
        assert (
            "fk_conversations_user_id_institution_id_users"
            in foreign_key_names(engine, "conversations")
        )

        with engine.connect() as conn:
            current_revision = conn.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar()
    finally:
        engine.dispose()

    script = ScriptDirectory.from_config(alembic_cfg)
    assert current_revision == script.get_current_head()


# Verifica especificamente a migration 5f638cb2d2c3 (constraints de valores
# de domínio): upgrade -> downgrade -> upgrade outra vez, para confirmar que
# tanto o upgrade como o downgrade estão corretos e são repetíveis.
def test_domain_check_constraints_migration_upgrade_downgrade_upgrade(
    migrations_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "database_url", migrations_database_url)
    alembic_cfg = Config(str(BACKEND_DIR / "alembic.ini"))

    def check_constraint_names(engine: Engine, table: str) -> set[str]:
        return {
            cc["name"]
            for cc in inspect(engine).get_check_constraints(table)
            if cc["name"] is not None
        }

    expected = {
        "users": "ck_users_role_allowed",
        "conversations": "ck_conversations_status_allowed",
        "messages": "ck_messages_role_allowed",
    }

    command.upgrade(alembic_cfg, "5f638cb2d2c3")
    engine = create_engine(migrations_database_url)
    try:
        for table, constraint in expected.items():
            assert constraint in check_constraint_names(engine, table)
    finally:
        engine.dispose()

    command.downgrade(alembic_cfg, "-1")
    engine = create_engine(migrations_database_url)
    try:
        for table, constraint in expected.items():
            assert constraint not in check_constraint_names(engine, table)
    finally:
        engine.dispose()

    command.upgrade(alembic_cfg, "head")
    engine = create_engine(migrations_database_url)
    try:
        for table, constraint in expected.items():
            assert constraint in check_constraint_names(engine, table)

        with engine.connect() as conn:
            current_revision = conn.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar()
    finally:
        engine.dispose()

    script = ScriptDirectory.from_config(alembic_cfg)
    assert current_revision == script.get_current_head()


# Verifica especificamente a migration 1482b165c943 (tabelas documentais):
# upgrade -> downgrade -> upgrade outra vez, para confirmar que tanto o
# upgrade como o downgrade estão corretos e são repetíveis.
def test_documents_migration_upgrade_downgrade_upgrade(
    migrations_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "database_url", migrations_database_url)
    alembic_cfg = Config(str(BACKEND_DIR / "alembic.ini"))

    def table_names(engine: Engine) -> set[str]:
        return set(inspect(engine).get_table_names())

    command.upgrade(alembic_cfg, "1482b165c943")
    engine = create_engine(migrations_database_url)
    try:
        names = table_names(engine)
        assert "documents" in names
        assert "document_versions" in names
    finally:
        engine.dispose()

    command.downgrade(alembic_cfg, "-1")
    engine = create_engine(migrations_database_url)
    try:
        names = table_names(engine)
        assert "documents" not in names
        assert "document_versions" not in names
    finally:
        engine.dispose()

    command.upgrade(alembic_cfg, "head")
    engine = create_engine(migrations_database_url)
    try:
        names = table_names(engine)
        assert "documents" in names
        assert "document_versions" in names

        with engine.connect() as conn:
            current_revision = conn.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar()
    finally:
        engine.dispose()

    script = ScriptDirectory.from_config(alembic_cfg)
    assert current_revision == script.get_current_head()
