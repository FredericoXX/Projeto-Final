"""add institution human support contact

Revision ID: a5c31f70b8d2
Revises: e7b1c9d4a2f0
Create Date: 2026-08-13

Destino humano default por instituição, usado pelo encaminhamento E1
(A2.3a). As três colunas são anuláveis e não recebem backfill: nenhuma
instituição existente ganha um contacto que ninguém configurou, e a
constraint aceita o estado "tudo NULL" em que todas as linhas históricas
ficam. Não há aqui qualquer contacto real — a configuração é feita pela
superfície administrativa.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a5c31f70b8d2"
down_revision: str | Sequence[str] | None = "e7b1c9d4a2f0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Duas condições combinadas, espelhando o modelo e
# is_valid_human_support_configuration (app/schemas/institution.py): nenhum
# campo presente pode ser vazio ou só whitespace, e a configuração está ou
# totalmente ausente, ou com nome e pelo menos uma via de contacto. O conjunto
# de corte do btrim é explícito — o btrim(x) sem argumento corta apenas
# espaços e deixaria passar um valor composto só por tabs ou newlines.
HUMAN_SUPPORT_CHECK = (
    "(human_support_name IS NULL"
    r" OR btrim(human_support_name, E' \t\n\r\f\v') <> '')"
    " AND (human_support_email IS NULL"
    r" OR btrim(human_support_email, E' \t\n\r\f\v') <> '')"
    " AND (human_support_url IS NULL"
    r" OR btrim(human_support_url, E' \t\n\r\f\v') <> '')"
    " AND ("
    "(human_support_name IS NULL"
    " AND human_support_email IS NULL"
    " AND human_support_url IS NULL)"
    " OR (human_support_name IS NOT NULL"
    " AND (human_support_email IS NOT NULL OR human_support_url IS NOT NULL))"
    ")"
)


def upgrade() -> None:
    op.add_column(
        "institutions",
        sa.Column("human_support_name", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "institutions",
        sa.Column("human_support_email", sa.String(length=320), nullable=True),
    )
    op.add_column(
        "institutions",
        sa.Column("human_support_url", sa.String(length=2048), nullable=True),
    )
    op.create_check_constraint(
        "ck_institutions_human_support_configuration",
        "institutions",
        HUMAN_SUPPORT_CHECK,
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_institutions_human_support_configuration",
        "institutions",
        type_="check",
    )
    op.drop_column("institutions", "human_support_url")
    op.drop_column("institutions", "human_support_email")
    op.drop_column("institutions", "human_support_name")
