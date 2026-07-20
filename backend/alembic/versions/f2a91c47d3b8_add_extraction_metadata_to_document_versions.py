"""Add extraction metadata columns to document_versions.

Suporte a PDFs digitalizados: regista como o texto foi obtido (native,
ocr ou mixed), a qualidade agregada, um aviso curto quando a qualidade é
baixa e os metadados por página. Versões históricas ficam NULL — nunca
se assume que foram extraídas por "native" e não há backfill.

Revision ID: f2a91c47d3b8
Revises: 800e7b121e93
Create Date: 2026-07-20
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "f2a91c47d3b8"
down_revision: Union[str, Sequence[str], None] = "800e7b121e93"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "document_versions",
        sa.Column("extraction_method", sa.String(length=10), nullable=True),
    )
    op.add_column(
        "document_versions",
        sa.Column("extraction_quality", sa.String(length=10), nullable=True),
    )
    op.add_column(
        "document_versions",
        sa.Column("extraction_warning", sa.Text(), nullable=True),
    )
    op.add_column(
        "document_versions",
        sa.Column("extraction_details", JSONB(), nullable=True),
    )
    op.create_check_constraint(
        "ck_document_versions_extraction_method_allowed",
        "document_versions",
        "extraction_method IS NULL OR extraction_method IN ('native', 'ocr', 'mixed')",
    )
    op.create_check_constraint(
        "ck_document_versions_extraction_quality_allowed",
        "document_versions",
        "extraction_quality IS NULL OR extraction_quality IN ('high', 'medium', 'low')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_document_versions_extraction_quality_allowed",
        "document_versions",
        type_="check",
    )
    op.drop_constraint(
        "ck_document_versions_extraction_method_allowed",
        "document_versions",
        type_="check",
    )
    op.drop_column("document_versions", "extraction_details")
    op.drop_column("document_versions", "extraction_warning")
    op.drop_column("document_versions", "extraction_quality")
    op.drop_column("document_versions", "extraction_method")
