import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.dependencies.auth import require_admin
from app.database.session import get_db
from app.models.user import User
from app.schemas.user import UserCreate, UserListResponse, UserRead, UserUpdate
from app.services import user_service

# Todas as rotas exigem um admin autenticado (require_admin) e operam
# exclusivamente sobre a instituição desse admin (isolamento multi-institucional).
router = APIRouter(prefix="/users", tags=["Users"])


@router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> UserRead:
    # institution_id vem sempre do admin autenticado, nunca do payload.
    user = user_service.create_user(db, admin.institution_id, payload)
    return UserRead.model_validate(user)


@router.get("", response_model=UserListResponse)
def list_users(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> UserListResponse:
    items, total = user_service.list_users(db, admin.institution_id, limit=limit, offset=offset)
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
    admin: User = Depends(require_admin),
) -> UserRead:
    user = user_service.get_user(db, admin.institution_id, user_id)
    return UserRead.model_validate(user)


@router.patch("/{user_id}", response_model=UserRead)
def update_user(
    user_id: uuid.UUID,
    payload: UserUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> UserRead:
    user = user_service.update_user(db, admin, user_id, payload)
    return UserRead.model_validate(user)
