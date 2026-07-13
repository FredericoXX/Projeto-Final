from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base

# Estados de processamento de uma versão. Espelhados na CHECK constraint
# abaixo; o significado de cada estado está em document_processing_service.
PROCESSING_STATUSES = ("pending", "processing", "processed", "failed")


class DocumentVersion(Base):
    """Um ficheiro concreto (revisão) de um documento lógico.

    O binário vive no armazenamento local (storage_path é relativo ao
    storage root, nunca absoluto); o PostgreSQL guarda apenas metadados
    e o texto extraído.
    """

    __tablename__ = "document_versions"
    __table_args__ = (
        UniqueConstraint(
            "document_id",
            "version_number",
            name="uq_document_versions_document_id_version_number",
        ),
        # O mesmo ficheiro (checksum) pode existir em instituições
        # diferentes, mas nunca duas vezes na mesma instituição.
        UniqueConstraint(
            "institution_id",
            "checksum_sha256",
            name="uq_document_versions_institution_id_checksum",
        ),
        # Uma versão pertence obrigatoriamente à mesma instituição do seu
        # documento — o PostgreSQL rejeita qualquer combinação cruzada.
        ForeignKeyConstraint(
            ["document_id", "institution_id"],
            ["documents.id", "documents.institution_id"],
            name="fk_document_versions_document_id_institution_id_documents",
        ),
        ForeignKeyConstraint(
            ["uploaded_by_user_id", "institution_id"],
            ["users.id", "users.institution_id"],
            name="fk_document_versions_uploaded_by_user_id_institution_id_users",
        ),
        CheckConstraint(
            "version_number > 0",
            name="ck_document_versions_version_number_positive",
        ),
        CheckConstraint(
            "size_bytes > 0",
            name="ck_document_versions_size_bytes_positive",
        ),
        CheckConstraint(
            "processing_status IN ('pending', 'processing', 'processed', 'failed')",
            name="ck_document_versions_processing_status_allowed",
        ),
        CheckConstraint(
            "page_count IS NULL OR page_count >= 0",
            name="ck_document_versions_page_count_non_negative",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        primary_key=True,
        default=uuid4,
    )

    # A referência real ao documento é a foreign key composta
    # (document_id, institution_id) em __table_args__.
    document_id: Mapped[UUID] = mapped_column(
        nullable=False,
        index=True,
    )

    # Duplicado de propósito a partir do documento: sustenta o isolamento
    # e as consultas por instituição sem join com "documents".
    institution_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "institutions.id",
            name="fk_document_versions_institution_id_institutions",
        ),
        nullable=False,
        index=True,
    )

    uploaded_by_user_id: Mapped[UUID] = mapped_column(
        nullable=False,
        index=True,
    )

    version_number: Mapped[int] = mapped_column(Integer, nullable=False)

    # Apenas metadado (sanitizado com Path(...).name no upload); nunca é
    # usado para construir caminhos no armazenamento.
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)

    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)

    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)

    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)

    # Relativo ao storage root; caminhos absolutos nunca entram na base.
    storage_path: Mapped[str] = mapped_column(String(1024), nullable=False)

    processing_status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="pending",
        index=True,
    )

    # Mensagem curta e segura (sem traceback, caminhos ou detalhes
    # internos); os detalhes técnicos ficam apenas no logging.
    processing_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    extracted_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

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

    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
