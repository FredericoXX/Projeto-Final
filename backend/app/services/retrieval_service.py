"""Orquestração fina da recuperação de evidências institucionais."""

from dataclasses import asdict
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.exceptions import ValidationError
from app.core.language import resolve_language
from app.core.text_normalization import normalize_text
from app.models.user import User
from app.retrieval.base import RetrievalContext, Retriever
from app.schemas.retrieval import (
    RetrievalEvidenceRead,
    RetrievalSearchRequest,
    RetrievalSearchResponse,
)
from app.services.institution_service import get_institution


def search_evidence(
    db: Session,
    current_user: User,
    payload: RetrievalSearchRequest,
    retriever: Retriever,
) -> RetrievalSearchResponse:
    institution = get_institution(db, current_user.institution_id)
    language = resolve_language(
        payload.language,
        supported_languages=institution.supported_languages,
        fallback=institution.default_language,
    )
    normalized_query = normalize_text(payload.query)
    if not normalized_query:
        raise ValidationError("query must contain searchable text")

    context = RetrievalContext(
        institution_id=current_user.institution_id,
        language=language,
        # Data em UTC, coerente com o resto do projeto (ex.: processed_at);
        # a data local do servidor podia divergir até um dia perto da meia-noite.
        reference_date=datetime.now(UTC).date(),
    )
    result = retriever.search(
        db,
        normalized_query,
        context,
        payload.top_k,
        payload.official_only,
    )
    # Só a evidência atravessa para HTTP. O trace e a semântica do score são
    # domínio interno: `asdict` sobre `Evidence` continua a ser a única fonte
    # dos campos públicos, e o Momento 6 fixa que esse conjunto é exatamente o
    # de `RetrievalEvidenceRead`.
    return RetrievalSearchResponse(
        query=payload.query,
        language=language,
        items=[RetrievalEvidenceRead(**asdict(item)) for item in result.evidence],
    )
