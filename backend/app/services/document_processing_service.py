"""Processamento (síncrono) de versões de documentos.

Estados de uma versão:

- pending: versão registada, extração ainda não iniciada;
- processing: extração em curso;
- processed: texto extraído e chunks persistidos com sucesso — uma
  versão nunca fica processed antes de os seus chunks estarem gravados;
- failed: a extração ou a segmentação/persistência dos chunks falhou (o
  ficheiro original permanece guardado, por isso a versão pode ser
  reprocessada mais tarde). Uma versão failed não mantém chunks.

Nesta fase o processamento corre de forma síncrona dentro do pedido de
upload/reprocessamento. A função process_version é autocontida (recebe a
sessão, a versão e o storage) precisamente para que uma futura execução
assíncrona (fila/worker) possa reutilizá-la sem alterações à lógica.
"""

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import ConflictError, NotFoundError
from app.models.document_version import DocumentVersion
from app.services import (
    document_chunk_service,
    document_chunking_service,
    message_source_service,
)
from app.services.document_extraction_service import ExtractionError, extract_text
from app.storage.base import DocumentStorage

logger = logging.getLogger(__name__)

# Mensagens genéricas para falhas inesperadas: nunca expor traceback,
# caminhos, SQL ou detalhes internos em processing_error.
GENERIC_PROCESSING_ERROR = "Text extraction failed unexpectedly."
CHUNKING_ERROR_MESSAGE = "Document segmentation failed unexpectedly."

FILE_UNAVAILABLE_MESSAGE = "The stored file for this version is unavailable."


def process_version(
    db: Session,
    version: DocumentVersion,
    storage: DocumentStorage,
) -> DocumentVersion:
    """Executa a extração, segmenta o texto em chunks e finaliza como
    processed ou failed.

    O estado "processing" é gravado (commit) antes da extração começar,
    para que o estado intermédio seja visível e o reprocessamento
    concorrente possa ser recusado com 409. O estado "processed" só é
    gravado depois de o texto extraído e o novo conjunto de chunks
    estarem na mesma transação — nunca há versão processed sem chunks,
    chunks parciais nem mistura de conjuntos antigo e novo.
    """
    # O processamento inicial e o reprocessamento usam o mesmo protocolo de
    # lock. Assim, nem um segundo processamento nem a persistência concorrente
    # de uma fonte podem atravessar a mudança para "processing".
    locked_version = db.scalar(
        select(DocumentVersion)
        .where(
            DocumentVersion.id == version.id,
            DocumentVersion.document_id == version.document_id,
            DocumentVersion.institution_id == version.institution_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if locked_version is None:
        msg = f"Document version '{version.id}' not found."
        raise NotFoundError(msg)
    if locked_version.processing_status == "processing":
        msg = f"Document version '{locked_version.id}' is already being processed."
        raise ConflictError(msg)
    if message_source_service.is_document_version_referenced(
        db,
        version_id=locked_version.id,
        document_id=locked_version.document_id,
        institution_id=locked_version.institution_id,
    ):
        raise ConflictError(message_source_service.REFERENCED_VERSION_MESSAGE)

    version = locked_version
    version.processing_status = "processing"
    version.processing_error = None
    version.extracted_text = None
    version.page_count = None
    version.processed_at = None
    db.commit()

    try:
        result = extract_text(storage.resolve_path(version.storage_path), version.mime_type)
    except ExtractionError as exc:
        return _finalize_failure(db, version, str(exc))
    except Exception as exc:
        # Falha imprevista (ex.: caminho inválido no storage): detalhes só
        # no logging; o cliente vê apenas a mensagem genérica.
        logger.error(
            "Document processing failed: version_id=%s reason=extraction_failed error_type=%s",
            version.id,
            type(exc).__name__,
        )
        return _finalize_failure(db, version, GENERIC_PROCESSING_ERROR)

    try:
        chunks = document_chunking_service.chunk_text(
            result.text,
            settings.document_chunk_size_chars,
            settings.document_chunk_overlap_chars,
        )
        # Substituição atómica: remoção dos chunks antigos e inserção dos
        # novos ficam pendentes na transação até ao commit final abaixo.
        document_chunk_service.replace_version_chunks(db, version, chunks)
    except Exception as exc:
        logger.error(
            "Document processing failed: version_id=%s reason=chunking_failed error_type=%s",
            version.id,
            type(exc).__name__,
        )
        # O rollback desfaz qualquer chunk pendente (os antigos, se
        # existirem, permanecem intactos até à limpeza do estado failed).
        db.rollback()
        return _finalize_failure(db, version, CHUNKING_ERROR_MESSAGE)

    version.processing_status = "processed"
    version.extracted_text = result.text
    version.page_count = result.page_count
    # processed_at regista apenas conclusões com sucesso.
    version.processed_at = datetime.now(UTC)

    try:
        db.commit()
    except Exception as exc:
        # O flush acima deteta normalmente erros de constraints, mas uma
        # falha também pode ocorrer ao confirmar a transação (por exemplo,
        # constraint diferida ou perda da ligação). Nesse caso, nenhum
        # conjunto parcial pode sobreviver e a versão não pode ficar presa
        # em processing.
        logger.error(
            "Document processing failed: version_id=%s reason=commit_failed error_type=%s",
            version.id,
            type(exc).__name__,
        )
        db.rollback()
        return _finalize_failure(db, version, CHUNKING_ERROR_MESSAGE)

    db.refresh(version)
    return version


def _finalize_failure(
    db: Session,
    version: DocumentVersion,
    message: str,
) -> DocumentVersion:
    """Grava o estado failed com uma mensagem curta e segura.

    Uma versão não processada não mantém chunks: os de um processamento
    anterior são removidos na mesma transação do estado failed, para que
    "ter chunks" seja sempre equivalente a "estar processed".
    """
    document_chunk_service.delete_version_chunks(db, version.id)
    version.processing_status = "failed"
    version.processing_error = message
    db.commit()
    db.refresh(version)
    return version


def reprocess_version(
    db: Session,
    version: DocumentVersion,
    storage: DocumentStorage,
) -> DocumentVersion:
    """Reexecuta a extração sobre o ficheiro original, sem criar nova versão.

    Permitido para versões pending, processed ou failed; uma versão já em
    processing é recusada (409) para não haver duas extrações simultâneas.
    """
    # Recarrega a versão sob lock, mesmo que a sessão já a tenha no identity
    # map. O filtro mantém o âmbito do documento/instituição previamente
    # validado pelo service/rota e impede que esse isolamento seja alargado.
    locked_version = db.scalar(
        select(DocumentVersion)
        .where(
            DocumentVersion.id == version.id,
            DocumentVersion.document_id == version.document_id,
            DocumentVersion.institution_id == version.institution_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if locked_version is None:
        msg = f"Document version '{version.id}' not found."
        raise NotFoundError(msg)

    if locked_version.processing_status == "processing":
        msg = f"Document version '{locked_version.id}' is already being processed."
        raise ConflictError(msg)

    if message_source_service.is_document_version_referenced(
        db,
        version_id=locked_version.id,
        document_id=locked_version.document_id,
        institution_id=locked_version.institution_id,
    ):
        raise ConflictError(message_source_service.REFERENCED_VERSION_MESSAGE)

    if not storage.exists(locked_version.storage_path):
        # Mensagem genérica de propósito: nunca expor o caminho.
        raise ConflictError(FILE_UNAVAILABLE_MESSAGE)

    # process_version repete a verificação sob o mesmo lock antes de gravar
    # processing. O commit liberta o lock; outro pedido acorda e revalida.
    return process_version(db, locked_version, storage)
