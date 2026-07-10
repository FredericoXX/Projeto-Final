from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import AuthenticationError, ConflictError, NotFoundError
from app.core.security import create_access_token, hash_password, verify_password
from app.models.institution import Institution
from app.models.user import User
from app.schemas.auth import RegisterInitialAdminRequest
from app.services.user_service import EMAIL_UNIQUE_INDEX, get_constraint_name

GENERIC_LOGIN_ERROR = "Invalid email or password."

# Hash dummy calculado uma única vez, usado para simular o custo de uma
# verificação real quando o email não existe (ver authenticate_user).
_DUMMY_PASSWORD_HASH = hash_password("dummy-password-for-timing-safety")


def register_initial_admin(db: Session, data: RegisterInitialAdminRequest) -> User:
    # SELECT ... FOR UPDATE bloqueia a linha da instituição até ao commit
    # (ou rollback) desta transação. Duas requisições concorrentes para a
    # mesma instituição ficam assim serializadas: a segunda só lê a linha
    # depois da primeira terminar, altura em que já vê o admin criado por
    # ela e falha com ConflictError — nunca as duas criam um admin inicial.
    institution = db.scalar(
        select(Institution).where(Institution.id == data.institution_id).with_for_update()
    )
    if institution is None:
        msg = f"Institution '{data.institution_id}' not found."
        raise NotFoundError(msg)

    # Uma instituição inativa nunca deve ganhar o seu primeiro admin: esse
    # admin nunca conseguiria iniciar sessão (authenticate_user também
    # verifica institution.is_active), por isso é melhor rejeitar aqui do
    # que criar uma conta inutilizável. 409 porque é um conflito de estado,
    # não um erro de validação do payload em si.
    if not institution.is_active:
        msg = f"Institution '{data.institution_id}' is not active."
        raise ConflictError(msg)

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

    # Idem para a instituição inativa: o login falha com o mesmo erro
    # genérico, sem revelar que a instituição (e não a password) é a causa.
    institution = db.get(Institution, user.institution_id)
    if institution is None or not institution.is_active:
        raise AuthenticationError(GENERIC_LOGIN_ERROR)

    return user


def create_token_for_user(user: User) -> str:
    return create_access_token(subject=str(user.id))
