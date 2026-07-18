"""Rotas do núcleo documental.

Nesta fase todos os endpoints de documentos são administrativos
(require_admin) e limitados à instituição do admin autenticado: um
documento ou versão de outra instituição é 404, nunca 403. O router
mantém-se fino: valida o formato do pedido e delega toda a regra de
negócio aos services; erros de domínio são convertidos em HTTP pelos
handlers globais.
"""

import uuid

from fastapi import APIRouter, Depends, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.dependencies.auth import require_admin
from app.core.exceptions import ConflictError
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

router = APIRouter(prefix="/documents", tags=["Documents"])


@router.post("", response_model=DocumentRead, status_code=status.HTTP_201_CREATED)
def create_document(
    payload: DocumentCreate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> DocumentRead:
    # institution_id e created_by_user_id vêm sempre do admin autenticado,
    # nunca do payload.
    document = document_service.create_document(db, admin, payload)
    return DocumentRead.model_validate(document)


@router.get("", response_model=DocumentListResponse)
def list_documents(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    is_active: bool | None = Query(default=None),
    official_source: bool | None = Query(default=None),
    language: str | None = Query(default=None),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> DocumentListResponse:
    items, total = document_service.list_documents(
        db,
        admin,
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
    admin: User = Depends(require_admin),
) -> DocumentRead:
    document = document_service.get_accessible_document(db, admin, document_id)
    return DocumentRead.model_validate(document)


@router.patch("/{document_id}", response_model=DocumentRead)
def update_document(
    document_id: uuid.UUID,
    payload: DocumentUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> DocumentRead:
    document = document_service.update_document(db, admin, document_id, payload)
    return DocumentRead.model_validate(document)


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
    storage: DocumentStorage = Depends(get_document_storage),
) -> None:
    # Sem body e sem response: 204 em sucesso; 409 (via handlers globais)
    # quando o documento está citado em respostas persistidas ou tem uma
    # versão em processamento; 404 fora da instituição do admin.
    document_service.delete_document(db, admin, document_id, storage=storage)


@router.post(
    "/{document_id}/versions",
    response_model=DocumentVersionRead,
    status_code=status.HTTP_201_CREATED,
)
def upload_document_version(
    document_id: uuid.UUID,
    file: UploadFile,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
    storage: DocumentStorage = Depends(get_document_storage),
) -> DocumentVersionRead:
    version = document_version_service.create_version(
        db,
        admin,
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
    admin: User = Depends(require_admin),
) -> DocumentVersionListResponse:
    items, total = document_version_service.list_versions(
        db, admin, document_id, limit=limit, offset=offset
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
    admin: User = Depends(require_admin),
) -> DocumentVersionRead:
    version = document_version_service.get_accessible_version(
        db, admin, document_id, version_id
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
    admin: User = Depends(require_admin),
) -> DocumentContentRead:
    text, total_characters = document_version_service.get_version_content(
        db, admin, document_id, version_id, offset=offset, limit=limit
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
    admin: User = Depends(require_admin),
    storage: DocumentStorage = Depends(get_document_storage),
) -> FileResponse:
    version = document_version_service.get_accessible_version(
        db, admin, document_id, version_id
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
    admin: User = Depends(require_admin),
    storage: DocumentStorage = Depends(get_document_storage),
) -> DocumentVersionRead:
    version = document_version_service.get_accessible_version(
        db, admin, document_id, version_id
    )
    version = document_processing_service.reprocess_version(db, version, storage)
    return DocumentVersionRead.model_validate(version)
