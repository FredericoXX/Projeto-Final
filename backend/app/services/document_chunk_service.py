"""Persistência dos chunks de uma versão de documento.

Os chunks são uma estrutura interna (sem endpoint público nesta fase):
cada versão mantém o seu próprio conjunto, substituído por inteiro no
(re)processamento. Este service nunca faz commit — as operações ficam na
transação do chamador (document_processing_service), que confirma tudo
junto com o estado da versão, para que a substituição seja atómica:
nunca ficam chunks parciais nem mistura de conjuntos antigo e novo.

institution_id, document_id e language nunca vêm de payload externo:
são sempre derivados da versão e do documento já validados.
"""

from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.document_version import DocumentVersion
from app.services.document_chunking_service import ChunkData


def replace_version_chunks(
    db: Session,
    version: DocumentVersion,
    chunks: list[ChunkData],
) -> list[DocumentChunk]:
    """Substitui o conjunto de chunks da versão pelo novo (sem commit).

    Apaga apenas os chunks desta versão — outras versões do mesmo
    documento mantêm os seus — e insere o novo conjunto na mesma
    transação. O idioma é herdado do documento da versão.
    """
    if not chunks:
        msg = "Cannot replace document version chunks with an empty collection."
        raise ValueError(msg)

    language = db.scalar(select(Document.language).where(Document.id == version.document_id))
    if language is None:
        # A FK composta garante que o documento existe; um None aqui só
        # aconteceria com uma versão ainda não persistida.
        msg = f"Document '{version.document_id}' not found for version '{version.id}'."
        raise ValueError(msg)

    db.execute(delete(DocumentChunk).where(DocumentChunk.document_version_id == version.id))

    entities = [
        DocumentChunk(
            institution_id=version.institution_id,
            document_id=version.document_id,
            document_version_id=version.id,
            chunk_index=chunk.chunk_index,
            content=chunk.content,
            normalized_content=chunk.normalized_content,
            content_sha256=chunk.content_sha256,
            start_char=chunk.start_char,
            end_char=chunk.end_char,
            page_number=chunk.page_number,
            section_title=chunk.section_title,
            structure_type=chunk.structure_type,
            chunking_strategy=chunk.chunking_strategy,
            language=language,
        )
        for chunk in chunks
    ]
    db.add_all(entities)
    # flush expõe erros de constraint dentro da transação do chamador,
    # antes do commit final.
    db.flush()
    return entities


def delete_version_chunks(db: Session, version_id: UUID) -> None:
    """Remove os chunks da versão (sem commit), na transação do chamador."""
    db.execute(delete(DocumentChunk).where(DocumentChunk.document_version_id == version_id))


def list_version_chunks(db: Session, version_id: UUID) -> list[DocumentChunk]:
    """Chunks da versão por ordem de chunk_index (uso interno e testes)."""
    return list(
        db.scalars(
            select(DocumentChunk)
            .where(DocumentChunk.document_version_id == version_id)
            .order_by(DocumentChunk.chunk_index)
        ).all()
    )
