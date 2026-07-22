import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.models.institution import Institution
from app.models.user import User
from app.schemas.institution import InstitutionAdminUpdate, InstitutionCreate

CODE_UNIQUE_CONSTRAINT = "uq_institutions_code"
DEFAULT_LANGUAGE_CHECK_CONSTRAINT = "ck_institutions_default_language_supported"


def get_constraint_name(error: IntegrityError) -> str | None:
    """Extract the PostgreSQL constraint name that triggered an IntegrityError.

    psycopg exposes the constraint name on the driver-level diagnostics
    object, which is only present for actual constraint violations (not
    every IntegrityError has one).
    """
    diag = getattr(error.orig, "diag", None)
    return getattr(diag, "constraint_name", None) if diag is not None else None


def validate_language_configuration(
    default_language: str,
    supported_languages: list[str],
) -> None:
    """Domain rule enforced here (not only in the schema) so any caller
    that bypasses the API — seed scripts, other services — can't create
    an institution whose default language isn't in its supported set."""
    if default_language not in supported_languages:
        msg = "default_language must be one of supported_languages"
        raise ValidationError(msg)


def create_institution(db: Session, data: InstitutionCreate) -> Institution:
    validate_language_configuration(data.default_language, data.supported_languages)

    existing = db.scalar(select(Institution).where(Institution.code == data.code))
    if existing is not None:
        msg = f"An institution with code '{data.code}' already exists."
        raise ConflictError(msg)

    institution = Institution(
        name=data.name,
        code=data.code,
        domain=data.domain,
        default_language=data.default_language,
        supported_languages=data.supported_languages,
        is_active=data.is_active,
    )
    db.add(institution)
    try:
        db.commit()
    except IntegrityError as exc:
        # O conflito é novamente tratado no commit porque duas requisições
        # concorrentes podem passar pela verificação prévia de unicidade
        # (linha 41) antes de qualquer uma delas gravar o registo.
        db.rollback()
        constraint_name = get_constraint_name(exc)
        if constraint_name == CODE_UNIQUE_CONSTRAINT:
            msg = f"An institution with code '{data.code}' already exists."
            raise ConflictError(msg) from exc
        if constraint_name == DEFAULT_LANGUAGE_CHECK_CONSTRAINT:
            msg = "default_language must be one of supported_languages"
            raise ValidationError(msg) from exc
        raise
    db.refresh(institution)
    return institution


def get_institution(db: Session, institution_id: uuid.UUID) -> Institution:
    institution = db.get(Institution, institution_id)
    if institution is None:
        msg = f"Institution '{institution_id}' not found."
        raise NotFoundError(msg)
    return institution


def get_institution_for_admin(
    db: Session,
    admin: User,
    institution_id: uuid.UUID,
) -> Institution:
    """An institutional admin may only ever see their own institution. Any
    other id is reported as 404, exactly like a non-existent institution,
    so this endpoint never confirms that another tenant exists."""
    if institution_id != admin.institution_id:
        msg = f"Institution '{institution_id}' not found."
        raise NotFoundError(msg)
    return get_institution(db, institution_id)


def list_institutions_for_admin(
    db: Session,
    admin: User,
    *,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[Institution], int]:
    # Limitado apenas à instituição do administrador: ainda não existe um papel
    # platform_admin capaz de listar várias instituições.
    query = select(Institution).where(Institution.id == admin.institution_id)
    count_query = (
        select(func.count())
        .select_from(Institution)
        .where(Institution.id == admin.institution_id)
    )

    total = db.scalar(count_query) or 0
    items = list(
        db.scalars(query.order_by(Institution.created_at.desc()).limit(limit).offset(offset)).all()
    )
    return items, total


def update_institution(
    db: Session,
    institution_id: uuid.UUID,
    data: InstitutionAdminUpdate,
) -> Institution:
    institution = get_institution(db, institution_id)

    changes = data.model_dump(exclude_unset=True)

    # Payloads parciais não podem ser validados no schema, pois o estado
    # resultante depende de campos ausentes deste pedido.
    resulting_default = changes.get("default_language", institution.default_language)
    resulting_supported = changes.get("supported_languages", institution.supported_languages)
    validate_language_configuration(resulting_default, resulting_supported)

    new_code = changes.get("code")
    if new_code is not None and new_code != institution.code:
        existing = db.scalar(
            select(Institution).where(
                Institution.code == new_code,
                Institution.id != institution_id,
            )
        )
        if existing is not None:
            msg = f"An institution with code '{new_code}' already exists."
            raise ConflictError(msg)

    # Aplica apenas os campos presentes no payload (PATCH), preservando
    # os restantes valores já existentes na entidade.
    for field, value in changes.items():
        setattr(institution, field, value)

    try:
        db.commit()
    except IntegrityError as exc:
        # Mesma justificação da criação: a corrida entre a verificação
        # de unicidade e o commit pode deixar passar um código duplicado.
        db.rollback()
        constraint_name = get_constraint_name(exc)
        if constraint_name == CODE_UNIQUE_CONSTRAINT:
            msg = f"An institution with code '{new_code}' already exists."
            raise ConflictError(msg) from exc
        if constraint_name == DEFAULT_LANGUAGE_CHECK_CONSTRAINT:
            msg = "default_language must be one of supported_languages"
            raise ValidationError(msg) from exc
        raise
    db.refresh(institution)
    return institution


def update_institution_for_admin(
    db: Session,
    admin: User,
    institution_id: uuid.UUID,
    data: InstitutionAdminUpdate,
) -> Institution:
    """Same 404-not-403 isolation as get_institution_for_admin: an admin
    can only ever update their own institution."""
    if institution_id != admin.institution_id:
        msg = f"Institution '{institution_id}' not found."
        raise NotFoundError(msg)
    return update_institution(db, institution_id, data)


def set_institution_status(db: Session, institution_id: uuid.UUID, is_active: bool) -> Institution:
    """Bootstrap-only recovery path: institutional admins can no longer
    touch is_active through PATCH /institutions/{id} (see
    InstitutionAdminUpdate), so this is now the only way to (de)activate
    an institution. Restricted to X-Bootstrap-Token by the route, not by
    any check here."""
    institution = get_institution(db, institution_id)
    institution.is_active = is_active
    db.commit()
    db.refresh(institution)
    return institution
