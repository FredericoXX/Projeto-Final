"""add conversational answer sources

Revision ID: c8b4f2d9e6a1
Revises: b7e2d8a9f4c1
Create Date: 2026-07-13 23:30:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c8b4f2d9e6a1"
down_revision: str | Sequence[str] | None = "b7e2d8a9f4c1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Persist atomic conversational turns and their cited source snapshots."""
    op.create_unique_constraint(
        "uq_messages_id_conversation_institution",
        "messages",
        ["id", "conversation_id", "institution_id"],
    )
    op.create_unique_constraint(
        "uq_messages_id_institution_role",
        "messages",
        ["id", "institution_id", "role"],
    )
    op.add_column(
        "messages",
        sa.Column("reply_to_message_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_messages_reply_to_conversation_institution",
        "messages",
        "messages",
        ["reply_to_message_id", "conversation_id", "institution_id"],
        ["id", "conversation_id", "institution_id"],
    )
    op.create_check_constraint(
        "ck_messages_reply_to_not_self",
        "messages",
        "reply_to_message_id IS NULL OR reply_to_message_id <> id",
    )

    op.create_unique_constraint(
        "uq_document_chunks_id_version_document_institution",
        "document_chunks",
        ["id", "document_version_id", "document_id", "institution_id"],
    )

    op.create_table(
        "message_sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("institution_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("message_role", sa.String(length=20), nullable=False),
        sa.Column("chunk_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("evidence_id", sa.String(length=32), nullable=False),
        sa.Column("citation_index", sa.Integer(), nullable=False),
        sa.Column("document_title", sa.String(length=255), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("source_url", sa.String(length=2048), nullable=True),
        sa.Column("official_source", sa.Boolean(), nullable=False),
        sa.Column("language", sa.String(length=8), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=True),
        sa.Column("valid_until", sa.Date(), nullable=True),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["message_id", "institution_id", "message_role"],
            ["messages.id", "messages.institution_id", "messages.role"],
            name="fk_message_sources_message_institution_role",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["chunk_id", "document_version_id", "document_id", "institution_id"],
            [
                "document_chunks.id",
                "document_chunks.document_version_id",
                "document_chunks.document_id",
                "document_chunks.institution_id",
            ],
            name="fk_message_sources_chunk_version_document_institution",
        ),
        sa.UniqueConstraint(
            "message_id",
            "evidence_id",
            name="uq_message_sources_message_evidence",
        ),
        sa.UniqueConstraint(
            "message_id",
            "citation_index",
            name="uq_message_sources_message_citation",
        ),
        sa.UniqueConstraint(
            "message_id",
            "chunk_id",
            name="uq_message_sources_message_chunk",
        ),
        sa.CheckConstraint(
            "message_role = 'assistant'",
            name="ck_message_sources_assistant_role",
        ),
        sa.CheckConstraint(
            "citation_index >= 0",
            name="ck_message_sources_citation_non_negative",
        ),
        sa.CheckConstraint(
            "chunk_index >= 0",
            name="ck_message_sources_chunk_index_non_negative",
        ),
        sa.CheckConstraint(
            "btrim(evidence_id) <> ''",
            name="ck_message_sources_evidence_not_blank",
        ),
        sa.CheckConstraint(
            "evidence_id ~ '^E[1-9][0-9]*$'",
            name="ck_message_sources_evidence_format",
        ),
        sa.CheckConstraint(
            "btrim(document_title) <> ''",
            name="ck_message_sources_title_not_blank",
        ),
        sa.CheckConstraint(
            "btrim(language) <> ''",
            name="ck_message_sources_language_not_blank",
        ),
        sa.CheckConstraint(
            "char_length(content_sha256) = 64",
            name="ck_message_sources_checksum_length",
        ),
        sa.CheckConstraint(
            "valid_from IS NULL OR valid_until IS NULL OR valid_from <= valid_until",
            name="ck_message_sources_validity_range",
        ),
    )
    # message_id and (message_id, citation_index) are already covered by the
    # three UNIQUE indexes above; only non-duplicating lookup indexes follow.
    op.create_index(
        "ix_message_sources_institution_id", "message_sources", ["institution_id"]
    )
    op.create_index("ix_message_sources_chunk_id", "message_sources", ["chunk_id"])
    op.create_index("ix_message_sources_document_id", "message_sources", ["document_id"])
    op.create_index(
        "ix_message_sources_document_version_id",
        "message_sources",
        ["document_version_id"],
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_referenced_chunk_update()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM message_sources
                WHERE chunk_id = OLD.id
                  AND document_version_id = OLD.document_version_id
                  AND document_id = OLD.document_id
                  AND institution_id = OLD.institution_id
            ) THEN
                RAISE EXCEPTION 'Referenced document chunks are immutable.'
                    USING ERRCODE = '23503',
                          CONSTRAINT = 'fk_message_sources_chunk_version_document_institution';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_document_chunks_prevent_referenced_update
        BEFORE UPDATE ON document_chunks
        FOR EACH ROW
        EXECUTE FUNCTION prevent_referenced_chunk_update()
        """
    )


def downgrade() -> None:
    """Remove source snapshots and restore the previous message/chunk schema."""
    op.execute(
        """
        DROP TRIGGER IF EXISTS trg_document_chunks_prevent_referenced_update
        ON document_chunks
        """
    )
    op.execute("DROP FUNCTION IF EXISTS prevent_referenced_chunk_update()")
    op.drop_index("ix_message_sources_document_version_id", table_name="message_sources")
    op.drop_index("ix_message_sources_document_id", table_name="message_sources")
    op.drop_index("ix_message_sources_chunk_id", table_name="message_sources")
    op.drop_index("ix_message_sources_institution_id", table_name="message_sources")
    op.drop_table("message_sources")

    op.drop_constraint(
        "fk_messages_reply_to_conversation_institution",
        "messages",
        type_="foreignkey",
    )
    op.drop_constraint("ck_messages_reply_to_not_self", "messages", type_="check")
    op.drop_column("messages", "reply_to_message_id")
    op.drop_constraint(
        "uq_messages_id_institution_role", "messages", type_="unique"
    )
    op.drop_constraint(
        "uq_messages_id_conversation_institution", "messages", type_="unique"
    )
    op.drop_constraint(
        "uq_document_chunks_id_version_document_institution",
        "document_chunks",
        type_="unique",
    )
