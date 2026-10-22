"""create user_external_identities

Revision ID: e3b9f1c7a5d8
Revises: d1a7c3e9b4f2
Create Date: 2026-10-09

Associação entre uma conta local, a sua instituição e um identificador
externo estável do sistema académico. Tabela nova e vazia: nenhuma conta
existente ganha associação, e o email não é usado para inferir nenhuma.

A tabela não guarda dados académicos. Os pedidos consultados ao fornecedor
não são persistidos neste incremento.

Reversão: o downgrade remove a tabela e, com ela, as associações
estabelecidas. Isso não afeta contas, conversas nem citações; as associações
teriam de ser restabelecidas administrativamente depois de um novo upgrade.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e3b9f1c7a5d8"
down_revision: str | Sequence[str] | None = "d1a7c3e9b4f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_external_identities",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("institution_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("external_subject", sa.String(length=128), nullable=False),
        sa.Column("link_method", sa.String(length=30), nullable=False),
        sa.Column("linked_by_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["institution_id"],
            ["institutions.id"],
            name="fk_user_external_identities_institution_id_institutions",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "institution_id"],
            ["users.id", "users.institution_id"],
            name="fk_user_external_identities_user_institution",
        ),
        sa.ForeignKeyConstraint(
            ["linked_by_user_id", "institution_id"],
            ["users.id", "users.institution_id"],
            name="fk_user_external_identities_linked_by_institution",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_user_external_identities_user_id"),
        sa.UniqueConstraint(
            "institution_id",
            "external_subject",
            name="uq_user_external_identities_institution_subject",
        ),
        sa.CheckConstraint(
            r"btrim(external_subject, E' \t\n\r\f\v') <> ''",
            name="ck_user_external_identities_subject_not_blank",
        ),
        sa.CheckConstraint(
            "link_method IN ('administrative')",
            name="ck_user_external_identities_link_method_allowed",
        ),
    )
    op.create_index(
        "ix_user_external_identities_institution_id",
        "user_external_identities",
        ["institution_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_user_external_identities_institution_id",
        table_name="user_external_identities",
    )
    op.drop_table("user_external_identities")
