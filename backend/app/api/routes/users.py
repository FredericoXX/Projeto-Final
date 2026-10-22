import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.dependencies.auth import require_permission
from app.core.permissions import Permission
from app.database.session import get_db
from app.models.user import User
from app.schemas.external_identity import ExternalIdentityLink, ExternalIdentityRead
from app.schemas.user import UserCreate, UserListResponse, UserRead, UserUpdate
from app.services import external_identity_service, user_service

# Todas as rotas exigem a permissão USERS_MANAGE (admin institucional) e operam
# exclusivamente sobre a instituição desse admin (isolamento multi-institucional).
require_users_manager = require_permission(Permission.USERS_MANAGE)
require_identity_manager = require_permission(Permission.EXTERNAL_IDENTITY_MANAGE)

router = APIRouter(prefix="/users", tags=["Users"])


@router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_users_manager),
) -> UserRead:
    # institution_id vem sempre do admin autenticado, nunca do payload.
    user = user_service.create_user(db, admin, payload)
    return UserRead.model_validate(user)


@router.get("", response_model=UserListResponse)
def list_users(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    admin: User = Depends(require_users_manager),
) -> UserListResponse:
    items, total = user_service.list_users(db, admin, limit=limit, offset=offset)
    return UserListResponse(
        items=[UserRead.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{user_id}", response_model=UserRead)
def get_user(
    user_id: uuid.UUID,
    db: Session = Depends(get_db),
    admin: User = Depends(require_users_manager),
) -> UserRead:
    user = user_service.get_user_for_admin(db, admin, user_id)
    return UserRead.model_validate(user)


@router.patch("/{user_id}", response_model=UserRead)
def update_user(
    user_id: uuid.UUID,
    payload: UserUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_users_manager),
) -> UserRead:
    user = user_service.update_user(db, admin, user_id, payload)
    return UserRead.model_validate(user)


# Associação a uma identidade externa estável: só por um admin autenticado da
# mesma instituição. Não existe rota pela qual o próprio utilizador a crie,
# altere ou escolha o identificador.
@router.get("/{user_id}/external-identity", response_model=ExternalIdentityRead)
def get_external_identity(
    user_id: uuid.UUID,
    db: Session = Depends(get_db),
    admin: User = Depends(require_identity_manager),
) -> ExternalIdentityRead:
    link = external_identity_service.get_link(db, admin, user_id)
    return ExternalIdentityRead.model_validate(link)


@router.put("/{user_id}/external-identity", response_model=ExternalIdentityRead)
def link_external_identity(
    user_id: uuid.UUID,
    payload: ExternalIdentityLink,
    db: Session = Depends(get_db),
    admin: User = Depends(require_identity_manager),
) -> ExternalIdentityRead:
    link = external_identity_service.link_account(db, admin, user_id, payload)
    return ExternalIdentityRead.model_validate(link)


@router.delete("/{user_id}/external-identity", status_code=status.HTTP_204_NO_CONTENT)
def unlink_external_identity(
    user_id: uuid.UUID,
    db: Session = Depends(get_db),
    admin: User = Depends(require_identity_manager),
) -> None:
    external_identity_service.unlink_account(db, admin, user_id)
