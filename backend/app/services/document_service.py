"""Regras de negócio dos documentos lógicos (metadados institucionais).

O isolamento multi-institucional segue o padrão dos restantes services:
todas as consultas filtram por current_admin.institution_id, e um
documento de outra instituição é reportado como 404, nunca 403, para não
revelar a sua existência.
"""

import uuid
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.language import normalize_language_code, resolve_language
from app.models.document import Document
from app.models.document_version import DocumentVersion
from app.models.user import User
from app.schemas.document import DocumentCreate, DocumentUpdate
from app.services.institution_service import get_institution

# Campos NOT NULL na base: um null explícito no PATCH seria um erro de
# base de dados; é rejeitado aqui como erro de validação (422).
_NON_NULLABLE_FIELDS = ("title", "language", "official_source", "is_active")


def _validate_validity_range(valid_from: date | None, valid_until: date | None) -> None:
    if valid_from is not None and valid_until is not None and valid_from > valid_until:
        msg = "valid_from must not be after valid_until"
        raise ValidationError(msg)


def create_document(db: Session, admin: User, data: DocumentCreate) -> Document:
    institution = get_institution(db, admin.institution_id)
    # Reutiliza a mesma regra de idioma das conversas/mensagens: omitido
    # herda o default da instituição; fornecido tem de ser suportado.
    language = resolve_language(
        data.language,
        supported_languages=institution.supported_languages,
        fallback=institution.default_language,
    )

    document = Document(
        institution_id=admin.institution_id,
        created_by_user_id=admin.id,
        title=data.title,
        description=data.description,
        language=language,
        source_url=data.source_url,
        official_source=data.official_source,
        valid_from=data.valid_from,
        valid_until=data.valid_until,
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    return document


def get_accessible_document(db: Session, admin: User, document_id: uuid.UUID) -> Document:
    document = db.scalar(
        select(Document).where(
            Document.id == document_id,
            Document.institution_id == admin.institution_id,
        )
    )
    if document is None:
        msg = f"Document '{document_id}' not found."
        raise NotFoundError(msg)
    return document


def list_documents(
    db: Session,
    admin: User,
    *,
    limit: int = 20,
    offset: int = 0,
    is_active: bool | None = None,
    official_source: bool | None = None,
    language: str | None = None,
) -> tuple[list[Document], int]:
    query = select(Document).where(Document.institution_id == admin.institution_id)
    count_query = (
        select(func.count())
        .select_from(Document)
        .where(Document.institution_id == admin.institution_id)
    )

    if is_active is not None:
        query = query.where(Document.is_active.is_(is_active))
        count_query = count_query.where(Document.is_active.is_(is_active))
    if official_source is not None:
        query = query.where(Document.official_source.is_(official_source))
        count_query = count_query.where(Document.official_source.is_(official_source))
    if language is not None:
        try:
            normalized = normalize_language_code(language)
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc
        query = query.where(Document.language == normalized)
        count_query = count_query.where(Document.language == normalized)

    total = db.scalar(count_query) or 0
    items = list(
        db.scalars(
            query.order_by(Document.created_at.desc(), Document.id.desc())
            .limit(limit)
            .offset(offset)
        ).all()
    )
    return items, total


def _has_versions(db: Session, document_id: uuid.UUID) -> bool:
    return (
        db.scalar(
            select(DocumentVersion.id)
            .where(DocumentVersion.document_id == document_id)
            .limit(1)
        )
        is not None
    )


def update_document(
    db: Session,
    admin: User,
    document_id: uuid.UUID,
    data: DocumentUpdate,
) -> Document:
    document = get_accessible_document(db, admin, document_id)

    changes = data.model_dump(exclude_unset=True)

    for field in _NON_NULLABLE_FIELDS:
        if field in changes and changes[field] is None:
            msg = f"{field} must not be null"
            raise ValidationError(msg)

    if "language" in changes:
        institution = get_institution(db, document.institution_id)
        resolved = resolve_language(
            changes["language"],
            supported_languages=institution.supported_languages,
            fallback=document.language,
        )
        # Depois de existir uma versão, o idioma é imutável: as versões
        # históricas não devem mudar implicitamente de idioma — uma
        # tradução é um novo documento lógico.
        if resolved != document.language and _has_versions(db, document.id):
            msg = (
                f"Document '{document_id}' already has versions; "
                "its language can no longer be changed."
            )
            raise ConflictError(msg)
        changes["language"] = resolved

    # O intervalo de validade é verificado sobre o estado final,
    # combinando payload e valores já existentes na entidade.
    resulting_from = changes.get("valid_from", document.valid_from)
    resulting_until = changes.get("valid_until", document.valid_until)
    _validate_validity_range(resulting_from, resulting_until)

    for field, value in changes.items():
        setattr(document, field, value)

    db.commit()
    db.refresh(document)
    return document
