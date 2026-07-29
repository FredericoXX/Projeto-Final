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

import uuid
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine

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
    # alembic/env.py aponta sempre para `settings.database_url`; assim a migração
    # é redirecionada para a base descartável em vez da base de desenvolvimento.
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
        # Uma conversa nunca pode referenciar um utilizador de outra instituição.
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

        # As FKs de conversation_id e user_id são compostas (migração
        # 3ed4bcad52c8): uma mensagem nunca pode referenciar uma conversa ou um
        # utilizador de outra instituição.
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


# Verifica especificamente a migration 68cb34527411 (document_chunks):
# upgrade -> downgrade -> upgrade outra vez, para confirmar que tanto o
# upgrade como o downgrade estão corretos e são repetíveis, incluindo a
# constraint de suporte em document_versions.
def test_document_chunks_migration_upgrade_downgrade_upgrade(
    migrations_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "database_url", migrations_database_url)
    alembic_cfg = Config(str(BACKEND_DIR / "alembic.ini"))

    def version_unique_constraints(engine: Engine) -> set[str]:
        return {
            uc["name"]
            for uc in inspect(engine).get_unique_constraints("document_versions")
            if uc["name"] is not None
        }

    def assert_chunks_schema(engine: Engine) -> None:
        inspector = inspect(engine)
        assert "document_chunks" in inspector.get_table_names()

        columns = {column["name"] for column in inspector.get_columns("document_chunks")}
        assert {
            "id",
            "institution_id",
            "document_id",
            "document_version_id",
            "chunk_index",
            "content",
            "normalized_content",
            "content_sha256",
            "start_char",
            "end_char",
            "language",
            "created_at",
        } <= columns

        # FK composta de três colunas: o chunk pertence à versão, ao
        # documento e à instituição corretos ao mesmo tempo.
        chunk_fks = inspector.get_foreign_keys("document_chunks")
        assert any(
            fk["referred_table"] == "document_versions"
            and set(fk["constrained_columns"])
            == {"document_version_id", "document_id", "institution_id"}
            for fk in chunk_fks
        )
        assert any(
            fk["referred_table"] == "institutions"
            and fk["constrained_columns"] == ["institution_id"]
            for fk in chunk_fks
        )

        chunk_uniques = {
            uc["name"] for uc in inspector.get_unique_constraints("document_chunks")
        }
        assert "uq_document_chunks_document_version_id_chunk_index" in chunk_uniques

        chunk_checks = {
            cc["name"] for cc in inspector.get_check_constraints("document_chunks")
        }
        assert "ck_document_chunks_chunk_index_non_negative" in chunk_checks
        assert "ck_document_chunks_start_char_non_negative" in chunk_checks
        assert "ck_document_chunks_end_char_after_start_char" in chunk_checks
        assert "ck_document_chunks_content_not_blank" in chunk_checks
        assert "ck_document_chunks_normalized_content_not_blank" in chunk_checks

        chunk_indexes = {index["name"] for index in inspector.get_indexes("document_chunks")}
        assert "ix_document_chunks_institution_id" in chunk_indexes
        assert "ix_document_chunks_document_id" in chunk_indexes
        assert "ix_document_chunks_document_version_id" in chunk_indexes
        assert "ix_document_chunks_institution_id_language" in chunk_indexes

        assert (
            "uq_document_versions_id_document_id_institution_id"
            in version_unique_constraints(engine)
        )

    command.upgrade(alembic_cfg, "68cb34527411")
    engine = create_engine(migrations_database_url)
    try:
        assert_chunks_schema(engine)
    finally:
        engine.dispose()

    command.downgrade(alembic_cfg, "-1")
    engine = create_engine(migrations_database_url)
    try:
        assert "document_chunks" not in inspect(engine).get_table_names()
        assert (
            "uq_document_versions_id_document_id_institution_id"
            not in version_unique_constraints(engine)
        )
    finally:
        engine.dispose()

    command.upgrade(alembic_cfg, "head")
    engine = create_engine(migrations_database_url)
    try:
        assert_chunks_schema(engine)

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


def test_lexical_search_vector_migration_upgrade_downgrade_upgrade(
    migrations_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A coluna stored é automática, atualizável e indexada por GIN."""
    monkeypatch.setattr(settings, "database_url", migrations_database_url)
    alembic_cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    command.upgrade(alembic_cfg, "b7e2d8a9f4c1")

    engine = create_engine(migrations_database_url)
    institution_id = uuid.uuid4()
    user_id = uuid.uuid4()
    document_id = uuid.uuid4()
    version_id = uuid.uuid4()
    chunk_id = uuid.uuid4()
    try:
        inspector = inspect(engine)
        columns = {column["name"]: column for column in inspector.get_columns("document_chunks")}
        assert "search_vector" in columns
        computed = columns["search_vector"]["computed"]
        assert computed["persisted"] is True
        assert "to_tsvector" in computed["sqltext"]
        assert "simple" in computed["sqltext"]

        with engine.begin() as conn:
            conn.execute(
                text(
                    """INSERT INTO institutions
                    (id, name, code, default_language, supported_languages, is_active)
                    VALUES (:id, 'Test', :code, 'pt', ARRAY['pt','en'], true)"""
                ),
                {"id": institution_id, "code": f"MIG-{uuid.uuid4().hex[:8]}"},
            )
            conn.execute(
                text(
                    """INSERT INTO users
                    (id, institution_id, full_name, email, password_hash, role, is_active)
                    VALUES (:id, :institution_id, 'Admin', :email, 'hash', 'admin', true)"""
                ),
                {
                    "id": user_id,
                    "institution_id": institution_id,
                    "email": f"migration-{uuid.uuid4().hex[:8]}@example.com",
                },
            )
            conn.execute(
                text(
                    """INSERT INTO documents
                    (id, institution_id, created_by_user_id, title, language,
                     official_source, is_active)
                    VALUES (:id, :institution_id, :user_id, 'Doc', 'pt', true, true)"""
                ),
                {"id": document_id, "institution_id": institution_id, "user_id": user_id},
            )
            conn.execute(
                text(
                    """INSERT INTO document_versions
                    (id, document_id, institution_id, uploaded_by_user_id,
                     version_number, original_filename, mime_type, size_bytes,
                     checksum_sha256, storage_path, processing_status)
                    VALUES (:id, :document_id, :institution_id, :user_id,
                            1, 'doc.txt', 'text/plain', 10, :checksum,
                            'inst/doc/version/source.txt', 'processed')"""
                ),
                {
                    "id": version_id,
                    "document_id": document_id,
                    "institution_id": institution_id,
                    "user_id": user_id,
                    "checksum": "a" * 64,
                },
            )
            conn.execute(
                text(
                    """INSERT INTO document_chunks
                    (id, institution_id, document_id, document_version_id,
                     chunk_index, content, normalized_content, content_sha256,
                     start_char, end_char, language)
                    VALUES (:id, :institution_id, :document_id, :version_id,
                            0, 'Matrícula aberta', 'matricula aberta', :checksum,
                            0, 17, 'pt')"""
                ),
                {
                    "id": chunk_id,
                    "institution_id": institution_id,
                    "document_id": document_id,
                    "version_id": version_id,
                    "checksum": "b" * 64,
                },
            )
            vector = conn.execute(
                text("SELECT search_vector::text FROM document_chunks WHERE id = :id"),
                {"id": chunk_id},
            ).scalar_one()
            assert "matricula" in vector

            conn.execute(
                text(
                    "UPDATE document_chunks SET normalized_content = 'enrollment open' "
                    "WHERE id = :id"
                ),
                {"id": chunk_id},
            )
            updated = conn.execute(
                text("SELECT search_vector::text FROM document_chunks WHERE id = :id"),
                {"id": chunk_id},
            ).scalar_one()
            assert "enrollment" in updated
            assert "matricula" not in updated

            index_definition = conn.execute(
                text(
                    "SELECT indexdef FROM pg_indexes "
                    "WHERE indexname = 'ix_document_chunks_search_vector'"
                )
            ).scalar_one()
            assert "USING gin" in index_definition
    finally:
        engine.dispose()

    command.downgrade(alembic_cfg, "-1")
    engine = create_engine(migrations_database_url)
    try:
        assert "search_vector" not in {
            column["name"] for column in inspect(engine).get_columns("document_chunks")
        }
        assert "ix_document_chunks_search_vector" not in {
            index["name"] for index in inspect(engine).get_indexes("document_chunks")
        }
    finally:
        engine.dispose()

    command.upgrade(alembic_cfg, "head")
    engine = create_engine(migrations_database_url)
    try:
        assert "search_vector" in {
            column["name"] for column in inspect(engine).get_columns("document_chunks")
        }
    finally:
        engine.dispose()


def test_conversational_sources_migration_upgrade_downgrade_upgrade(
    migrations_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The reply/source schema is complete, reversible, and remains at head."""
    monkeypatch.setattr(settings, "database_url", migrations_database_url)
    alembic_cfg = Config(str(BACKEND_DIR / "alembic.ini"))

    def constraint_names(items: Iterable[Any]) -> set[str]:
        return {item["name"] for item in items if item["name"] is not None}

    def assert_sources_schema(engine: Engine) -> None:
        inspector = inspect(engine)
        assert "message_sources" in inspector.get_table_names()

        message_columns = {
            column["name"] for column in inspector.get_columns("messages")
        }
        assert "reply_to_message_id" in message_columns
        message_uniques = constraint_names(
            inspector.get_unique_constraints("messages")
        )
        assert "uq_messages_id_conversation_institution" in message_uniques
        assert "uq_messages_id_institution_role" in message_uniques
        message_fks = constraint_names(inspector.get_foreign_keys("messages"))
        assert "fk_messages_reply_to_conversation_institution" in message_fks
        message_checks = constraint_names(
            inspector.get_check_constraints("messages")
        )
        assert "ck_messages_reply_to_not_self" in message_checks

        chunk_uniques = constraint_names(
            inspector.get_unique_constraints("document_chunks")
        )
        assert (
            "uq_document_chunks_id_version_document_institution" in chunk_uniques
        )

        source_columns = {
            column["name"] for column in inspector.get_columns("message_sources")
        }
        assert {
            "id",
            "institution_id",
            "message_id",
            "message_role",
            "chunk_id",
            "document_id",
            "document_version_id",
            "evidence_id",
            "citation_index",
            "document_title",
            "chunk_index",
            "source_url",
            "official_source",
            "language",
            "valid_from",
            "valid_until",
            "content_sha256",
            "created_at",
        } <= source_columns

        source_fks = {
            fk["name"]: fk for fk in inspector.get_foreign_keys("message_sources")
        }
        assert {
            "fk_message_sources_message_institution_role",
            "fk_message_sources_chunk_version_document_institution",
        } <= source_fks.keys()
        assert (
            source_fks["fk_message_sources_message_institution_role"]
            .get("options", {})
            .get("ondelete")
            == "CASCADE"
        )

        source_uniques = constraint_names(
            inspector.get_unique_constraints("message_sources")
        )
        assert {
            "uq_message_sources_message_evidence",
            "uq_message_sources_message_citation",
            "uq_message_sources_message_chunk",
        } <= source_uniques

        source_checks = constraint_names(
            inspector.get_check_constraints("message_sources")
        )
        assert {
            "ck_message_sources_assistant_role",
            "ck_message_sources_citation_non_negative",
            "ck_message_sources_chunk_index_non_negative",
            "ck_message_sources_evidence_not_blank",
            "ck_message_sources_evidence_format",
            "ck_message_sources_title_not_blank",
            "ck_message_sources_language_not_blank",
            "ck_message_sources_checksum_length",
            "ck_message_sources_validity_range",
        } <= source_checks

        source_indexes = {
            index["name"] for index in inspector.get_indexes("message_sources")
        }
        assert {
            "ix_message_sources_institution_id",
            "ix_message_sources_chunk_id",
            "ix_message_sources_document_id",
            "ix_message_sources_document_version_id",
        } <= source_indexes

        with engine.connect() as conn:
            trigger_exists = conn.execute(
                text(
                    "SELECT EXISTS ("
                    "SELECT 1 FROM pg_trigger "
                    "WHERE tgname = 'trg_document_chunks_prevent_referenced_update' "
                    "AND NOT tgisinternal)"
                )
            ).scalar_one()
            function_exists = conn.execute(
                text(
                    "SELECT EXISTS ("
                    "SELECT 1 FROM pg_proc "
                    "WHERE proname = 'prevent_referenced_chunk_update')"
                )
            ).scalar_one()
        assert trigger_exists is True
        assert function_exists is True

    command.upgrade(alembic_cfg, "c8b4f2d9e6a1")
    engine = create_engine(migrations_database_url)
    try:
        assert_sources_schema(engine)
    finally:
        engine.dispose()

    command.downgrade(alembic_cfg, "-1")
    engine = create_engine(migrations_database_url)
    try:
        inspector = inspect(engine)
        assert "message_sources" not in inspector.get_table_names()
        assert "reply_to_message_id" not in {
            column["name"] for column in inspector.get_columns("messages")
        }
        assert "uq_messages_id_conversation_institution" not in constraint_names(
            inspector.get_unique_constraints("messages")
        )
        assert "uq_messages_id_institution_role" not in constraint_names(
            inspector.get_unique_constraints("messages")
        )
        assert (
            "uq_document_chunks_id_version_document_institution"
            not in constraint_names(
                inspector.get_unique_constraints("document_chunks")
            )
        )
        with engine.connect() as conn:
            trigger_exists = conn.execute(
                text(
                    "SELECT EXISTS ("
                    "SELECT 1 FROM pg_trigger "
                    "WHERE tgname = 'trg_document_chunks_prevent_referenced_update' "
                    "AND NOT tgisinternal)"
                )
            ).scalar_one()
            function_exists = conn.execute(
                text(
                    "SELECT EXISTS ("
                    "SELECT 1 FROM pg_proc "
                    "WHERE proname = 'prevent_referenced_chunk_update')"
                )
            ).scalar_one()
        assert trigger_exists is False
        assert function_exists is False
    finally:
        engine.dispose()

    command.upgrade(alembic_cfg, "head")
    engine = create_engine(migrations_database_url)
    try:
        assert_sources_schema(engine)
        with engine.connect() as conn:
            current_revision = conn.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
    finally:
        engine.dispose()

    script = ScriptDirectory.from_config(alembic_cfg)
    assert current_revision == script.get_current_head()


# Verifica a migration 800e7b121e93 (storage_cleanup_tasks):
# upgrade -> downgrade -> upgrade, confirmando criação e remoção da tabela.
def test_storage_cleanup_tasks_migration_upgrade_downgrade_upgrade(
    migrations_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "database_url", migrations_database_url)
    alembic_cfg = Config(str(BACKEND_DIR / "alembic.ini"))

    command.upgrade(alembic_cfg, "800e7b121e93")
    engine = create_engine(migrations_database_url)
    try:
        inspector = inspect(engine)
        assert "storage_cleanup_tasks" in inspector.get_table_names()
        columns = {c["name"] for c in inspector.get_columns("storage_cleanup_tasks")}
        assert {"id", "document_id", "storage_path", "created_at"} <= columns
        checks = {c["name"] for c in inspector.get_check_constraints("storage_cleanup_tasks")}
        assert "ck_storage_cleanup_tasks_path_not_blank" in checks
    finally:
        engine.dispose()

    command.downgrade(alembic_cfg, "-1")
    engine = create_engine(migrations_database_url)
    try:
        assert "storage_cleanup_tasks" not in inspect(engine).get_table_names()
    finally:
        engine.dispose()

    command.upgrade(alembic_cfg, "head")
    engine = create_engine(migrations_database_url)
    try:
        assert "storage_cleanup_tasks" in inspect(engine).get_table_names()
        with engine.connect() as conn:
            current_revision = conn.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar()
    finally:
        engine.dispose()

    script = ScriptDirectory.from_config(alembic_cfg)
    assert current_revision == script.get_current_head()


def test_extraction_metadata_migration_upgrade_downgrade_upgrade(
    migrations_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A migration dos metadados de extração aplica, reverte e reaplica.

    Dados históricos (linhas anteriores à migration) continuam válidos:
    as novas colunas são nullable e as CHECK constraints aceitam NULL.
    """
    monkeypatch.setattr(settings, "database_url", migrations_database_url)
    alembic_cfg = Config(str(BACKEND_DIR / "alembic.ini"))

    new_columns = {
        "extraction_method",
        "extraction_quality",
        "extraction_warning",
        "extraction_details",
    }

    command.upgrade(alembic_cfg, "f2a91c47d3b8")
    engine = create_engine(migrations_database_url)
    try:
        inspector = inspect(engine)
        columns = {c["name"]: c for c in inspector.get_columns("document_versions")}
        assert new_columns <= set(columns)
        # Nullable: versões históricas ficam NULL, sem backfill.
        assert all(columns[name]["nullable"] for name in new_columns)
        checks = {c["name"] for c in inspector.get_check_constraints("document_versions")}
        assert "ck_document_versions_extraction_method_allowed" in checks
        assert "ck_document_versions_extraction_quality_allowed" in checks
    finally:
        engine.dispose()

    command.downgrade(alembic_cfg, "-1")
    engine = create_engine(migrations_database_url)
    try:
        columns_after = {c["name"] for c in inspect(engine).get_columns("document_versions")}
        assert not (new_columns & columns_after)
    finally:
        engine.dispose()

    command.upgrade(alembic_cfg, "head")
    engine = create_engine(migrations_database_url)
    try:
        columns_final = {c["name"] for c in inspect(engine).get_columns("document_versions")}
        assert new_columns <= columns_final
        with engine.connect() as conn:
            current_revision = conn.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar()
    finally:
        engine.dispose()

    script = ScriptDirectory.from_config(alembic_cfg)
    assert current_revision == script.get_current_head()


def test_structured_chunk_metadata_migration_upgrade_downgrade_upgrade(
    migrations_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Metadados estruturais são anuláveis, reversíveis e sem backfill."""

    monkeypatch.setattr(settings, "database_url", migrations_database_url)
    alembic_cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    new_columns = {
        "page_number",
        "section_title",
        "structure_type",
        "chunking_strategy",
    }
    new_checks = {
        "ck_document_chunks_page_number_positive",
        "ck_document_chunks_structure_type_allowed",
        "ck_document_chunks_chunking_strategy_allowed",
    }

    command.upgrade(alembic_cfg, "4a7c1e9d2b63")
    engine = create_engine(migrations_database_url)
    try:
        inspector = inspect(engine)
        columns = {
            column["name"]: column
            for column in inspector.get_columns("document_chunks")
        }
        assert new_columns <= set(columns)
        assert all(columns[name]["nullable"] for name in new_columns)
        checks = {
            check["name"]
            for check in inspector.get_check_constraints("document_chunks")
        }
        assert new_checks <= checks
    finally:
        engine.dispose()

    command.downgrade(alembic_cfg, "-1")
    engine = create_engine(migrations_database_url)
    try:
        columns_after = {
            column["name"]
            for column in inspect(engine).get_columns("document_chunks")
        }
        assert not (new_columns & columns_after)
    finally:
        engine.dispose()

    command.upgrade(alembic_cfg, "head")
    engine = create_engine(migrations_database_url)
    try:
        inspector = inspect(engine)
        columns_final = {
            column["name"] for column in inspector.get_columns("document_chunks")
        }
        assert new_columns <= columns_final
        with engine.connect() as conn:
            current_revision = conn.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar()
    finally:
        engine.dispose()

    script = ScriptDirectory.from_config(alembic_cfg)
    assert current_revision == script.get_current_head()


def test_localized_search_vector_migration_upgrade_downgrade_upgrade(
    migrations_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A migração localiza o search_vector por idioma, é reversível e
    revectoriza chunks históricos automaticamente (sem backfill)."""
    monkeypatch.setattr(settings, "database_url", migrations_database_url)
    alembic_cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    command.upgrade(alembic_cfg, "e7b1c9d4a2f0")

    engine = create_engine(migrations_database_url)
    institution_id = uuid.uuid4()
    user_id = uuid.uuid4()
    document_id = uuid.uuid4()
    version_id = uuid.uuid4()
    pt_chunk = uuid.uuid4()
    en_chunk = uuid.uuid4()
    other_chunk = uuid.uuid4()
    try:
        inspector = inspect(engine)
        columns = {column["name"]: column for column in inspector.get_columns("document_chunks")}
        expression = columns["search_vector"]["computed"]["sqltext"]
        assert "portuguese" in expression
        assert "english" in expression
        assert "simple" in expression

        with engine.begin() as conn:
            conn.execute(
                text(
                    """INSERT INTO institutions
                    (id, name, code, default_language, supported_languages, is_active)
                    VALUES (:id, 'Test', :code, 'pt', ARRAY['pt','en'], true)"""
                ),
                {"id": institution_id, "code": f"LOC-{uuid.uuid4().hex[:8]}"},
            )
            conn.execute(
                text(
                    """INSERT INTO users
                    (id, institution_id, full_name, email, password_hash, role, is_active)
                    VALUES (:id, :institution_id, 'Admin', :email, 'hash', 'admin', true)"""
                ),
                {
                    "id": user_id,
                    "institution_id": institution_id,
                    "email": f"loc-{uuid.uuid4().hex[:8]}@example.com",
                },
            )
            conn.execute(
                text(
                    """INSERT INTO documents
                    (id, institution_id, created_by_user_id, title, language,
                     official_source, is_active)
                    VALUES (:id, :institution_id, :user_id, 'Doc', 'pt', true, true)"""
                ),
                {"id": document_id, "institution_id": institution_id, "user_id": user_id},
            )
            conn.execute(
                text(
                    """INSERT INTO document_versions
                    (id, document_id, institution_id, uploaded_by_user_id,
                     version_number, original_filename, mime_type, size_bytes,
                     checksum_sha256, storage_path, processing_status)
                    VALUES (:id, :document_id, :institution_id, :user_id,
                            1, 'doc.txt', 'text/plain', 10, :checksum,
                            'inst/doc/version/source.txt', 'processed')"""
                ),
                {
                    "id": version_id,
                    "document_id": document_id,
                    "institution_id": institution_id,
                    "user_id": user_id,
                    "checksum": "a" * 64,
                },
            )
            insert_chunk = text(
                """INSERT INTO document_chunks
                (id, institution_id, document_id, document_version_id,
                 chunk_index, content, normalized_content, content_sha256,
                 start_char, end_char, language)
                VALUES (:id, :institution_id, :document_id, :version_id,
                        :index, :content, :normalized, :checksum, 0, 20, :language)"""
            )
            common = {
                "institution_id": institution_id,
                "document_id": document_id,
                "version_id": version_id,
            }
            conn.execute(
                insert_chunk,
                {
                    **common, "id": pt_chunk, "index": 0,
                    "content": "matricula matriculas", "normalized": "matricula matriculas",
                    "checksum": "b" * 64, "language": "pt",
                },
            )
            conn.execute(
                insert_chunk,
                {
                    **common, "id": en_chunk, "index": 1,
                    "content": "enrollment enrollments", "normalized": "enrollment enrollments",
                    "checksum": "c" * 64, "language": "en",
                },
            )
            conn.execute(
                insert_chunk,
                {
                    **common, "id": other_chunk, "index": 2,
                    "content": "matriculas", "normalized": "matriculas",
                    "checksum": "d" * 64, "language": "fr",
                },
            )

        def vector(conn: Any, chunk_id: uuid.UUID) -> str:
            return conn.execute(
                text("SELECT search_vector::text FROM document_chunks WHERE id = :id"),
                {"id": chunk_id},
            ).scalar_one()

        with engine.connect() as conn:
            # Português: singular e plural colapsam no mesmo stem.
            pt_vector = vector(conn, pt_chunk)
            assert "matricul" in pt_vector
            assert "matriculas" not in pt_vector
            # Inglês: stemming próprio do inglês.
            en_vector = vector(conn, en_chunk)
            assert "enrol" in en_vector
            assert "enrollments" not in en_vector
            # Idioma sem configuração: simple, sem stemming.
            assert "matriculas" in vector(conn, other_chunk)

            index_definition = conn.execute(
                text(
                    "SELECT indexdef FROM pg_indexes "
                    "WHERE indexname = 'ix_document_chunks_search_vector'"
                )
            ).scalar_one()
            assert "USING gin" in index_definition
    finally:
        engine.dispose()

    # Downgrade: volta ao simple; o chunk pt deixa de colapsar o plural.
    command.downgrade(alembic_cfg, "-1")
    engine = create_engine(migrations_database_url)
    try:
        with engine.connect() as conn:
            reverted = conn.execute(
                text("SELECT search_vector::text FROM document_chunks WHERE id = :id"),
                {"id": pt_chunk},
            ).scalar_one()
        assert "matriculas" in reverted
    finally:
        engine.dispose()

    command.upgrade(alembic_cfg, "head")
    engine = create_engine(migrations_database_url)
    try:
        with engine.connect() as conn:
            current_revision = conn.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar()
    finally:
        engine.dispose()
    script = ScriptDirectory.from_config(alembic_cfg)
    assert current_revision == script.get_current_head()
