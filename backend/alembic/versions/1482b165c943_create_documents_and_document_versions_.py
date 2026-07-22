"""create documents and document versions tables

Revision ID: 1482b165c943
Revises: 5f638cb2d2c3
Create Date: 2026-07-13 15:13:15.720987

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# Identificadores da revisão, usados pelo Alembic.
revision: str = '1482b165c943'
down_revision: Union[str, Sequence[str], None] = '5f638cb2d2c3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Cria o núcleo documental: "documents" (documento lógico e metadados
    institucionais) e "document_versions" (cada ficheiro/revisão concreta).
    O binário fica no armazenamento local; a base guarda apenas metadados,
    o texto extraído e o caminho relativo do ficheiro. As foreign keys
    compostas seguem a mesma estratégia de defesa em profundidade da
    migration 3ed4bcad52c8: o PostgreSQL rejeita qualquer combinação de
    linhas de instituições diferentes.
    """
    op.create_table(
        "documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("institution_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("language", sa.String(length=8), nullable=False),
        sa.Column("source_url", sa.String(length=2048), nullable=True),
        sa.Column(
            "official_source",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column("valid_from", sa.Date(), nullable=True),
        sa.Column("valid_until", sa.Date(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["institution_id"],
            ["institutions.id"],
            name="fk_documents_institution_id_institutions",
        ),
        # Quem cria o documento tem de pertencer à mesma instituição.
        sa.ForeignKeyConstraint(
            ["created_by_user_id", "institution_id"],
            ["users.id", "users.institution_id"],
            name="fk_documents_created_by_user_id_institution_id_users",
        ),
        # Constraint "degenerada": suporta a foreign key composta a partir
        # de document_versions.
        sa.UniqueConstraint("id", "institution_id", name="uq_documents_id_institution_id"),
        sa.CheckConstraint(
            "valid_from IS NULL OR valid_until IS NULL OR valid_from <= valid_until",
            name="ck_documents_validity_range",
        ),
    )
    op.create_index("ix_documents_institution_id", "documents", ["institution_id"])
    op.create_index("ix_documents_created_by_user_id", "documents", ["created_by_user_id"])
    op.create_index("ix_documents_language", "documents", ["language"])
    op.create_index(
        "ix_documents_institution_id_is_active",
        "documents",
        ["institution_id", "is_active"],
    )
    op.create_index(
        "ix_documents_institution_id_official_source",
        "documents",
        ["institution_id", "official_source"],
    )

    op.create_table(
        "document_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("institution_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("uploaded_by_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("mime_type", sa.String(length=100), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=False),
        # Sempre relativo ao storage root; caminhos absolutos nunca entram na base.
        sa.Column("storage_path", sa.String(length=1024), nullable=False),
        sa.Column(
            "processing_status",
            sa.String(length=30),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("processing_error", sa.Text(), nullable=True),
        sa.Column("extracted_text", sa.Text(), nullable=True),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["institution_id"],
            ["institutions.id"],
            name="fk_document_versions_institution_id_institutions",
        ),
        # Uma versão pertence obrigatoriamente à mesma instituição do
        # documento e de quem fez o upload.
        sa.ForeignKeyConstraint(
            ["document_id", "institution_id"],
            ["documents.id", "documents.institution_id"],
            name="fk_document_versions_document_id_institution_id_documents",
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by_user_id", "institution_id"],
            ["users.id", "users.institution_id"],
            name="fk_document_versions_uploaded_by_user_id_institution_id_users",
        ),
        sa.UniqueConstraint(
            "document_id",
            "version_number",
            name="uq_document_versions_document_id_version_number",
        ),
        # O mesmo checksum pode existir em instituições diferentes, mas
        # nunca duas vezes na mesma instituição.
        sa.UniqueConstraint(
            "institution_id",
            "checksum_sha256",
            name="uq_document_versions_institution_id_checksum",
        ),
        sa.CheckConstraint(
            "version_number > 0",
            name="ck_document_versions_version_number_positive",
        ),
        sa.CheckConstraint(
            "size_bytes > 0",
            name="ck_document_versions_size_bytes_positive",
        ),
        sa.CheckConstraint(
            "processing_status IN ('pending', 'processing', 'processed', 'failed')",
            name="ck_document_versions_processing_status_allowed",
        ),
        sa.CheckConstraint(
            "page_count IS NULL OR page_count >= 0",
            name="ck_document_versions_page_count_non_negative",
        ),
    )
    op.create_index("ix_document_versions_document_id", "document_versions", ["document_id"])
    op.create_index(
        "ix_document_versions_institution_id", "document_versions", ["institution_id"]
    )
    op.create_index(
        "ix_document_versions_uploaded_by_user_id",
        "document_versions",
        ["uploaded_by_user_id"],
    )
    op.create_index(
        "ix_document_versions_processing_status",
        "document_versions",
        ["processing_status"],
    )


def downgrade() -> None:
    """Downgrade schema: remove as tabelas documentais e os seus índices."""
    op.drop_index("ix_document_versions_processing_status", table_name="document_versions")
    op.drop_index("ix_document_versions_uploaded_by_user_id", table_name="document_versions")
    op.drop_index("ix_document_versions_institution_id", table_name="document_versions")
    op.drop_index("ix_document_versions_document_id", table_name="document_versions")
    op.drop_table("document_versions")

    op.drop_index("ix_documents_institution_id_official_source", table_name="documents")
    op.drop_index("ix_documents_institution_id_is_active", table_name="documents")
    op.drop_index("ix_documents_language", table_name="documents")
    op.drop_index("ix_documents_created_by_user_id", table_name="documents")
    op.drop_index("ix_documents_institution_id", table_name="documents")
    op.drop_table("documents")
