"""Testes puros da fase de elegibilidade e da proximidade corrigida.

Camada sem base de dados: a decisão de elegibilidade
(``app.retrieval.eligibility``) é uma função pura sobre os termos canónicos
da pergunta, os sinais de conteúdo e a estratégia que recuperou o
candidato. Cobre os contraexemplos reais encontrados na verificação: uma
correspondência de 1 termo numa pergunta de 3 não é evidência, e o título
ou a secção nunca criam elegibilidade.
"""

import math
from uuid import UUID, uuid4

import pytest

from app.core.text_normalization import normalize_text
from app.retrieval.eligibility import (
    MIN_COVERAGE_RATIO,
    EligibilityBasis,
    ExclusionReason,
    decide_eligibility,
    required_matches,
)
from app.retrieval.query_planning import LexicalQueryStrategy
from app.retrieval.reranking import (
    LexicalCandidate,
    compute_content_match,
    compute_proximity,
    informative_query_terms,
    rerank,
)

_MIN = 0.05


def _cand(
    content: str,
    *,
    title: str = "Documento",
    section: str | None = None,
    structure: str | None = None,
    strategy: LexicalQueryStrategy = LexicalQueryStrategy.REDUCED_OR,
    raw: float = 0.05,
    document_id: UUID | None = None,
) -> LexicalCandidate:
    return LexicalCandidate(
        chunk_id=uuid4(),
        document_id=document_id or uuid4(),
        document_version_id=uuid4(),
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
        structure_type=structure,
        chunking_strategy=None,
        raw_score=raw,
        strategy=strategy,
    )


def _decide(
    query: str,
    candidate: LexicalCandidate,
    strategy: LexicalQueryStrategy | None = None,
):
    terms = informative_query_terms(normalize_text(query), "pt")
    match = compute_content_match(terms, candidate)
    return decide_eligibility(terms, match, strategy or candidate.strategy)


def _rank(query: str, candidates: list[LexicalCandidate], min_relevance: float = _MIN):
    return rerank(normalize_text(query), candidates, "pt", min_relevance_score=min_relevance)


# --- required_matches: fórmula centralizada ----------------------------------


@pytest.mark.parametrize(
    ("term_count", "expected"),
    [(0, 1), (1, 1), (2, 2), (3, 2), (4, 2), (5, 3), (6, 3), (7, 4), (12, 6)],
)
def test_required_matches_formula(term_count: int, expected: int) -> None:
    assert required_matches(term_count) == expected


def test_required_matches_always_implies_minimum_coverage() -> None:
    for term_count in range(2, 13):
        assert required_matches(term_count) / term_count >= MIN_COVERAGE_RATIO


# --- 1: consulta sem termos informativos -------------------------------------


def test_query_without_informative_terms_yields_no_eligible_candidate() -> None:
    decision = _decide("Qual é o que?", _cand("o que e a matricula"))
    assert not decision.eligible
    assert decision.reason is ExclusionReason.NO_CONTENT_MATCH


# --- 2-3: consulta de um termo -----------------------------------------------


def test_single_term_with_surface_match_is_eligible() -> None:
    decision = _decide("matricula", _cand("a matricula abre em setembro"))
    assert decision.eligible
    assert decision.basis is EligibilityBasis.SINGLE_TERM_SURFACE


def test_single_term_retrieved_by_stemming_is_eligible() -> None:
    """"matrículas" ⇄ "matrícula": sem correspondência de superfície, mas o
    candidato só chegou aqui porque o índice GIN o devolveu."""
    decision = _decide("matriculas", _cand("informacao sobre a matricula anual"))
    assert decision.eligible
    assert decision.basis is EligibilityBasis.SINGLE_TERM_FTS


# --- 4-6: cobertura mínima em consultas multi-termo --------------------------


def test_one_match_out_of_three_terms_is_not_evidence() -> None:
    decision = _decide("regime avaliacao exames", _cand("regime institucional geral"))
    assert not decision.eligible
    assert decision.reason is ExclusionReason.INSUFFICIENT_COVERAGE


def test_two_matches_out_of_three_terms_are_evidence() -> None:
    decision = _decide(
        "regime avaliacao exames", _cand("o regime de avaliacao dos estudantes")
    )
    assert decision.eligible
    assert decision.basis is EligibilityBasis.COVERAGE


def test_two_matches_out_of_four_terms_are_evidence() -> None:
    decision = _decide(
        "regime avaliacao exames finais", _cand("o regime de avaliacao dos estudantes")
    )
    assert decision.eligible
    assert decision.basis is EligibilityBasis.COVERAGE


def test_one_match_out_of_two_terms_is_not_evidence() -> None:
    decision = _decide("aulas setembro", _cand("aulas de laboratorio"))
    assert not decision.eligible
    assert decision.reason is ExclusionReason.INSUFFICIENT_COVERAGE


# --- 7-9: sinais auxiliares nunca criam elegibilidade ------------------------


def test_matching_title_alone_never_creates_eligibility() -> None:
    candidate = _cand(
        "texto administrativo sem qualquer termo procurado",
        title="Regime Avaliacao Exames",
    )
    decision = _decide("regime avaliacao exames", candidate)
    assert not decision.eligible
    assert decision.reason is ExclusionReason.NO_CONTENT_MATCH


def test_matching_section_alone_never_creates_eligibility() -> None:
    candidate = _cand(
        "texto administrativo sem qualquer termo procurado",
        section="Regime Avaliacao Exames",
    )
    decision = _decide("regime avaliacao exames", candidate)
    assert not decision.eligible
    assert decision.reason is ExclusionReason.NO_CONTENT_MATCH


def test_high_raw_fts_alone_never_creates_eligibility() -> None:
    candidate = _cand("conteudo sem relacao nenhuma", raw=9.0)
    decision = _decide("regime avaliacao exames", candidate)
    assert not decision.eligible
    assert decision.reason is ExclusionReason.NO_CONTENT_MATCH


def test_table_row_and_short_length_never_create_eligibility() -> None:
    candidate = _cand("outro assunto | 3", structure="table_row")
    decision = _decide("regime avaliacao exames", candidate)
    assert not decision.eligible


def test_exact_strategy_never_creates_eligibility_without_content_match() -> None:
    """Cobertura zero é sempre inelegível numa consulta multi-termo, mesmo
    com a melhor estratégia possível."""
    candidate = _cand("conteudo sem relacao", strategy=LexicalQueryStrategy.EXACT)
    decision = _decide("regime avaliacao exames", candidate)
    assert not decision.eligible
    assert decision.reason is ExclusionReason.NO_CONTENT_MATCH


# --- 10-13: condições fortes --------------------------------------------------


def test_exact_phrase_is_a_strong_condition() -> None:
    decision = _decide("regime avaliacao", _cand("o regime avaliacao consta aqui"))
    assert decision.eligible
    assert decision.basis is EligibilityBasis.EXACT_PHRASE


def test_conjunctive_strategy_is_a_strong_condition() -> None:
    """Recuperado por reduced_and: a conjunção FTS exigiu ambos os termos
    (aqui "comecam" casou por stemming com "comeca")."""
    candidate = _cand(
        "as aulas comeca em setembro",
        strategy=LexicalQueryStrategy.REDUCED_AND,
    )
    decision = _decide("comecam aulas", candidate)
    assert decision.eligible
    assert decision.basis is EligibilityBasis.CONJUNCTIVE_STRATEGY


def test_canonical_relaxed_and_requires_the_ordinal_to_match() -> None:
    # Conteúdo em que os termos não formam frase exata: a elegibilidade tem
    # de vir da relaxação canónica (contexto completo + ordinal presente).
    matching = _cand(
        "exames finais da 1.a chamada de fevereiro",
        strategy=LexicalQueryStrategy.CANONICAL_RELAXED_AND,
    )
    decision = _decide("exames primeira chamada", matching)
    assert decision.eligible
    assert decision.basis is EligibilityBasis.CANONICAL_RELAXED


def test_canonical_relaxed_and_requires_the_range_to_match() -> None:
    matching = _cand(
        "periodo anual de inscricoes 1 a 12",
        strategy=LexicalQueryStrategy.CANONICAL_RELAXED_AND,
    )
    decision = _decide("periodo inscricoes 01a12", matching)
    assert decision.eligible
    assert decision.basis is EligibilityBasis.CANONICAL_RELAXED


def test_explicit_or_is_not_reported_as_conjunctive_proof() -> None:
    """Uma união explícita `a OR b` corresponde a um dos lados por desenho.

    O candidato é elegível — o utilizador escreveu o operador e o sistema
    honra essa intenção —, mas a base registada tem de dizer a verdade:
    `explicit_syntax`, nunca `conjunctive_strategy`.
    """
    candidate = _cand("calendario de aulas teoricas", strategy=LexicalQueryStrategy.EXACT)
    terms = informative_query_terms(normalize_text("aulas OR exames"), "pt")
    match = compute_content_match(terms, candidate)
    decision = decide_eligibility(
        terms, match, LexicalQueryStrategy.EXACT, explicit_syntax=True
    )
    assert decision.eligible
    assert decision.basis is EligibilityBasis.EXPLICIT_SYNTAX
    assert decision.basis is not EligibilityBasis.CONJUNCTIVE_STRATEGY


def test_negated_query_is_reported_as_explicit_syntax() -> None:
    candidate = _cand("matricula gratuita para bolseiros", strategy=LexicalQueryStrategy.EXACT)
    terms = informative_query_terms(normalize_text("matricula -propinas"), "pt")
    match = compute_content_match(terms, candidate)
    decision = decide_eligibility(
        terms, match, LexicalQueryStrategy.EXACT, explicit_syntax=True
    )
    assert decision.eligible
    assert decision.basis is EligibilityBasis.EXPLICIT_SYNTAX


def test_websearch_or_operator_is_not_an_informative_term() -> None:
    """`or` é sempre operador para o PostgreSQL, nunca conteúdo: contá-lo
    baixaria artificialmente a cobertura de "aulas OR exames" para 2/3."""
    assert informative_query_terms(normalize_text("aulas OR exames"), "pt") == (
        "aulas",
        "exames",
    )
    assert informative_query_terms(normalize_text("aulas OR exames"), "en") == (
        "aulas",
        "exames",
    )


def test_normal_query_without_explicit_syntax_stays_conjunctive() -> None:
    """Sem operadores, a estratégia exact continua a ser prova conjuntiva."""
    candidate = _cand("as aulas comeca em setembro", strategy=LexicalQueryStrategy.EXACT)
    decision = _decide("comecam aulas", candidate, LexicalQueryStrategy.EXACT)
    assert decision.basis is EligibilityBasis.CONJUNCTIVE_STRATEGY


def test_explicit_syntax_still_cannot_rescue_zero_coverage() -> None:
    """A sintaxe explícita honra a intenção do utilizador, mas continua a
    exigir alguma correspondência real no conteúdo."""
    candidate = _cand("conteudo sem qualquer relacao", strategy=LexicalQueryStrategy.EXACT)
    terms = informative_query_terms(normalize_text("aulas OR exames"), "pt")
    match = compute_content_match(terms, candidate)
    decision = decide_eligibility(
        terms, match, LexicalQueryStrategy.EXACT, explicit_syntax=True
    )
    assert not decision.eligible
    assert decision.reason is ExclusionReason.NO_CONTENT_MATCH


def test_canonical_relaxed_and_without_marker_falls_back_to_coverage() -> None:
    """A 2.ª chamada partilha o contexto mas não o ordinal: continua
    elegível apenas por cobertura, e nunca pela relaxação canónica."""
    other = _cand(
        "exames da 2.a chamada | 22 de fevereiro",
        strategy=LexicalQueryStrategy.CANONICAL_RELAXED_AND,
    )
    decision = _decide("exames primeira chamada", other)
    assert decision.eligible
    assert decision.basis is EligibilityBasis.COVERAGE


# --- 14: resultado vazio ------------------------------------------------------


def test_partial_candidate_produces_an_empty_retrieval() -> None:
    result = _rank("regime avaliacao exames", [_cand("regime institucional geral")])
    assert result.ranked == ()
    assert result.excluded_count(ExclusionReason.INSUFFICIENT_COVERAGE) == 1


# --- Proximidade --------------------------------------------------------------


def _proximity(query: str, content: str) -> float:
    terms = informative_query_terms(normalize_text(query), "pt")
    return compute_content_match(terms, _cand(content)).proximity


def test_proximity_is_zero_without_matches() -> None:
    assert _proximity("regime avaliacao exames", "nada em comum") == 0.0


def test_proximity_of_one_match_in_a_single_term_query_is_one() -> None:
    assert _proximity("regime", "o regime consta aqui") == 1.0


def test_proximity_of_one_match_in_a_two_term_query_is_not_one() -> None:
    value = _proximity("regime avaliacao", "o regime consta aqui")
    assert value == pytest.approx(0.5)
    assert value < 1.0


def test_proximity_of_one_match_in_a_three_term_query_is_not_one() -> None:
    value = _proximity("regime avaliacao exames", "o regime consta aqui")
    assert value == pytest.approx(1 / 3)
    assert value < 1.0


def test_proximity_two_of_three_adjacent_beats_two_of_three_distant() -> None:
    adjacent = _proximity("regime avaliacao exames", "regime avaliacao aqui")
    distant = _proximity(
        "regime avaliacao exames", "regime xx yy zz ww vv uu avaliacao"
    )
    assert adjacent == pytest.approx(2 / 3)
    assert distant < adjacent


def test_proximity_of_three_of_three_adjacent_is_one() -> None:
    assert _proximity("regime avaliacao exames", "regime avaliacao exames") == 1.0


def test_proximity_ignores_order() -> None:
    forward = _proximity("regime avaliacao", "regime avaliacao")
    reverse = _proximity("regime avaliacao", "avaliacao regime")
    assert forward == reverse


def test_proximity_is_deterministic_finite_and_bounded() -> None:
    cases = [
        ("regime avaliacao exames", "nada"),
        ("regime", "regime"),
        ("regime avaliacao", "regime"),
        ("regime avaliacao exames", "regime avaliacao exames"),
        ("regime avaliacao exames", "regime " * 200 + "avaliacao"),
    ]
    for query, content in cases:
        first = _proximity(query, content)
        second = _proximity(query, content)
        assert first == second
        assert math.isfinite(first)
        assert 0.0 <= first <= 1.0


def test_compute_proximity_handles_empty_inputs() -> None:
    assert compute_proximity((), frozenset(), {}) == (0.0, 0.0)
    assert compute_proximity(("a",), frozenset(), {}) == (0.0, 0.0)
