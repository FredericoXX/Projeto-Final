"""add knowledge_manager role

Revision ID: d1a7c3e9b4f2
Revises: c4f7ab19d3e5
Create Date: 2026-10-09

Acrescenta ``knowledge_manager`` aos papéis aceites por ``ck_users_role_allowed``.
A gestão documental passa a pertencer a este papel e deixa de ser uma
permissão implícita de ``admin`` (ver app/core/permissions.py).

Preservação de dados: nenhuma linha é alterada. Nenhum ``admin`` existente é
convertido em ``knowledge_manager`` — essa atribuição é uma decisão de cada
instituição, feita por um admin autenticado através de ``PATCH /users/{id}``.

Reversão: o downgrade repõe a constraint anterior **apenas se não existir
nenhuma conta com o papel novo**. Se existir, recusa-se a continuar em vez de
apagar, desativar ou reatribuir contas em silêncio: o operador tem de decidir
primeiro que papel cada uma dessas contas deve ter.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d1a7c3e9b4f2"
down_revision: str | Sequence[str] | None = "c4f7ab19d3e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLES_AFTER = "role IN ('admin', 'knowledge_manager', 'staff', 'student', 'user')"
ROLES_BEFORE = "role IN ('admin', 'staff', 'student', 'user')"


def upgrade() -> None:
    op.drop_constraint("ck_users_role_allowed", "users", type_="check")
    op.create_check_constraint("ck_users_role_allowed", "users", ROLES_AFTER)


def downgrade() -> None:
    remaining = op.get_bind().scalar(
        sa.text("SELECT count(*) FROM users WHERE role = 'knowledge_manager'")
    )
    if remaining:
        msg = (
            f"Cannot downgrade: {remaining} account(s) still have the "
            "'knowledge_manager' role. Reassign them to an existing role "
            "before downgrading; no account is changed automatically."
        )
        raise RuntimeError(msg)
    op.drop_constraint("ck_users_role_allowed", "users", type_="check")
    op.create_check_constraint("ck_users_role_allowed", "users", ROLES_BEFORE)
