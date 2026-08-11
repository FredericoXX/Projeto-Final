"""Revalidação, snapshots e consulta das fontes de mensagens persistidas."""

import hashlib
from dataclasses import dataclass
from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError
from app.core.text_normalization import normalize_text
from app.documents.retrievability import (
    CitationPersistenceEligibility,
    RetrievabilityContext,
    RetrievabilitySubject,
)
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.document_version import DocumentVersion
from app.models.message import Message
from app.models.message_source import MessageSource
from app.schemas.answering import AnswerSourceRead

SOURCES_CHANGED_MESSAGE = (
    "The documentary sources changed while the answer was being generated. "
    "Please retry the request."
)
REFERENCED_VERSION_MESSAGE = (
    "This document version is referenced by persisted answers and cannot be "
    "reprocessed. Upload a new version instead."
)


@dataclass(frozen=True)
class SourceSnapshot:
    evidence_id: str
    citation_index: int
    chunk_id: UUID
    document_id: UUID
    document_version_id: UUID
    document_title: str
    chunk_index: int
    source_url: str | None
    official_source: bool
    language: str
    valid_from: date | None
    valid_until: date | None
    content_sha256: str


def _source_conflict() -> ConflictError:
    return ConflictError(SOURCES_CHANGED_MESSAGE)


def revalidate_and_lock_sources(
    db: Session,
    *,
    institution_id: UUID,
    cited_sources: list[AnswerSourceRead],
    language: str,
    reference_date: date,
    official_only: bool,
) -> tuple[SourceSnapshot, ...]:
    """Recarrega e bloqueia as fontes citadas antes de qualquer insert.

    As versões, documentos e chunks são bloqueados por UUID em ordem
    determinística. Todos os snapshots são derivados das linhas atuais da
    base; os metadados do DTO servem apenas para detetar mudanças ocorridas
    durante a geração.

    A **admissibilidade documental** não é definida aqui: vem inteira de
    ``CitationPersistenceEligibility``, em ``app.documents.retrievability``.
    Essa política responde a "esta evidência foi legitimamente usada para
    gerar **esta** resposta", e por isso **não** inclui C5: uma versão
    ``processed`` entretanto superada por N+1 continua a ser a fonte real da
    resposta já gerada, e continua admissível aqui. Este service nunca
    resolve a versão efetiva nem consulta a política de recuperação.

    O que permanece deste lado é matéria distinta, e assim deve continuar:
    a consistência dos identificadores (defesa em profundidade sobre a FK
    composta), a deteção de metadados alterados durante a geração e a
    integridade do snapshot — checksums, normalização e coerência com o
    ``extracted_text`` da versão.
    """
    if not cited_sources:
        raise _source_conflict()

    chunk_ids = {source.chunk_id for source in cited_sources}
    document_ids = {source.document_id for source in cited_sources}
    version_ids = {source.document_version_id for source in cited_sources}
    if len(chunk_ids) != len(cited_sources):
        raise _source_conflict()

    versions = list(
        db.scalars(
            select(DocumentVersion)
            .where(
                DocumentVersion.id.in_(version_ids),
                DocumentVersion.institution_id == institution_id,
            )
            .order_by(DocumentVersion.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).all()
    )
    documents = list(
        db.scalars(
            select(Document)
            .where(
                Document.id.in_(document_ids),
                Document.institution_id == institution_id,
            )
            .order_by(Document.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).all()
    )
    chunks = list(
        db.scalars(
            select(DocumentChunk)
            .where(
                DocumentChunk.id.in_(chunk_ids),
                DocumentChunk.institution_id == institution_id,
            )
            .order_by(DocumentChunk.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).all()
    )

    if (
        len(versions) != len(version_ids)
        or len(documents) != len(document_ids)
        or len(chunks) != len(chunk_ids)
    ):
        raise _source_conflict()

    versions_by_id = {version.id: version for version in versions}
    documents_by_id = {document.id: document for document in documents}
    chunks_by_id = {chunk.id: chunk for chunk in chunks}
    snapshots: list[SourceSnapshot] = []

    # Os mesmos quatro valores que o pedido de persistência já recebe: não se
    # introduz configuração nova, apenas se traduz o contexto.
    retrievability = RetrievabilityContext(
        institution_id=institution_id,
        language=language,
        reference_date=reference_date,
        official_only=official_only,
    )

    for citation_index, source in enumerate(cited_sources):
        version = versions_by_id.get(source.document_version_id)
        document = documents_by_id.get(source.document_id)
        chunk = chunks_by_id.get(source.chunk_id)
        if version is None or document is None or chunk is None:
            raise _source_conflict()

        # Defesa em profundidade sobre a foreign key composta, e não
        # admissibilidade documental: sobrepõe-se deliberadamente a C1–C3.
        identifiers_match = (
            version.document_id == source.document_id
            and version.institution_id == institution_id
            and chunk.document_version_id == source.document_version_id
            and chunk.document_id == source.document_id
            and chunk.institution_id == institution_id
        )
        # ``effective_version_id`` fica por resolver de propósito: C5 não faz
        # parte desta política, e resolvê-la aqui reintroduziria a pergunta do
        # retrieval ("é recuperável agora") onde a pergunta é outra.
        verdict = CitationPersistenceEligibility.explain(
            RetrievabilitySubject.from_entities(
                chunk=chunk,
                document=document,
                version=version,
            ),
            retrievability,
        )
        metadata_unchanged = (
            source.document_title == document.title
            and source.chunk_index == chunk.chunk_index
            and source.source_url == document.source_url
            and source.official_source == document.official_source
            and source.language == document.language
            and source.valid_from == document.valid_from
            and source.valid_until == document.valid_until
        )
        expected_checksum = source.internal_content_sha256
        calculated_checksum = hashlib.sha256(chunk.content.encode("utf-8")).hexdigest()
        content_matches_version = (
            version.extracted_text is not None
            and version.extracted_text[chunk.start_char : chunk.end_char] == chunk.content
        )
        snapshot_valid = (
            bool(document.title.strip())
            and expected_checksum is not None
            and len(expected_checksum) == 64
            and len(chunk.content_sha256) == 64
            and chunk.content_sha256 == expected_checksum
            and calculated_checksum == expected_checksum
            and chunk.normalized_content == normalize_text(chunk.content)
            and content_matches_version
        )
        # Erro único e genérico: a condição concreta que falhou nunca chega ao
        # cliente, nem sequer o nome da condição do veredicto.
        if (
            not identifiers_match
            or not verdict.eligible
            or not metadata_unchanged
            or not snapshot_valid
        ):
            raise _source_conflict()

        snapshots.append(
            SourceSnapshot(
                evidence_id=source.evidence_id,
                citation_index=citation_index,
                chunk_id=chunk.id,
                document_id=document.id,
                document_version_id=version.id,
                document_title=document.title,
                chunk_index=chunk.chunk_index,
                source_url=document.source_url,
                official_source=document.official_source,
                language=document.language,
                valid_from=document.valid_from,
                valid_until=document.valid_until,
                content_sha256=chunk.content_sha256,
            )
        )

    return tuple(snapshots)


def create_message_sources(
    db: Session,
    *,
    assistant_message: Message,
    snapshots: tuple[SourceSnapshot, ...],
) -> list[MessageSource]:
    """Cria as associações já revalidadas, sem commit."""
    if assistant_message.role != "assistant" or not snapshots:
        raise _source_conflict()

    entities = [
        MessageSource(
            institution_id=assistant_message.institution_id,
            message_id=assistant_message.id,
            message_role=assistant_message.role,
            chunk_id=snapshot.chunk_id,
            document_id=snapshot.document_id,
            document_version_id=snapshot.document_version_id,
            evidence_id=snapshot.evidence_id,
            citation_index=snapshot.citation_index,
            document_title=snapshot.document_title,
            chunk_index=snapshot.chunk_index,
            source_url=snapshot.source_url,
            official_source=snapshot.official_source,
            language=snapshot.language,
            valid_from=snapshot.valid_from,
            valid_until=snapshot.valid_until,
            content_sha256=snapshot.content_sha256,
        )
        for snapshot in snapshots
    ]
    db.add_all(entities)
    return entities


def list_message_sources(
    db: Session,
    message_id: UUID,
    *,
    institution_id: UUID,
) -> list[MessageSource]:
    """Lista snapshots por ordem de citação, sempre dentro da instituição."""
    statement = select(MessageSource).where(
        MessageSource.message_id == message_id,
        MessageSource.institution_id == institution_id,
    )
    return list(
        db.scalars(
            statement.order_by(MessageSource.citation_index, MessageSource.id)
        ).all()
    )


def is_document_referenced(
    db: Session,
    *,
    document_id: UUID,
    institution_id: UUID,
) -> bool:
    """Indica se qualquer chunk/versão do documento foi citado numa
    resposta persistida (avaliar sob os locks do chamador)."""
    return (
        db.scalar(
            select(MessageSource.id)
            .where(
                MessageSource.document_id == document_id,
                MessageSource.institution_id == institution_id,
            )
            .limit(1)
        )
        is not None
    )


def is_document_version_referenced(
    db: Session,
    *,
    version_id: UUID,
    document_id: UUID,
    institution_id: UUID,
) -> bool:
    """Indica se uma versão bloqueada já foi usada numa resposta."""
    return (
        db.scalar(
            select(MessageSource.id)
            .where(
                MessageSource.document_version_id == version_id,
                MessageSource.document_id == document_id,
                MessageSource.institution_id == institution_id,
            )
            .limit(1)
        )
        is not None
    )
