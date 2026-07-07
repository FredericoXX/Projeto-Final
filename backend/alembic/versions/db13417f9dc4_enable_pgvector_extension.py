"""enable pgvector extension

Revision ID: db13417f9dc4
Revises: 
Create Date: 2026-07-01 15:10:18.542314

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'db13417f9dc4'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Extensão ativada antecipadamente (primeira migration) para que futuras
    # tabelas possam usar colunas do tipo vector na pesquisa semântica de documentos.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP EXTENSION IF EXISTS vector")
