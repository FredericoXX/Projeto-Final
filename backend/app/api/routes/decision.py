"""Rotas do modo experimental da política de decisão v1.7.

O modo está desativado por omissão (``DECISION_POLICY_MODE=disabled``): o turno
da política responde 503 antes de resolver estimador ou gerador. O B0
(``POST /conversations/{id}/ask``) não é afetado por nada aqui.

A configuração de âmbito e catálogo é do admin institucional
(``institution.manage``), sempre da instituição da sessão.
"""

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.answering.base import AnswerGenerator
from app.answering.dependencies import get_answer_generator
from app.api.dependencies.auth import get_current_user, require_permission
from app.core.exceptions import NotFoundError
from app.core.permissions import Permission
from app.database.session import get_db
from app.decision.estimators.base import DimensionEstimator
from app.decision.estimators.dependencies import get_dimension_estimator
from app.models.user import User
from app.retrieval.base import Retriever
from app.retrieval.dependencies import get_retriever
from app.schemas.decision import (
    ConversationDecisionResponse,
    DecisionStatusRead,
    DecisionTurnRequest,
)
from app.schemas.decision_catalog import (
    DecisionCatalogListResponse,
    DecisionCatalogRead,
    DecisionCatalogWrite,
)
from app.services import decision_catalog_service, decision_service

require_institution_manager = require_permission(Permission.INSTITUTION_MANAGE)

router = APIRouter(tags=["Decision policy (experimental)"])


def require_policy_enabled() -> None:
    """Resolvida antes do estimador e do gerador: desativado é sempre 503."""
    decision_service.ensure_enabled()


@router.get("/decision/status", response_model=DecisionStatusRead)
def get_decision_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DecisionStatusRead:
    return decision_service.get_status(db, current_user)


@router.get("/decision/catalog", response_model=DecisionCatalogRead)
def get_active_catalog(
    db: Session = Depends(get_db),
    admin: User = Depends(require_institution_manager),
) -> DecisionCatalogRead:
    versions = decision_catalog_service.list_catalog_versions(db, admin)
    active = next((version for version in versions if version.is_active), None)
    if active is None:
        msg = "No decision catalog is configured for this institution."
        raise NotFoundError(msg)
    return DecisionCatalogRead.model_validate(active)


@router.get("/decision/catalog/versions", response_model=DecisionCatalogListResponse)
def list_catalog_versions(
    db: Session = Depends(get_db),
    admin: User = Depends(require_institution_manager),
) -> DecisionCatalogListResponse:
    versions = decision_catalog_service.list_catalog_versions(db, admin)
    return DecisionCatalogListResponse(
        items=[DecisionCatalogRead.model_validate(version) for version in versions]
    )


@router.put(
    "/decision/catalog",
    response_model=DecisionCatalogRead,
    status_code=status.HTTP_201_CREATED,
)
def publish_catalog(
    payload: DecisionCatalogWrite,
    db: Session = Depends(get_db),
    admin: User = Depends(require_institution_manager),
) -> DecisionCatalogRead:
    """Publica uma nova versão; a anterior fica no histórico, inativa."""
    catalog = decision_catalog_service.publish_catalog(db, admin, payload)
    return DecisionCatalogRead.model_validate(catalog)


@router.post(
    "/conversations/{conversation_id}/decide",
    response_model=ConversationDecisionResponse,
    dependencies=[Depends(require_policy_enabled)],
)
def decide_in_conversation(
    conversation_id: uuid.UUID,
    payload: DecisionTurnRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    retriever: Retriever = Depends(get_retriever),
    generator: AnswerGenerator = Depends(get_answer_generator),
    estimator: DimensionEstimator = Depends(get_dimension_estimator),
) -> ConversationDecisionResponse:
    """Turno da política v1.7: ANSWER, CLARIFY, ABSTAIN ou ESCALATE.

    ``ESCALATE`` é uma recomendação de contacto (E1): nada é enviado a nenhum
    serviço.
    """
    return decision_service.decide_in_conversation(
        db, current_user, conversation_id, payload, retriever, generator, estimator
    )
