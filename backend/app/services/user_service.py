import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import AuthorizationError, ConflictError, NotFoundError
from app.core.security import hash_password
from app.models.institution import Institution
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


def _count_other_active_admins(db: Session, institution_id: uuid.UUID, user_id: uuid.UUID) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(User)
            .where(
                User.institution_id == institution_id,
                User.role == "admin",
                User.is_active.is_(True),
                User.id != user_id,
            )
        )
        or 0
    )


def update_user(
    db: Session,
    acting_admin: User,
    user_id: uuid.UUID,
    data: UserUpdate,
) -> User:
    institution_id = acting_admin.institution_id
    user = get_user(db, institution_id, user_id)

    changes = data.model_dump(exclude_unset=True)

    new_email = changes.get("email")
    if new_email is not None and new_email != user.email:
        existing = db.scalar(select(User).where(User.email == new_email, User.id != user_id))
        if existing is not None:
            msg = f"A user with email '{new_email}' already exists."
            raise ConflictError(msg)

    deactivating = changes.get("is_active") is False
    demoting_from_admin = user.role == "admin" and changes.get("role", "admin") != "admin"

    if user.role == "admin" and (deactivating or demoting_from_admin):
        # SELECT ... FOR UPDATE na linha da instituição serializa qualquer
        # operação concorrente que desative/despromova admins da mesma
        # instituição: a segunda destas operações só continua depois da
        # primeira terminar (commit ou rollback), altura em que a contagem
        # abaixo já reflete a alteração feita pela primeira. Sem este lock,
        # duas transações concorrentes podiam ambas ler "ainda há outro
        # admin ativo" antes de qualquer uma delas gravar, e deixar a
        # instituição sem nenhum admin ativo.
        db.execute(select(Institution.id).where(Institution.id == institution_id).with_for_update())

        if deactivating and user.id == acting_admin.id:
            msg = "An admin cannot deactivate their own account."
            raise AuthorizationError(msg)

        # Só pode desativar/despromover este admin se sobrar pelo menos
        # mais um admin ativo na instituição depois da alteração.
        if _count_other_active_admins(db, institution_id, user_id) == 0:
            msg = "The institution must keep at least one active admin."
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
