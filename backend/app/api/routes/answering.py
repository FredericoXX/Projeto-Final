"""Endpoint autenticado de perguntas com resposta fundamentada."""

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.answering.base import AnswerGenerator
from app.answering.dependencies import get_answer_generator
from app.api.dependencies.auth import get_current_user
from app.database.session import get_db
from app.models.user import User
from app.retrieval.base import Retriever
from app.retrieval.dependencies import get_retriever
from app.schemas.answering import AnsweringRequest, AnsweringResponse
from app.services import answering_service, authorization_service

router = APIRouter(prefix="/answering", tags=["Answering"])


@router.post(
    "/ask",
    response_model=AnsweringResponse,
    status_code=status.HTTP_200_OK,
)
def ask(
    payload: AnsweringRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    retriever: Retriever = Depends(get_retriever),
    generator: AnswerGenerator = Depends(get_answer_generator),
) -> AnsweringResponse:
    # 200 tanto para answered como para insufficient_evidence; 503/502
    # (provider não configurado/falha) chegam pelos handlers globais.
    user_id, institution_id = current_user.id, current_user.institution_id
    response = answering_service.ask(db, current_user, payload, retriever, generator)
    # A geração pode demorar e chama um fornecedor externo, por isso não é
    # feita sob lock. A conta é reconfirmada depois dela e antes de entregar a
    # resposta: uma desativação ocorrida durante a geração impede a entrega.
    authorization_service.revalidate_actor(db, user_id=user_id, institution_id=institution_id)
    return response
