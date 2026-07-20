from datetime import datetime
from typing import Any
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
from sqlalchemy.dialects.postgresql import JSONB
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
        # Constraint "degenerada" (id já é único): existe apenas para ser
        # referenciada pela foreign key composta de document_chunks,
        # garantindo que um chunk pertence à versão, ao documento e à
        # instituição corretos ao mesmo tempo.
        UniqueConstraint(
            "id",
            "document_id",
            "institution_id",
            name="uq_document_versions_id_document_id_institution_id",
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
        # Metadados de extração: nullable porque versões históricas
        # (anteriores ao OCR) ficam NULL — nunca se assume que foram
        # extraídas por "native" e nunca se faz backfill.
        CheckConstraint(
            "extraction_method IS NULL OR extraction_method IN ('native', 'ocr', 'mixed')",
            name="ck_document_versions_extraction_method_allowed",
        ),
        CheckConstraint(
            "extraction_quality IS NULL OR extraction_quality IN ('high', 'medium', 'low')",
            name="ck_document_versions_extraction_quality_allowed",
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

    # Como o texto foi obtido: native, ocr ou mixed (NULL em versões
    # históricas anteriores à introdução do OCR).
    extraction_method: Mapped[str | None] = mapped_column(String(10), nullable=True)

    # Qualidade agregada e determinística da extração: high, medium, low.
    extraction_quality: Mapped[str | None] = mapped_column(String(10), nullable=True)

    # Aviso curto e seguro quando o processamento terminou com sucesso mas
    # com qualidade baixa; nunca substitui processing_error.
    extraction_warning: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Metadados por página (método, contagens, confiança, qualidade) —
    # nunca texto integral, imagens, caminhos ou comandos.
    extraction_details: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSONB, nullable=True
    )

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
