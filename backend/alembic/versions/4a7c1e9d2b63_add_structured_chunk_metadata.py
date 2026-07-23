"""add structured chunk metadata

Revision ID: 4a7c1e9d2b63
Revises: f2a91c47d3b8
Create Date: 2026-07-23

As colunas são anuláveis e não recebem backfill: chunks históricos não
ganham uma página ou estratégia que nunca foi observada no processamento.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "4a7c1e9d2b63"
down_revision: str | Sequence[str] | None = "f2a91c47d3b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "document_chunks",
        sa.Column("page_number", sa.Integer(), nullable=True),
    )
    op.add_column(
        "document_chunks",
        sa.Column("section_title", sa.Text(), nullable=True),
    )
    op.add_column(
        "document_chunks",
        sa.Column("structure_type", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "document_chunks",
        sa.Column("chunking_strategy", sa.String(length=32), nullable=True),
    )
    op.create_check_constraint(
        "ck_document_chunks_page_number_positive",
        "document_chunks",
        "page_number IS NULL OR page_number > 0",
    )
    op.create_check_constraint(
        "ck_document_chunks_structure_type_allowed",
        "document_chunks",
        "structure_type IS NULL OR structure_type IN "
        "('heading', 'paragraph', 'table_row', 'list_item', "
        "'list_block', 'mixed', 'fallback_fragment')",
    )
    op.create_check_constraint(
        "ck_document_chunks_chunking_strategy_allowed",
        "document_chunks",
        "chunking_strategy IS NULL OR chunking_strategy IN "
        "('structured_v1', 'character_fallback_v1')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_document_chunks_chunking_strategy_allowed",
        "document_chunks",
        type_="check",
    )
    op.drop_constraint(
        "ck_document_chunks_structure_type_allowed",
        "document_chunks",
        type_="check",
    )
    op.drop_constraint(
        "ck_document_chunks_page_number_positive",
        "document_chunks",
        type_="check",
    )
    op.drop_column("document_chunks", "chunking_strategy")
    op.drop_column("document_chunks", "structure_type")
    op.drop_column("document_chunks", "section_title")
    op.drop_column("document_chunks", "page_number")
