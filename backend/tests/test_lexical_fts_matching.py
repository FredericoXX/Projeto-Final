"""Correspondência morfológica confirmada pelo FTS na elegibilidade lexical.

O PostgreSQL recupera um segmento porque o *stemmer* português reduz
``notas`` e ``nota`` ao mesmo lexema. A cobertura, porém, era calculada
apenas por igualdade de formas canónicas — ``notas`` não é ``nota`` — pelo
que o candidato recuperado por ``reduced_or`` era eliminado por
``INSUFFICIENT_COVERAGE`` **antes** de o limiar de relevância chegar a ser
aplicado. A decisão de elegibilidade contradizia a recuperação que a
tinha produzido.

Estes testes fixam as duas metades da correção:

- as correspondências morfológicas **entram** em ``matched_terms`` e em
  ``coverage``, porque foram confirmadas pelo mesmo ``search_vector`` e pela
  mesma configuração FTS que recuperaram o candidato;
- não entram em ``exact_phrase``, ``ordered`` nem ``proximity``, que
  descrevem a disposição **literal** dos termos no conteúdo e que uma
  correspondência por radical não observa.

Os limiares não são tocados: ``MIN_MATCHED_TERMS``, ``MIN_COVERAGE_RATIO`` e
``retrieval_min_relevance_score`` valem aqui exatamente o que valem em
produção, e vários testes existem precisamente para o confirmar.
"""

import uuid
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, Text, event
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.core.text_normalization import normalize_text
from app.evaluation.candidate_budget import merge_candidate
from app.evaluation.lexical_variants import (
    identity_projection,
    variant_content_match,
)
from app.retrieval.base import RetrievalContext, RetrievalQuery
from app.retrieval.eligibility import (
    MIN_COVERAGE_RATIO,
    MIN_MATCHED_TERMS,
    ContentMatch,
    EligibilityBasis,
    ExclusionReason,
    decide_eligibility,
)
from app.retrieval.fts_config import resolve_fts_config
from app.retrieval.lexical import (
    LEXICAL_PIPELINE_VERSION,
    LexicalRetrievalTrace,
    PostgresLexicalRetriever,
)
from app.retrieval.lexical_normalization import (
    accent_map_for_query,
    build_lexical_representation,
)
from app.retrieval.query_planning import LexicalQueryStrategy, plan_lexical_query
from app.retrieval.reranking import (
    LexicalCandidate,
    compute_content_match,
    fts_probe_terms,
    informative_query_terms,
    rerank,
)
from tests.test_retrieval import _create_searchable, _search, _setup

# A pergunta do caso real, e o conteúdo que o PostgreSQL recupera para ela.
GRADE_QUESTION = "As notas vão de zero a quanto?"
GRADE_CONTENT = (
    "A avaliação de cada unidade curricular traduz-se numa nota final. "
    "A nota final é expressa numa escala numérica de (0) zero a 20 (vinte) "
    "valores, arredondada às unidades."
)

_MIN = 0.05


def _terms(query: str) -> tuple[str, ...]:
    return informative_query_terms(normalize_text(query), "pt")


def _candidate(
    content: str,
    *,
    fts_matched_terms: frozenset[str] = frozenset(),
    content_fts_matched_terms: frozenset[str] = frozenset(),
    title: str = "Regulamento Geral Provisório",
    section: str | None = None,
    strategy: LexicalQueryStrategy = LexicalQueryStrategy.REDUCED_OR,
    raw: float = 0.05,
) -> LexicalCandidate:
    return LexicalCandidate(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        document_version_id=uuid.uuid4(),
        document_title=title,
        chunk_index=0,
        content=content,
        normalized_content=normalize_text(content),
        language="pt",
        official_source=True,
        source_url=None,
        valid_from=None,
        valid_until=None,
        page_number=None,
        section_title=section,
        structure_type=None,
        chunking_strategy=None,
        raw_score=raw,
        strategy=strategy,
        # O parâmetro homónimo alimenta a origem indexada, que é a via por
        # omissão; a acentuada tem parâmetro próprio para que um teste possa
        # dizer exatamente por onde a correspondência entrou.
        indexed_fts_matched_terms=fts_matched_terms,
        content_fts_matched_terms=content_fts_matched_terms,
    )


def _decide(query: str, candidate: LexicalCandidate):
    terms = _terms(query)
    return decide_eligibility(terms, compute_content_match(terms, candidate), candidate.strategy)


# --- A falha reproduzida ------------------------------------------------------


def test_without_the_fts_evidence_the_candidate_is_excluded_by_coverage() -> None:
    """A falha original, preservada como referência.

    Um candidato que não transporta as correspondências morfológicas é
    avaliado apenas por igualdade de formas: de ``notas``, ``vao``, ``zero``
    e ``quanto`` só ``zero`` aparece literalmente, e 1/4 fica abaixo de
    ``MIN_COVERAGE_RATIO``. O que a correção altera não é a regra — é a
    prova que a regra recebe.
    """
    candidate = _candidate(GRADE_CONTENT)
    match = compute_content_match(_terms(GRADE_QUESTION), candidate)

    assert match.matched_terms == frozenset({"zero"})
    assert match.coverage == pytest.approx(0.25)

    decision = _decide(GRADE_QUESTION, candidate)
    assert not decision.eligible
    assert decision.reason is ExclusionReason.INSUFFICIENT_COVERAGE


def test_the_fts_evidence_makes_the_same_candidate_eligible() -> None:
    """``notas`` ⇄ ``nota``: a mesma regra, agora com a prova que faltava."""
    candidate = _candidate(GRADE_CONTENT, fts_matched_terms=frozenset({"notas"}))
    match = compute_content_match(_terms(GRADE_QUESTION), candidate)

    assert match.matched_terms == frozenset({"notas", "zero"})
    assert match.fts_matched_terms == frozenset({"notas"})
    assert match.coverage == pytest.approx(0.5)
    assert len(match.matched_terms) >= MIN_MATCHED_TERMS
    assert match.coverage >= MIN_COVERAGE_RATIO

    decision = _decide(GRADE_QUESTION, candidate)
    assert decision.eligible
    assert decision.basis is EligibilityBasis.COVERAGE


# --- O que a correspondência morfológica não pode fazer -----------------------


def test_morphological_matches_never_inflate_phrase_order_or_proximity() -> None:
    """Os sinais posicionais descrevem o texto literal, e não o radical.

    ``exact_phrase``, ``ordered``, ``proximity`` e ``compactness`` são
    calculados sobre o *stream* canónico do conteúdo, onde ``notas`` não
    ocorre. Se a correspondência morfológica lhes tocasse, um candidato
    ganharia por dois mecanismos com uma só prova.
    """
    terms = _terms(GRADE_QUESTION)
    without = compute_content_match(terms, _candidate(GRADE_CONTENT))
    with_fts = compute_content_match(
        terms, _candidate(GRADE_CONTENT, fts_matched_terms=frozenset({"notas"}))
    )

    assert with_fts.exact_phrase == without.exact_phrase
    assert with_fts.ordered == without.ordered
    assert with_fts.proximity == pytest.approx(without.proximity)
    assert with_fts.compactness == pytest.approx(without.compactness)
    # E a cobertura, essa, tem de ter mudado — senão o teste era vazio.
    assert with_fts.coverage > without.coverage


def test_a_single_morphological_match_is_never_enough_evidence() -> None:
    """``MIN_MATCHED_TERMS`` continua a valer 2 numa consulta multi-termo."""
    candidate = _candidate(
        "O presente regulamento entra em vigor na data da sua publicação.",
        fts_matched_terms=frozenset({"notas"}),
    )
    match = compute_content_match(_terms(GRADE_QUESTION), candidate)

    assert match.matched_terms == frozenset({"notas"})
    assert len(match.matched_terms) < MIN_MATCHED_TERMS

    decision = _decide(GRADE_QUESTION, candidate)
    assert not decision.eligible
    assert decision.reason is ExclusionReason.INSUFFICIENT_COVERAGE


def test_title_and_section_matches_do_not_reach_the_fts_evidence() -> None:
    """A sonda lê o ``search_vector``, que é construído só do conteúdo.

    O título e a secção não têm vetor próprio, pelo que nunca podem aparecer
    em ``fts_matched_terms``. A garantia histórica — título ou secção nunca
    criam evidência — permanece, agora também do lado morfológico.
    """
    candidate = _candidate(
        "O presente regulamento entra em vigor na data da sua publicação.",
        title="Escala de notas e classificações",
        section="Das notas e da escala",
    )
    match = compute_content_match(_terms(GRADE_QUESTION), candidate)

    assert match.matched_terms == frozenset()
    assert match.fts_matched_terms == frozenset()

    decision = _decide(GRADE_QUESTION, candidate)
    assert not decision.eligible
    assert decision.reason is ExclusionReason.NO_CONTENT_MATCH


def test_fts_terms_outside_the_question_never_change_the_coverage() -> None:
    """A cobertura é uma fração dos termos **desta** pergunta.

    Um termo transportado que não pertença à pergunta corrente não conta,
    nem no numerador nem no denominador.
    """
    terms = _terms(GRADE_QUESTION)
    intruder = _candidate(GRADE_CONTENT, fts_matched_terms=frozenset({"matriculas"}))

    match = compute_content_match(terms, intruder)
    assert match.matched_terms == frozenset({"zero"})
    assert match.fts_matched_terms == frozenset()
    assert match.coverage == pytest.approx(0.25)


def test_surface_matches_are_never_reported_as_morphological() -> None:
    """``fts_matched_terms`` regista o que **só** o radical explica.

    A partição é disjunta por construção: ``matched_terms`` menos
    ``fts_matched_terms`` recupera exatamente as correspondências de
    superfície, e é isso que torna o trace auditável.
    """
    terms = _terms(GRADE_QUESTION)
    candidate = _candidate(GRADE_CONTENT, fts_matched_terms=frozenset({"notas", "zero"}))

    match = compute_content_match(terms, candidate)
    assert match.fts_matched_terms == frozenset({"notas"})
    assert match.matched_terms - match.fts_matched_terms == frozenset({"zero"})


# --- Ordinais e intervalos canónicos ------------------------------------------


def test_canonical_markers_are_never_sent_to_the_fts_probe() -> None:
    """``ord:1`` e ``rng:1-12`` não são palavras: sondá-los seria expandi-los.

    ``websearch_to_tsquery('portuguese', 'ord:1')`` devolve ``'ord' & '1'``,
    e ``'rng:1-12'`` devolve ``'rng' & '1' <-> '-12'``. Qualquer um deles
    faria um ordinal corresponder a um cardinal solto — exatamente a
    expansão que o planeamento existe para impedir.
    """
    terms = informative_query_terms(normalize_text("Exames da primeira chamada de 01a12"), "pt")
    assert any(term.startswith("ord:") for term in terms)
    assert any(term.startswith("rng:") for term in terms)

    probe = fts_probe_terms(terms)
    assert all(not term.startswith(("ord:", "rng:")) for term in probe)
    assert set(probe) < set(terms)


def test_a_transported_marker_can_never_satisfy_the_canonical_relaxation() -> None:
    """O marcador canónico continua a exigir correspondência canónica real.

    A sonda nunca produz marcadores, mas a recusa está **também** em
    ``compute_content_match``: uma regra que dependa de o chamador ter
    filtrado bem perde-se em silêncio no dia em que outro chamador apareça.
    Aqui o marcador é injetado à força, e continua a não contar.

    A pergunta tem dois termos e o conteúdo é o da 2.ª chamada: sem o
    marcador, resta uma correspondência, abaixo de ``MIN_MATCHED_TERMS``.
    Se o ``ord:1`` transportado contasse, a cobertura passaria a 1.0 e a
    linha errada tornar-se-ia evidência.
    """
    terms = _terms("Exames da primeira")
    assert terms == ("exames", "ord:1")

    candidate = _candidate(
        "Os exames da segunda chamada decorrem em fevereiro.",
        strategy=LexicalQueryStrategy.CANONICAL_RELAXED_AND,
        fts_matched_terms=frozenset({"ord:1", "exames"}),
    )

    match = compute_content_match(terms, candidate)
    assert "ord:1" not in match.matched_terms
    assert match.fts_matched_terms == frozenset()
    assert match.coverage == pytest.approx(0.5)

    decision = decide_eligibility(terms, match, candidate.strategy)
    assert not decision.eligible
    assert decision.reason is ExclusionReason.INSUFFICIENT_COVERAGE


# --- Agregação entre variantes ------------------------------------------------


def test_merging_variants_unions_the_morphological_matches() -> None:
    """Duas variantes provam coisas diferentes; a união preserva as duas.

    A deduplicação por ``chunk_id`` guarda um só candidato. Se guardasse as
    correspondências de apenas uma das variantes, a cobertura passaria a
    depender da ordem de execução do plano.
    """
    retriever = PostgresLexicalRetriever()
    chunk_id = uuid.uuid4()
    candidates: dict[Any, LexicalCandidate] = {}

    first = _RowStub(chunk_id, score=0.02, fts_matched_terms=["notas"])
    second = _RowStub(chunk_id, score=0.09, fts_matched_terms=["zero"])

    retriever._merge_candidate(candidates, first, LexicalQueryStrategy.REDUCED_OR)
    retriever._merge_candidate(candidates, second, LexicalQueryStrategy.REDUCED_AND)

    merged = candidates[chunk_id]
    assert merged.indexed_fts_matched_terms == frozenset({"notas", "zero"})
    assert merged.fts_matched_terms == frozenset({"notas", "zero"})
    # As regras que já existiam continuam: melhor estratégia, melhor FTS cru.
    assert merged.strategy is LexicalQueryStrategy.REDUCED_AND
    assert merged.raw_score == pytest.approx(0.09)


def test_the_evaluation_pool_merges_the_morphological_matches_the_same_way() -> None:
    """``candidate_budget.merge_candidate`` espelha ``_merge_candidate``.

    O módulo de avaliação declara-se um espelho da deduplicação de produção.
    Se divergisse aqui, mediria um sistema diferente daquele que existe.
    """
    chunk_id = uuid.uuid4()
    base = replace(
        _candidate(GRADE_CONTENT, fts_matched_terms=frozenset({"notas"})),
        chunk_id=chunk_id,
        strategy=LexicalQueryStrategy.REDUCED_OR,
    )
    other = replace(
        base,
        indexed_fts_matched_terms=frozenset({"zero"}),
        strategy=LexicalQueryStrategy.REDUCED_AND,
        raw_score=0.09,
    )

    pool: dict[object, LexicalCandidate] = {}
    merge_candidate(pool, base)
    merge_candidate(pool, other)

    merged = pool[chunk_id]
    assert merged.fts_matched_terms == frozenset({"notas", "zero"})
    assert merged.strategy is LexicalQueryStrategy.REDUCED_AND
    assert merged.raw_score == pytest.approx(0.09)


def test_merging_is_independent_of_the_variant_order() -> None:
    forward: dict[object, LexicalCandidate] = {}
    backward: dict[object, LexicalCandidate] = {}
    chunk_id = uuid.uuid4()
    first = replace(
        _candidate(GRADE_CONTENT, fts_matched_terms=frozenset({"notas"})),
        chunk_id=chunk_id,
    )
    second = replace(first, indexed_fts_matched_terms=frozenset({"zero"}), raw_score=0.09)

    merge_candidate(forward, first)
    merge_candidate(forward, second)
    merge_candidate(backward, second)
    merge_candidate(backward, first)

    assert forward[chunk_id].fts_matched_terms == backward[chunk_id].fts_matched_terms


class _RowStub:
    """Linha mínima com a forma que ``_row_to_candidate`` consome."""

    def __init__(
        self,
        chunk_id: uuid.UUID,
        *,
        score: float,
        fts_matched_terms: list[str],
        content_fts_matched_terms: list[str] | None = None,
    ) -> None:
        self.chunk_id = chunk_id
        self.document_id = uuid.uuid4()
        self.document_version_id = uuid.uuid4()
        self.document_title = "Regulamento Geral Provisório"
        self.chunk_index = 0
        self.content = GRADE_CONTENT
        self.normalized_content = normalize_text(GRADE_CONTENT)
        self.language = "pt"
        self.official_source = True
        self.source_url = None
        self.valid_from = None
        self.valid_until = None
        self.page_number = None
        self.section_title = None
        self.structure_type = None
        self.chunking_strategy = None
        self.score = score
        self.indexed_fts_matched_terms = fts_matched_terms
        self.content_fts_matched_terms = content_fts_matched_terms or []


# --- O limiar e a ordem das fases continuam intactos --------------------------


def test_the_relevance_threshold_still_applies_after_eligibility() -> None:
    """A elegibilidade deixa passar; o limiar continua a ser aplicado a todos.

    Com um limiar irrealista, o mesmo candidato elegível sai por
    ``BELOW_THRESHOLD`` — o motivo tipado que distingue "não é evidência" de
    "é evidência fraca de mais".
    """
    candidate = _candidate(GRADE_CONTENT, fts_matched_terms=frozenset({"notas"}))

    kept = rerank(normalize_text(GRADE_QUESTION), [candidate], "pt", min_relevance_score=_MIN)
    assert len(kept.ranked) == 1

    rejected = rerank(normalize_text(GRADE_QUESTION), [candidate], "pt", min_relevance_score=0.99)
    assert rejected.ranked == ()
    assert rejected.excluded_count(ExclusionReason.BELOW_THRESHOLD) == 1


def test_the_production_thresholds_are_the_ones_used_here() -> None:
    """Nenhum limiar foi baixado para fazer o caso passar."""
    assert MIN_MATCHED_TERMS == 2
    assert MIN_COVERAGE_RATIO == 0.5
    assert settings.retrieval_min_relevance_score == pytest.approx(0.05)


# --- O que o PostgreSQL realmente diz -----------------------------------------


def _context(institution_id: str) -> RetrievalContext:
    return RetrievalContext(
        institution_id=uuid.UUID(institution_id),
        language="pt",
        reference_date=datetime.now(UTC).date(),
    )


def test_the_probe_reports_the_morphological_match_of_the_real_stemmer(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> None:
    """A sonda é avaliada pelo PostgreSQL, na consulta de recuperação.

    Não há segunda ida à base de dados nem *stemmer* reimplementado em
    Python: a coluna vem da mesma consulta que traz o candidato, contra o
    mesmo ``search_vector`` e a mesma configuração FTS.
    """
    institution, headers, _ = _setup(client)
    _create_searchable(client, headers, GRADE_CONTENT, title="Regulamento Geral Provisório")

    context = _context(institution["id"])
    terms = _terms(GRADE_QUESTION)
    statement = PostgresLexicalRetriever()._build_statement(
        _probe_query(terms),
        context,
        20,
        True,
        fts_probe_terms=fts_probe_terms(terms),
    )

    with test_session_factory() as db:
        rows = list(db.execute(statement))

    assert rows, "o chunk tem de ser recuperado pelo índice"
    matched = frozenset(rows[0].indexed_fts_matched_terms)
    # "notas" casa "nota" por radical; "zero" casa literalmente e também por
    # radical; "vao" e "quanto" não casam de forma nenhuma.
    assert "notas" in matched
    assert "vao" not in matched
    assert "quanto" not in matched


def _probe_query(terms: tuple[str, ...]):
    from sqlalchemy import func

    return func.websearch_to_tsquery(resolve_fts_config("pt").value, " OR ".join(terms))


def test_the_grade_scale_question_keeps_the_chunk_as_evidence(
    client: TestClient,
) -> None:
    """O caso real, ponta a ponta, pelo endpoint público."""
    _, headers, _ = _setup(client)
    _create_searchable(client, headers, GRADE_CONTENT, title="Regulamento Geral Provisório")
    _create_searchable(
        client,
        headers,
        "As propinas são pagas em dez prestações mensais durante o ano letivo.",
        title="Regulamento de Propinas",
    )

    items = _search(client, headers, GRADE_QUESTION).json()["items"]

    assert items, "a evidência correta deve ser recuperada e mantida"
    assert "escala numérica de (0) zero a 20 (vinte) valores" in items[0]["content"]
    assert items[0]["score"] >= settings.retrieval_min_relevance_score


def test_the_retrieved_chunk_is_admitted_by_coverage_and_traced_as_such(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> None:
    """O trace tem de mostrar **porquê**, não só que passou."""
    institution, headers, _ = _setup(client)
    _create_searchable(client, headers, GRADE_CONTENT, title="Regulamento Geral Provisório")

    with test_session_factory() as db:
        result = PostgresLexicalRetriever().search(
            db, RetrievalQuery.from_text(GRADE_QUESTION), _context(institution["id"]), 5, True
        )

    assert isinstance(result.trace, LexicalRetrievalTrace)
    assert result.trace.excluded_insufficient_coverage == 0
    assert result.trace.results, "o candidato tem de sobreviver à elegibilidade"

    row = result.trace.results[0]
    assert row.strategy == LexicalQueryStrategy.REDUCED_OR.value
    assert set(row.matched_terms) == {"notas", "zero"}
    assert set(row.indexed_fts_matched_terms) == {"notas"}
    assert set(row.content_fts_matched_terms) == set()
    assert row.coverage == pytest.approx(0.5)
    # A frase exata não foi simulada pela correspondência morfológica.
    assert row.exact_phrase == 0.0


def test_the_probe_costs_one_statement_per_variant_and_not_one_per_term(
    client: TestClient, test_engine: Engine, test_session_factory: sessionmaker[Session]
) -> None:
    """Sem N+1: o número de consultas depende do plano, não dos termos.

    A pergunta tem quatro termos informativos e o plano tem três variantes.
    Se a sonda fosse uma consulta por termo — ou por segmento —, a contagem
    cresceria com eles. Contam-se as consultas ao nível do *cursor*, que é
    onde uma ida extra à base de dados apareceria.
    """
    institution, headers, _ = _setup(client)
    _create_searchable(client, headers, GRADE_CONTENT, title="Regulamento Geral Provisório")

    normalized = normalize_text(GRADE_QUESTION)
    planned = len(plan_lexical_query(normalized, "pt").variants)
    assert len(_terms(GRADE_QUESTION)) == 4
    assert planned == 3

    executed: list[str] = []

    def _record(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        executed.append(statement)

    with test_session_factory() as db:
        event.listen(test_engine, "before_cursor_execute", _record)
        try:
            PostgresLexicalRetriever().search(
                db, RetrievalQuery.from_text(GRADE_QUESTION), _context(institution["id"]), 5, True
            )
        finally:
            event.remove(test_engine, "before_cursor_execute", _record)

    selects = [sql for sql in executed if sql.lstrip().upper().startswith("SELECT")]
    assert len(selects) == planned
    # E a sonda viaja dentro dessas mesmas consultas.
    assert all("indexed_fts_matched_terms" in sql for sql in selects)


def test_queries_without_evidence_still_return_nothing(client: TestClient) -> None:
    """As consultas negativas não passaram a encontrar coincidências.

    O corpus fala de notas e de propinas; nenhum dos documentos diz o que
    estas perguntas procuram, e a correspondência morfológica não inventa a
    cobertura que falta.
    """
    _, headers, _ = _setup(client)
    _create_searchable(client, headers, GRADE_CONTENT, title="Regulamento Geral Provisório")
    _create_searchable(
        client,
        headers,
        "As propinas são pagas em dez prestações mensais durante o ano letivo.",
        title="Regulamento de Propinas",
    )

    for question in (
        "Onde fica a residência universitária de Assomada?",
        "Qual é o horário da piscina municipal?",
        "Quantos lugares tem o parque de estacionamento subterrâneo?",
    ):
        assert _search(client, headers, question).json()["items"] == [], question


CLASSIFICATION_CONTENT = (
    "A classificação final é atribuída pelo júri de avaliação, nos termos do presente regulamento."
)
CLASSIFICATION_QUESTION = "Como são atribuídas as classificações?"


def test_postgresql_reduces_the_accented_pair_to_the_same_lexeme(
    test_session_factory: sessionmaker[Session],
) -> None:
    """A premissa linguística da via acentuada, dita pelo PostgreSQL.

    Com diacríticos, ``classificações`` e ``classificação`` reduzem ambos a
    ``classific``. Sem eles, o *stemmer* produz ``classificaco`` e
    ``classificaca`` — a regra ``-ção`` não dispara sobre texto já
    desacentuado. É esta assimetria que a via acentuada resolve.
    """
    with test_session_factory() as db:
        row = db.execute(_accent_comparison()).one()

    assert row.accented_query_lexeme == row.accented_content_lexeme
    assert row.stripped_query_lexeme != row.stripped_content_lexeme
    assert row.accented_matches is True
    assert row.stripped_matches is False


def test_the_accented_question_retrieves_the_accented_chunk(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> None:
    """A consulta de recuperação devolve o segmento, pela via acentuada."""
    institution, headers, _ = _setup(client)
    _create_searchable(
        client, headers, CLASSIFICATION_CONTENT, title="Regulamento Geral Provisório"
    )

    query = RetrievalQuery.from_text(CLASSIFICATION_QUESTION)
    with test_session_factory() as db:
        result = PostgresLexicalRetriever().search(db, query, _context(institution["id"]), 5, True)

    assert result.evidence, "o chunk com «classificação» tem de ser recuperado"
    assert "classificação" in result.evidence[0].content


def test_the_endpoint_keeps_the_accented_chunk_as_evidence(client: TestClient) -> None:
    """Ponta a ponta: a pergunta acentuada mantém a evidência."""
    _, headers, _ = _setup(client)
    _create_searchable(
        client, headers, CLASSIFICATION_CONTENT, title="Regulamento Geral Provisório"
    )
    _create_searchable(
        client,
        headers,
        "As propinas são pagas em dez prestações mensais durante o ano letivo.",
        title="Regulamento de Propinas",
    )

    items = _search(client, headers, CLASSIFICATION_QUESTION).json()["items"]

    assert items, "a evidência tem de sobreviver à elegibilidade e ao limiar"
    assert "classificação" in items[0]["content"]
    assert items[0]["score"] >= settings.retrieval_min_relevance_score


def test_the_trace_names_the_origin_of_the_morphological_match(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> None:
    """O trace distingue as duas origens FTS, e não só a existência delas."""
    institution, headers, _ = _setup(client)
    _create_searchable(
        client, headers, CLASSIFICATION_CONTENT, title="Regulamento Geral Provisório"
    )

    query = RetrievalQuery.from_text(CLASSIFICATION_QUESTION)
    with test_session_factory() as db:
        result = PostgresLexicalRetriever().search(db, query, _context(institution["id"]), 5, True)

    assert isinstance(result.trace, LexicalRetrievalTrace)
    assert result.trace.results
    row = result.trace.results[0]

    # A correspondência veio do vetor calculado sobre o `content` acentuado,
    # e não do `search_vector` indexado, que é onde ela não existe.
    assert "classificacoes" in row.content_fts_matched_terms
    assert "classificacoes" not in row.indexed_fts_matched_terms
    assert "classificacoes" in row.matched_terms
    # E continua a não haver frase exata inventada.
    assert row.exact_phrase == 0.0


def test_the_unindexed_path_is_absent_when_no_diacritic_was_lost(
    client: TestClient, test_engine: Engine, test_session_factory: sessionmaker[Session]
) -> None:
    """Sem perda de diacríticos, o SQL é o de sempre: só o índice.

    A via acentuada é cara e existe para um caso concreto. Uma pergunta que
    não perca acentos nenhuns não pode pagá-la — e a prova é a ausência da
    expressão no SQL executado, não uma medição de tempo.
    """
    institution, headers, _ = _setup(client)
    _create_searchable(client, headers, GRADE_CONTENT, title="Regulamento Geral Provisório")

    executed: list[str] = []

    def _record(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        executed.append(statement)

    # "Quanto vale a nota maxima?" não tem um único diacrítico.
    query = RetrievalQuery.from_text("Quanto vale a nota maxima?")
    assert accent_map_for_query(query.original) == {}

    with test_session_factory() as db:
        event.listen(test_engine, "before_cursor_execute", _record)
        try:
            PostgresLexicalRetriever().search(db, query, _context(institution["id"]), 5, True)
        finally:
            event.remove(test_engine, "before_cursor_execute", _record)

    selects = [sql for sql in executed if sql.lstrip().upper().startswith("SELECT")]
    assert selects
    assert all("to_tsvector" not in sql for sql in selects)


def _accent_comparison():
    """Lexemas e correspondências, calculados pelo próprio PostgreSQL.

    ``to_tsvector`` exige ``regconfig`` no primeiro argumento; o nome é uma
    constante do código, nunca input, pelo que entra como parâmetro tipado.
    """
    from sqlalchemy import bindparam, cast, func, select
    from sqlalchemy.dialects.postgresql import REGCONFIG

    config = cast(bindparam("fts_config", "portuguese"), REGCONFIG)

    def _vector(text: str):
        return func.strip(func.to_tsvector(config, text))

    def _query_lexeme(term: str):
        return func.cast(func.websearch_to_tsquery(config, term), Text)

    def _matches(text: str, term: str):
        return func.to_tsvector(config, text).op("@@")(func.websearch_to_tsquery(config, term))

    return select(
        _query_lexeme("classificacoes").label("stripped_query_lexeme"),
        func.cast(_vector("classificacao"), Text).label("stripped_content_lexeme"),
        _query_lexeme("classificações").label("accented_query_lexeme"),
        func.cast(_vector("classificação"), Text).label("accented_content_lexeme"),
        _matches("a classificação final", "classificações").label("accented_matches"),
        _matches("a classificacao final", "classificacoes").label("stripped_matches"),
    )


def _text_search_indexes():
    """Índices de pesquisa textual existentes em ``document_chunks``.

    A perna da prova que fecha as alternativas: se existisse um índice sobre
    uma expressão acentuada, a recuperação seria possível sem varredura e
    esta asserção falharia — que é o comportamento desejado.
    """
    from sqlalchemy import select, text

    return (
        select(text("indexname"))
        .select_from(text("pg_indexes"))
        .where(
            text("tablename = 'document_chunks'"),
            text("indexdef LIKE '%USING gin%'"),
        )
    )


# --- Invariantes estruturais e consumidores offline ---------------------------


def test_the_morphological_parcel_is_always_part_of_the_whole() -> None:
    """``fts_matched_terms ⊆ matched_terms``, verificado na construção.

    É esta invariante que dá sentido a ``matched_terms - fts_matched_terms``
    como "correspondências literais" — a expressão de que a elegibilidade
    depende e que o trace publica. Um ``ContentMatch`` incoerente falha já,
    em vez de sobreviver como um conjunto sem significado.
    """
    with pytest.raises(ValueError, match="subconjunto de matched_terms"):
        ContentMatch(
            coverage=0.5,
            matched_terms=frozenset({"notas"}),
            exact_phrase=0.0,
            ordered=0.0,
            proximity=0.0,
            compactness=0.0,
            indexed_fts_matched_terms=frozenset({"zero"}),
        )


@pytest.mark.parametrize(
    "query",
    [
        GRADE_QUESTION,
        "Exames da primeira chamada",
        "Como funciona o regime de avaliação?",
        "matricula",
    ],
)
def test_every_produced_content_match_satisfies_the_invariant(query: str) -> None:
    """A invariante vale para o que a produção realmente constrói."""
    terms = _terms(query)
    for carried in (frozenset(), frozenset(terms), frozenset({"notas", "intruso"})):
        match = compute_content_match(terms, _candidate(GRADE_CONTENT, fts_matched_terms=carried))
        assert match.fts_matched_terms <= match.matched_terms


def test_the_offline_variant_never_inherits_a_stale_morphological_parcel() -> None:
    """A projeção substitui o modelo de correspondência, parcela incluída.

    ``variant_content_match`` recalcula ``matched_terms`` no espaço projetado.
    Herdar a parcela de produção intacta deixaria declarada como morfológica
    uma correspondência que a variante pode já não fazer — e podia violar a
    invariante, porque o conjunto novo não contém necessariamente o antigo.
    """
    terms = ("notas", "zero")
    candidate = _candidate(GRADE_CONTENT, fts_matched_terms=frozenset({"notas"}))
    base = compute_content_match(terms, candidate)
    assert base.fts_matched_terms == frozenset({"notas"})

    # Projeção identidade: "notas" deixa de corresponder (não está no conteúdo
    # em superfície), e a parcela tem de o acompanhar.
    variant = variant_content_match(
        base=base,
        query_terms=terms,
        representation=build_lexical_representation(candidate.normalized_content, "pt"),
        projection=identity_projection(),
    )

    assert "notas" not in variant.matched_terms
    assert "notas" not in variant.fts_matched_terms
    assert variant.fts_matched_terms <= variant.matched_terms


def test_the_frozen_experiment_declares_a_historical_pipeline() -> None:
    """A divergência das experiências congeladas é declarada, não presumida.

    O script de experiência reproduz a consulta do ``v1``, sem a sonda
    morfológica, para que os digests publicados continuem a reproduzir-se.
    O que não pode acontecer é essa diferença ficar por dizer: se alguém
    alinhar o script com produção, esta asserção obriga a subir a versão
    declarada no mesmo gesto.
    """
    from scripts.evaluate_retrieval_experiment import (
        REPRODUCED_LEXICAL_PIPELINE_VERSION,
        _row_to_candidate,
    )

    assert REPRODUCED_LEXICAL_PIPELINE_VERSION != LEXICAL_PIPELINE_VERSION

    row = _RowStub(uuid.uuid4(), score=0.05, fts_matched_terms=[])
    candidate = _row_to_candidate(row, LexicalQueryStrategy.REDUCED_OR)
    assert candidate.fts_matched_terms == frozenset()


def test_a_baseline_from_another_pipeline_is_refused(tmp_path) -> None:
    """A declaração histórica é verificada, e não apenas escrita.

    Um baseline produzido por outra versão da pipeline descreve outro conjunto
    de candidatos. Comparar a experiência com ele atribuiria ao fator em
    estudo uma diferença que vem da pipeline — por isso falha alto e cedo, em
    vez de publicar um número sem significado.
    """
    from scripts.evaluate_retrieval_experiment import (
        REPRODUCED_LEXICAL_PIPELINE_VERSION,
        ExperimentError,
        verify_reproduced_pipeline,
    )

    # O baseline da versão que este script reproduz passa.
    verify_reproduced_pipeline(
        {"retrieval": {"pipeline_version": REPRODUCED_LEXICAL_PIPELINE_VERSION}}
    )

    # O da pipeline de produção atual, não.
    with pytest.raises(ExperimentError, match="not comparable"):
        verify_reproduced_pipeline({"retrieval": {"pipeline_version": LEXICAL_PIPELINE_VERSION}})

    # E um artefacto anterior à identidade da pipeline também não.
    with pytest.raises(ExperimentError, match="does not declare"):
        verify_reproduced_pipeline({"retrieval": {}})


def test_the_new_artefact_declares_the_pipeline_it_reproduced() -> None:
    """O campo viaja no artefacto, não só no código.

    Quem ler o ficheiro daqui a um ano tem de poder saber que pipeline o
    produziu sem ir ao histórico do git.
    """
    import scripts.evaluate_retrieval_experiment as experiment

    source = Path(experiment.__file__).read_text(encoding="utf-8")
    assert '"reproduced_pipeline_version": REPRODUCED_LEXICAL_PIPELINE_VERSION,' in source


def test_a_retrieval_query_cannot_carry_two_different_questions() -> None:
    """A invariante é do tipo, e não uma promessa do docstring.

    Sem a verificação, o par ``("notas", "propinas")`` viajava como uma só
    pergunta: o planeamento e a cobertura liam uma, as consultas FTS
    acentuadas liam a outra, e a evidência devolvida respondia a uma pergunta
    que ninguém fez — sem erro visível em lado nenhum.
    """
    with pytest.raises(ValueError, match="normalize_text"):
        RetrievalQuery(original="notas", normalized="propinas")

    # A forma correta continua a construir-se sem atrito, das duas maneiras.
    assert RetrievalQuery.from_text("As Notas?").normalized == "as notas?"
    assert RetrievalQuery(original="As Notas?", normalized="as notas?").original == "As Notas?"


def test_no_production_code_builds_a_retrieval_query_by_hand() -> None:
    """Todos os consumidores passam por ``from_text``.

    A verificação em ``__post_init__`` já impede o par incoerente; esta
    asserção mantém o caminho único, para que um chamador futuro não
    reintroduza a normalização solta ao lado da construção.
    """
    roots = (Path("app"), Path("scripts"))
    offenders = [
        f"{path}:{number}"
        for root in roots
        for path in root.rglob("*.py")
        # O módulo que define a classe fala dela no docstring, incluindo o par
        # incoerente que serve de exemplo ao que a verificação impede.
        if path != Path("app/retrieval/base.py")
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        if "RetrievalQuery(" in line and "from_text" not in line
    ]
    assert offenders == []


@pytest.mark.parametrize(
    ("original", "normalized", "expected"),
    [
        # Colisão: a mesma forma normalizada escrita de duas maneiras. Repor o
        # acento em ambas mudaria a segunda palavra, que o utilizador escreveu
        # sem ele — passaria a procurar outra coisa.
        ("avô avo", "avo avo", "avo avo"),
        # Sem colisão, a reposição acontece em todas as ocorrências.
        ("avô do avô", "avo do avo", "avô do avô"),
        # Operadores websearch atravessam intactos.
        ('"regime de avaliação"', '"regime de avaliacao"', '"regime de avaliação"'),
        ("matrícula -propinas", "matricula -propinas", "matrícula -propinas"),
        ("aulas OR avaliação", "aulas OR avaliacao", "aulas OR avaliação"),
    ],
)
def test_the_accented_rewrite_preserves_what_the_user_wrote(
    original: str, normalized: str, expected: str
) -> None:
    from app.retrieval.lexical import _accented_input

    assert _accented_input(normalized, accent_map_for_query(original)) == expected


def test_explicit_syntax_with_accents_keeps_its_behaviour(client: TestClient) -> None:
    """Aspas, ``OR`` e negação continuam a decidir o plano, com acentos ou sem.

    A via acentuada reescreve os operandos e nunca os operadores, pelo que a
    intenção explícita do utilizador atravessa intacta.
    """
    _, headers, _ = _setup(client)
    _create_searchable(
        client, headers, CLASSIFICATION_CONTENT, title="Regulamento Geral Provisório"
    )
    _create_searchable(
        client,
        headers,
        "As propinas são pagas em dez prestações mensais.",
        title="Regulamento de Propinas",
    )

    # A negação continua a excluir, mesmo com o operando acentuado.
    for item in _search(client, headers, "classificação -propinas").json()["items"]:
        assert "propinas" not in item["content"].lower()

    # A união continua a admitir qualquer dos lados.
    assert _search(client, headers, "classificação OR propinas").json()["items"]
