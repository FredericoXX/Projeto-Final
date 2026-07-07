import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.schemas.institution import (
    InstitutionCreate,
    InstitutionListResponse,
    InstitutionRead,
    InstitutionUpdate,
)
from app.services import institution_service

# O router mantém-se fino de propósito: valida apenas o formato da
# requisição (via schemas) e delega toda a regra de negócio ao serviço.
# Erros de domínio (ConflictError, ValidationError, NotFoundError) não são
# capturados aqui — são convertidos em respostas HTTP pelos handlers globais.
router = APIRouter(prefix="/institutions", tags=["Institutions"])


@router.post(
    "",
    response_model=InstitutionRead,
    status_code=status.HTTP_201_CREATED,
)
def create_institution(
    payload: InstitutionCreate,
    db: Session = Depends(get_db),
) -> InstitutionRead:
    institution = institution_service.create_institution(db, payload)
    return InstitutionRead.model_validate(institution)


@router.get("", response_model=InstitutionListResponse)
def list_institutions(
    is_active: bool | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> InstitutionListResponse:
    items, total = institution_service.list_institutions(
        db, is_active=is_active, limit=limit, offset=offset
    )
    return InstitutionListResponse(
        items=[InstitutionRead.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{institution_id}", response_model=InstitutionRead)
def get_institution(
    institution_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> InstitutionRead:
    institution = institution_service.get_institution(db, institution_id)
    return InstitutionRead.model_validate(institution)


@router.patch("/{institution_id}", response_model=InstitutionRead)
def update_institution(
    institution_id: uuid.UUID,
    payload: InstitutionUpdate,
    db: Session = Depends(get_db),
) -> InstitutionRead:
    institution = institution_service.update_institution(db, institution_id, payload)
    return InstitutionRead.model_validate(institution)
