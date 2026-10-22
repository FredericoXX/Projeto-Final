"""add decision policy v1.7 experimental storage

Revision ID: a8c4e2f6b1d9
Revises: e3b9f1c7a5d8
Create Date: 2026-10-22

Três alterações da extensão experimental da política de decisão v1.7:

1. ``documents.access_roles`` — autorização documental por papel (C13 de
   ``app.documents.retrievability``). Coluna nova com ``'{}'`` por omissão:
   **todos os documentos existentes continuam sem restrição de papel**, isto
   é, públicos dentro da instituição, exatamente como antes. Uma constraint
   limita os valores aos papéis existentes.
2. ``institution_decision_catalogs`` — domínio de âmbito (D1) e catálogo de
   serviços competentes (D6), por versões imutáveis, no máximo uma ativa por
   instituição. Tabela nova e vazia: nenhuma instituição fica configurada.
3. ``decision_records`` — registo interno protegido das execuções da política.
   Tabela nova e vazia.

Reversão: o downgrade **recusa-se** a correr se existir algum documento com
restrição de papel (remover a coluna tornaria esses documentos públicos sem
aviso), alguma versão de catálogo ou algum registo de decisão (perder-se-iam
configuração e auditoria). Para reverter, as restrições, os catálogos e os
registos têm de ser tratados explicitamente antes.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a8c4e2f6b1d9"
down_revision: str | Sequence[str] | None = "e3b9f1c7a5d8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column(
            "access_roles",
            postgresql.ARRAY(sa.String(length=32)),
            nullable=False,
            server_default=sa.text("'{}'::varchar[]"),
        ),
    )
    op.create_check_constraint(
        "ck_documents_access_roles_allowed",
        "documents",
        "access_roles <@ ARRAY['admin', 'knowledge_manager', 'staff', 'student', "
        "'user']::varchar[]",
    )

    op.create_table(
        "institution_decision_catalogs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("institution_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("scope_description", sa.Text(), nullable=False),
        sa.Column("topics", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("services", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id", "institution_id"],
            ["users.id", "users.institution_id"],
            name="fk_institution_decision_catalogs_created_by_institution",
        ),
        sa.ForeignKeyConstraint(
            ["institution_id"],
            ["institutions.id"],
            name="fk_institution_decision_catalogs_institution_id_institutions",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "institution_id", "version", name="uq_institution_decision_catalogs_version"
        ),
    )
    op.create_index(
        op.f("ix_institution_decision_catalogs_institution_id"),
        "institution_decision_catalogs",
        ["institution_id"],
        unique=False,
    )
    op.create_index(
        "uq_institution_decision_catalogs_one_active",
        "institution_decision_catalogs",
        ["institution_id"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )

    op.create_table(
        "decision_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("institution_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_message_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("assistant_message_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("failure_code", sa.String(length=64), nullable=True),
        sa.Column("action", sa.String(length=20), nullable=True),
        sa.Column("rule", sa.String(length=8), nullable=True),
        sa.Column("policy_version", sa.String(length=64), nullable=False),
        sa.Column("reference_date", sa.Date(), nullable=False),
        sa.Column("requester_role", sa.String(length=32), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("record", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('decided', 'technical_failure')", name="ck_decision_records_status"
        ),
        sa.CheckConstraint(
            "(status = 'decided' AND action IS NOT NULL AND rule IS NOT NULL "
            "AND failure_code IS NULL) OR "
            "(status = 'technical_failure' AND action IS NULL AND rule IS NULL "
            "AND failure_code IS NOT NULL)",
            name="ck_decision_records_outcome_coherent",
        ),
        sa.CheckConstraint(
            "action IS NULL OR action IN ('answer', 'clarify', 'abstain', 'escalate')",
            name="ck_decision_records_action",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id", "institution_id"],
            ["conversations.id", "conversations.institution_id"],
            name="fk_decision_records_conversation_institution",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "institution_id"],
            ["users.id", "users.institution_id"],
            name="fk_decision_records_user_institution",
        ),
        sa.ForeignKeyConstraint(
            ["assistant_message_id", "conversation_id", "institution_id"],
            ["messages.id", "messages.conversation_id", "messages.institution_id"],
            name="fk_decision_records_assistant_message",
        ),
        sa.ForeignKeyConstraint(
            ["user_message_id", "conversation_id", "institution_id"],
            ["messages.id", "messages.conversation_id", "messages.institution_id"],
            name="fk_decision_records_user_message",
        ),
        sa.ForeignKeyConstraint(
            ["institution_id"],
            ["institutions.id"],
            name="fk_decision_records_institution_id_institutions",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id"),
    )
    op.create_index(
        op.f("ix_decision_records_institution_id"),
        "decision_records",
        ["institution_id"],
        unique=False,
    )
    op.create_index(
        "ix_decision_records_conversation",
        "decision_records",
        ["conversation_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    bind = op.get_bind()
    restricted = bind.execute(
        sa.text("SELECT count(*) FROM documents WHERE cardinality(access_roles) > 0")
    ).scalar_one()
    catalogs = bind.execute(
        sa.text("SELECT count(*) FROM institution_decision_catalogs")
    ).scalar_one()
    records = bind.execute(sa.text("SELECT count(*) FROM decision_records")).scalar_one()
    if restricted or catalogs or records:
        msg = (
            "Downgrade refused: "
            f"{restricted} document(s) restricted by role, {catalogs} decision catalog "
            f"version(s) and {records} decision record(s) exist. Removing them would make "
            "restricted documents public and discard configuration and audit data."
        )
        raise RuntimeError(msg)

    op.drop_index("ix_decision_records_conversation", table_name="decision_records")
    op.drop_index(op.f("ix_decision_records_institution_id"), table_name="decision_records")
    op.drop_table("decision_records")
    op.drop_index(
        "uq_institution_decision_catalogs_one_active",
        table_name="institution_decision_catalogs",
    )
    op.drop_index(
        op.f("ix_institution_decision_catalogs_institution_id"),
        table_name="institution_decision_catalogs",
    )
    op.drop_table("institution_decision_catalogs")
    op.drop_constraint("ck_documents_access_roles_allowed", "documents", type_="check")
    op.drop_column("documents", "access_roles")
