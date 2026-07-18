"""Regras de negócio dos documentos lógicos (metadados institucionais).

O isolamento multi-institucional segue o padrão dos restantes services:
todas as consultas filtram por current_admin.institution_id, e um
documento de outra instituição é reportado como 404, nunca 403, para não
revelar a sua existência.
"""

import logging
import uuid
from datetime import date

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.language import normalize_language_code, resolve_language
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.document_version import DocumentVersion
from app.models.storage_cleanup_task import StorageCleanupTask
from app.models.user import User
from app.schemas.document import DocumentCreate, DocumentUpdate
from app.services import message_source_service
from app.services.institution_service import get_institution
from app.storage.base import DocumentStorage

logger = logging.getLogger(__name__)

# Mensagens curtas e seguras (sem caminhos nem detalhes internos).
DOCUMENT_REFERENCED_MESSAGE = (
    "This document has been used as a source in persisted answers and "
    "cannot be deleted. Deactivate it to prevent its use in new answers."
)
DOCUMENT_PROCESSING_MESSAGE = (
    "This document has a version currently being processed and cannot be "
    "deleted right now."
)

def acquire_document_lifecycle_lock(db: Session, document_id: uuid.UUID) -> None:
    """Advisory lock transacional por documento (libertado no commit ou
    rollback), partilhado pelo upload de versões e pela eliminação.

    Serializa por completo "criar versão" vs "eliminar documento": a
    eliminação nunca fotografa uma lista de versões que um upload em
    curso ainda vai alargar (ficheiro órfão), e um upload que perca a
    corrida encontra o documento já removido e falha com 404 limpo. As
    ordens de lock de linhas existentes (versões -> documento, usadas
    também pela revalidação de fontes) permanecem inalteradas.
    """
    db.execute(
        select(func.pg_advisory_xact_lock(func.hashtextextended(str(document_id), 0)))
    )

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


def delete_document(
    db: Session,
    admin: User,
    document_id: uuid.UUID,
    *,
    storage: DocumentStorage,
) -> None:
    """Elimina permanentemente um documento nunca citado.

    Ordem de locks compatível com a revalidação de fontes do fluxo
    conversacional (versões por id ascendente, depois o documento): quem
    chegar primeiro bloqueia o outro, sem inversão de ordem — a
    revalidação concorrente que perder a corrida deixa de encontrar as
    versões e falha sem persistir turno parcial; a eliminação que perder
    encontra a MessageSource acabada de persistir e devolve 409.

    A base de dados tem prioridade sobre o storage: os registos são
    eliminados e as tarefas de limpeza registadas numa única transação —
    a falha ao registar a limpeza faz rollback de tudo, nunca é
    silenciosa. Só depois do commit os ficheiros são removidos; os que
    falharem mantêm a sua tarefa para reconciliação posterior.
    """
    document = get_accessible_document(db, admin, document_id)

    try:
        # Serializa contra uploads concorrentes ANTES de fotografar as
        # versões: nenhum upload pode acrescentar uma versão (e um
        # ficheiro) invisível a esta transação.
        acquire_document_lifecycle_lock(db, document.id)
        versions = list(
            db.scalars(
                select(DocumentVersion)
                .where(
                    DocumentVersion.document_id == document.id,
                    DocumentVersion.institution_id == admin.institution_id,
                )
                .order_by(DocumentVersion.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            ).all()
        )
        locked_document = db.scalar(
            select(Document)
            .where(
                Document.id == document.id,
                Document.institution_id == admin.institution_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if locked_document is None:
            # Eliminado por um pedido concorrente entre a leitura e o lock.
            msg = f"Document '{document_id}' not found."
            raise NotFoundError(msg)

        for version in versions:
            if version.processing_status == "processing":
                raise ConflictError(DOCUMENT_PROCESSING_MESSAGE)

        # Verificado sob os locks: nenhuma fonte pode ser persistida em
        # paralelo para estas versões (a revalidação bloqueia nas mesmas
        # linhas). O histórico auditável nunca é destruído.
        if message_source_service.is_document_referenced(
            db,
            document_id=locked_document.id,
            institution_id=admin.institution_id,
        ):
            raise ConflictError(DOCUMENT_REFERENCED_MESSAGE)

        # Tarefas duráveis de limpeza: registadas na MESMA transação que
        # elimina os registos. Se este insert falhar, o rollback abaixo
        # desfaz a eliminação inteira — nada é removido sem que a limpeza
        # correspondente fique agendada de forma durável.
        _enqueue_cleanup_tasks(
            db,
            document_id=locked_document.id,
            storage_paths=[version.storage_path for version in versions],
        )

        # Ordem de remoção respeita as foreign keys: chunks -> versões ->
        # documento, tudo na mesma transação (rollback integral em falha).
        db.execute(
            delete(DocumentChunk).where(
                DocumentChunk.document_id == locked_document.id,
                DocumentChunk.institution_id == admin.institution_id,
            )
        )
        db.execute(
            delete(DocumentVersion).where(
                DocumentVersion.document_id == locked_document.id,
                DocumentVersion.institution_id == admin.institution_id,
            )
        )
        version_count = len(versions)
        db.delete(locked_document)
        db.commit()
    except Exception:
        db.rollback()
        raise

    # Limpeza do armazenamento apenas depois do commit (a base tem
    # prioridade). Processa as tarefas acabadas de registar e quaisquer
    # resíduos de eliminações anteriores; as que falharem permanecem na
    # tabela para nova tentativa. Nos logs entram apenas contagens, ids e
    # tipo de erro, nunca caminhos.
    removed_files = _run_reconciliation(db, storage)
    logger.info(
        "Document deleted: document_id=%s versions=%d files_removed=%d",
        document_id,
        version_count,
        removed_files,
    )


def _enqueue_cleanup_tasks(
    db: Session,
    *,
    document_id: uuid.UUID,
    storage_paths: list[str],
) -> None:
    """Regista as tarefas de limpeza na transação atual (sem commit)."""
    db.add_all(
        StorageCleanupTask(document_id=document_id, storage_path=path)
        for path in storage_paths
    )
    db.flush()


def _run_reconciliation(db: Session, storage: DocumentStorage) -> int:
    """Invólucro best-effort: a reconciliação nunca transforma uma
    eliminação já confirmada num erro para o cliente."""
    try:
        return reconcile_pending_deletions(db, storage)
    except Exception as exc:
        db.rollback()
        logger.warning(
            "Storage cleanup reconciliation failed: error_type=%s",
            type(exc).__name__,
        )
        return 0


def reconcile_pending_deletions(db: Session, storage: DocumentStorage) -> int:
    """Processa as tarefas de limpeza pendentes; devolve quantas concluiu.

    Concorrência-segura: FOR UPDATE SKIP LOCKED particiona as tarefas
    entre reconciliações simultâneas sem bloquear nem perder entradas —
    cada tarefa só é removida na transação que apagou (ou confirmou
    ausente) o respetivo ficheiro. Reexecutável e idempotente; as que
    continuarem a falhar ficam para a próxima oportunidade. Limitação
    documentada do armazenamento local síncrono: sem fila nem daemon, a
    reconciliação corre nas eliminações seguintes ou por invocação
    administrativa direta.
    """
    tasks = list(
        db.scalars(
            select(StorageCleanupTask)
            .order_by(StorageCleanupTask.created_at, StorageCleanupTask.id)
            .with_for_update(skip_locked=True)
        ).all()
    )
    if not tasks:
        db.rollback()
        return 0

    removed = 0
    failed = 0
    for task in tasks:
        try:
            # delete ignora ficheiros já ausentes: a tarefa conclui.
            storage.delete(task.storage_path)
        except Exception as exc:
            failed += 1
            logger.warning(
                "Storage cleanup retry failed: task_id=%s document_id=%s error_type=%s",
                task.id,
                task.document_id,
                type(exc).__name__,
            )
            continue
        db.delete(task)
        removed += 1
    db.commit()
    if removed or failed:
        logger.info(
            "Storage cleanup reconciled: removed=%d remaining=%d", removed, failed
        )
    return removed
