"""Consulta dos próprios pedidos académicos (integração institucional).

Só leitura e só da própria conta: não cria, aprova, altera nem cancela
pedidos, e não tem notificações, polling ou webhooks. Sem Retriever e sem
AnswerGenerator nas dependências — a consulta é estruturada e não usa LLM.
"""

from fastapi import APIRouter, Depends, Path
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_user, require_permission
from app.core.permissions import Permission
from app.database.session import get_db
from app.institutional.contracts import InstitutionalDataProvider
from app.institutional.dependencies import get_institutional_data_provider
from app.models.user import User
from app.schemas.academic_request import (
    REQUEST_ID_PATTERN,
    AcademicRequestAccessRead,
    AcademicRequestDetailResponse,
    AcademicRequestListResponse,
)
from app.services import academic_request_service

require_own_requests_reader = require_permission(Permission.ACADEMIC_REQUESTS_READ_OWN)

router = APIRouter(prefix="/academic-requests", tags=["Academic requests"])


@router.get("/access", response_model=AcademicRequestAccessRead)
def get_access(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    provider: InstitutionalDataProvider | None = Depends(get_institutional_data_provider),
) -> AcademicRequestAccessRead:
    # Disponível para qualquer conta autenticada: responde "não disponível"
    # com o motivo, sem contactar a fonte, para a interface decidir se mostra
    # a área de consulta.
    return academic_request_service.get_access(db, current_user, provider)


@router.get("", response_model=AcademicRequestListResponse)
def list_own_requests(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_own_requests_reader),
    provider: InstitutionalDataProvider | None = Depends(get_institutional_data_provider),
) -> AcademicRequestListResponse:
    return academic_request_service.list_own_requests(db, current_user, provider)


@router.get("/{request_id}", response_model=AcademicRequestDetailResponse)
def get_own_request(
    request_id: str = Path(pattern=REQUEST_ID_PATTERN),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_own_requests_reader),
    provider: InstitutionalDataProvider | None = Depends(get_institutional_data_provider),
) -> AcademicRequestDetailResponse:
    return academic_request_service.get_own_request(db, current_user, request_id, provider)
