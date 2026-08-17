"""add chunk embeddings table

Revision ID: c4f7ab19d3e5
Revises: a5c31f70b8d2
Create Date: 2026-08-16

Tabela **acrescentada**, nunca uma alteração à tabela de produção: nenhuma
coluna de ``document_chunks`` é criada, alterada ou removida, e ``search_vector``
mantém-se exatamente como estava. O retrieval lexical não lê esta tabela.

A extensão ``vector`` já está ativa desde a primeira migration (db13417f9dc4),
pelo que aqui não é criada nem alterada.

Sem índice ANN por decisão explícita: um índice HNSW/IVFFlat tornaria o
resultado da pesquisa dependente dos parâmetros de recall do índice, e a
experiência que esta tabela serve compara estratégias, não configurações de
índice. Com um corpus desta ordem a pesquisa exata é barata.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "c4f7ab19d3e5"
down_revision: str | Sequence[str] | None = "a5c31f70b8d2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Espelha app.models.chunk_embedding.EMBEDDING_DIMENSION. Um modelo de largura
# diferente exige migration própria — é o tipo da coluna que garante que os
# vetores comparados têm a mesma dimensão.
EMBEDDING_DIMENSION = 1536


def upgrade() -> None:
    op.create_table(
        "chunk_embeddings",
        sa.Column("chunk_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("configuration_version", sa.String(length=64), nullable=False),
        sa.Column("embedded_content_sha256", sa.String(length=64), nullable=False),
        sa.Column("embedding", Vector(EMBEDDING_DIMENSION), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["chunk_id"],
            ["document_chunks.id"],
            name="fk_chunk_embeddings_chunk_id_document_chunks",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "chunk_id", "provider", "model", name="pk_chunk_embeddings"
        ),
        # ``btrim(x)`` sem segundo argumento corta apenas espaços: um valor só
        # com tabulações ou mudanças de linha passaria por identificador válido.
        sa.CheckConstraint(
            r"btrim(provider, E' \t\n\r\f\v') <> ''",
            name="ck_chunk_embeddings_provider_not_blank",
        ),
        sa.CheckConstraint(
            r"btrim(model, E' \t\n\r\f\v') <> ''",
            name="ck_chunk_embeddings_model_not_blank",
        ),
        sa.CheckConstraint(
            r"btrim(configuration_version, E' \t\n\r\f\v') <> ''",
            name="ck_chunk_embeddings_configuration_version_not_blank",
        ),
    )


def downgrade() -> None:
    op.drop_table("chunk_embeddings")
