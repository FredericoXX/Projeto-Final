"""Regras de negócio das versões de documentos (upload e consulta).

O upload é feito em streaming (blocos de 1 MB): o tamanho e o SHA-256
são calculados durante a escrita para um ficheiro temporário, sem nunca
carregar o ficheiro inteiro em memória. O número de versão é atribuído
sob um lock da linha do documento (SELECT ... FOR UPDATE), com a UNIQUE
constraint (document_id, version_number) como segunda defesa contra
uploads concorrentes.
"""

import hashlib
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import IO

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import (
    ConflictError,
    NotFoundError,
    PayloadTooLargeError,
    UnsupportedMediaTypeError,
    ValidationError,
)
from app.models.document import Document
from app.models.document_version import DocumentVersion
from app.models.user import User
from app.services.document_service import get_accessible_document
from app.services.user_service import get_constraint_name
from app.storage.base import DocumentStorage

CHUNK_SIZE = 1024 * 1024

PDF_SIGNATURE = b"%PDF-"

# Formatos suportados nesta fase: extensão -> MIME canónico guardado na base.
ALLOWED_EXTENSIONS: dict[str, str] = {
    ".pdf": "application/pdf",
    ".txt": "text/plain",
    ".md": "text/markdown",
}

# Content types declarados aceites por extensão; tipos genéricos (ausente
# ou octet-stream) são tolerados, prevalecendo o MIME canónico da extensão.
_ACCEPTED_DECLARED_TYPES: dict[str, set[str]] = {
    ".pdf": {"application/pdf"},
    ".txt": {"text/plain"},
    ".md": {"text/markdown", "text/plain"},
}
_GENERIC_DECLARED_TYPES = {"", "application/octet-stream"}

CHECKSUM_CONFLICT_MESSAGE = "A file with the same content already exists in this institution."

_CHECKSUM_UNIQUE_CONSTRAINT = "uq_document_versions_institution_id_checksum"
_VERSION_NUMBER_UNIQUE_CONSTRAINT = "uq_document_versions_document_id_version_number"


def _ensure_checksum_unique(db: Session, institution_id: uuid.UUID, checksum: str) -> None:
    existing = db.scalar(
        select(DocumentVersion.id).where(
            DocumentVersion.institution_id == institution_id,
            DocumentVersion.checksum_sha256 == checksum,
        )
    )
    if existing is not None:
        raise ConflictError(CHECKSUM_CONFLICT_MESSAGE)


def _validate_file(
    storage: DocumentStorage,
    temp_path: str,
    size_bytes: int,
    extension: str,
    declared_content_type: str | None,
) -> None:
    if size_bytes == 0:
        msg = "uploaded file is empty"
        raise ValidationError(msg)

    if extension not in ALLOWED_EXTENSIONS:
        msg = "unsupported file type; allowed types are PDF, TXT and Markdown"
        raise UnsupportedMediaTypeError(msg)

    # Multipart pode declarar parâmetros (ex.: "text/plain; charset=utf-8");
    # só o tipo em si interessa aqui.
    declared = (declared_content_type or "").split(";")[0].strip().lower()
    if declared not in _GENERIC_DECLARED_TYPES and declared not in _ACCEPTED_DECLARED_TYPES[
        extension
    ]:
        msg = f"declared content type '{declared}' does not match the file extension"
        raise UnsupportedMediaTypeError(msg)

    if extension == ".pdf":
        with storage.open(temp_path) as handle:
            signature = handle.read(len(PDF_SIGNATURE))
        if signature != PDF_SIGNATURE:
            msg = "file does not have a valid PDF signature"
            raise UnsupportedMediaTypeError(msg)


def create_version(
    db: Session,
    admin: User,
    document_id: uuid.UUID,
    *,
    upload_stream: IO[bytes],
    filename: str | None,
    declared_content_type: str | None,
    storage: DocumentStorage,
) -> DocumentVersion:
    # Isolamento primeiro: documento de outra instituição é 404 antes de
    # qualquer byte ser lido.
    document = get_accessible_document(db, admin, document_id)

    # O nome do cliente é apenas metadado; Path(...).name descarta qualquer
    # componente de diretório ("../../evil.txt" -> "evil.txt").
    safe_filename = Path(filename or "").name
    if not safe_filename:
        msg = "a filename is required"
        raise ValidationError(msg)
    extension = Path(safe_filename).suffix.lower()

    hasher = hashlib.sha256()
    size_bytes = 0
    max_bytes = settings.document_max_file_size_bytes

    def _chunks() -> Iterator[bytes]:
        # Conta e faz hash durante o streaming; exceder o limite aborta a
        # escrita a meio e o storage remove o ficheiro parcial.
        nonlocal size_bytes
        while True:
            chunk = upload_stream.read(CHUNK_SIZE)
            if not chunk:
                return
            size_bytes += len(chunk)
            if size_bytes > max_bytes:
                msg = (
                    "file exceeds the maximum allowed size of "
                    f"{settings.document_max_file_size_mb} MB"
                )
                raise PayloadTooLargeError(msg)
            hasher.update(chunk)
            yield chunk

    temp_path = storage.save_temp(_chunks())

    try:
        _validate_file(storage, temp_path, size_bytes, extension, declared_content_type)

        checksum = hasher.hexdigest()
        _ensure_checksum_unique(db, document.institution_id, checksum)

        # Lock da linha do documento: serializa uploads concorrentes, para
        # que dois pedidos nunca calculem o mesmo número de versão.
        db.execute(select(Document.id).where(Document.id == document.id).with_for_update())
        current_max = db.scalar(
            select(func.max(DocumentVersion.version_number)).where(
                DocumentVersion.document_id == document.id
            )
        )
        version_number = (current_max or 0) + 1

        version_id = uuid.uuid4()
        # O caminho final usa apenas identificadores gerados pela aplicação,
        # nunca o filename do cliente.
        final_path = (
            f"{document.institution_id}/{document.id}/{version_id}/source{extension}"
        )
        storage.move_to_final(temp_path, final_path)
    except BaseException:
        storage.delete(temp_path)
        raise

    version = DocumentVersion(
        id=version_id,
        document_id=document.id,
        institution_id=document.institution_id,
        uploaded_by_user_id=admin.id,
        version_number=version_number,
        original_filename=safe_filename,
        mime_type=ALLOWED_EXTENSIONS[extension],
        size_bytes=size_bytes,
        checksum_sha256=checksum,
        storage_path=final_path,
        processing_status="pending",
    )
    db.add(version)
    try:
        db.commit()
    except IntegrityError as exc:
        # A verificação prévia pode perder a corrida com um upload
        # concorrente; as constraints são a segunda defesa. O ficheiro
        # final já movido nunca pode ficar órfão.
        db.rollback()
        storage.delete(final_path)
        constraint_name = get_constraint_name(exc)
        if constraint_name == _CHECKSUM_UNIQUE_CONSTRAINT:
            raise ConflictError(CHECKSUM_CONFLICT_MESSAGE) from exc
        if constraint_name == _VERSION_NUMBER_UNIQUE_CONSTRAINT:
            msg = "A concurrent upload assigned the same version number; retry the upload."
            raise ConflictError(msg) from exc
        raise
    except BaseException:
        db.rollback()
        storage.delete(final_path)
        raise
    db.refresh(version)
    return version


def get_accessible_version(
    db: Session,
    admin: User,
    document_id: uuid.UUID,
    version_id: uuid.UUID,
) -> DocumentVersion:
    # O acesso ao documento (com isolamento institucional) é validado
    # primeiro; uma versão de outro documento/instituição é 404.
    document = get_accessible_document(db, admin, document_id)
    version = db.scalar(
        select(DocumentVersion).where(
            DocumentVersion.id == version_id,
            DocumentVersion.document_id == document.id,
        )
    )
    if version is None:
        msg = f"Document version '{version_id}' not found."
        raise NotFoundError(msg)
    return version


def list_versions(
    db: Session,
    admin: User,
    document_id: uuid.UUID,
    *,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[DocumentVersion], int]:
    document = get_accessible_document(db, admin, document_id)

    query = select(DocumentVersion).where(DocumentVersion.document_id == document.id)
    count_query = (
        select(func.count())
        .select_from(DocumentVersion)
        .where(DocumentVersion.document_id == document.id)
    )

    total = db.scalar(count_query) or 0
    items = list(
        db.scalars(
            query.order_by(DocumentVersion.version_number.desc()).limit(limit).offset(offset)
        ).all()
    )
    return items, total


def get_version_content(
    db: Session,
    admin: User,
    document_id: uuid.UUID,
    version_id: uuid.UUID,
    *,
    offset: int,
    limit: int,
) -> tuple[str, int]:
    """Devolve (excerto, total de caracteres) do texto extraído.

    O texto nunca é devolvido por inteiro sem limite: a paginação por
    caracteres (offset/limit) é obrigatória e imposta na rota.
    """
    version = get_accessible_version(db, admin, document_id, version_id)

    if version.processing_status != "processed":
        msg = (
            f"Document version '{version_id}' is {version.processing_status} "
            "and has no extracted content available."
        )
        raise ConflictError(msg)

    text = version.extracted_text or ""
    return text[offset : offset + limit], len(text)
