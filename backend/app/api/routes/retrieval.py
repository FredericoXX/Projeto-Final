"""Endpoint autenticado de pesquisa de evidências documentais."""

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_user
from app.database.session import get_db
from app.models.user import User
from app.retrieval.base import Retriever
from app.retrieval.dependencies import get_retriever
from app.schemas.retrieval import RetrievalSearchRequest, RetrievalSearchResponse
from app.services import retrieval_service

router = APIRouter(prefix="/retrieval", tags=["Retrieval"])


@router.post(
    "/search",
    response_model=RetrievalSearchResponse,
    status_code=status.HTTP_200_OK,
)
def search_evidence(
    payload: RetrievalSearchRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    retriever: Retriever = Depends(get_retriever),
) -> RetrievalSearchResponse:
    return retrieval_service.search_evidence(db, current_user, payload, retriever)
