from datetime import date, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class DecisionRecord(Base):
    """Registo protegido de uma execução da política experimental v1.7.

    Auditoria **interna**: não existe endpoint que o devolva, e nenhum schema
    público o serializa. É lido pelo replay offline
    (``scripts/replay_decision_record.py``) e pela avaliação.

    Guarda o mínimo autorizado: entradas validadas da política (D0–D6 e a
    origem de cada estimativa), a razão estruturada, as versões de política,
    estimadores, prompts, modelo, catálogo, mensagens e autorização documental,
    a configuração da recuperação, os identificadores e hashes das evidências
    admissíveis (nunca o seu conteúdo), o diagnóstico temporal permitido, a
    data de referência, tentativas, duração e utilização do fornecedor quando
    disponível. Não guarda raciocínio interno de nenhum modelo, nem prompts
    completos, nem respostas brutas do fornecedor.

    ``status='technical_failure'`` regista uma falha técnica — timeout,
    indisponibilidade, saída inválida — que **não** é uma das quatro ações:
    nesse caso ``action`` e ``rule`` ficam nulos e não há mensagens.
    """

    __tablename__ = "decision_records"
    __table_args__ = (
        ForeignKeyConstraint(
            ["conversation_id", "institution_id"],
            ["conversations.id", "conversations.institution_id"],
            name="fk_decision_records_conversation_institution",
        ),
        ForeignKeyConstraint(
            ["user_id", "institution_id"],
            ["users.id", "users.institution_id"],
            name="fk_decision_records_user_institution",
        ),
        ForeignKeyConstraint(
            ["assistant_message_id", "conversation_id", "institution_id"],
            ["messages.id", "messages.conversation_id", "messages.institution_id"],
            name="fk_decision_records_assistant_message",
        ),
        ForeignKeyConstraint(
            ["user_message_id", "conversation_id", "institution_id"],
            ["messages.id", "messages.conversation_id", "messages.institution_id"],
            name="fk_decision_records_user_message",
        ),
        CheckConstraint(
            "status IN ('decided', 'technical_failure')",
            name="ck_decision_records_status",
        ),
        CheckConstraint(
            "(status = 'decided' AND action IS NOT NULL AND rule IS NOT NULL "
            "AND failure_code IS NULL) OR "
            "(status = 'technical_failure' AND action IS NULL AND rule IS NULL "
            "AND failure_code IS NOT NULL)",
            name="ck_decision_records_outcome_coherent",
        ),
        CheckConstraint(
            "action IS NULL OR action IN ('answer', 'clarify', 'abstain', 'escalate')",
            name="ck_decision_records_action",
        ),
        Index("ix_decision_records_conversation", "conversation_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    institution_id: Mapped[UUID] = mapped_column(
        ForeignKey("institutions.id", name="fk_decision_records_institution_id_institutions"),
        nullable=False,
        index=True,
    )
    conversation_id: Mapped[UUID] = mapped_column(nullable=False)
    user_id: Mapped[UUID] = mapped_column(nullable=False)
    user_message_id: Mapped[UUID | None] = mapped_column(nullable=True)
    assistant_message_id: Mapped[UUID | None] = mapped_column(nullable=True)
    run_id: Mapped[UUID] = mapped_column(nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    failure_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    action: Mapped[str | None] = mapped_column(String(20), nullable=True)
    rule: Mapped[str | None] = mapped_column(String(8), nullable=True)
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    reference_date: Mapped[date] = mapped_column(Date, nullable=False)
    requester_role: Mapped[str] = mapped_column(String(32), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    record: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
