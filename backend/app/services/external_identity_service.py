"""Associação administrativa entre contas locais e identidades externas.

É o único caminho que cria ou remove uma associação nesta fase. O utilizador
associado não tem nenhuma operação sobre ela: não a cria, não a altera e não a
vê através de payloads ou parâmetros que controle. A igualdade de email nunca
é usada para inferir uma associação.

Todas as operações partem do admin autenticado e filtram pela sua
instituição: uma conta de outra instituição responde como inexistente (404).
"""

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError
from app.core.permissions import Permission, has_permission
from app.models.user import User
from app.models.user_external_identity import (
    LINK_METHOD_ADMINISTRATIVE,
    UserExternalIdentity,
)
from app.schemas.external_identity import ExternalIdentityLink
from app.services import authorization_service
from app.services.user_service import get_constraint_name, get_user

SUBJECT_UNIQUE_CONSTRAINT = "uq_user_external_identities_institution_subject"
USER_UNIQUE_CONSTRAINT = "uq_user_external_identities_user_id"

SUBJECT_ALREADY_LINKED_MESSAGE = "This external identity is already linked to another account."
ACCOUNT_ALREADY_LINKED_MESSAGE = (
    "This account is already linked to a different external identity. "
    "Remove the existing link first."
)
ROLE_NOT_LINKABLE_MESSAGE = "This account's role cannot be linked to an external academic identity."


def find_link_for_account(
    db: Session, *, institution_id: uuid.UUID, user_id: uuid.UUID, lock: bool = False
) -> UserExternalIdentity | None:
    """A associação de uma conta, filtrada sempre pela instituição da sessão.

    Com ``lock``, a linha fica sob ``FOR SHARE`` até ao fim da transação: uma
    remoção ou substituição concorrente espera, em vez de fazer commit entre a
    verificação e a entrega do que a associação autorizou. É adquirido depois
    dos locks da instituição e da conta, pela ordem comum.
    """
    statement = select(UserExternalIdentity).where(
        UserExternalIdentity.user_id == user_id,
        UserExternalIdentity.institution_id == institution_id,
    )
    if lock:
        statement = statement.with_for_update(read=True).execution_options(
            populate_existing=True
        )
    return db.scalar(statement)


def _revalidate_admin(db: Session, acting_admin: User) -> User:
    """Reconfirma, sob lock, o admin e a permissão external_identity.manage.

    Um admin despromovido ou desativado por uma transação concorrente não
    chega a criar, ler nem remover a associação.
    """
    return authorization_service.revalidate_actor(
        db,
        user_id=acting_admin.id,
        institution_id=acting_admin.institution_id,
        permission=Permission.EXTERNAL_IDENTITY_MANAGE,
    )


def get_link(db: Session, acting_admin: User, user_id: uuid.UUID) -> UserExternalIdentity:
    acting_admin = _revalidate_admin(db, acting_admin)
    target = get_user(db, acting_admin.institution_id, user_id)
    link = find_link_for_account(db, institution_id=target.institution_id, user_id=target.id)
    if link is None:
        msg = f"User '{user_id}' has no external identity link."
        raise NotFoundError(msg)
    return link


def link_account(
    db: Session,
    acting_admin: User,
    user_id: uuid.UUID,
    data: ExternalIdentityLink,
) -> UserExternalIdentity:
    """Cria a associação, ou confirma-a se já existir com o mesmo identificador.

    Substituir silenciosamente uma associação existente não é permitido: mudar
    o identificador de uma conta muda os registos individuais que ela lê, e
    exige remover primeiro a associação anterior, de forma explícita.
    """
    acting_admin = _revalidate_admin(db, acting_admin)
    institution_id = acting_admin.institution_id
    target = get_user(db, institution_id, user_id)

    # Só papéis que podem consultar os próprios registos individuais são
    # associáveis: uma associação noutro papel não teria uso legítimo.
    if not has_permission(target.role, Permission.ACADEMIC_REQUESTS_READ_OWN):
        raise ConflictError(ROLE_NOT_LINKABLE_MESSAGE)

    existing = find_link_for_account(db, institution_id=institution_id, user_id=target.id)
    if existing is not None:
        if existing.external_subject == data.external_subject:
            return existing
        raise ConflictError(ACCOUNT_ALREADY_LINKED_MESSAGE)

    taken = db.scalar(
        select(UserExternalIdentity.id).where(
            UserExternalIdentity.institution_id == institution_id,
            UserExternalIdentity.external_subject == data.external_subject,
        )
    )
    if taken is not None:
        raise ConflictError(SUBJECT_ALREADY_LINKED_MESSAGE)

    link = UserExternalIdentity(
        institution_id=institution_id,
        user_id=target.id,
        external_subject=data.external_subject,
        link_method=LINK_METHOD_ADMINISTRATIVE,
        linked_by_user_id=acting_admin.id,
    )
    db.add(link)
    try:
        db.commit()
    except IntegrityError as exc:
        # Duas associações concorrentes podem passar ambas pelas verificações
        # acima; as constraints únicas decidem, e a resposta é a mesma.
        db.rollback()
        constraint_name = get_constraint_name(exc)
        if constraint_name == SUBJECT_UNIQUE_CONSTRAINT:
            raise ConflictError(SUBJECT_ALREADY_LINKED_MESSAGE) from exc
        if constraint_name == USER_UNIQUE_CONSTRAINT:
            raise ConflictError(ACCOUNT_ALREADY_LINKED_MESSAGE) from exc
        raise
    db.refresh(link)
    return link


def unlink_account(db: Session, acting_admin: User, user_id: uuid.UUID) -> None:
    link = get_link(db, acting_admin, user_id)
    db.delete(link)
    db.commit()
