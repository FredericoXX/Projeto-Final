"""add lexical search vector

Revision ID: b7e2d8a9f4c1
Revises: 68cb34527411
Create Date: 2026-07-13 21:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b7e2d8a9f4c1"
down_revision: str | Sequence[str] | None = "68cb34527411"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the generated lexical vector and its GIN index."""
    op.add_column(
        "document_chunks",
        sa.Column(
            "search_vector",
            postgresql.TSVECTOR(),
            sa.Computed(
                "to_tsvector('simple'::regconfig, normalized_content)",
                persisted=True,
            ),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_document_chunks_search_vector",
        "document_chunks",
        ["search_vector"],
        unique=False,
        postgresql_using="gin",
    )


def downgrade() -> None:
    """Remove the GIN index before removing its generated column."""
    op.drop_index(
        "ix_document_chunks_search_vector",
        table_name="document_chunks",
        postgresql_using="gin",
    )
    op.drop_column("document_chunks", "search_vector")
