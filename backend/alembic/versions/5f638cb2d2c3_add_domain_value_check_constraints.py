"""add domain value check constraints

Revision ID: 5f638cb2d2c3
Revises: 3ed4bcad52c8
Create Date: 2026-07-11 02:19:43.344797

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '5f638cb2d2c3'
down_revision: Union[str, Sequence[str], None] = '3ed4bcad52c8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    The allowed values for users.role, conversations.status and
    messages.role were until now only enforced by the API schemas.
    These CHECK constraints mirror those rules in PostgreSQL itself
    (the same defense-in-depth strategy already used for the composite
    multi-institution foreign keys), so rows inserted outside the API —
    seed scripts, future services, direct SQL — can't hold invalid
    values either. Existing valid data satisfies all three constraints,
    so this migration performs no data changes.
    """
    op.create_check_constraint(
        "ck_users_role_allowed",
        "users",
        "role IN ('admin', 'staff', 'student', 'user')",
    )
    op.create_check_constraint(
        "ck_conversations_status_allowed",
        "conversations",
        "status IN ('active', 'closed', 'archived')",
    )
    op.create_check_constraint(
        "ck_messages_role_allowed",
        "messages",
        "role IN ('user', 'assistant', 'system')",
    )


def downgrade() -> None:
    """Downgrade schema: drop the three domain-value CHECK constraints."""
    op.drop_constraint("ck_messages_role_allowed", "messages", type_="check")
    op.drop_constraint("ck_conversations_status_allowed", "conversations", type_="check")
    op.drop_constraint("ck_users_role_allowed", "users", type_="check")
