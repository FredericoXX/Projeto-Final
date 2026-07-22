"""add composite multi institution constraints

Revision ID: 3ed4bcad52c8
Revises: 9ec09d09f22f
Create Date: 2026-07-10 22:04:45.056909

"""
from typing import Sequence, Union

from alembic import op

# Identificadores da revisão, usados pelo Alembic.
revision: str = '3ed4bcad52c8'
down_revision: Union[str, Sequence[str], None] = '9ec09d09f22f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    The existing simple foreign keys only guarantee that a referenced row
    exists, not that it belongs to the same institution. This adds
    "degenerate" unique constraints on (id, institution_id) — id alone is
    already unique, they exist purely to be referenced by composite
    foreign keys — and replaces the foreign keys they supersede with
    composite ones, so PostgreSQL itself rejects any row whose
    institution_id doesn't match its referenced row's institution_id.
    """
    op.create_unique_constraint(
        "uq_users_id_institution_id", "users", ["id", "institution_id"]
    )
    op.create_unique_constraint(
        "uq_conversations_id_institution_id", "conversations", ["id", "institution_id"]
    )

    # conversations.user_id deve pertencer a conversations.institution_id.
    op.drop_constraint("fk_conversations_user_id_users", "conversations", type_="foreignkey")
    op.create_foreign_key(
        "fk_conversations_user_id_institution_id_users",
        "conversations",
        "users",
        ["user_id", "institution_id"],
        ["id", "institution_id"],
    )

    # messages.conversation_id deve pertencer a messages.institution_id.
    op.drop_constraint(
        "fk_messages_conversation_id_conversations", "messages", type_="foreignkey"
    )
    op.create_foreign_key(
        "fk_messages_conversation_id_institution_id_conversations",
        "messages",
        "conversations",
        ["conversation_id", "institution_id"],
        ["id", "institution_id"],
    )

    # messages.user_id, quando não nulo, deve pertencer a messages.institution_id.
    # O MATCH SIMPLE padrão do PostgreSQL ignora esta restrição quando user_id é
    # NULL, mantendo compatibilidade com mensagens "assistant" futuras criadas
    # sem um utilizador autenticado.
    op.drop_constraint("fk_messages_user_id_users", "messages", type_="foreignkey")
    op.create_foreign_key(
        "fk_messages_user_id_institution_id_users",
        "messages",
        "users",
        ["user_id", "institution_id"],
        ["id", "institution_id"],
    )


def downgrade() -> None:
    """Downgrade schema: restore the original simple foreign keys and drop
    the composite ones and the unique constraints that supported them."""
    op.drop_constraint(
        "fk_messages_user_id_institution_id_users", "messages", type_="foreignkey"
    )
    op.create_foreign_key(
        "fk_messages_user_id_users", "messages", "users", ["user_id"], ["id"]
    )

    op.drop_constraint(
        "fk_messages_conversation_id_institution_id_conversations",
        "messages",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_messages_conversation_id_conversations",
        "messages",
        "conversations",
        ["conversation_id"],
        ["id"],
    )

    op.drop_constraint(
        "fk_conversations_user_id_institution_id_users", "conversations", type_="foreignkey"
    )
    op.create_foreign_key(
        "fk_conversations_user_id_users", "conversations", "users", ["user_id"], ["id"]
    )

    op.drop_constraint(
        "uq_conversations_id_institution_id", "conversations", type_="unique"
    )
    op.drop_constraint("uq_users_id_institution_id", "users", type_="unique")
