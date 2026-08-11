"""Diagnóstico read-only do pipeline documental.

Observa, sem alterar nada, os dados já persistidos de um documento —
texto extraído, chunks e resultados do retrieval existente — e produz um
relatório que localiza a etapa onde uma falha ou risco ocorre:

1. extração de texto;
2. integridade e segmentação em chunks;
3. elegibilidade e recuperação lexical;
4. contexto fornecido à etapa posterior de geração.

Regras estruturais deste módulo:

- apenas leitura: nenhuma função executa INSERT/UPDATE/DELETE nem commit;
  a execução real corre dentro de uma transação PostgreSQL READ ONLY;
- todas as consultas próprias aplicam institution_id no próprio SQL;
- o retrieval reutiliza o retriever existente (contrato Retriever) sem
  duplicar a sua SQL nem alterar a pergunta;
- a admissibilidade documental não é definida aqui: vem de
  ``RetrievalEligibility`` (app.documents.retrievability), a mesma política
  que o retrieval aplica. O relatório declara-a explicitamente, para que
  "não recuperável agora" nunca seja lido como um juízo sobre citações
  históricas já persistidas;
- o answering pipeline e o cliente OpenAI nunca são chamados nem
  importados;
- a comparação de termos reutiliza normalize_text — nunca uma segunda
  implementação de remoção de acentos, whitespace ou casefold.
"""

import json
import logging
import re
import unicodedata
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, fields, is_dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
from statistics import mean
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.language import normalize_language_code
from app.core.text_normalization import normalize_text
from app.documents.retrievability import (
    ConditionOutcome,
    RetrievabilityContext,
    RetrievabilitySubject,
    RetrievabilityVerdict,
    RetrievalEligibility,
)
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.document_version import DocumentVersion
from app.models.institution import Institution
from app.retrieval.base import Evidence, RetrievalContext, Retriever
from app.retrieval.lexical import LexicalRetrievalTrace
from app.services.document_extraction_service import PAGE_SEPARATOR

logger = logging.getLogger(__name__)

# Versão 5 (Fase 4 da issue #24): a elegibilidade deixa de ser reproduzida
# aqui e passa a vir de ``RetrievalEligibility``. O bloco de elegibilidade do
# relatório muda em duas coisas observáveis: identifica a política avaliada
# (campo ``policy``) e passa a incluir ``chunk_language_compatible`` — a
# condição C8, que o diagnóstico não avaliava (divergência D2 do Momento 6).
#
# Versão 4: o trace do retriever lexical passa a refletir o orçamento global
# de candidatos com quotas por variante e a separação entre elegibilidade e
# ranking — os candidatos removidos são classificados por motivo tipado
# (ausência de correspondência, cobertura insuficiente, limiar) e as
# contagens são matematicamente consistentes entre si.
DIAGNOSTIC_REPORT_VERSION = 5

# Limites deliberados: o relatório é evidência, não um dump do documento.
MAX_OCCURRENCES_PER_FACT = 8
MAX_COVERING_SETS = 5
MAX_COVERING_SET_SIZE = 3
MAX_RELEVANT_CHUNKS_FOR_COVER_SEARCH = 12
PROXIMITY_RISK_DISTANCE_CHARS = 300
COMPETING_OCCURRENCES_WINDOW_CHARS = 400

DEFAULT_MAX_EXCERPT_CHARS = 240
MIN_EXCERPT_CHARS = 80
MAX_EXCERPT_CHARS = 1000

PAGE_BREAK_MARKER = "[quebra de página]"
LINE_BREAK_MARKER = "⏎"

PRE_GENERATION_OK_MESSAGE = (
    "Não foi detetada falha antes da geração para esta pergunta. "
    "A formulação e a seleção final da resposta devem ser analisadas "
    "numa etapa posterior."
)


class PrimaryConclusion(StrEnum):
    EXTRACTION_FAILURE = "EXTRACTION_FAILURE"
    CHUNK_INTEGRITY_FAILURE = "CHUNK_INTEGRITY_FAILURE"
    RETRIEVAL_FAILURE = "RETRIEVAL_FAILURE"
    DOCUMENT_NOT_RETRIEVAL_ELIGIBLE = "DOCUMENT_NOT_RETRIEVAL_ELIGIBLE"
    PRE_GENERATION_PIPELINE_OK = "PRE_GENERATION_PIPELINE_OK"
    INSUFFICIENT_EXPECTATION_DATA = "INSUFFICIENT_EXPECTATION_DATA"


class DiagnosticFinding(StrEnum):
    CONTEXT_FRAGMENTATION_RISK = "CONTEXT_FRAGMENTATION_RISK"
    FACT_ASSOCIATION_PROXIMITY_RISK = "FACT_ASSOCIATION_PROXIMITY_RISK"
    SELECTED_VERSION_DIFFERS_FROM_EFFECTIVE_RETRIEVAL_VERSION = (
        "SELECTED_VERSION_DIFFERS_FROM_EFFECTIVE_RETRIEVAL_VERSION"
    )
    TARGET_DOCUMENT_NOT_RETRIEVED = "TARGET_DOCUMENT_NOT_RETRIEVED"
    OTHER_DOCUMENT_PROVIDED_EXPECTED_FACTS = "OTHER_DOCUMENT_PROVIDED_EXPECTED_FACTS"
    MULTIPLE_COMPETING_OCCURRENCES = "MULTIPLE_COMPETING_OCCURRENCES"
    NO_EFFECTIVE_RETRIEVAL_VERSION = "NO_EFFECTIVE_RETRIEVAL_VERSION"


# ---------------------------------------------------------------------------
# Erros controlados (mensagens curtas, sem segredos nem caminhos)
# ---------------------------------------------------------------------------


class DiagnosticError(Exception):
    """Base dos erros controlados do diagnóstico."""


class QuestionsFileError(DiagnosticError):
    """Ficheiro de perguntas inválido; a mensagem inclui índice e id."""


class InstitutionNotFoundError(DiagnosticError):
    """A instituição indicada não existe."""


class DocumentSelectionError(DiagnosticError):
    """Documento não encontrado dentro da instituição indicada."""


class AmbiguousFilenameError(DiagnosticError):
    """Vários documentos lógicos correspondem ao mesmo filename."""

    def __init__(self, matches: list[tuple[UUID, str]]) -> None:
        self.matches = matches
        listing = "; ".join(f"{doc_id} ({title})" for doc_id, title in matches)
        super().__init__(
            "The filename matches more than one logical document in this "
            f"institution: {listing}. Select one explicitly with --document-id."
        )


class VersionSelectionError(DiagnosticError):
    """Versão não encontrada ou documento sem versões."""


class UnusableExtractedTextError(DiagnosticError):
    """A versão selecionada não tem extracted_text utilizável."""


# ---------------------------------------------------------------------------
# Perguntas e factos esperados
# ---------------------------------------------------------------------------

_ALLOWED_QUESTION_FIELDS = frozenset(
    {"id", "question", "language", "expected_answer", "expected_facts"}
)
_ALLOWED_FACT_FIELDS = frozenset({"name", "alternatives"})


@dataclass(frozen=True)
class ExpectedFact:
    name: str
    alternatives: tuple[str, ...]


@dataclass(frozen=True)
class DiagnosticQuestion:
    id: str
    question: str
    language: str
    expected_answer: str
    expected_facts: tuple[ExpectedFact, ...]


def _question_error(index: int, question_id: str | None, message: str) -> QuestionsFileError:
    identity = f"index={index}" + (f" id={question_id}" if question_id else "")
    return QuestionsFileError(f"Invalid question ({identity}): {message}")


def _parse_expected_fact(index: int, question_id: str | None, raw: object) -> ExpectedFact:
    if not isinstance(raw, dict):
        raise _question_error(index, question_id, "each expected_fact must be an object")
    unknown = set(raw) - _ALLOWED_FACT_FIELDS
    if unknown:
        raise _question_error(
            index, question_id, f"unknown expected_fact fields: {sorted(unknown)}"
        )
    name = raw.get("name")
    if not isinstance(name, str) or not name.strip():
        raise _question_error(index, question_id, "expected_fact.name must be a non-empty string")
    alternatives = raw.get("alternatives")
    if not isinstance(alternatives, list) or not alternatives:
        raise _question_error(
            index, question_id, "expected_fact.alternatives must be a non-empty list"
        )
    parsed: list[str] = []
    for alternative in alternatives:
        if not isinstance(alternative, str) or not alternative.strip():
            raise _question_error(
                index, question_id, "expected_fact alternatives must be non-empty strings"
            )
        parsed.append(alternative)
    return ExpectedFact(name=name, alternatives=tuple(parsed))


def parse_questions_payload(payload: object) -> tuple[DiagnosticQuestion, ...]:
    """Valida integralmente o JSON de perguntas; nunca aceita parcialmente."""
    if not isinstance(payload, list) or not payload:
        raise QuestionsFileError("The questions file must contain a non-empty JSON list.")
    questions: list[DiagnosticQuestion] = []
    seen_ids: set[str] = set()
    for index, raw in enumerate(payload):
        if not isinstance(raw, dict):
            raise _question_error(index, None, "each question must be an object")
        question_id = raw.get("id") if isinstance(raw.get("id"), str) else None
        unknown = set(raw) - _ALLOWED_QUESTION_FIELDS
        if unknown:
            raise _question_error(index, question_id, f"unknown fields: {sorted(unknown)}")
        if not question_id or not question_id.strip():
            raise _question_error(index, None, "id must be a non-empty string")
        if question_id in seen_ids:
            raise _question_error(index, question_id, "duplicate question id")
        seen_ids.add(question_id)
        question_text = raw.get("question")
        if not isinstance(question_text, str) or not question_text.strip():
            raise _question_error(index, question_id, "question must be a non-empty string")
        language_raw = raw.get("language")
        if not isinstance(language_raw, str):
            raise _question_error(index, question_id, "language must be a string")
        try:
            language = normalize_language_code(language_raw)
        except ValueError as exc:
            raise _question_error(index, question_id, str(exc)) from None
        expected_answer = raw.get("expected_answer")
        if not isinstance(expected_answer, str) or not expected_answer.strip():
            raise _question_error(index, question_id, "expected_answer must be a non-empty string")
        raw_facts = raw.get("expected_facts")
        if not isinstance(raw_facts, list) or not raw_facts:
            raise _question_error(index, question_id, "expected_facts must be a non-empty list")
        facts = tuple(_parse_expected_fact(index, question_id, fact) for fact in raw_facts)
        questions.append(
            DiagnosticQuestion(
                id=question_id,
                question=question_text,
                language=language,
                expected_answer=expected_answer,
                expected_facts=facts,
            )
        )
    return tuple(questions)


def parse_questions_json(raw_text: str) -> tuple[DiagnosticQuestion, ...]:
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise QuestionsFileError(f"The questions file is not valid JSON: {exc.msg}.") from None
    return parse_questions_payload(payload)


# ---------------------------------------------------------------------------
# Índice normalizado com mapeamento seguro para o texto original
# ---------------------------------------------------------------------------

_NON_WHITESPACE_RE = re.compile(r"\S+")
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0e-\x1f\x7f]")


@dataclass(frozen=True)
class _Segment:
    original_start: int
    original_end: int
    normalized_start: int
    normalized_end: int


@dataclass(frozen=True)
class NormalizedTextIndex:
    """Texto normalizado com mapeamento por token para o texto original.

    O mapeamento é feito à granularidade do token (sequência sem
    whitespace): uma correspondência no espaço normalizado é convertida
    no intervalo original dos tokens que a contêm. Dentro de um token a
    normalização pode mudar o comprimento (acentos, ligaduras), por isso
    nunca se apresenta um offset intra-token como se fosse exato.

    Quando a reconstrução por tokens não reproduz normalize_text(texto)
    (casos-limite Unicode), `exact` fica False e o diagnóstico continua
    apenas com presença/contagem, sem offsets originais — documentado no
    relatório como aproximação, nunca como posição falsa.
    """

    normalized_text: str
    segments: tuple[_Segment, ...]
    exact: bool


def build_normalized_index(original_text: str) -> NormalizedTextIndex:
    segments: list[_Segment] = []
    normalized_parts: list[str] = []
    cursor = 0
    for match in _NON_WHITESPACE_RE.finditer(original_text):
        normalized = normalize_text(match.group())
        if not normalized:
            continue
        if normalized_parts:
            cursor += 1  # espaço único entre tokens, como em normalize_text
        segments.append(
            _Segment(
                original_start=match.start(),
                original_end=match.end(),
                normalized_start=cursor,
                normalized_end=cursor + len(normalized),
            )
        )
        normalized_parts.append(normalized)
        cursor += len(normalized)
    reconstructed = " ".join(normalized_parts)
    reference = normalize_text(original_text)
    if reconstructed != reference:
        # Aproximação documentada: presença sem offsets originais.
        return NormalizedTextIndex(normalized_text=reference, segments=(), exact=False)
    return NormalizedTextIndex(normalized_text=reconstructed, segments=tuple(segments), exact=True)


def _original_span(
    index: NormalizedTextIndex, normalized_start: int, normalized_end: int
) -> tuple[int, int] | None:
    """Intervalo original (limites de token) que contém a correspondência."""
    if not index.exact:
        return None
    covering = [
        segment
        for segment in index.segments
        if segment.normalized_end > normalized_start and segment.normalized_start < normalized_end
    ]
    if not covering:
        return None
    return covering[0].original_start, covering[-1].original_end


def sanitize_excerpt(raw: str) -> str:
    """Excerto legível de linha única: separadores de página e quebras de
    linha ficam visíveis; caracteres de controlo ilegíveis são removidos."""
    without_pages = raw.replace(PAGE_SEPARATOR, f" {PAGE_BREAK_MARKER} ")
    without_newlines = (
        without_pages.replace("\r\n", LINE_BREAK_MARKER)
        .replace("\n", LINE_BREAK_MARKER)
        .replace("\r", LINE_BREAK_MARKER)
    )
    cleaned = _CONTROL_CHARS_RE.sub("", without_newlines.replace("\t", " "))
    return unicodedata.normalize("NFC", cleaned)


def _limit_excerpt(raw: str, max_excerpt_chars: int) -> str:
    """Sanitiza e aplica o limite DEPOIS da sanitização: os marcadores
    legíveis nunca podem expandir o excerto para lá do limite."""
    sanitized = sanitize_excerpt(raw[:max_excerpt_chars])
    return sanitized[:max_excerpt_chars]


def _bounded_excerpt(source_text: str, start: int, end: int, max_excerpt_chars: int) -> str:
    """Excerto original em redor de [start, end), limitado com rigor."""
    span_length = end - start
    margin = max(0, (max_excerpt_chars - span_length) // 2)
    window_start = max(0, start - margin)
    window_end = min(len(source_text), end + margin)
    return _limit_excerpt(source_text[window_start:window_end], max_excerpt_chars)


def _page_number(source_text: str, position: int) -> int | None:
    if PAGE_SEPARATOR not in source_text:
        return None
    return source_text.count(PAGE_SEPARATOR, 0, position) + 1


@dataclass(frozen=True)
class FactOccurrence:
    alternative: str
    normalized_start: int
    original_start: int | None
    original_end: int | None
    excerpt: str | None
    approximate_page: int | None
    crosses_page_break: bool


@dataclass(frozen=True)
class FactPresence:
    fact_name: str
    found: bool
    matched_alternative: str | None
    occurrence_count: int
    occurrences: tuple[FactOccurrence, ...]
    position_mapping_exact: bool


def find_fact_in_text(
    index: NormalizedTextIndex,
    source_text: str,
    fact: ExpectedFact,
    max_excerpt_chars: int,
) -> FactPresence:
    """Presença de um facto: basta uma alternativa após normalização.

    Regista a alternativa que correspondeu e as posições (limitadas).
    Sem fuzzy matching e sem equivalências semânticas inventadas.
    """
    for alternative in fact.alternatives:
        normalized_alternative = normalize_text(alternative)
        if not normalized_alternative:
            continue
        occurrences: list[FactOccurrence] = []
        search_from = 0
        total = 0
        while True:
            position = index.normalized_text.find(normalized_alternative, search_from)
            if position < 0:
                break
            total += 1
            if len(occurrences) < MAX_OCCURRENCES_PER_FACT:
                span = _original_span(index, position, position + len(normalized_alternative))
                if span is None:
                    occurrences.append(
                        FactOccurrence(
                            alternative=alternative,
                            normalized_start=position,
                            original_start=None,
                            original_end=None,
                            excerpt=None,
                            approximate_page=None,
                            crosses_page_break=False,
                        )
                    )
                else:
                    original_start, original_end = span
                    occurrences.append(
                        FactOccurrence(
                            alternative=alternative,
                            normalized_start=position,
                            original_start=original_start,
                            original_end=original_end,
                            excerpt=_bounded_excerpt(
                                source_text, original_start, original_end, max_excerpt_chars
                            ),
                            approximate_page=_page_number(source_text, original_start),
                            crosses_page_break=PAGE_SEPARATOR
                            in source_text[original_start:original_end],
                        )
                    )
            search_from = position + 1
        if total:
            return FactPresence(
                fact_name=fact.name,
                found=True,
                matched_alternative=alternative,
                occurrence_count=total,
                occurrences=tuple(occurrences),
                position_mapping_exact=index.exact,
            )
    return FactPresence(
        fact_name=fact.name,
        found=False,
        matched_alternative=None,
        occurrence_count=0,
        occurrences=(),
        position_mapping_exact=index.exact,
    )


# ---------------------------------------------------------------------------
# Métricas posicionais entre factos da mesma pergunta
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FactPairProximity:
    fact_a: str
    fact_b: str
    min_distance_chars: int | None
    same_line: bool | None
    adjacent_lines: bool | None
    same_approximate_page: bool | None
    order: tuple[str, str] | None
    combined_excerpt: str | None
    competing_occurrences_nearby: int


def compute_fact_pair_proximity(
    source_text: str,
    presence_a: FactPresence,
    presence_b: FactPresence,
    max_excerpt_chars: int,
) -> FactPairProximity:
    """Relação posicional entre dois factos: evidência de risco de
    associação incorreta, nunca prova semântica de pertença."""
    pairs: list[tuple[int, FactOccurrence, FactOccurrence]] = []
    for occurrence_a in presence_a.occurrences:
        if occurrence_a.original_start is None or occurrence_a.original_end is None:
            continue
        for occurrence_b in presence_b.occurrences:
            if occurrence_b.original_start is None or occurrence_b.original_end is None:
                continue
            if occurrence_a.original_start <= occurrence_b.original_start:
                gap = max(0, occurrence_b.original_start - occurrence_a.original_end)
            else:
                gap = max(0, occurrence_a.original_start - occurrence_b.original_end)
            pairs.append((gap, occurrence_a, occurrence_b))
    if not pairs:
        return FactPairProximity(
            fact_a=presence_a.fact_name,
            fact_b=presence_b.fact_name,
            min_distance_chars=None,
            same_line=None,
            adjacent_lines=None,
            same_approximate_page=None,
            order=None,
            combined_excerpt=None,
            competing_occurrences_nearby=0,
        )
    pairs.sort(key=lambda item: (item[0], item[1].original_start or 0))
    distance, best_a, best_b = pairs[0]
    assert best_a.original_start is not None and best_a.original_end is not None
    assert best_b.original_start is not None and best_b.original_end is not None
    span_start = min(best_a.original_start, best_b.original_start)
    span_end = max(best_a.original_end, best_b.original_end)
    between = source_text[span_start:span_end]
    newline_count = between.count("\n")
    order = (
        (presence_a.fact_name, presence_b.fact_name)
        if best_a.original_start <= best_b.original_start
        else (presence_b.fact_name, presence_a.fact_name)
    )
    combined = (
        _bounded_excerpt(source_text, span_start, span_end, max_excerpt_chars)
        if span_end - span_start <= max_excerpt_chars
        else None
    )
    window_start = span_start - COMPETING_OCCURRENCES_WINDOW_CHARS
    window_end = span_end + COMPETING_OCCURRENCES_WINDOW_CHARS
    competing = 0
    for presence, chosen in ((presence_a, best_a), (presence_b, best_b)):
        for occurrence in presence.occurrences:
            if occurrence is chosen or occurrence.original_start is None:
                continue
            if window_start <= occurrence.original_start <= window_end:
                competing += 1
    return FactPairProximity(
        fact_a=presence_a.fact_name,
        fact_b=presence_b.fact_name,
        min_distance_chars=distance,
        same_line=newline_count == 0,
        adjacent_lines=newline_count == 1,
        same_approximate_page=(
            _page_number(source_text, best_a.original_start)
            == _page_number(source_text, best_b.original_start)
            if PAGE_SEPARATOR in source_text
            else None
        ),
        order=order,
        combined_excerpt=combined,
        competing_occurrences_nearby=competing,
    )


# ---------------------------------------------------------------------------
# Seleção segura do documento e das versões
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SelectionContext:
    document: Document
    selected_version: DocumentVersion
    effective_retrieval_version: DocumentVersion | None
    effective_reason: str


def load_institution(db: Session, institution_id: UUID) -> Institution:
    institution = db.scalar(select(Institution).where(Institution.id == institution_id))
    if institution is None:
        raise InstitutionNotFoundError("Institution not found.")
    return institution


def _effective_retrieval_version(
    db: Session, *, institution_id: UUID, document_id: UUID
) -> DocumentVersion | None:
    """A versão processed de maior version_number que o retriever atual
    considera (mesma regra da window rn=1 do retriever, sem duplicar a
    sua SQL de pesquisa)."""
    return db.scalar(
        select(DocumentVersion)
        .where(
            DocumentVersion.institution_id == institution_id,
            DocumentVersion.document_id == document_id,
            DocumentVersion.processing_status == "processed",
        )
        .order_by(DocumentVersion.version_number.desc())
        .limit(1)
    )


def _load_document(db: Session, *, institution_id: UUID, document_id: UUID) -> Document:
    document = db.scalar(
        select(Document).where(
            Document.institution_id == institution_id,
            Document.id == document_id,
        )
    )
    if document is None:
        # Mensagem idêntica para "não existe" e "pertence a outra
        # instituição": nunca revelar a existência noutra instituição.
        raise DocumentSelectionError("Document not found in this institution.")
    return document


def _latest_version(
    db: Session, *, institution_id: UUID, document_id: UUID
) -> DocumentVersion | None:
    return db.scalar(
        select(DocumentVersion)
        .where(
            DocumentVersion.institution_id == institution_id,
            DocumentVersion.document_id == document_id,
        )
        .order_by(DocumentVersion.version_number.desc())
        .limit(1)
    )


def _selection_with_effective(
    db: Session,
    *,
    institution_id: UUID,
    document: Document,
    selected_version: DocumentVersion,
) -> SelectionContext:
    effective = _effective_retrieval_version(
        db, institution_id=institution_id, document_id=document.id
    )
    if effective is None:
        reason = (
            "No processed version exists for this document, so the current "
            "retriever cannot consider it at all."
        )
    elif effective.id == selected_version.id:
        reason = (
            "The selected version is the highest-numbered processed version, "
            "so it is exactly the version the current retriever considers."
        )
    else:
        reason = (
            f"The selected version (number {selected_version.version_number}, "
            f"status {selected_version.processing_status}) is not the version "
            "the retriever considers; the highest-numbered processed version "
            f"is number {effective.version_number}."
        )
    return SelectionContext(
        document=document,
        selected_version=selected_version,
        effective_retrieval_version=effective,
        effective_reason=reason,
    )


def select_by_document_id(
    db: Session, *, institution_id: UUID, document_id: UUID
) -> SelectionContext:
    document = _load_document(db, institution_id=institution_id, document_id=document_id)
    latest = _latest_version(db, institution_id=institution_id, document_id=document_id)
    if latest is None:
        raise VersionSelectionError("The document has no versions.")
    return _selection_with_effective(
        db, institution_id=institution_id, document=document, selected_version=latest
    )


def select_by_version_id(
    db: Session, *, institution_id: UUID, version_id: UUID
) -> SelectionContext:
    version = db.scalar(
        select(DocumentVersion).where(
            DocumentVersion.institution_id == institution_id,
            DocumentVersion.id == version_id,
        )
    )
    if version is None:
        raise VersionSelectionError("Document version not found in this institution.")
    document = _load_document(db, institution_id=institution_id, document_id=version.document_id)
    return _selection_with_effective(
        db, institution_id=institution_id, document=document, selected_version=version
    )


def select_by_filename(db: Session, *, institution_id: UUID, filename: str) -> SelectionContext:
    """Correspondência exata e case-insensitive de original_filename,
    dentro da instituição; sem correspondência parcial e sem normalizar
    ou remover acentos do nome."""
    rows = db.execute(
        select(DocumentVersion, Document.title)
        .join(
            Document,
            (Document.id == DocumentVersion.document_id)
            & (Document.institution_id == DocumentVersion.institution_id),
        )
        .where(
            DocumentVersion.institution_id == institution_id,
            Document.institution_id == institution_id,
            func.lower(DocumentVersion.original_filename) == filename.lower(),
        )
        .order_by(DocumentVersion.version_number.desc(), DocumentVersion.id)
    ).all()
    if not rows:
        raise DocumentSelectionError("Document not found in this institution.")
    by_document: dict[UUID, str] = {}
    for version, title in rows:
        by_document.setdefault(version.document_id, title)
    if len(by_document) > 1:
        matches = sorted(by_document.items(), key=lambda item: str(item[0]))
        raise AmbiguousFilenameError(matches)
    selected_version = rows[0][0]
    document = _load_document(
        db, institution_id=institution_id, document_id=selected_version.document_id
    )
    return _selection_with_effective(
        db, institution_id=institution_id, document=document, selected_version=selected_version
    )


# ---------------------------------------------------------------------------
# Chunks: carregamento único e integridade
# ---------------------------------------------------------------------------


def load_version_chunks(db: Session, version: DocumentVersion) -> list[DocumentChunk]:
    """Todos os chunks da versão numa única consulta ordenada (sem N+1)."""
    return list(
        db.scalars(
            select(DocumentChunk)
            .where(
                DocumentChunk.institution_id == version.institution_id,
                DocumentChunk.document_id == version.document_id,
                DocumentChunk.document_version_id == version.id,
            )
            .order_by(DocumentChunk.chunk_index, DocumentChunk.id)
        ).all()
    )


@dataclass(frozen=True)
class ChunkIntegrityIssue:
    chunk_id: UUID
    chunk_index: int
    issue: str


@dataclass(frozen=True)
class ChunkIntegritySummary:
    total_chunks: int
    min_size: int | None
    max_size: int | None
    mean_size: float | None
    issues: tuple[ChunkIntegrityIssue, ...]
    duplicate_indexes: tuple[int, ...]
    out_of_order_indexes: bool
    gap_count: int
    overlap_count: int
    chunks_by_page: tuple[tuple[int | None, int], ...] = ()
    chunks_by_type: tuple[tuple[str | None, int], ...] = ()
    table_row_count: int = 0
    fallback_fragment_count: int = 0
    cross_page_chunk_count: int = 0
    split_table_row_count: int = 0

    @property
    def compromised_chunk_ids(self) -> frozenset[UUID]:
        return frozenset(issue.chunk_id for issue in self.issues)


def analyze_chunk_integrity(
    chunks: list[DocumentChunk], extracted_text: str
) -> ChunkIntegritySummary:
    issues: list[ChunkIntegrityIssue] = []
    text_length = len(extracted_text)
    seen_indexes: set[int] = set()
    duplicates: list[int] = []
    cross_page_chunk_count = 0
    for chunk in chunks:
        if chunk.chunk_index in seen_indexes:
            duplicates.append(chunk.chunk_index)
        seen_indexes.add(chunk.chunk_index)
        if chunk.start_char < 0:
            issues.append(
                ChunkIntegrityIssue(chunk.id, chunk.chunk_index, "start_char is negative")
            )
        if chunk.end_char <= chunk.start_char:
            issues.append(
                ChunkIntegrityIssue(
                    chunk.id, chunk.chunk_index, "end_char is not greater than start_char"
                )
            )
        if chunk.end_char > text_length:
            issues.append(
                ChunkIntegrityIssue(
                    chunk.id, chunk.chunk_index, "end_char exceeds extracted_text length"
                )
            )
        elif (
            chunk.start_char >= 0
            and chunk.content != extracted_text[chunk.start_char : chunk.end_char]
        ):
            issues.append(
                ChunkIntegrityIssue(
                    chunk.id,
                    chunk.chunk_index,
                    "content differs from extracted_text[start_char:end_char]",
                )
            )
        if not chunk.content.strip():
            issues.append(ChunkIntegrityIssue(chunk.id, chunk.chunk_index, "content is blank"))
        if (
            0 <= chunk.start_char < chunk.end_char <= text_length
            and PAGE_SEPARATOR in extracted_text[chunk.start_char : chunk.end_char]
        ):
            cross_page_chunk_count += 1
            issues.append(
                ChunkIntegrityIssue(
                    chunk.id,
                    chunk.chunk_index,
                    "chunk crosses a PAGE_SEPARATOR boundary",
                )
            )
        if (
            chunk.page_number is not None
            and 0 <= chunk.start_char < text_length
            and _page_number(extracted_text, chunk.start_char) != chunk.page_number
        ):
            issues.append(
                ChunkIntegrityIssue(
                    chunk.id,
                    chunk.chunk_index,
                    "page_number differs from the global start_char page",
                )
            )
    ordered_indexes = [chunk.chunk_index for chunk in chunks]
    out_of_order = ordered_indexes != sorted(ordered_indexes)
    by_offset = sorted(chunks, key=lambda chunk: (chunk.start_char, chunk.end_char))
    gap_count = 0
    overlap_count = 0
    for previous, current in zip(by_offset, by_offset[1:], strict=False):
        if current.start_char > previous.end_char:
            gap_text = extracted_text[previous.end_char : current.start_char]
            if any(
                not character.isspace()
                for character in gap_text.replace(PAGE_SEPARATOR, "")
            ):
                gap_count += 1
        elif current.start_char < previous.end_char:
            overlap_count += 1
    table_row_spans = [
        (match.start(), match.end())
        for match in re.finditer(r"[^\r\n\f]* \| [^\r\n\f]*", extracted_text)
    ]
    split_table_row_count = sum(
        sum(
            chunk.start_char < row_end and chunk.end_char > row_start
            for chunk in chunks
        )
        > 1
        for row_start, row_end in table_row_spans
    )
    pages = Counter(chunk.page_number for chunk in chunks)
    types = Counter(chunk.structure_type for chunk in chunks)
    sizes = [len(chunk.content) for chunk in chunks]
    return ChunkIntegritySummary(
        total_chunks=len(chunks),
        min_size=min(sizes) if sizes else None,
        max_size=max(sizes) if sizes else None,
        mean_size=round(mean(sizes), 1) if sizes else None,
        issues=tuple(issues),
        duplicate_indexes=tuple(duplicates),
        out_of_order_indexes=out_of_order,
        gap_count=gap_count,
        overlap_count=overlap_count,
        chunks_by_page=tuple(
            sorted(pages.items(), key=lambda item: (item[0] is None, item[0] or 0))
        ),
        chunks_by_type=tuple(
            sorted(types.items(), key=lambda item: (item[0] is None, item[0] or ""))
        ),
        table_row_count=types.get("table_row", 0),
        fallback_fragment_count=types.get("fallback_fragment", 0),
        cross_page_chunk_count=cross_page_chunk_count,
        split_table_row_count=split_table_row_count,
    )


# ---------------------------------------------------------------------------
# Cobertura dos factos pelos chunks
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ChunkFactView:
    chunk_id: UUID
    chunk_index: int
    start_char: int
    end_char: int
    content_sha256: str
    language: str
    content_length: int
    excerpt: str
    facts_found: tuple[str, ...]
    page_number: int | None = None
    section_title: str | None = None
    structure_type: str | None = None
    chunking_strategy: str | None = None


@dataclass(frozen=True)
class QuestionChunkAnalysis:
    all_facts_in_extracted_text: bool
    all_facts_present_in_chunks: bool
    all_facts_in_same_chunk: bool
    facts_split_across_chunks: bool
    missing_from_chunks: tuple[str, ...]
    matching_chunk_ids: tuple[UUID, ...]
    covering_chunk_sets: tuple[tuple[UUID, ...], ...]
    minimum_covering_chunk_count: int | None
    relevant_chunks: tuple[ChunkFactView, ...]
    fact_pair_proximity_by_chunk: tuple[FactPairProximity, ...]
    expected_facts_in_same_table_row: bool = False


def _facts_in_chunk(chunk: DocumentChunk, facts: tuple[ExpectedFact, ...]) -> tuple[str, ...]:
    """Factos presentes no chunk, comparando alternativas normalizadas com
    o normalized_content persistido (gerado pela mesma normalize_text)."""
    found: list[str] = []
    for fact in facts:
        for alternative in fact.alternatives:
            normalized = normalize_text(alternative)
            if normalized and normalized in chunk.normalized_content:
                found.append(fact.name)
                break
    return tuple(found)


def _covering_sets(
    fact_names: tuple[str, ...],
    chunk_facts: list[tuple[UUID, frozenset[str]]],
) -> tuple[tuple[tuple[UUID, ...], ...], int | None]:
    """Conjuntos determinísticos e limitados de chunks cuja união cobre
    todos os factos, e o tamanho mínimo desse conjunto."""
    needed = frozenset(fact_names)
    candidates = [(chunk_id, facts) for chunk_id, facts in chunk_facts if facts]
    candidates = candidates[:MAX_RELEVANT_CHUNKS_FOR_COVER_SEARCH]
    if not needed or not candidates:
        return (), None
    union_all = frozenset().union(*(facts for _, facts in candidates))
    if not needed <= union_all:
        return (), None
    for size in range(1, min(MAX_COVERING_SET_SIZE, len(candidates)) + 1):
        found: list[tuple[UUID, ...]] = []
        for combination in _combinations(candidates, size):
            covered = frozenset().union(*(facts for _, facts in combination))
            if needed <= covered:
                found.append(tuple(chunk_id for chunk_id, _ in combination))
                if len(found) >= MAX_COVERING_SETS:
                    break
        if found:
            return tuple(found), size
    # Cobertura só com mais chunks do que o limite de pesquisa exaustiva:
    # aproximação greedy determinística para o tamanho mínimo.
    remaining = set(needed)
    chosen: list[UUID] = []
    for chunk_id, facts in candidates:
        if remaining & facts:
            chosen.append(chunk_id)
            remaining -= facts
        if not remaining:
            break
    if remaining:
        return (), None
    return (tuple(chosen),), len(chosen)


def _combinations(
    candidates: list[tuple[UUID, frozenset[str]]], size: int
) -> list[tuple[tuple[UUID, frozenset[str]], ...]]:
    from itertools import combinations

    return list(combinations(candidates, size))


def analyze_question_chunks(
    question: DiagnosticQuestion,
    chunks: list[DocumentChunk],
    extraction: tuple[FactPresence, ...],
    max_excerpt_chars: int,
) -> QuestionChunkAnalysis:
    fact_names = tuple(fact.name for fact in question.expected_facts)
    facts_in_text = {presence.fact_name for presence in extraction if presence.found}
    all_in_text = set(fact_names) <= facts_in_text

    chunk_fact_map: list[tuple[UUID, frozenset[str]]] = []
    relevant_views: list[ChunkFactView] = []
    proximity_by_chunk: list[FactPairProximity] = []
    facts_anywhere: set[str] = set()
    matching_ids: list[UUID] = []
    matching_table_row_ids: list[UUID] = []
    for chunk in chunks:
        found = _facts_in_chunk(chunk, question.expected_facts)
        chunk_fact_map.append((chunk.id, frozenset(found)))
        if not found:
            continue
        facts_anywhere.update(found)
        relevant_views.append(
            ChunkFactView(
                chunk_id=chunk.id,
                chunk_index=chunk.chunk_index,
                start_char=chunk.start_char,
                end_char=chunk.end_char,
                content_sha256=chunk.content_sha256,
                language=chunk.language,
                content_length=len(chunk.content),
                excerpt=_limit_excerpt(chunk.content, max_excerpt_chars),
                facts_found=found,
                page_number=chunk.page_number,
                section_title=chunk.section_title,
                structure_type=chunk.structure_type,
                chunking_strategy=chunk.chunking_strategy,
            )
        )
        if set(found) >= set(fact_names):
            matching_ids.append(chunk.id)
            if chunk.structure_type == "table_row":
                matching_table_row_ids.append(chunk.id)
        if len(found) >= 2:
            chunk_index = build_normalized_index(chunk.content)
            presences = [
                find_fact_in_text(chunk_index, chunk.content, fact, max_excerpt_chars)
                for fact in question.expected_facts
                if fact.name in found
            ]
            for first in range(len(presences)):
                for second in range(first + 1, len(presences)):
                    proximity_by_chunk.append(
                        compute_fact_pair_proximity(
                            chunk.content,
                            presences[first],
                            presences[second],
                            max_excerpt_chars,
                        )
                    )

    all_in_chunks = set(fact_names) <= facts_anywhere
    missing = tuple(
        name for name in fact_names if name in facts_in_text and name not in facts_anywhere
    )
    covering_sets, minimum_cover = _covering_sets(fact_names, chunk_fact_map)
    return QuestionChunkAnalysis(
        all_facts_in_extracted_text=all_in_text,
        all_facts_present_in_chunks=all_in_chunks,
        all_facts_in_same_chunk=bool(matching_ids),
        facts_split_across_chunks=all_in_chunks and not matching_ids and len(fact_names) > 1,
        missing_from_chunks=missing,
        matching_chunk_ids=tuple(matching_ids),
        covering_chunk_sets=covering_sets,
        minimum_covering_chunk_count=minimum_cover,
        relevant_chunks=tuple(relevant_views),
        fact_pair_proximity_by_chunk=tuple(proximity_by_chunk),
        expected_facts_in_same_table_row=bool(matching_table_row_ids),
    )


# ---------------------------------------------------------------------------
# Elegibilidade para o retrieval
#
# A admissibilidade documental **não é definida aqui**: vem inteira de
# ``RetrievalEligibility``, em app.documents.retrievability — a mesma política
# que o retrieval lexical aplica no PostgreSQL. O diagnóstico pergunta "esta
# versão seria recuperável **agora**", pelo que a política correta é a que
# inclui C5, e não ``CitationPersistenceEligibility``, que responde a uma
# pergunta diferente (ver a nota de proveniência histórica no módulo da
# política).
#
# O que permanece deste lado é a camada de seleção e de apresentação: C12
# ("existe alguma versão processed?") não é condição sobre uma linha mas sobre
# o conjunto de versões, e por isso continua fora da política; e as dataclasses
# abaixo continuam a ser o DTO do relatório, alimentadas pelo veredicto.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EligibilityCondition:
    """Condição no relatório — projeção de um ``ConditionOutcome`` da política.

    Continua a existir como forma de apresentação; deixou de ser onde a
    condição é **decidida**.
    """

    name: str
    satisfied: bool
    detail: str


@dataclass(frozen=True)
class VersionEligibility:
    """Elegibilidade de uma versão, com a política que a decidiu declarada.

    ``policy`` existe para que o relatório não seja lido como uma afirmação
    sobre citações históricas: "não recuperável agora" é um veredicto de
    ``RetrievalEligibility`` e nada diz sobre a legitimidade de um
    ``MessageSource`` já persistido, que nunca é reavaliado por política
    nenhuma.
    """

    version_id: UUID | None
    version_number: int | None
    processing_status: str | None
    conditions: tuple[EligibilityCondition, ...]
    eligible: bool
    policy: str = RetrievalEligibility.name


#: Condições expostas no relatório, na ordem histórica, com C8 no lugar que lhe
#: corresponde. Os nomes são os da política: a Fase 1 adotou deliberadamente os
#: nomes que o diagnóstico já usava, para que esta fase fosse delegação e não
#: renomeação.
#:
#: C1–C3 (isolamento institucional) são avaliadas pela política mas **não** são
#: expostas: o diagnóstico nunca as mostrou, porque as suas próprias consultas
#: já restringem ``institution_id`` no PostgreSQL. Acrescentá-las aqui alargaria
#: a superfície do relatório sem acrescentar informação.
REPORTED_CONDITION_NAMES: tuple[str, ...] = (
    "version_processed",
    "version_is_highest_processed",
    "document_active",
    "language_compatible",
    "chunk_language_compatible",
    "valid_from_compatible",
    "valid_until_compatible",
    "official_source_compatible",
)


def _report_conditions(
    verdicts: Sequence[RetrievabilityVerdict],
) -> tuple[EligibilityCondition, ...]:
    """Projeta os veredictos por chunk nas condições do relatório.

    A composição é **existencial**, porque é essa a pergunta do retrieval: uma
    versão contribui evidência se **algum** dos seus chunks é admissível. Só
    C1 e C8 dependem do chunk; as restantes condições valem o mesmo para todos
    os chunks da versão, pelo que para elas o ``any`` devolve simplesmente esse
    valor comum.

    Quando os chunks divergem numa condição — o caso real de D2 —, a contagem
    entra no detalhe, para que um chunk problemático não fique escondido atrás
    dos que estão bem. Quando todos concordam, o detalhe é exatamente o da
    política, e o texto histórico do relatório não se altera.
    """
    if not verdicts:
        return ()
    outcomes_by_name: dict[str, list[ConditionOutcome]] = {}
    for verdict in verdicts:
        for outcome in verdict.conditions:
            outcomes_by_name.setdefault(outcome.name, []).append(outcome)

    conditions: list[EligibilityCondition] = []
    for name in REPORTED_CONDITION_NAMES:
        outcomes = outcomes_by_name.get(name)
        if not outcomes:
            continue
        satisfied = any(outcome.satisfied for outcome in outcomes)
        # Representante coerente com o valor composto: perante divergência,
        # o detalhe mostrado é o de um chunk que justifica esse valor.
        representative = next(
            outcome for outcome in outcomes if outcome.satisfied == satisfied
        )
        detail = representative.detail
        matching = sum(outcome.satisfied for outcome in outcomes)
        if matching != len(outcomes):
            detail = f"{detail} ({matching} of {len(outcomes)} chunks satisfy it)."
        conditions.append(
            EligibilityCondition(name=name, satisfied=satisfied, detail=detail)
        )
    return tuple(conditions)


def evaluate_eligibility(
    selection: SelectionContext,
    version: DocumentVersion | None,
    *,
    question_language: str,
    reference_date: date,
    official_only: bool,
    chunks: Sequence[DocumentChunk],
) -> VersionEligibility:
    """Relata a recuperabilidade da versão segundo ``RetrievalEligibility``.

    A política é a fonte de verdade: nenhuma condição é decidida aqui. O que
    este nível faz é o que a política não pode fazer — resolver C12 (existe
    versão ``processed``?), que é uma propriedade do conjunto de versões e não
    de uma linha, e projetar o veredicto na superfície do relatório.

    ``chunks`` são os chunks **desta** versão. São obrigatórios porque a
    política avalia candidatos, não versões: C8 (idioma do chunk) só existe
    sobre um chunk concreto. Uma versão sem chunks não tem candidato algum e
    portanto não tem evidência recuperável — o ``any`` devolve falso sem
    qualquer caso especial, tal como o retrieval não devolveria nada dela.

    A ferramenta nunca altera nenhuma destas condições, e nunca escreve.
    """
    document = selection.document
    if version is None:
        # C12 — ausência de linhas, não condição sobre uma linha. Fica fora da
        # política deliberadamente: não há sujeito para avaliar.
        return VersionEligibility(
            version_id=None,
            version_number=None,
            processing_status=None,
            conditions=(
                EligibilityCondition(
                    name="processed_version_exists",
                    satisfied=False,
                    detail="No processed version is available for retrieval.",
                ),
            ),
            eligible=False,
            policy=RetrievalEligibility.name,
        )

    effective = selection.effective_retrieval_version
    context = RetrievabilityContext(
        institution_id=document.institution_id,
        language=question_language,
        reference_date=reference_date,
        official_only=official_only,
    )
    # C5 vem da mesma resolução de versão efetiva que a seleção já fez
    # (_effective_retrieval_version): uma única definição de "versão efetiva",
    # não uma segunda implementação de "latest processed".
    effective_version_id = effective.id if effective is not None else None
    verdicts = [
        RetrievalEligibility.explain(
            RetrievabilitySubject.from_entities(
                chunk=chunk,
                document=document,
                version=version,
                effective_version_id=effective_version_id,
            ),
            context,
        )
        for chunk in chunks
    ]
    return VersionEligibility(
        version_id=version.id,
        version_number=version.version_number,
        processing_status=version.processing_status,
        conditions=_report_conditions(verdicts),
        # O veredicto da política decide, não as condições projetadas: C1–C3
        # não são expostas, e se alguma delas falhasse o relatório falharia
        # para o lado seguro em vez de declarar elegível o que a política
        # recusa.
        eligible=any(verdict.eligible for verdict in verdicts),
        policy=RetrievalEligibility.name,
    )


# ---------------------------------------------------------------------------
# Retrieval real, executado exatamente uma vez por pergunta
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RetrievalResultView:
    rank: int
    chunk_id: UUID
    document_id: UUID
    document_version_id: UUID
    document_title: str
    chunk_index: int
    score: float
    language: str
    official_source: bool
    valid_from: date | None
    valid_until: date | None
    excerpt: str
    belongs_to_target_document: bool
    belongs_to_selected_version: bool
    belongs_to_effective_retrieval_version: bool
    facts_found: tuple[str, ...]
    is_matching_chunk: bool
    cumulative_fact_coverage: tuple[str, ...]


@dataclass(frozen=True)
class QuestionRetrievalAnalysis:
    query: str
    language: str
    reference_date: date
    top_k: int
    official_only: bool
    result_count: int
    results: tuple[RetrievalResultView, ...]
    target_document_retrieved: bool
    selected_version_retrieved: bool
    effective_retrieval_version_retrieved: bool
    matching_chunk_retrieved: bool
    covering_chunk_set_retrieved: bool
    expected_fact_coverage_across_results: tuple[str, ...]
    all_expected_facts_covered_across_results: bool
    irrelevant_for_expected_facts_count: int
    retrieval_returned_only_results_without_expected_facts: bool
    eligible_evidence_exists_but_was_not_retrieved: bool
    correct_target_evidence_exists_but_other_document_was_used: bool
    other_document_covers_all_expected_facts: bool


def _facts_in_evidence(content: str, facts: tuple[ExpectedFact, ...]) -> tuple[str, ...]:
    normalized_content = normalize_text(content)
    found: list[str] = []
    for fact in facts:
        for alternative in fact.alternatives:
            normalized = normalize_text(alternative)
            if normalized and normalized in normalized_content:
                found.append(fact.name)
                break
    return tuple(found)


def verify_results_institution(db: Session, results: list[Evidence], institution_id: UUID) -> None:
    """Confirma que nenhum resultado pertence a outra instituição.

    Confia nos filtros do retriever; esta é apenas a verificação final
    exigida sobre o resultado, com institution_id aplicado na consulta.
    """
    document_ids = {result.document_id for result in results}
    if not document_ids:
        return
    allowed = set(
        db.scalars(
            select(Document.id).where(
                Document.institution_id == institution_id,
                Document.id.in_(document_ids),
            )
        ).all()
    )
    unexpected = document_ids - allowed
    if unexpected:
        # Nunca listar os IDs estrangeiros: apenas o facto controlado.
        raise DiagnosticError(
            "Retrieval returned results outside the requested institution; aborting."
        )


def analyze_question_retrieval(
    question: DiagnosticQuestion,
    results: list[Evidence],
    selection: SelectionContext,
    chunk_analysis: QuestionChunkAnalysis,
    eligibility: VersionEligibility,
    *,
    reference_date: date,
    top_k: int,
    official_only: bool,
    max_excerpt_chars: int,
) -> QuestionRetrievalAnalysis:
    fact_names = tuple(fact.name for fact in question.expected_facts)
    matching_ids = set(chunk_analysis.matching_chunk_ids)
    effective = selection.effective_retrieval_version
    views: list[RetrievalResultView] = []
    covered: list[str] = []
    retrieved_chunk_ids: set[UUID] = set()
    other_document_facts: set[str] = set()
    irrelevant = 0
    for rank, result in enumerate(results, start=1):
        facts_found = _facts_in_evidence(result.content, question.expected_facts)
        if not facts_found:
            irrelevant += 1
        for name in facts_found:
            if name not in covered:
                covered.append(name)
        retrieved_chunk_ids.add(result.chunk_id)
        if result.document_id != selection.document.id:
            other_document_facts.update(facts_found)
        views.append(
            RetrievalResultView(
                rank=rank,
                chunk_id=result.chunk_id,
                document_id=result.document_id,
                document_version_id=result.document_version_id,
                document_title=result.document_title,
                chunk_index=result.chunk_index,
                score=result.score,
                language=result.language,
                official_source=result.official_source,
                valid_from=result.valid_from,
                valid_until=result.valid_until,
                excerpt=_limit_excerpt(result.content, max_excerpt_chars),
                belongs_to_target_document=result.document_id == selection.document.id,
                belongs_to_selected_version=(
                    result.document_version_id == selection.selected_version.id
                ),
                belongs_to_effective_retrieval_version=(
                    effective is not None and result.document_version_id == effective.id
                ),
                facts_found=facts_found,
                is_matching_chunk=result.chunk_id in matching_ids,
                cumulative_fact_coverage=tuple(covered),
            )
        )
    covering_retrieved = any(
        set(cover) <= retrieved_chunk_ids for cover in chunk_analysis.covering_chunk_sets
    )
    all_covered = set(fact_names) <= set(covered)
    evidence_exists = bool(chunk_analysis.covering_chunk_sets) and eligibility.eligible
    target_retrieved = any(view.belongs_to_target_document for view in views)
    return QuestionRetrievalAnalysis(
        query=question.question,
        language=question.language,
        reference_date=reference_date,
        top_k=top_k,
        official_only=official_only,
        result_count=len(views),
        results=tuple(views),
        target_document_retrieved=target_retrieved,
        selected_version_retrieved=any(view.belongs_to_selected_version for view in views),
        effective_retrieval_version_retrieved=any(
            view.belongs_to_effective_retrieval_version for view in views
        ),
        matching_chunk_retrieved=bool(matching_ids & retrieved_chunk_ids),
        covering_chunk_set_retrieved=covering_retrieved,
        expected_fact_coverage_across_results=tuple(covered),
        all_expected_facts_covered_across_results=all_covered,
        irrelevant_for_expected_facts_count=irrelevant,
        retrieval_returned_only_results_without_expected_facts=(
            bool(views) and irrelevant == len(views)
        ),
        eligible_evidence_exists_but_was_not_retrieved=(evidence_exists and not all_covered),
        correct_target_evidence_exists_but_other_document_was_used=(
            evidence_exists and not target_retrieved and bool(views)
        ),
        other_document_covers_all_expected_facts=set(fact_names) <= other_document_facts,
    )


# ---------------------------------------------------------------------------
# Conclusões
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Projeção redigida do trace do retriever
# ---------------------------------------------------------------------------
#
# O trace devolvido por ``search_with_trace`` é uma estrutura **interna**: vive
# em memória e inclui as formas canónicas dos termos da pergunta, úteis para
# depuração e testes. Estas dataclasses são a fronteira entre esse trace e o
# relatório: tudo o que atravessa são contagens, métricas, marcadores
# estruturais e identificadores técnicos — nunca o texto dos termos.
#
# Âmbito exato desta redação: o relatório **contém deliberadamente** a pergunta
# e a resposta esperada (ver ``QuestionDiagnostic``), que são o input do próprio
# operador — daí o aviso de confidencialidade no topo do documento. O que não
# faz sentido é o trace derivar dessa pergunta um segundo conjunto de termos
# canónicos e arrastá-lo para o relatório sem que ninguém o tenha pedido: é
# informação duplicada, de utilidade marginal fora da depuração, que aumenta
# desnecessariamente a superfície do artefacto. A proibição literal de registar
# a pergunta aplica-se aos **logs**, onde nunca aparece.
#
# Os ordinais e intervalos reconhecidos permanecem porque são marcadores
# estruturais exigidos pelo relatório (``ord:1``, ``rng:1-12``) e não conteúdo
# lexical da pergunta.


@dataclass(frozen=True)
class LexicalVariantReport:
    strategy: str
    quota: int
    returned_count: int


@dataclass(frozen=True)
class LexicalResultReport:
    """Linha de resultado no relatório — métricas, sem termos."""

    chunk_id: str
    document_id: str
    chunk_index: int
    strategy: str
    raw_score: float
    score: float
    coverage: float
    exact_phrase: float
    ordered: float
    proximity: float
    title_overlap: float
    section_overlap: float
    structure_type: str | None
    matched_term_count: int
    reason: str


@dataclass(frozen=True)
class LexicalExclusionReport:
    """Linha de exclusão no relatório — motivo tipado, sem termos."""

    chunk_id: str
    document_id: str
    chunk_index: int
    strategy: str
    reason: str
    coverage: float
    matched_term_count: int
    score: float | None


@dataclass(frozen=True)
class LexicalTraceReport:
    """Trace do retriever lexical, redigido para o relatório."""

    fts_config: str
    informative_term_count: int
    query_ordinals: tuple[int, ...]
    query_ranges: tuple[str, ...]
    planned_variants: tuple[str, ...]
    global_candidate_limit: int
    variants: tuple[LexicalVariantReport, ...]
    total_returned_before_dedup: int
    unique_after_dedup: int
    candidates_evaluated: int
    excluded_no_content_match: int
    excluded_insufficient_coverage: int
    excluded_below_threshold: int
    final_result_count: int
    results: tuple[LexicalResultReport, ...]
    excluded: tuple[LexicalExclusionReport, ...]


def redact_lexical_trace(trace: LexicalRetrievalTrace) -> LexicalTraceReport:
    """Converte o trace interno na sua projeção redigida para o relatório.

    Os termos informativos e os termos correspondidos passam a **contagens**:
    o relatório continua a explicar quanta correspondência houve, sem nunca
    revelar o que foi perguntado.
    """
    return LexicalTraceReport(
        fts_config=trace.fts_config,
        informative_term_count=len(trace.informative_terms),
        query_ordinals=trace.query_ordinals,
        query_ranges=trace.query_ranges,
        planned_variants=trace.planned_variants,
        global_candidate_limit=trace.global_candidate_limit,
        variants=tuple(
            LexicalVariantReport(variant.strategy, variant.quota, variant.returned_count)
            for variant in trace.variants
        ),
        total_returned_before_dedup=trace.total_returned_before_dedup,
        unique_after_dedup=trace.unique_after_dedup,
        candidates_evaluated=trace.candidates_evaluated,
        excluded_no_content_match=trace.excluded_no_content_match,
        excluded_insufficient_coverage=trace.excluded_insufficient_coverage,
        excluded_below_threshold=trace.excluded_below_threshold,
        final_result_count=trace.final_result_count,
        results=tuple(
            LexicalResultReport(
                chunk_id=result.chunk_id,
                document_id=result.document_id,
                chunk_index=result.chunk_index,
                strategy=result.strategy,
                raw_score=result.raw_score,
                score=result.score,
                coverage=result.coverage,
                exact_phrase=result.exact_phrase,
                ordered=result.ordered,
                proximity=result.proximity,
                title_overlap=result.title_overlap,
                section_overlap=result.section_overlap,
                structure_type=result.structure_type,
                matched_term_count=len(result.matched_terms),
                reason=result.reason,
            )
            for result in trace.results
        ),
        excluded=tuple(
            LexicalExclusionReport(
                chunk_id=excluded.chunk_id,
                document_id=excluded.document_id,
                chunk_index=excluded.chunk_index,
                strategy=excluded.strategy,
                reason=excluded.reason,
                coverage=excluded.coverage,
                matched_term_count=len(excluded.matched_terms),
                score=excluded.score,
            )
            for excluded in trace.excluded
        ),
    )


@dataclass(frozen=True)
class QuestionDiagnostic:
    question_id: str
    question: str
    language: str
    expected_answer: str
    extraction: tuple[FactPresence, ...]
    fact_pair_proximity: tuple[FactPairProximity, ...]
    chunk_analysis: QuestionChunkAnalysis
    selected_version_eligibility: VersionEligibility
    effective_version_eligibility: VersionEligibility
    retrieval: QuestionRetrievalAnalysis
    primary_conclusion: PrimaryConclusion
    findings: tuple[DiagnosticFinding, ...]
    evidence_summary: tuple[str, ...]
    # Trace do retriever lexical, já redigido (None quando o retriever ativo
    # não o suporta, ex.: um retriever alternativo ou um duplo de teste).
    lexical_trace: LexicalTraceReport | None = None


def classify_question(
    question: DiagnosticQuestion,
    extraction: tuple[FactPresence, ...],
    chunk_analysis: QuestionChunkAnalysis,
    effective_eligibility: VersionEligibility,
    retrieval: QuestionRetrievalAnalysis,
    integrity: ChunkIntegritySummary,
    selection: SelectionContext,
) -> tuple[PrimaryConclusion, tuple[DiagnosticFinding, ...], tuple[str, ...]]:
    findings: list[DiagnosticFinding] = []
    summary: list[str] = []

    effective = selection.effective_retrieval_version
    if effective is None:
        findings.append(DiagnosticFinding.NO_EFFECTIVE_RETRIEVAL_VERSION)
    elif effective.id != selection.selected_version.id:
        findings.append(DiagnosticFinding.SELECTED_VERSION_DIFFERS_FROM_EFFECTIVE_RETRIEVAL_VERSION)
    if chunk_analysis.facts_split_across_chunks:
        findings.append(DiagnosticFinding.CONTEXT_FRAGMENTATION_RISK)
    proximity_risk = any(
        (
            pair.min_distance_chars is not None
            and pair.min_distance_chars > PROXIMITY_RISK_DISTANCE_CHARS
        )
        or pair.same_approximate_page is False
        or pair.competing_occurrences_nearby >= 2
        for pair in _all_pairs_for_risk(chunk_analysis)
    )
    if proximity_risk:
        findings.append(DiagnosticFinding.FACT_ASSOCIATION_PROXIMITY_RISK)
    if any(presence.occurrence_count >= 3 for presence in extraction):
        findings.append(DiagnosticFinding.MULTIPLE_COMPETING_OCCURRENCES)
    if retrieval.result_count and not retrieval.target_document_retrieved:
        findings.append(DiagnosticFinding.TARGET_DOCUMENT_NOT_RETRIEVED)
    if retrieval.other_document_covers_all_expected_facts:
        findings.append(DiagnosticFinding.OTHER_DOCUMENT_PROVIDED_EXPECTED_FACTS)

    if not question.expected_facts:
        summary.append("The questions file provides no expected facts for this question.")
        return PrimaryConclusion.INSUFFICIENT_EXPECTATION_DATA, tuple(findings), tuple(summary)

    missing_in_text = [presence.fact_name for presence in extraction if not presence.found]
    if missing_in_text:
        summary.append(
            f"Expected facts absent from the extracted text: {', '.join(missing_in_text)}."
        )
        return PrimaryConclusion.EXTRACTION_FAILURE, tuple(findings), tuple(summary)
    summary.append("All expected facts are present in the extracted text.")

    compromised = integrity.compromised_chunk_ids
    relevant_compromised = [
        view.chunk_id for view in chunk_analysis.relevant_chunks if view.chunk_id in compromised
    ]
    if chunk_analysis.missing_from_chunks or relevant_compromised:
        if chunk_analysis.missing_from_chunks:
            summary.append(
                "Facts present in the extracted text but absent from every "
                f"chunk: {', '.join(chunk_analysis.missing_from_chunks)}."
            )
        if relevant_compromised:
            summary.append(
                f"{len(relevant_compromised)} relevant chunk(s) have integrity "
                "issues (offsets or content mismatch)."
            )
        return PrimaryConclusion.CHUNK_INTEGRITY_FAILURE, tuple(findings), tuple(summary)
    summary.append("All expected facts appear in at least one chunk of the selected version.")

    if not effective_eligibility.eligible:
        failed = [c.name for c in effective_eligibility.conditions if not c.satisfied]
        summary.append(
            "The document has no retrieval-eligible evidence under the "
            f"current rules (failed conditions: {', '.join(failed)})."
        )
        return (
            PrimaryConclusion.DOCUMENT_NOT_RETRIEVAL_ELIGIBLE,
            tuple(findings),
            tuple(summary),
        )
    summary.append("An effective retrieval version exists and passes the current filters.")

    if retrieval.all_expected_facts_covered_across_results:
        summary.append(
            "The union of the retrieved results covers all expected facts "
            f"(coverage: {', '.join(retrieval.expected_fact_coverage_across_results)})."
        )
        summary.append(PRE_GENERATION_OK_MESSAGE)
        return PrimaryConclusion.PRE_GENERATION_PIPELINE_OK, tuple(findings), tuple(summary)

    if retrieval.other_document_covers_all_expected_facts:
        summary.append(
            "The target document's results do not cover all expected facts, "
            "but another returned document provides equivalent coverage of "
            "the defined facts."
        )
        summary.append(PRE_GENERATION_OK_MESSAGE)
        return PrimaryConclusion.PRE_GENERATION_PIPELINE_OK, tuple(findings), tuple(summary)

    covered = set(retrieval.expected_fact_coverage_across_results)
    uncovered = [
        name for name in (fact.name for fact in question.expected_facts) if name not in covered
    ]
    summary.append(
        "Eligible evidence covering all expected facts exists in the chunks, "
        f"but the top_k results leave facts uncovered: {', '.join(uncovered)}."
    )
    return PrimaryConclusion.RETRIEVAL_FAILURE, tuple(findings), tuple(summary)


def _all_pairs_for_risk(chunk_analysis: QuestionChunkAnalysis) -> list[FactPairProximity]:
    return list(chunk_analysis.fact_pair_proximity_by_chunk)


# ---------------------------------------------------------------------------
# Relatório completo
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ExecutionInfo:
    executed_at_utc: str
    reference_date: date
    report_format: str
    top_k: int
    official_only: bool
    max_excerpt_chars: int
    diagnostic_report_version: int
    base_sha: str | None


@dataclass(frozen=True)
class InstitutionInfo:
    institution_id: UUID
    name: str


@dataclass(frozen=True)
class DocumentInfo:
    document_id: UUID
    title: str
    language: str
    is_active: bool
    official_source: bool
    valid_from: date | None
    valid_until: date | None


@dataclass(frozen=True)
class ExtractionPageSummary:
    """Linha da tabela por página: apenas metadados persistidos e
    sanitizados; o diagnóstico nunca reexecuta OCR."""

    page_number: int | None
    method: str | None
    extracted_characters: int | None
    ocr_confidence: float | None
    quality: str | None
    warning: str | None


@dataclass(frozen=True)
class SelectedVersionInfo:
    version_id: UUID
    version_number: int
    original_filename: str
    mime_type: str
    size_bytes: int
    checksum_sha256_prefix: str
    processing_status: str
    processing_error: str | None
    page_count: int | None
    extracted_text_length: int
    processed_at: str | None
    # Metadados de extração do Momento 2; None em versões históricas.
    extraction_method: str | None
    extraction_quality: str | None
    extraction_warning: str | None
    native_page_count: int | None
    ocr_page_count: int | None
    low_quality_page_count: int | None
    page_summaries: tuple[ExtractionPageSummary, ...]


@dataclass(frozen=True)
class EffectiveVersionInfo:
    version_id: UUID | None
    version_number: int | None
    processing_status: str | None
    reason: str
    differs_from_selected: bool


@dataclass(frozen=True)
class ConfigurationInfo:
    chunk_size_chars: int
    chunk_overlap_chars: int
    top_k: int
    reference_date: date


@dataclass(frozen=True)
class GlobalConclusion:
    conclusions_by_question: tuple[tuple[str, str], ...]
    counts: tuple[tuple[str, int], ...]
    message: str


@dataclass(frozen=True)
class DiagnosticReport:
    diagnostic_report_version: int
    execution: ExecutionInfo
    institution: InstitutionInfo
    document: DocumentInfo
    selected_version: SelectedVersionInfo
    effective_retrieval_version: EffectiveVersionInfo
    configuration: ConfigurationInfo
    chunk_integrity: ChunkIntegritySummary
    questions: tuple[QuestionDiagnostic, ...]
    global_conclusion: GlobalConclusion
    limitations: tuple[str, ...]


# Limite deliberado da tabela por página no relatório: evita relatórios
# excessivos em documentos longos.
MAX_PAGE_SUMMARIES_IN_REPORT = 60


def _build_extraction_page_summaries(
    details: object,
) -> tuple[tuple[ExtractionPageSummary, ...], int | None, int | None, int | None]:
    """Converte extraction_details persistido (JSONB) em linhas seguras.

    Defensivo por construção: aceita None e entradas malformadas (versões
    históricas ou dados futuros) sem falhar; sanitiza avisos.
    """
    if not isinstance(details, list):
        return (), None, None, None
    summaries: list[ExtractionPageSummary] = []
    native_pages = 0
    ocr_pages = 0
    low_quality_pages = 0
    for entry in details:
        if not isinstance(entry, dict):
            continue
        method = entry.get("method")
        quality = entry.get("quality")
        if method == "native":
            native_pages += 1
        elif method == "ocr":
            ocr_pages += 1
        if quality == "low":
            low_quality_pages += 1
        warning = entry.get("warning")
        confidence = entry.get("ocr_confidence")
        characters = entry.get("extracted_characters")
        page_number = entry.get("page_number")
        summaries.append(
            ExtractionPageSummary(
                page_number=page_number if isinstance(page_number, int) else None,
                method=method if isinstance(method, str) else None,
                extracted_characters=characters if isinstance(characters, int) else None,
                ocr_confidence=(
                    float(confidence) if isinstance(confidence, int | float) else None
                ),
                quality=quality if isinstance(quality, str) else None,
                warning=(
                    sanitize_excerpt(warning)[:160] if isinstance(warning, str) else None
                ),
            )
        )
    return tuple(summaries), native_pages, ocr_pages, low_quality_pages


def _build_selected_version_info(
    selected: DocumentVersion, extracted_text_length: int
) -> SelectedVersionInfo:
    summaries, native_pages, ocr_pages, low_pages = _build_extraction_page_summaries(
        selected.extraction_details
    )
    return SelectedVersionInfo(
        version_id=selected.id,
        version_number=selected.version_number,
        original_filename=selected.original_filename,
        mime_type=selected.mime_type,
        size_bytes=selected.size_bytes,
        checksum_sha256_prefix=selected.checksum_sha256[:12],
        processing_status=selected.processing_status,
        processing_error=(
            sanitize_excerpt(selected.processing_error)[:200]
            if selected.processing_error
            else None
        ),
        page_count=selected.page_count,
        extracted_text_length=extracted_text_length,
        processed_at=(selected.processed_at.isoformat() if selected.processed_at else None),
        extraction_method=selected.extraction_method,
        extraction_quality=selected.extraction_quality,
        extraction_warning=(
            sanitize_excerpt(selected.extraction_warning)[:200]
            if selected.extraction_warning
            else None
        ),
        native_page_count=native_pages,
        ocr_page_count=ocr_pages,
        low_quality_page_count=low_pages,
        page_summaries=summaries[:MAX_PAGE_SUMMARIES_IN_REPORT],
    )


LIMITATIONS: tuple[str, ...] = (
    "A ferramenta não executa OCR nem reabre o PDF: observa apenas os dados já persistidos.",
    "Não interpreta visualmente tabelas; a estrutura tabular pode perder-se na extração.",
    "Não valida semanticamente a resposta e não chama o modelo de geração.",
    "Não corrige o pipeline: apenas observa, mede e compara.",
    "A análise depende inteiramente dos factos esperados fornecidos no ficheiro de perguntas.",
    "Proximidade textual entre factos é evidência, nunca prova de associação semântica.",
    "A divisão de factos por vários chunks não é automaticamente uma falha: o answering "
    "recebe vários chunks no mesmo contexto.",
    "As posições no texto original são mapeadas à granularidade do token; quando o "
    "mapeamento não é exato, apresenta-se apenas presença e contagem.",
)


def _build_global_conclusion(
    questions: tuple[QuestionDiagnostic, ...],
) -> GlobalConclusion:
    counts: dict[str, int] = {}
    for question in questions:
        counts[question.primary_conclusion.value] = (
            counts.get(question.primary_conclusion.value, 0) + 1
        )
    ordered_counts = tuple(sorted(counts.items()))
    per_question = tuple(
        (question.question_id, question.primary_conclusion.value) for question in questions
    )
    distinct = set(counts)
    if distinct == {PrimaryConclusion.PRE_GENERATION_PIPELINE_OK.value}:
        message = (
            "Não foi detetada falha antes da geração em nenhuma das perguntas "
            "analisadas. A formulação e a seleção final da resposta devem ser "
            "analisadas numa etapa posterior."
        )
    elif len(distinct) == 1:
        message = (
            f"Todas as perguntas partilham a mesma conclusão: {next(iter(distinct))}. "
            "Ver o detalhe por pergunta antes de qualquer correção."
        )
    else:
        parts = ", ".join(f"{name}={count}" for name, count in ordered_counts)
        message = (
            "Resultados mistos: perguntas diferentes falham em etapas "
            f"diferentes ({parts}). Nenhuma causa única explica todos os "
            "casos; cada conclusão por pergunta deve ser tratada em separado."
        )
    return GlobalConclusion(
        conclusions_by_question=per_question,
        counts=ordered_counts,
        message=message,
    )


def _search_with_optional_trace(
    retriever: Retriever,
    db: Session,
    normalized_query: str,
    context: RetrievalContext,
    top_k: int,
    official_only: bool,
) -> tuple[list[Evidence], LexicalRetrievalTrace | None]:
    """Executa a pesquisa uma única vez, capturando o trace se existir.

    O contrato ``Retriever`` mantém-se neutro (só ``search``); o trace é
    um extra opcional, detetado por introspeção. Um retriever alternativo
    ou um duplo de teste sem ``search_with_trace`` continua a funcionar.
    """
    search_with_trace = getattr(retriever, "search_with_trace", None)
    if callable(search_with_trace):
        results, trace = search_with_trace(db, normalized_query, context, top_k, official_only)
        return results, trace
    return retriever.search(db, normalized_query, context, top_k, official_only), None


def run_diagnostic(
    db: Session,
    retriever: Retriever,
    *,
    institution_id: UUID,
    questions: tuple[DiagnosticQuestion, ...],
    document_id: UUID | None = None,
    version_id: UUID | None = None,
    filename: str | None = None,
    reference_date: date | None = None,
    top_k: int = 5,
    official_only: bool = True,
    max_excerpt_chars: int = DEFAULT_MAX_EXCERPT_CHARS,
    report_format: str = "markdown",
    base_sha: str | None = None,
    clock: Any = None,
) -> DiagnosticReport:
    """Executa o diagnóstico completo dentro de uma transação READ ONLY.

    Produz exatamente um objeto de diagnóstico; os renderizadores geram
    Markdown ou JSON a partir dele sem voltar a executar o retrieval.
    """
    selectors = [value for value in (document_id, version_id, filename) if value is not None]
    if len(selectors) != 1:
        raise DiagnosticError("Exactly one of document_id, version_id or filename is required.")
    now = clock() if clock is not None else datetime.now(UTC)
    resolved_reference_date = reference_date if reference_date is not None else now.date()

    # Qualquer escrita acidental a partir daqui falha na própria base de
    # dados: a transação é explicitamente read-only.
    db.rollback()
    db.execute(text("SET TRANSACTION READ ONLY"))
    try:
        institution = load_institution(db, institution_id)
        if version_id is not None:
            selection = select_by_version_id(
                db, institution_id=institution_id, version_id=version_id
            )
        elif document_id is not None:
            selection = select_by_document_id(
                db, institution_id=institution_id, document_id=document_id
            )
        else:
            assert filename is not None
            selection = select_by_filename(db, institution_id=institution_id, filename=filename)

        selected = selection.selected_version
        extracted_text = selected.extracted_text
        if extracted_text is None or not extracted_text.strip():
            raise UnusableExtractedTextError("The selected version has no usable extracted_text.")

        chunks = load_version_chunks(db, selected)
        integrity = analyze_chunk_integrity(chunks, extracted_text)
        text_index = build_normalized_index(extracted_text)

        # A elegibilidade é avaliada sobre os chunks **da versão em causa**: a
        # versão efetiva do retrieval pode não ser a selecionada, e avaliar C8
        # com os chunks da outra responderia à pergunta errada. Leitura única,
        # fora do ciclo das perguntas, porque não depende da pergunta.
        effective_version = selection.effective_retrieval_version
        if effective_version is None:
            effective_chunks: list[DocumentChunk] = []
        elif effective_version.id == selected.id:
            effective_chunks = chunks
        else:
            effective_chunks = load_version_chunks(db, effective_version)

        question_reports: list[QuestionDiagnostic] = []
        for question in questions:
            extraction = tuple(
                find_fact_in_text(text_index, extracted_text, fact, max_excerpt_chars)
                for fact in question.expected_facts
            )
            proximity: list[FactPairProximity] = []
            for first in range(len(extraction)):
                for second in range(first + 1, len(extraction)):
                    if extraction[first].found and extraction[second].found:
                        proximity.append(
                            compute_fact_pair_proximity(
                                extracted_text,
                                extraction[first],
                                extraction[second],
                                max_excerpt_chars,
                            )
                        )
            chunk_analysis = analyze_question_chunks(
                question, chunks, extraction, max_excerpt_chars
            )
            selected_eligibility = evaluate_eligibility(
                selection,
                selected,
                question_language=question.language,
                reference_date=resolved_reference_date,
                official_only=official_only,
                chunks=chunks,
            )
            effective_eligibility = evaluate_eligibility(
                selection,
                effective_version,
                question_language=question.language,
                reference_date=resolved_reference_date,
                official_only=official_only,
                chunks=effective_chunks,
            )
            # O retrieval corre exatamente uma vez por pergunta, com o
            # contrato real: pergunta normalizada, contexto e filtros atuais.
            # Quando o retriever suporta um trace interno, usa-se a variante
            # que o devolve — a pesquisa continua a correr uma só vez.
            normalized_query = normalize_text(question.question)
            context = RetrievalContext(
                institution_id=institution_id,
                language=question.language,
                reference_date=resolved_reference_date,
            )
            results, raw_trace = _search_with_optional_trace(
                retriever, db, normalized_query, context, top_k, official_only
            )
            # O trace atravessa para o relatório apenas na forma redigida: as
            # formas canónicas derivadas da pergunta passam a contagens.
            lexical_trace = redact_lexical_trace(raw_trace) if raw_trace is not None else None
            verify_results_institution(db, results, institution_id)
            retrieval = analyze_question_retrieval(
                question,
                results,
                selection,
                chunk_analysis,
                effective_eligibility,
                reference_date=resolved_reference_date,
                top_k=top_k,
                official_only=official_only,
                max_excerpt_chars=max_excerpt_chars,
            )
            conclusion, findings, summary = classify_question(
                question,
                extraction,
                chunk_analysis,
                effective_eligibility,
                retrieval,
                integrity,
                selection,
            )
            question_reports.append(
                QuestionDiagnostic(
                    question_id=question.id,
                    question=question.question,
                    language=question.language,
                    expected_answer=question.expected_answer,
                    extraction=extraction,
                    fact_pair_proximity=tuple(proximity),
                    chunk_analysis=chunk_analysis,
                    selected_version_eligibility=selected_eligibility,
                    effective_version_eligibility=effective_eligibility,
                    retrieval=retrieval,
                    primary_conclusion=conclusion,
                    findings=findings,
                    evidence_summary=summary,
                    lexical_trace=lexical_trace,
                )
            )

        effective = selection.effective_retrieval_version
        report = DiagnosticReport(
            diagnostic_report_version=DIAGNOSTIC_REPORT_VERSION,
            execution=ExecutionInfo(
                executed_at_utc=now.isoformat(),
                reference_date=resolved_reference_date,
                report_format=report_format,
                top_k=top_k,
                official_only=official_only,
                max_excerpt_chars=max_excerpt_chars,
                diagnostic_report_version=DIAGNOSTIC_REPORT_VERSION,
                base_sha=base_sha,
            ),
            institution=InstitutionInfo(institution_id=institution.id, name=institution.name),
            document=DocumentInfo(
                document_id=selection.document.id,
                title=selection.document.title,
                language=selection.document.language,
                is_active=selection.document.is_active,
                official_source=selection.document.official_source,
                valid_from=selection.document.valid_from,
                valid_until=selection.document.valid_until,
            ),
            selected_version=_build_selected_version_info(selected, len(extracted_text)),
            effective_retrieval_version=EffectiveVersionInfo(
                version_id=effective.id if effective else None,
                version_number=effective.version_number if effective else None,
                processing_status=effective.processing_status if effective else None,
                reason=selection.effective_reason,
                differs_from_selected=effective is None or effective.id != selected.id,
            ),
            configuration=ConfigurationInfo(
                chunk_size_chars=settings.document_chunk_size_chars,
                chunk_overlap_chars=settings.document_chunk_overlap_chars,
                top_k=top_k,
                reference_date=resolved_reference_date,
            ),
            chunk_integrity=integrity,
            questions=tuple(question_reports),
            global_conclusion=_build_global_conclusion(tuple(question_reports)),
            limitations=LIMITATIONS,
        )
        logger.info(
            "Document pipeline diagnostic completed: institution_id=%s document_id=%s "
            "selected_version_id=%s effective_version_id=%s questions=%d chunks=%d",
            institution.id,
            selection.document.id,
            selected.id,
            effective.id if effective else None,
            len(questions),
            integrity.total_chunks,
        )
        return report
    finally:
        # Fecha a transação read-only sem nunca confirmar nada.
        db.rollback()


# ---------------------------------------------------------------------------
# Renderização (a partir do mesmo objeto, sem repetir o retrieval)
# ---------------------------------------------------------------------------


def _to_jsonable(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return {item.name: _to_jsonable(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, frozenset):
        return sorted(str(item) for item in value)
    if isinstance(value, list | tuple):
        return [_to_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _to_jsonable(item) for key, item in value.items()}
    return value


def render_json(report: DiagnosticReport) -> str:
    payload = _to_jsonable(report)
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def _md_escape(value: str) -> str:
    # Manter os valores fornecidos pelo utilizador/documento numa única linha
    # Markdown e impedir que se tornem títulos, HTML ou delimitadores de tabela/código.
    sanitized = sanitize_excerpt(value)
    return (
        sanitized.replace("\\", "\\\\")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("|", "\\|")
        .replace("`", "\\`")
        .replace("*", "\\*")
        .replace("_", "\\_")
        .replace("#", "\\#")
    )


def _md_bool(value: bool | None) -> str:
    if value is None:
        return "—"
    return "sim" if value else "não"


def _add_lexical_trace(
    add: Callable[[str], None], trace: LexicalTraceReport
) -> None:
    """Renderiza o trace lexical: apenas metadados e componentes do score.

    Nunca a pergunta, os seus termos, o conteúdo dos chunks, títulos
    fornecidos, secções, URLs ou segredos — só a config FTS, a **contagem**
    de termos informativos, os marcadores estruturais (ordinais/intervalos),
    as contagens do orçamento e os sinais do ranking.
    """
    add("")
    add("#### Trace do retrieval lexical")
    add("")
    add(f"- Configuração FTS: {trace.fts_config}")
    add(f"- Termos informativos: {trace.informative_term_count}")
    add(f"- Ordinais reconhecidos: {list(trace.query_ordinals) or 'nenhum'}")
    add(f"- Intervalos reconhecidos: {list(trace.query_ranges) or 'nenhum'}")
    add(f"- Variantes planeadas: {list(trace.planned_variants) or 'nenhuma'}")
    add(f"- Limite global de candidatos: {trace.global_candidate_limit}")
    for variant in trace.variants:
        add(
            f"  - {variant.strategy}: quota={variant.quota} "
            f"devolvidos={variant.returned_count}"
        )
    add(f"- Total devolvido antes da deduplicação: {trace.total_returned_before_dedup}")
    add(f"- Únicos após deduplicação: {trace.unique_after_dedup}")
    add(f"- Candidatos avaliados: {trace.candidates_evaluated}")
    add(f"- Removidos por ausência de correspondência: {trace.excluded_no_content_match}")
    add(f"- Removidos por cobertura insuficiente: {trace.excluded_insufficient_coverage}")
    add(f"- Removidos pelo limiar: {trace.excluded_below_threshold}")
    add(f"- Resultados finais: {trace.final_result_count}")
    for result in trace.results:
        add(
            f"- chunk_id={result.chunk_id} estratégia={result.strategy} "
            f"raw_fts={result.raw_score:.6f} score={result.score:.6f} "
            f"cobertura={result.coverage:.2f} frase_exata={result.exact_phrase:.0f} "
            f"ordem={result.ordered:.2f} proximidade={result.proximity:.2f} "
            f"titulo={result.title_overlap:.2f} seccao={result.section_overlap:.2f} "
            f"tipo={result.structure_type or '—'}"
        )
        add(
            f"  - termos correspondidos: {result.matched_term_count}; "
            f"razão: {result.reason}"
        )
    if trace.excluded:
        add("- Excluídos:")
        for excluded in trace.excluded:
            score = "—" if excluded.score is None else f"{excluded.score:.6f}"
            add(
                f"  - chunk_id={excluded.chunk_id} motivo={excluded.reason} "
                f"estratégia={excluded.strategy} score={score} "
                f"cobertura={excluded.coverage:.2f} "
                f"termos correspondidos={excluded.matched_term_count}"
            )


def render_markdown(report: DiagnosticReport) -> str:
    lines: list[str] = []
    add = lines.append
    add("# Diagnóstico do pipeline documental")
    add("")
    add("## Aviso de confidencialidade")
    add("")
    add(
        "Este relatório contém excertos de documentos institucionais e "
        "identificadores técnicos reais. Não deve ser publicado, partilhado "
        "ou enviado para repositórios sem revisão humana prévia."
    )
    add("")
    add("## Execução")
    add("")
    execution = report.execution
    add(f"- Data e hora (UTC): {execution.executed_at_utc}")
    add(f"- reference_date: {execution.reference_date.isoformat()}")
    add(f"- Formato: {execution.report_format}")
    add(f"- top_k: {execution.top_k}")
    add(f"- official_only: {_md_bool(execution.official_only)}")
    add(f"- max_excerpt_chars: {execution.max_excerpt_chars}")
    add(f"- Versão do formato do relatório: {execution.diagnostic_report_version}")
    if execution.base_sha:
        add(f"- BASE_SHA: {execution.base_sha}")
    add("")
    add("## Identificação institucional")
    add("")
    add(f"- institution_id: {report.institution.institution_id}")
    add(f"- Nome: {_md_escape(report.institution.name)}")
    add("")
    add("## Documento")
    add("")
    document = report.document
    add(f"- document_id: {document.document_id}")
    add(f"- Título: {_md_escape(document.title)}")
    add(f"- Idioma: {document.language}")
    add(f"- is_active: {_md_bool(document.is_active)}")
    add(f"- official_source: {_md_bool(document.official_source)}")
    add(f"- valid_from: {document.valid_from.isoformat() if document.valid_from else '—'}")
    add(f"- valid_until: {document.valid_until.isoformat() if document.valid_until else '—'}")
    add("")
    add("## Versão selecionada")
    add("")
    selected = report.selected_version
    add(f"- version_id: {selected.version_id}")
    add(f"- version_number: {selected.version_number}")
    add(f"- original_filename: {_md_escape(selected.original_filename)}")
    add(f"- mime_type: {selected.mime_type}")
    add(f"- size_bytes: {selected.size_bytes}")
    add(f"- checksum_sha256 (truncado): {selected.checksum_sha256_prefix}…")
    add(f"- processing_status: {selected.processing_status}")
    if selected.processing_error:
        add(f"- processing_error: {_md_escape(selected.processing_error)}")
    add(f"- page_count: {selected.page_count if selected.page_count is not None else '—'}")
    add(f"- Total de caracteres extraídos: {selected.extracted_text_length}")
    add(f"- Processado em: {selected.processed_at or '—'}")
    add(f"- extraction_method: {selected.extraction_method or '—'}")
    add(f"- extraction_quality: {selected.extraction_quality or '—'}")
    if selected.extraction_warning:
        add(f"- extraction_warning: {_md_escape(selected.extraction_warning)}")
    if selected.native_page_count is not None:
        add(f"- Páginas extraídas nativamente: {selected.native_page_count}")
        add(f"- Páginas extraídas por OCR: {selected.ocr_page_count}")
        add(f"- Páginas com qualidade baixa: {selected.low_quality_page_count}")
    if selected.page_summaries:
        add("")
        add("| Página | Método | Caracteres | Confiança OCR | Qualidade | Aviso |")
        add("| --- | --- | --- | --- | --- | --- |")
        for page_row in selected.page_summaries:
            row_confidence = (
                f"{page_row.ocr_confidence:.1f}"
                if page_row.ocr_confidence is not None
                else "—"
            )
            row_characters = (
                page_row.extracted_characters
                if page_row.extracted_characters is not None
                else "—"
            )
            add(
                f"| {page_row.page_number if page_row.page_number is not None else '—'} "
                f"| {page_row.method or '—'} "
                f"| {row_characters} "
                f"| {row_confidence} "
                f"| {page_row.quality or '—'} "
                f"| {_md_escape(page_row.warning) if page_row.warning else '—'} |"
            )
    add("")
    add("## Versão efetiva do retrieval")
    add("")
    effective = report.effective_retrieval_version
    add(f"- version_id: {effective.version_id or '—'}")
    add(
        "- version_number: "
        f"{effective.version_number if effective.version_number is not None else '—'}"
    )
    add(f"- processing_status: {effective.processing_status or '—'}")
    add(f"- Difere da versão selecionada: {_md_bool(effective.differs_from_selected)}")
    add(f"- Motivo: {_md_escape(effective.reason)}")
    add("")
    add("## Configuração relevante")
    add("")
    configuration = report.configuration
    add(f"- chunk_size (caracteres): {configuration.chunk_size_chars}")
    add(f"- overlap (caracteres): {configuration.chunk_overlap_chars}")
    add(f"- top_k: {configuration.top_k}")
    add(f"- reference_date: {configuration.reference_date.isoformat()}")
    add("")
    add("## Integridade dos chunks")
    add("")
    integrity = report.chunk_integrity
    add(f"- Total: {integrity.total_chunks}")
    add(f"- Tamanho mínimo: {integrity.min_size if integrity.min_size is not None else '—'}")
    add(f"- Tamanho máximo: {integrity.max_size if integrity.max_size is not None else '—'}")
    add(f"- Tamanho médio: {integrity.mean_size if integrity.mean_size is not None else '—'}")
    add(f"- Índices duplicados: {list(integrity.duplicate_indexes) or 'nenhum'}")
    add(f"- Índices fora de ordem: {_md_bool(integrity.out_of_order_indexes)}")
    add(f"- Gaps entre chunks: {integrity.gap_count}")
    add(f"- Sobreposições (não são erro): {integrity.overlap_count}")
    add(
        "- Chunks por página: "
        f"{dict(integrity.chunks_by_page) if integrity.chunks_by_page else 'nenhum'}"
    )
    add(
        "- Chunks por tipo: "
        f"{dict(integrity.chunks_by_type) if integrity.chunks_by_type else 'nenhum'}"
    )
    add(f"- table_rows: {integrity.table_row_count}")
    add(f"- fallback fragments: {integrity.fallback_fragment_count}")
    add(f"- Chunks que atravessam página: {integrity.cross_page_chunk_count}")
    add(f"- table_rows divididas: {integrity.split_table_row_count}")
    if integrity.issues:
        add(f"- Problemas de integridade ({len(integrity.issues)}):")
        for issue in integrity.issues:
            add(f"  - chunk_index={issue.chunk_index} chunk_id={issue.chunk_id}: {issue.issue}")
    else:
        add("- Problemas de integridade: nenhum")
    add("")
    add("## Resultados por pergunta")
    for question in report.questions:
        add("")
        add(f"### Pergunta — {_md_escape(question.question_id)}")
        add("")
        add(f"{_md_escape(question.question)}")
        add("")
        add("#### Resposta esperada")
        add("")
        add(f"{_md_escape(question.expected_answer)}")
        add("")
        add("#### Extração")
        add("")
        for presence in question.extraction:
            if not presence.found:
                add(f"- **{_md_escape(presence.fact_name)}**: não encontrado no texto extraído.")
                continue
            add(
                f"- **{_md_escape(presence.fact_name)}**: encontrado "
                f"({presence.occurrence_count} ocorrência(s)); alternativa: "
                f"“{_md_escape(presence.matched_alternative or '')}”."
            )
            for occurrence in presence.occurrences:
                position = (
                    f"posição original ≈ [{occurrence.original_start}, {occurrence.original_end})"
                    if occurrence.original_start is not None
                    else "posição original indisponível (mapeamento aproximado)"
                )
                page = (
                    f"; página ≈ {occurrence.approximate_page}"
                    if occurrence.approximate_page is not None
                    else ""
                )
                crosses = "; atravessa separador de página" if occurrence.crosses_page_break else ""
                add(f"  - {position}{page}{crosses}")
                if occurrence.excerpt:
                    add(f"    - excerto: `{_md_escape(occurrence.excerpt)}`")
        add("")
        add("#### Associação posicional")
        add("")
        if question.fact_pair_proximity:
            for pair in question.fact_pair_proximity:
                distance = (
                    f"{pair.min_distance_chars} caracteres"
                    if pair.min_distance_chars is not None
                    else "indisponível"
                )
                add(
                    f"- {_md_escape(pair.fact_a)} ↔ {_md_escape(pair.fact_b)}: "
                    f"distância mínima {distance}; mesma linha: {_md_bool(pair.same_line)}; "
                    f"linhas adjacentes: {_md_bool(pair.adjacent_lines)}; "
                    f"mesma página ≈: {_md_bool(pair.same_approximate_page)}; "
                    f"ordem: {' → '.join(pair.order) if pair.order else '—'}; "
                    f"ocorrências concorrentes próximas: {pair.competing_occurrences_nearby}"
                )
                if pair.combined_excerpt:
                    add(f"  - excerto combinado: `{_md_escape(pair.combined_excerpt)}`")
        else:
            add("- Sem pares de factos com posições comparáveis no texto extraído.")
        add("")
        add("#### Chunks")
        add("")
        analysis = question.chunk_analysis
        add(f"- all_facts_in_extracted_text: {_md_bool(analysis.all_facts_in_extracted_text)}")
        add(f"- all_facts_present_in_chunks: {_md_bool(analysis.all_facts_present_in_chunks)}")
        add(f"- all_facts_in_same_chunk: {_md_bool(analysis.all_facts_in_same_chunk)}")
        add(
            "- expected_facts_in_same_table_row: "
            f"{_md_bool(analysis.expected_facts_in_same_table_row)}"
        )
        add(f"- facts_split_across_chunks: {_md_bool(analysis.facts_split_across_chunks)}")
        add(f"- missing_from_chunks: {list(analysis.missing_from_chunks) or 'nenhum'}")
        add(
            "- matching_chunk_ids: "
            f"{[str(chunk_id) for chunk_id in analysis.matching_chunk_ids] or 'nenhum'}"
        )
        add(
            "- covering_chunk_sets: "
            + (
                "; ".join(
                    "{" + ", ".join(str(chunk_id) for chunk_id in cover) + "}"
                    for cover in analysis.covering_chunk_sets
                )
                or "nenhum"
            )
        )
        add(
            "- minimum_covering_chunk_count: "
            f"{
                analysis.minimum_covering_chunk_count
                if analysis.minimum_covering_chunk_count is not None
                else '—'
            }"
        )
        for view in analysis.relevant_chunks:
            add(
                f"- chunk_index={view.chunk_index} chunk_id={view.chunk_id} "
                f"[{view.start_char}, {view.end_char}) sha256={view.content_sha256[:12]}… "
                f"idioma={view.language} tamanho={view.content_length} "
                f"página={view.page_number if view.page_number is not None else '—'} "
                f"tipo={view.structure_type or '—'} "
                f"estratégia={view.chunking_strategy or '—'} "
                f"secção={_md_escape(view.section_title) if view.section_title else '—'} "
                f"factos={list(view.facts_found)}"
            )
            add(f"  - excerto: `{_md_escape(view.excerpt)}`")
        if analysis.fact_pair_proximity_by_chunk:
            add("- Proximidade dos factos dentro de chunks:")
            for pair in analysis.fact_pair_proximity_by_chunk:
                distance = (
                    f"{pair.min_distance_chars}" if pair.min_distance_chars is not None else "—"
                )
                add(
                    f"  - {_md_escape(pair.fact_a)} ↔ {_md_escape(pair.fact_b)}: "
                    f"distância {distance}; mesma linha: {_md_bool(pair.same_line)}"
                )
        add("")
        add("#### Elegibilidade")
        add("")
        # Qual pergunta está a ser respondida. Sem isto, "não elegível" podia
        # ser lido como um juízo sobre citações já persistidas, que nenhuma
        # política reavalia.
        add(
            f"- Política avaliada: {question.effective_version_eligibility.policy} "
            "(recuperabilidade atual)"
        )
        for label, eligibility in (
            ("Versão selecionada", question.selected_version_eligibility),
            ("Versão efetiva do retrieval", question.effective_version_eligibility),
        ):
            add(
                f"- {label}: "
                + ("elegível" if eligibility.eligible else "não elegível")
                + (
                    f" (version_number={eligibility.version_number}, "
                    f"status={eligibility.processing_status})"
                    if eligibility.version_id is not None
                    else " (inexistente)"
                )
            )
            for condition in eligibility.conditions:
                marker = "✓" if condition.satisfied else "✗"
                add(f"  - {marker} {condition.name}: {_md_escape(condition.detail)}")
        add("")
        add("#### Retrieval")
        add("")
        retrieval = question.retrieval
        add(f"- Query original: {_md_escape(retrieval.query)}")
        add(f"- Idioma: {retrieval.language}")
        add(f"- reference_date: {retrieval.reference_date.isoformat()}")
        add(f"- top_k: {retrieval.top_k}; official_only: {_md_bool(retrieval.official_only)}")
        add(f"- Número de resultados: {retrieval.result_count}")
        for result_view in retrieval.results:
            add(
                f"- #{result_view.rank} score={result_view.score:.6f} "
                f"documento=“{_md_escape(result_view.document_title)}” "
                f"document_id={result_view.document_id} "
                f"chunk_index={result_view.chunk_index} "
                f"chunk_id={result_view.chunk_id} idioma={result_view.language} "
                f"oficial={_md_bool(result_view.official_source)}"
            )
            add(
                "  - do documento analisado: "
                f"{_md_bool(result_view.belongs_to_target_document)}; "
                "da versão selecionada: "
                f"{_md_bool(result_view.belongs_to_selected_version)}; "
                "da versão efetiva: "
                f"{_md_bool(result_view.belongs_to_effective_retrieval_version)}; "
                f"matching_chunk: {_md_bool(result_view.is_matching_chunk)}"
            )
            add(
                "  - factos presentes: "
                f"{list(result_view.facts_found) or 'nenhum dos esperados'}; "
                "cobertura cumulativa: "
                f"{list(result_view.cumulative_fact_coverage) or 'nenhuma'}"
            )
            add(f"  - excerto: `{_md_escape(result_view.excerpt)}`")
        add(f"- target_document_retrieved: {_md_bool(retrieval.target_document_retrieved)}")
        add(f"- selected_version_retrieved: {_md_bool(retrieval.selected_version_retrieved)}")
        add(
            "- effective_retrieval_version_retrieved: "
            f"{_md_bool(retrieval.effective_retrieval_version_retrieved)}"
        )
        add(f"- matching_chunk_retrieved: {_md_bool(retrieval.matching_chunk_retrieved)}")
        add(f"- covering_chunk_set_retrieved: {_md_bool(retrieval.covering_chunk_set_retrieved)}")
        add(
            "- expected_fact_coverage_across_results: "
            f"{list(retrieval.expected_fact_coverage_across_results) or 'nenhuma'}"
        )
        add(
            "- all_expected_facts_covered_across_results: "
            f"{_md_bool(retrieval.all_expected_facts_covered_across_results)}"
        )
        add(
            "- irrelevant_for_expected_facts_count: "
            f"{retrieval.irrelevant_for_expected_facts_count} "
            "(sem factos esperados para este caso; não significa irrelevância geral)"
        )
        add(
            "- eligible_evidence_exists_but_was_not_retrieved: "
            f"{_md_bool(retrieval.eligible_evidence_exists_but_was_not_retrieved)}"
        )
        add(
            "- correct_target_evidence_exists_but_other_document_was_used: "
            f"{_md_bool(retrieval.correct_target_evidence_exists_but_other_document_was_used)}"
        )
        if question.lexical_trace is not None:
            _add_lexical_trace(add, question.lexical_trace)
        add("")
        add("#### Conclusão principal")
        add("")
        add(f"`{question.primary_conclusion.value}`")
        add("")
        add("#### Findings")
        add("")
        if question.findings:
            for finding in question.findings:
                add(f"- `{finding.value}`")
        else:
            add("- nenhum")
        add("")
        add("#### Evidência resumida")
        add("")
        for line in question.evidence_summary:
            add(f"- {_md_escape(line)}")
    add("")
    add("## Resumo global")
    add("")
    add("| Pergunta | Extração | Chunks íntegros | Cobertura no retrieval | Conclusão | Findings |")
    add("| --- | --- | --- | --- | --- | --- |")
    for question in report.questions:
        analysis = question.chunk_analysis
        chunks_ok = not analysis.missing_from_chunks and not (
            report.chunk_integrity.compromised_chunk_ids
            & {view.chunk_id for view in analysis.relevant_chunks}
        )
        findings_cell = (
            ", ".join(finding.value for finding in question.findings) if question.findings else "—"
        )
        add(
            f"| {_md_escape(question.question_id)} "
            f"| {_md_bool(analysis.all_facts_in_extracted_text)} "
            f"| {_md_bool(chunks_ok)} "
            f"| {_md_bool(question.retrieval.all_expected_facts_covered_across_results)} "
            f"| {question.primary_conclusion.value} "
            f"| {findings_cell} |"
        )
    add("")
    add("## Conclusão global")
    add("")
    add(report.global_conclusion.message)
    add("")
    for question_id, conclusion in report.global_conclusion.conclusions_by_question:
        add(f"- {_md_escape(question_id)}: `{conclusion}`")
    add("")
    add("## Limitações")
    add("")
    for limitation in report.limitations:
        add(f"- {limitation}")
    add("")
    return "\n".join(lines)
