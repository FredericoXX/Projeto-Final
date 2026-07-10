from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import AuthenticationError, ConflictError
from app.core.security import create_access_token, hash_password, verify_password
from app.models.user import User
from app.schemas.auth import RegisterInitialAdminRequest
from app.services.institution_service import get_institution
from app.services.user_service import EMAIL_UNIQUE_INDEX, get_constraint_name

GENERIC_LOGIN_ERROR = "Invalid email or password."

# Hash dummy calculado uma única vez, usado para simular o custo de uma
# verificação real quando o email não existe (ver authenticate_user).
_DUMMY_PASSWORD_HASH = hash_password("dummy-password-for-timing-safety")


def register_initial_admin(db: Session, data: RegisterInitialAdminRequest) -> User:
    # A instituição tem de já existir: este endpoint nunca cria instituições,
    # apenas o primeiro admin de uma instituição já criada via /institutions.
    get_institution(db, data.institution_id)

    # Só é permitido um admin inicial por instituição; admins adicionais
    # devem ser criados por um admin já autenticado através de POST /users.
    existing_admin = db.scalar(
        select(User).where(User.institution_id == data.institution_id, User.role == "admin")
    )
    if existing_admin is not None:
        msg = "This institution already has an admin."
        raise ConflictError(msg)

    existing_email = db.scalar(select(User).where(User.email == data.email))
    if existing_email is not None:
        msg = f"A user with email '{data.email}' already exists."
        raise ConflictError(msg)

    admin = User(
        institution_id=data.institution_id,
        full_name=data.full_name,
        email=data.email,
        password_hash=hash_password(data.password),
        role="admin",
        is_active=True,
    )
    db.add(admin)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        constraint_name = get_constraint_name(exc)
        if constraint_name == EMAIL_UNIQUE_INDEX:
            msg = f"A user with email '{data.email}' already exists."
            raise ConflictError(msg) from exc
        raise
    db.refresh(admin)
    return admin


def authenticate_user(db: Session, email: str, password: str) -> User:
    user = db.scalar(select(User).where(User.email == email))

    if user is None:
        # Faz uma verificação de password "falsa" contra um hash dummy para
        # que o tempo de resposta não denuncie se o email existe ou não.
        verify_password(password, _DUMMY_PASSWORD_HASH)
        raise AuthenticationError(GENERIC_LOGIN_ERROR)

    # Mesma mensagem genérica para password errada e para user inativo:
    # não revelamos ao cliente qual das duas condições falhou.
    if not verify_password(password, user.password_hash) or not user.is_active:
        raise AuthenticationError(GENERIC_LOGIN_ERROR)

    return user


def create_token_for_user(user: User) -> str:
    return create_access_token(subject=str(user.id))
