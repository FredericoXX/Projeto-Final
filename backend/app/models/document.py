from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class Document(Base):
    """Documento institucional lógico (regulamento, calendário, manual...).

    Guarda apenas metadados; cada ficheiro concreto é uma linha em
    document_versions, para que atualizações não percam o histórico.
    """

    __tablename__ = "documents"
    __table_args__ = (
        # Constraint "degenerada" (id já é único): existe apenas para ser
        # referenciada pela foreign key composta de document_versions,
        # garantindo que uma versão pertence à mesma instituição do documento.
        UniqueConstraint("id", "institution_id", name="uq_documents_id_institution_id"),
        # Quem cria o documento tem de pertencer à mesma instituição.
        ForeignKeyConstraint(
            ["created_by_user_id", "institution_id"],
            ["users.id", "users.institution_id"],
            name="fk_documents_created_by_user_id_institution_id_users",
        ),
        CheckConstraint(
            "valid_from IS NULL OR valid_until IS NULL OR valid_from <= valid_until",
            name="ck_documents_validity_range",
        ),
        # Autorização documental por papel (política v1.7, C13): só papéis
        # existentes. A lista vazia é "sem restrição".
        CheckConstraint(
            "access_roles <@ ARRAY['admin', 'knowledge_manager', 'staff', 'student', "
            "'user']::varchar[]",
            name="ck_documents_access_roles_allowed",
        ),
        # Consultas administrativas típicas: documentos ativos e/ou de
        # fonte oficial de uma instituição.
        Index("ix_documents_institution_id_is_active", "institution_id", "is_active"),
        Index(
            "ix_documents_institution_id_official_source",
            "institution_id",
            "official_source",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        primary_key=True,
        default=uuid4,
    )

    institution_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "institutions.id",
            name="fk_documents_institution_id_institutions",
        ),
        nullable=False,
        index=True,
    )

    # Nunca aceite do payload: é sempre o gestor documental autenticado que cria.
    created_by_user_id: Mapped[UUID] = mapped_column(
        nullable=False,
        index=True,
    )

    title: Mapped[str] = mapped_column(String(255), nullable=False)

    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    language: Mapped[str] = mapped_column(String(8), nullable=False, index=True)

    source_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)

    official_source: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Papéis autorizados a ser fundamentados por este documento (C13 de
    # app.documents.retrievability). Vazio = sem restrição dentro da
    # instituição — o valor dos documentos anteriores a esta coluna.
    # documents.manage não é afetado: governa a gestão, não a fundamentação.
    access_roles: Mapped[list[str]] = mapped_column(
        ARRAY(String(32)),
        nullable=False,
        default=list,
        server_default=text("'{}'::varchar[]"),
    )

    # Vigência normativa do documento lógico. Pertence ao documento, não à
    # versão: a última versão processada não herda nem transmite validade.
    valid_from: Mapped[date | None] = mapped_column(Date, nullable=True)

    valid_until: Mapped[date | None] = mapped_column(Date, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
