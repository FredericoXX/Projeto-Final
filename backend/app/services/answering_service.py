"""Orquestração da geração experimental de respostas fundamentadas.

Fluxo: resolver instituição/idioma → normalizar a pergunta → recuperar
evidências (Retriever) → política de evidência → construir contexto →
gerar (AnswerGenerator) → validar deterministicamente → responder com as
fontes citadas.

Este service não contém SQL, não importa SDKs de fornecedores e não
persiste nada (sem conversas, mensagens, prompts ou respostas). Nos logs
ficam apenas dados operacionais (contagens e IDs técnicos) — nunca a
pergunta completa, o contexto documental ou a resposta bruta.
"""

import logging
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.answering.base import (
    AnswerGenerator,
    AnsweringContext,
    InvalidGeneratedAnswerError,
)
from app.answering.context import select_evidence
from app.answering.fallback import get_fallback_message
from app.answering.validation import validate_generated_answer
from app.core.config import settings
from app.core.exceptions import ValidationError
from app.core.language import resolve_language
from app.core.text_normalization import normalize_text
from app.models.user import User
from app.retrieval.base import RetrievalContext, Retriever
from app.schemas.answering import (
    AnsweringRequest,
    AnsweringResponse,
    AnswerSourceRead,
)
from app.services.institution_service import get_institution

logger = logging.getLogger(__name__)


def ask(
    db: Session,
    current_user: User,
    payload: AnsweringRequest,
    retriever: Retriever,
    generator: AnswerGenerator,
) -> AnsweringResponse:
    institution = get_institution(db, current_user.institution_id)
    language = resolve_language(
        payload.language,
        supported_languages=institution.supported_languages,
        fallback=institution.default_language,
    )

    normalized_query = normalize_text(payload.query)
    if not normalized_query:
        msg = "query must contain searchable text"
        raise ValidationError(msg)

    top_k = payload.top_k if payload.top_k is not None else settings.answering_default_top_k
    if top_k > settings.answering_max_top_k:
        msg = f"top_k must be at most {settings.answering_max_top_k}"
        raise ValidationError(msg)

    context = RetrievalContext(
        institution_id=current_user.institution_id,
        language=language,
        reference_date=datetime.now(UTC).date(),
    )
    evidence = retriever.search(db, normalized_query, context, top_k, payload.official_only)

    # Política de evidência desta etapa: zero evidências → fallback
    # determinístico, sem chamar o gerador; nunca há resposta livre.
    if not evidence:
        logger.info(
            "Answering sem evidências (instituição %s): fallback devolvido",
            current_user.institution_id,
        )
        return AnsweringResponse(
            status="insufficient_evidence",
            query=payload.query,
            language=language,
            answer=get_fallback_message(language),
            sources=[],
        )

    entries = select_evidence(
        evidence,
        settings.answering_max_context_chars,
        query=payload.query,
        language=language,
        institution_name=institution.name,
    )
    answering_context = AnsweringContext(
        query=payload.query,
        language=language,
        institution_name=institution.name,
        evidence=entries,
        max_context_chars=settings.answering_max_context_chars,
    )

    generated = generator.generate(answering_context)
    try:
        cited_ids = validate_generated_answer(
            generated,
            allowed_evidence_ids={entry.evidence_id for entry in entries},
            max_answer_chars=settings.answering_max_answer_chars,
        )
    except InvalidGeneratedAnswerError as exc:
        # Apenas o código estável e contagens chegam aos logs — nunca os
        # valores devolvidos pelo fornecedor (IDs, resposta, citações).
        # O cliente recebe só a mensagem segura via handler global (502).
        logger.warning(
            "Generated answer rejected: institution=%s reason=%s invalid_count=%d",
            current_user.institution_id,
            exc.reason_code,
            exc.invalid_count,
        )
        raise

    # Apenas as fontes citadas, pela ordem das citações do gerador.
    entries_by_id = {entry.evidence_id: entry for entry in entries}
    sources = [
        AnswerSourceRead(
            evidence_id=evidence_id,
            chunk_id=entries_by_id[evidence_id].evidence.chunk_id,
            document_id=entries_by_id[evidence_id].evidence.document_id,
            document_version_id=entries_by_id[evidence_id].evidence.document_version_id,
            document_title=entries_by_id[evidence_id].evidence.document_title,
            chunk_index=entries_by_id[evidence_id].evidence.chunk_index,
            source_url=entries_by_id[evidence_id].evidence.source_url,
            official_source=entries_by_id[evidence_id].evidence.official_source,
            language=entries_by_id[evidence_id].evidence.language,
            valid_from=entries_by_id[evidence_id].evidence.valid_from,
            valid_until=entries_by_id[evidence_id].evidence.valid_until,
        )
        for evidence_id in cited_ids
    ]
    logger.info(
        "Answering concluído (instituição %s): %d evidências, %d citadas",
        current_user.institution_id,
        len(entries),
        len(sources),
    )
    return AnsweringResponse(
        status="answered",
        query=payload.query,
        language=language,
        answer=generated.answer,
        sources=sources,
    )
