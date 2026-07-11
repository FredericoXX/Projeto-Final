import uuid

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.exceptions import AuthenticationError, AuthorizationError
from app.core.security import decode_access_token
from app.database.session import get_db
from app.models.institution import Institution
from app.models.user import User

# HTTPBearer (não OAuth2PasswordBearer): login continua a ser JSON simples
# (email + password), não o formulário OAuth2 password-flow que o botão
# "Authorize" do Swagger monta para OAuth2PasswordBearer. HTTPBearer faz o
# OpenAPI declarar um esquema HTTP Bearer simples, que o Swagger apresenta
# como um único campo para colar o token — sem tentar autenticar sozinho.
# auto_error=False: controlamos nós próprios o formato da resposta 401
# (via AuthenticationError) em vez do HTTPException por omissão do FastAPI.
bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise AuthenticationError("Not authenticated.")

    payload = decode_access_token(credentials.credentials)
    subject = payload.get("sub")
    try:
        user_id = uuid.UUID(str(subject))
    except (ValueError, TypeError) as exc:
        raise AuthenticationError("Invalid authentication token.") from exc

    # O role nunca é confiado a partir do token: o utilizador é sempre
    # revalidado na base de dados, incluindo o seu estado is_active atual.
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise AuthenticationError("Invalid authentication token.")

    # Um token continua criptograficamente válido mesmo que a instituição
    # do utilizador tenha sido entretanto desativada; é preciso revalidar
    # isso aqui para que esse acesso deixe de funcionar de imediato.
    institution = db.get(Institution, user.institution_id)
    if institution is None or not institution.is_active:
        raise AuthenticationError("Invalid authentication token.")

    return user


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    # Isolamento multi-institucional: require_admin só garante o role;
    # o filtro por institution_id continua a ser feito em cada serviço,
    # usando current_user.institution_id.
    if current_user.role != "admin":
        raise AuthorizationError("Admin privileges are required.")
    return current_user
