from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_user
from app.database.session import get_db
from app.models.user import User
from app.schemas.auth import LoginRequest, RegisterInitialAdminRequest, TokenResponse
from app.schemas.user import UserRead
from app.services import auth_service

# O router mantém-se fino: valida apenas o formato da requisição e delega
# toda a regra de negócio ao serviço. Erros de domínio (NotFoundError,
# ConflictError, AuthenticationError) são convertidos em respostas HTTP
# pelos handlers globais.
router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post(
    "/register-initial-admin",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
)
def register_initial_admin(
    payload: RegisterInitialAdminRequest,
    db: Session = Depends(get_db),
) -> UserRead:
    admin = auth_service.register_initial_admin(db, payload)
    return UserRead.model_validate(admin)


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    user = auth_service.authenticate_user(db, payload.email, payload.password)
    token = auth_service.create_token_for_user(user)
    return TokenResponse(access_token=token)


@router.get("/me", response_model=UserRead)
def read_current_user(current_user: User = Depends(get_current_user)) -> UserRead:
    return UserRead.model_validate(current_user)
