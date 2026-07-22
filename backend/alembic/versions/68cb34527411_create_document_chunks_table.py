"""create document chunks table

Revision ID: 68cb34527411
Revises: 1482b165c943
Create Date: 2026-07-13 17:27:00.134449

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# Identificadores da revisão, usados pelo Alembic.
revision: str = '68cb34527411'
down_revision: Union[str, Sequence[str], None] = '1482b165c943'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Cria "document_chunks": os segmentos do texto extraído de cada versão
    de documento, estrutura interna que prepara futuras estratégias de
    recuperação de informação (sem embeddings, TSVECTOR ou índices de
    pesquisa nesta fase). A foreign key composta de três colunas segue a
    mesma estratégia de defesa em profundidade das migrations 3ed4bcad52c8
    e 1482b165c943: o PostgreSQL garante diretamente que um chunk pertence
    à versão, ao documento e à instituição corretos, sem depender do
    service. A UNIQUE de suporte em "document_versions" é "degenerada"
    (id já é único) e existe apenas para ser referenciada por essa FK.
    """
    op.create_unique_constraint(
        "uq_document_versions_id_document_id_institution_id",
        "document_versions",
        ["id", "document_id", "institution_id"],
    )

    op.create_table(
        "document_chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("institution_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("normalized_content", sa.Text(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("start_char", sa.Integer(), nullable=False),
        sa.Column("end_char", sa.Integer(), nullable=False),
        sa.Column("language", sa.String(length=8), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["institution_id"],
            ["institutions.id"],
            name="fk_document_chunks_institution_id_institutions",
        ),
        # Um chunk pertence obrigatoriamente à versão indicada, ao documento
        # dessa versão e à mesma instituição.
        sa.ForeignKeyConstraint(
            ["document_version_id", "document_id", "institution_id"],
            [
                "document_versions.id",
                "document_versions.document_id",
                "document_versions.institution_id",
            ],
            name="fk_document_chunks_version_document_institution",
        ),
        sa.UniqueConstraint(
            "document_version_id",
            "chunk_index",
            name="uq_document_chunks_document_version_id_chunk_index",
        ),
        sa.CheckConstraint(
            "chunk_index >= 0",
            name="ck_document_chunks_chunk_index_non_negative",
        ),
        sa.CheckConstraint(
            "start_char >= 0",
            name="ck_document_chunks_start_char_non_negative",
        ),
        sa.CheckConstraint(
            "end_char > start_char",
            name="ck_document_chunks_end_char_after_start_char",
        ),
        sa.CheckConstraint(
            "btrim(content) <> ''",
            name="ck_document_chunks_content_not_blank",
        ),
        sa.CheckConstraint(
            "btrim(normalized_content) <> ''",
            name="ck_document_chunks_normalized_content_not_blank",
        ),
    )
    op.create_index("ix_document_chunks_institution_id", "document_chunks", ["institution_id"])
    op.create_index("ix_document_chunks_document_id", "document_chunks", ["document_id"])
    op.create_index(
        "ix_document_chunks_document_version_id",
        "document_chunks",
        ["document_version_id"],
    )
    # Consultas futuras por instituição e idioma. O par
    # (document_version_id, chunk_index) já é indexado pela UNIQUE
    # constraint; não é criado um índice adicional duplicado.
    op.create_index(
        "ix_document_chunks_institution_id_language",
        "document_chunks",
        ["institution_id", "language"],
    )


def downgrade() -> None:
    """Downgrade schema: remove document_chunks, os seus índices e a
    constraint de suporte em document_versions."""
    op.drop_index("ix_document_chunks_institution_id_language", table_name="document_chunks")
    op.drop_index("ix_document_chunks_document_version_id", table_name="document_chunks")
    op.drop_index("ix_document_chunks_document_id", table_name="document_chunks")
    op.drop_index("ix_document_chunks_institution_id", table_name="document_chunks")
    op.drop_table("document_chunks")

    op.drop_constraint(
        "uq_document_versions_id_document_id_institution_id",
        "document_versions",
        type_="unique",
    )
