from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class DocumentChunk(Base):
    """Segmento (chunk) do texto extraído de uma versão de documento.

    Estrutura interna que prepara os documentos para futuras estratégias
    de recuperação de informação (a decidir após a revisão da literatura);
    nesta fase existe apenas uma baseline lexical substituível; não há
    embeddings, pesquisa semântica/híbrida nem endpoints públicos de
    chunks. Cada versão mantém o seu próprio conjunto de chunks, que é
    substituído por inteiro no reprocessamento.
    """

    __tablename__ = "document_chunks"
    __table_args__ = (
        # Um índice de chunk é único dentro da versão: o reprocessamento
        # substitui o conjunto inteiro, nunca acrescenta duplicados.
        UniqueConstraint(
            "document_version_id",
            "chunk_index",
            name="uq_document_chunks_document_version_id_chunk_index",
        ),
        # O chunk pertence obrigatoriamente à versão indicada, ao documento
        # dessa versão e à mesma instituição — o PostgreSQL rejeita qualquer
        # combinação cruzada, sem depender das verificações do service.
        ForeignKeyConstraint(
            ["document_version_id", "document_id", "institution_id"],
            [
                "document_versions.id",
                "document_versions.document_id",
                "document_versions.institution_id",
            ],
            name="fk_document_chunks_version_document_institution",
        ),
        CheckConstraint(
            "chunk_index >= 0",
            name="ck_document_chunks_chunk_index_non_negative",
        ),
        CheckConstraint(
            "start_char >= 0",
            name="ck_document_chunks_start_char_non_negative",
        ),
        CheckConstraint(
            "end_char > start_char",
            name="ck_document_chunks_end_char_after_start_char",
        ),
        CheckConstraint(
            "btrim(content) <> ''",
            name="ck_document_chunks_content_not_blank",
        ),
        CheckConstraint(
            "btrim(normalized_content) <> ''",
            name="ck_document_chunks_normalized_content_not_blank",
        ),
        # Consultas futuras por instituição e idioma (retrieval multi-idioma).
        Index(
            "ix_document_chunks_institution_id_language",
            "institution_id",
            "language",
        ),
        Index(
            "ix_document_chunks_search_vector",
            "search_vector",
            postgresql_using="gin",
        ),
        # O par (document_version_id, chunk_index) já é indexado pela UNIQUE
        # constraint acima; não é criado um índice adicional duplicado.
    )

    id: Mapped[UUID] = mapped_column(
        primary_key=True,
        default=uuid4,
    )

    # Duplicado de propósito a partir da versão: sustenta o isolamento e as
    # consultas por instituição sem join com "document_versions".
    institution_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "institutions.id",
            name="fk_document_chunks_institution_id_institutions",
        ),
        nullable=False,
        index=True,
    )

    # A referência real à versão/documento é a foreign key composta
    # (document_version_id, document_id, institution_id) em __table_args__.
    document_id: Mapped[UUID] = mapped_column(
        nullable=False,
        index=True,
    )

    document_version_id: Mapped[UUID] = mapped_column(
        nullable=False,
        index=True,
    )

    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)

    # Texto original do chunk, tal como aparece no extracted_text da versão
    # (content == extracted_text[start_char:end_char]).
    content: Mapped[str] = mapped_column(Text, nullable=False)

    # Forma normalizada e determinística do content (ver
    # app.core.text_normalization), preparada para pesquisa futura.
    normalized_content: Mapped[str] = mapped_column(Text, nullable=False)

    # Baseline lexical: o PostgreSQL mantém este vetor automaticamente.
    # A configuração simple evita assumir stemming específico de português
    # ou inglês antes da avaliação experimental da estratégia de retrieval.
    search_vector: Mapped[str | None] = mapped_column(
        TSVECTOR,
        Computed(
            "to_tsvector('simple'::regconfig, normalized_content)",
            persisted=True,
        ),
        nullable=True,
    )

    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)

    start_char: Mapped[int] = mapped_column(Integer, nullable=False)

    end_char: Mapped[int] = mapped_column(Integer, nullable=False)

    # Idioma herdado do documento no momento da segmentação.
    language: Mapped[str] = mapped_column(String(8), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
