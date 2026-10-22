"""Rotas do núcleo documental.

Todos os endpoints de documentos exigem a permissão DOCUMENTS_MANAGE
(papel knowledge_manager; ver app.core.permissions) e estão limitados à
instituição do gestor autenticado: um documento ou versão de outra
instituição é 404, nunca 403. O admin institucional deixou de ter esta
permissão implícita. O router
mantém-se fino: valida o formato do pedido e delega toda a regra de
negócio aos services; erros de domínio são convertidos em HTTP pelos
handlers globais.
"""

import uuid

from fastapi import APIRouter, Depends, Query, Request, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.dependencies.auth import require_permission
from app.core.exceptions import ConflictError, ValidationError
from app.core.permissions import Permission
from app.database.session import get_db
from app.models.user import User
from app.schemas.document import (
    DocumentContentRead,
    DocumentCreate,
    DocumentListResponse,
    DocumentRead,
    DocumentUpdate,
    DocumentVersionListResponse,
    DocumentVersionRead,
)
from app.services import (
    document_processing_service,
    document_service,
    document_version_service,
)
from app.storage import DocumentStorage, get_document_storage

CONTENT_DEFAULT_LIMIT = 50_000
CONTENT_MAX_LIMIT = 100_000

require_document_manager = require_permission(Permission.DOCUMENTS_MANAGE)

router = APIRouter(prefix="/documents", tags=["Documents"])


@router.post("", response_model=DocumentRead, status_code=status.HTTP_201_CREATED)
def create_document(
    payload: DocumentCreate,
    db: Session = Depends(get_db),
    manager: User = Depends(require_document_manager),
) -> DocumentRead:
    # institution_id e created_by_user_id vêm sempre do gestor autenticado,
    # nunca do payload.
    document = document_service.create_document(db, manager, payload)
    return DocumentRead.model_validate(document)


@router.get("", response_model=DocumentListResponse)
def list_documents(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    is_active: bool | None = Query(default=None),
    official_source: bool | None = Query(default=None),
    language: str | None = Query(default=None),
    db: Session = Depends(get_db),
    manager: User = Depends(require_document_manager),
) -> DocumentListResponse:
    items, total = document_service.list_documents(
        db,
        manager,
        limit=limit,
        offset=offset,
        is_active=is_active,
        official_source=official_source,
        language=language,
    )
    return DocumentListResponse(
        items=[DocumentRead.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{document_id}", response_model=DocumentRead)
def get_document(
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
    manager: User = Depends(require_document_manager),
) -> DocumentRead:
    document = document_service.get_accessible_document(db, manager, document_id)
    return DocumentRead.model_validate(document)


@router.patch("/{document_id}", response_model=DocumentRead)
def update_document(
    document_id: uuid.UUID,
    payload: DocumentUpdate,
    db: Session = Depends(get_db),
    manager: User = Depends(require_document_manager),
) -> DocumentRead:
    document = document_service.update_document(db, manager, document_id, payload)
    return DocumentRead.model_validate(document)


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
    manager: User = Depends(require_document_manager),
    storage: DocumentStorage = Depends(get_document_storage),
) -> None:
    # Sem body e sem response: 204 em sucesso; 409 (via handlers globais)
    # quando o documento está citado em respostas persistidas ou tem uma
    # versão em processamento; 404 fora da instituição do gestor.
    document_service.delete_document(db, manager, document_id, storage=storage)


# Campos que o cliente nunca pode enviar no upload: os metadados de
# extração são calculados exclusivamente pelo servidor e "force_ocr" não
# existe nesta fase (a decisão de OCR é automática, por página).
FORBIDDEN_UPLOAD_FORM_FIELDS = frozenset(
    {
        "extraction_method",
        "extraction_quality",
        "extraction_warning",
        "extraction_details",
        "force_ocr",
    }
)


async def _reject_server_calculated_fields(request: Request) -> None:
    """Rejeita (422) campos calculados pelo servidor no multipart.

    O Request.form() do Starlette é memoizado, pelo que o UploadFile do
    endpoint continua a usar a mesma leitura do corpo. A mensagem só pode
    conter nomes da lista fixa acima — nunca input arbitrário do cliente.
    """
    form = await request.form()
    forbidden = FORBIDDEN_UPLOAD_FORM_FIELDS.intersection(form.keys())
    if forbidden:
        msg = (
            "These fields are calculated by the server and must not be "
            f"sent: {', '.join(sorted(forbidden))}."
        )
        raise ValidationError(msg)


@router.post(
    "/{document_id}/versions",
    response_model=DocumentVersionRead,
    status_code=status.HTTP_201_CREATED,
)
def upload_document_version(
    document_id: uuid.UUID,
    file: UploadFile,
    db: Session = Depends(get_db),
    manager: User = Depends(require_document_manager),
    # Depois da autenticação: pedidos não autenticados continuam 401/403.
    _: None = Depends(_reject_server_calculated_fields),
    storage: DocumentStorage = Depends(get_document_storage),
) -> DocumentVersionRead:
    version = document_version_service.create_version(
        db,
        manager,
        document_id,
        upload_stream=file.file,
        filename=file.filename,
        declared_content_type=file.content_type,
        storage=storage,
    )
    # Processamento síncrono nesta fase. A resposta é 201 mesmo que a
    # extração termine em failed: a versão foi criada e o ficheiro ficou
    # guardado para reprocessamento; o resultado é visível em
    # processing_status/processing_error.
    version = document_processing_service.process_version(db, version, storage)
    return DocumentVersionRead.model_validate(version)


@router.get("/{document_id}/versions", response_model=DocumentVersionListResponse)
def list_document_versions(
    document_id: uuid.UUID,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    manager: User = Depends(require_document_manager),
) -> DocumentVersionListResponse:
    items, total = document_version_service.list_versions(
        db, manager, document_id, limit=limit, offset=offset
    )
    return DocumentVersionListResponse(
        items=[DocumentVersionRead.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{document_id}/versions/{version_id}",
    response_model=DocumentVersionRead,
)
def get_document_version(
    document_id: uuid.UUID,
    version_id: uuid.UUID,
    db: Session = Depends(get_db),
    manager: User = Depends(require_document_manager),
) -> DocumentVersionRead:
    version = document_version_service.get_accessible_version(
        db, manager, document_id, version_id
    )
    return DocumentVersionRead.model_validate(version)


@router.get(
    "/{document_id}/versions/{version_id}/content",
    response_model=DocumentContentRead,
)
def get_document_version_content(
    document_id: uuid.UUID,
    version_id: uuid.UUID,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=CONTENT_DEFAULT_LIMIT, ge=1, le=CONTENT_MAX_LIMIT),
    db: Session = Depends(get_db),
    manager: User = Depends(require_document_manager),
) -> DocumentContentRead:
    text, total_characters = document_version_service.get_version_content(
        db, manager, document_id, version_id, offset=offset, limit=limit
    )
    return DocumentContentRead(
        text=text,
        total_characters=total_characters,
        offset=offset,
        limit=limit,
    )


@router.get("/{document_id}/versions/{version_id}/download")
def download_document_version(
    document_id: uuid.UUID,
    version_id: uuid.UUID,
    db: Session = Depends(get_db),
    manager: User = Depends(require_document_manager),
    storage: DocumentStorage = Depends(get_document_storage),
) -> FileResponse:
    version = document_version_service.get_accessible_version(
        db, manager, document_id, version_id
    )
    if not storage.exists(version.storage_path):
        # Mensagem genérica de propósito: o caminho nunca é exposto.
        raise ConflictError(document_processing_service.FILE_UNAVAILABLE_MESSAGE)
    return FileResponse(
        path=storage.resolve_path(version.storage_path),
        media_type=version.mime_type,
        # original_filename já foi sanitizado com Path(...).name no upload.
        filename=version.original_filename,
    )


@router.post(
    "/{document_id}/versions/{version_id}/reprocess",
    response_model=DocumentVersionRead,
)
def reprocess_document_version(
    document_id: uuid.UUID,
    version_id: uuid.UUID,
    db: Session = Depends(get_db),
    manager: User = Depends(require_document_manager),
    storage: DocumentStorage = Depends(get_document_storage),
) -> DocumentVersionRead:
    version = document_version_service.get_accessible_version(
        db, manager, document_id, version_id
    )
    version = document_processing_service.reprocess_version(db, version, storage)
    return DocumentVersionRead.model_validate(version)
