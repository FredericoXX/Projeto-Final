"""Snapshots auditáveis das fontes citadas por respostas persistidas."""

from datetime import date, datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import (
    DDL,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    event,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base

if TYPE_CHECKING:
    from app.models.message import Message


class MessageSource(Base):
    """Fonte efetivamente citada por uma mensagem ``assistant``.

    Os metadados são copiados no momento do turno para que alterações futuras
    no documento não reescrevam o histórico. O conteúdo não é duplicado: a
    foreign key composta mantém o chunk original referenciado e imutável.
    """

    __tablename__ = "message_sources"
    __table_args__ = (
        ForeignKeyConstraint(
            ["message_id", "institution_id", "message_role"],
            ["messages.id", "messages.institution_id", "messages.role"],
            name="fk_message_sources_message_institution_role",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["chunk_id", "document_version_id", "document_id", "institution_id"],
            [
                "document_chunks.id",
                "document_chunks.document_version_id",
                "document_chunks.document_id",
                "document_chunks.institution_id",
            ],
            name="fk_message_sources_chunk_version_document_institution",
        ),
        UniqueConstraint(
            "message_id",
            "evidence_id",
            name="uq_message_sources_message_evidence",
        ),
        UniqueConstraint(
            "message_id",
            "citation_index",
            name="uq_message_sources_message_citation",
        ),
        UniqueConstraint(
            "message_id",
            "chunk_id",
            name="uq_message_sources_message_chunk",
        ),
        CheckConstraint(
            "message_role = 'assistant'",
            name="ck_message_sources_assistant_role",
        ),
        CheckConstraint(
            "citation_index >= 0",
            name="ck_message_sources_citation_non_negative",
        ),
        CheckConstraint(
            "chunk_index >= 0",
            name="ck_message_sources_chunk_index_non_negative",
        ),
        CheckConstraint(
            "btrim(evidence_id) <> ''",
            name="ck_message_sources_evidence_not_blank",
        ),
        CheckConstraint(
            "evidence_id ~ '^E[1-9][0-9]*$'",
            name="ck_message_sources_evidence_format",
        ),
        CheckConstraint(
            "btrim(document_title) <> ''",
            name="ck_message_sources_title_not_blank",
        ),
        CheckConstraint(
            "btrim(language) <> ''",
            name="ck_message_sources_language_not_blank",
        ),
        CheckConstraint(
            "char_length(content_sha256) = 64",
            name="ck_message_sources_checksum_length",
        ),
        CheckConstraint(
            "valid_from IS NULL OR valid_until IS NULL OR valid_from <= valid_until",
            name="ck_message_sources_validity_range",
        ),
        Index("ix_message_sources_institution_id", "institution_id"),
        Index("ix_message_sources_chunk_id", "chunk_id"),
        Index("ix_message_sources_document_id", "document_id"),
        Index("ix_message_sources_document_version_id", "document_version_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    institution_id: Mapped[UUID] = mapped_column(nullable=False)
    message_id: Mapped[UUID] = mapped_column(nullable=False)
    message_role: Mapped[str] = mapped_column(String(20), nullable=False)
    chunk_id: Mapped[UUID] = mapped_column(nullable=False)
    document_id: Mapped[UUID] = mapped_column(nullable=False)
    document_version_id: Mapped[UUID] = mapped_column(nullable=False)
    evidence_id: Mapped[str] = mapped_column(String(32), nullable=False)
    citation_index: Mapped[int] = mapped_column(Integer, nullable=False)
    document_title: Mapped[str] = mapped_column(String(255), nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    official_source: Mapped[bool] = mapped_column(Boolean, nullable=False)
    language: Mapped[str] = mapped_column(String(8), nullable=False)
    valid_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    valid_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    message: Mapped["Message"] = relationship(back_populates="sources")


# SQLAlchemy não representa triggers no MetaData. Estes eventos mantêm o
# schema criado por Base.metadata.create_all() (usado nos testes) equivalente
# à migration Alembic: depois de citado, nenhum campo do chunk pode mudar.
_CREATE_IMMUTABILITY_FUNCTION = DDL(
    """
    CREATE OR REPLACE FUNCTION prevent_referenced_chunk_update()
    RETURNS trigger
    LANGUAGE plpgsql
    AS $$
    BEGIN
        IF EXISTS (
            SELECT 1
            FROM message_sources
            WHERE chunk_id = OLD.id
              AND document_version_id = OLD.document_version_id
              AND document_id = OLD.document_id
              AND institution_id = OLD.institution_id
        ) THEN
            RAISE EXCEPTION 'Referenced document chunks are immutable.'
                USING ERRCODE = '23503',
                      CONSTRAINT = 'fk_message_sources_chunk_version_document_institution';
        END IF;
        RETURN NEW;
    END;
    $$
    """
).execute_if(dialect="postgresql")

_CREATE_IMMUTABILITY_TRIGGER = DDL(
    """
    CREATE TRIGGER trg_document_chunks_prevent_referenced_update
    BEFORE UPDATE ON document_chunks
    FOR EACH ROW
    EXECUTE FUNCTION prevent_referenced_chunk_update()
    """
).execute_if(dialect="postgresql")

_DROP_IMMUTABILITY_TRIGGER = DDL(
    """
    DROP TRIGGER IF EXISTS trg_document_chunks_prevent_referenced_update
    ON document_chunks
    """
).execute_if(dialect="postgresql")

_DROP_IMMUTABILITY_FUNCTION = DDL(
    "DROP FUNCTION IF EXISTS prevent_referenced_chunk_update()"
).execute_if(dialect="postgresql")

event.listen(MessageSource.__table__, "after_create", _CREATE_IMMUTABILITY_FUNCTION)
event.listen(MessageSource.__table__, "after_create", _CREATE_IMMUTABILITY_TRIGGER)
event.listen(MessageSource.__table__, "before_drop", _DROP_IMMUTABILITY_TRIGGER)
event.listen(MessageSource.__table__, "before_drop", _DROP_IMMUTABILITY_FUNCTION)
