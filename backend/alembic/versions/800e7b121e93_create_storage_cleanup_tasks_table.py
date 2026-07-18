"""create storage cleanup tasks table

Revision ID: 800e7b121e93
Revises: c8b4f2d9e6a1
Create Date: 2026-07-18 14:30:06.725516

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '800e7b121e93'
down_revision: Union[str, Sequence[str], None] = 'c8b4f2d9e6a1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Cria "storage_cleanup_tasks": tarefas duráveis de limpeza do
    armazenamento local, registadas na mesma transação que elimina um
    documento. Sem foreign key para documents de propósito — o documento
    é removido nessa transação; document_id fica apenas para diagnóstico.
    """
    op.create_table(
        "storage_cleanup_tasks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("storage_path", sa.String(length=1024), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "btrim(storage_path) <> ''",
            name="ck_storage_cleanup_tasks_path_not_blank",
        ),
    )


def downgrade() -> None:
    """Downgrade schema: remove a tabela de tarefas de limpeza."""
    op.drop_table("storage_cleanup_tasks")
