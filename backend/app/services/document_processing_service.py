"""Processamento (síncrono) de versões de documentos.

Estados de uma versão:

- pending: versão registada, extração ainda não iniciada;
- processing: extração em curso;
- processed: texto extraído com sucesso;
- failed: extração falhou (o ficheiro original permanece guardado, por
  isso a versão pode ser reprocessada mais tarde).

Nesta fase o processamento corre de forma síncrona dentro do pedido de
upload/reprocessamento. A função process_version é autocontida (recebe a
sessão, a versão e o storage) precisamente para que uma futura execução
assíncrona (fila/worker) possa reutilizá-la sem alterações à lógica.
"""

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError
from app.models.document_version import DocumentVersion
from app.services.document_extraction_service import ExtractionError, extract_text
from app.storage.base import DocumentStorage

logger = logging.getLogger(__name__)

# Mensagem genérica para falhas inesperadas: nunca expor traceback,
# caminhos ou detalhes internos em processing_error.
GENERIC_PROCESSING_ERROR = "Text extraction failed unexpectedly."

FILE_UNAVAILABLE_MESSAGE = "The stored file for this version is unavailable."


def process_version(
    db: Session,
    version: DocumentVersion,
    storage: DocumentStorage,
) -> DocumentVersion:
    """Executa a extração de texto e finaliza como processed ou failed.

    O estado "processing" é gravado (commit) antes da extração começar,
    para que o estado intermédio seja visível e o reprocessamento
    concorrente possa ser recusado com 409.
    """
    version.processing_status = "processing"
    version.processing_error = None
    version.extracted_text = None
    version.page_count = None
    version.processed_at = None
    db.commit()

    try:
        result = extract_text(storage.resolve_path(version.storage_path), version.mime_type)
    except ExtractionError as exc:
        version.processing_status = "failed"
        version.processing_error = str(exc)
    except Exception:
        # Falha imprevista (ex.: caminho inválido no storage): detalhes só
        # no logging; o cliente vê apenas a mensagem genérica.
        logger.exception(
            "Erro inesperado ao processar a versão de documento %s", version.id
        )
        version.processing_status = "failed"
        version.processing_error = GENERIC_PROCESSING_ERROR
    else:
        version.processing_status = "processed"
        version.extracted_text = result.text
        version.page_count = result.page_count
        # processed_at regista apenas conclusões com sucesso.
        version.processed_at = datetime.now(UTC)

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

    if not storage.exists(locked_version.storage_path):
        # Mensagem genérica de propósito: nunca expor o caminho.
        raise ConflictError(FILE_UNAVAILABLE_MESSAGE)

    # process_version limpa os campos anteriores e faz commit do estado
    # processing antes da extração. Esse commit liberta o lock; um segundo
    # pedido acorda, relê processing e é recusado com 409.
    return process_version(db, locked_version, storage)
