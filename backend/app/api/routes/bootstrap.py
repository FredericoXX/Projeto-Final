import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.dependencies.bootstrap import require_bootstrap_token
from app.database.session import get_db
from app.schemas.institution import InstitutionRead, InstitutionStatusUpdate
from app.services import institution_service

# Rotas de bootstrap: operações de plataforma sensíveis que ainda não têm
# um papel platform_admin dedicado (ver require_bootstrap_token). Todas as
# rotas deste router exigem X-Bootstrap-Token, nunca um JWT de utilizador —
# são um mecanismo temporário e explícito, não uma interface administrativa.
router = APIRouter(
    prefix="/bootstrap",
    tags=["Bootstrap"],
    dependencies=[Depends(require_bootstrap_token)],
)


@router.patch(
    "/institutions/{institution_id}/status",
    response_model=InstitutionRead,
    status_code=status.HTTP_200_OK,
)
def set_institution_status(
    institution_id: uuid.UUID,
    payload: InstitutionStatusUpdate,
    db: Session = Depends(get_db),
) -> InstitutionRead:
    # Único ponto de mutação de is_active: o admin institucional já não
    # pode ativar/desativar a própria instituição (ver InstitutionAdminUpdate),
    # por isso este endpoint de bootstrap é o único caminho de recuperação
    # se uma instituição ficar inativa.
    institution = institution_service.set_institution_status(
        db, institution_id, payload.is_active
    )
    return InstitutionRead.model_validate(institution)
