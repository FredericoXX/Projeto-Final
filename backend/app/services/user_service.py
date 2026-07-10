import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError
from app.core.security import hash_password
from app.models.user import User
from app.schemas.user import UserCreate, UserUpdate

# Nome do índice único de email definido na migration (ix_users_email);
# usado para distinguir este conflito de outros IntegrityError no commit.
EMAIL_UNIQUE_INDEX = "ix_users_email"


def get_constraint_name(error: IntegrityError) -> str | None:
    """Extract the PostgreSQL constraint/index name that triggered an IntegrityError."""
    diag = getattr(error.orig, "diag", None)
    return getattr(diag, "constraint_name", None) if diag is not None else None


def create_user(db: Session, institution_id: uuid.UUID, data: UserCreate) -> User:
    # Email é único a nível global (não apenas por instituição) por agora.
    existing = db.scalar(select(User).where(User.email == data.email))
    if existing is not None:
        msg = f"A user with email '{data.email}' already exists."
        raise ConflictError(msg)

    user = User(
        institution_id=institution_id,
        full_name=data.full_name,
        email=data.email,
        password_hash=hash_password(data.password),
        role=data.role,
        is_active=True,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        # Mesma corrida entre verificação prévia e commit descrita em
        # institution_service: duas requisições concorrentes podem passar
        # ambas pela verificação de unicidade acima.
        db.rollback()
        constraint_name = get_constraint_name(exc)
        if constraint_name == EMAIL_UNIQUE_INDEX:
            msg = f"A user with email '{data.email}' already exists."
            raise ConflictError(msg) from exc
        raise
    db.refresh(user)
    return user


def get_user(db: Session, institution_id: uuid.UUID, user_id: uuid.UUID) -> User:
    # Filtra sempre por institution_id: um user de outra instituição deve
    # parecer inexistente para este admin, nunca revelar que existe noutro lado.
    user = db.scalar(
        select(User).where(User.id == user_id, User.institution_id == institution_id)
    )
    if user is None:
        msg = f"User '{user_id}' not found."
        raise NotFoundError(msg)
    return user


def list_users(
    db: Session,
    institution_id: uuid.UUID,
    *,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[User], int]:
    query = select(User).where(User.institution_id == institution_id)
    count_query = (
        select(func.count()).select_from(User).where(User.institution_id == institution_id)
    )

    total = db.scalar(count_query) or 0
    items = list(
        db.scalars(
            query.order_by(User.created_at.desc(), User.id.desc()).limit(limit).offset(offset)
        ).all()
    )
    return items, total


def update_user(
    db: Session,
    institution_id: uuid.UUID,
    user_id: uuid.UUID,
    data: UserUpdate,
) -> User:
    user = get_user(db, institution_id, user_id)

    changes = data.model_dump(exclude_unset=True)

    new_email = changes.get("email")
    if new_email is not None and new_email != user.email:
        existing = db.scalar(select(User).where(User.email == new_email, User.id != user_id))
        if existing is not None:
            msg = f"A user with email '{new_email}' already exists."
            raise ConflictError(msg)

    for field, value in changes.items():
        setattr(user, field, value)

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        constraint_name = get_constraint_name(exc)
        if constraint_name == EMAIL_UNIQUE_INDEX:
            msg = f"A user with email '{new_email}' already exists."
            raise ConflictError(msg) from exc
        raise
    db.refresh(user)
    return user
