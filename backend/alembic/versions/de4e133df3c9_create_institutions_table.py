"""create institutions table

Revision ID: de4e133df3c9
Revises: db13417f9dc4
Create Date: 2026-07-06 01:56:03.381806

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'de4e133df3c9'
down_revision: Union[str, Sequence[str], None] = 'db13417f9dc4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "institutions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("domain", sa.String(length=255), nullable=True),
        sa.Column("default_language", sa.String(length=8), nullable=False),
        sa.Column(
            "supported_languages",
            postgresql.ARRAY(sa.String(length=8)),
            nullable=False,
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
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
        sa.UniqueConstraint("code", name="uq_institutions_code"),
        sa.CheckConstraint(
            "default_language = ANY (supported_languages)",
            name="ck_institutions_default_language_supported",
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("institutions")
