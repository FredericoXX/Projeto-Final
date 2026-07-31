"""Testes puros do reranking lexical determinístico (sem base de dados).

Verificam as invariantes da política de score (secção 22 do Momento 4): a
cobertura domina, a frase exata vence a coincidência isolada, a
proximidade e a estrutura desempatam, o score FTS é auxiliar, o score é
finito, determinístico e limitado a [0, 1], e os empates finais são
estáveis.
"""

import math
from uuid import UUID, uuid4

from app.core.text_normalization import normalize_text
from app.retrieval.eligibility import ExclusionReason
from app.retrieval.query_planning import LexicalQueryStrategy
from app.retrieval.reranking import (
    _WEIGHT_SUM,
    LexicalCandidate,
    compute_features,
    compute_score,
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
    index: int = 0,
    document_id: UUID | None = None,
    chunk_id: UUID | None = None,
) -> LexicalCandidate:
    return LexicalCandidate(
        chunk_id=chunk_id or uuid4(),
        document_id=document_id or uuid4(),
        document_version_id=uuid4(),
        document_title=title,
        chunk_index=index,
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


def _rank(query: str, candidates: list[LexicalCandidate], min_relevance: float = _MIN):
    return rerank(normalize_text(query), candidates, "pt", min_relevance_score=min_relevance)


def _features(query: str, candidate: LexicalCandidate):
    terms = informative_query_terms(normalize_text(query), "pt")
    return compute_features(terms, candidate)


# 1
def test_all_terms_beat_single_term() -> None:
    full = _cand("regime avaliacao exames finais", chunk_id=uuid4())
    partial = _cand("avaliacao apenas isolada")
    ranked = _rank("regime avaliacao exames", [partial, full]).ranked
    assert ranked[0].candidate is full


# 2
def test_exact_phrase_beats_scattered_terms() -> None:
    phrase = _cand("o regime de avaliacao consta aqui")
    scattered = _cand("avaliacao muito texto intermedio diverso e depois regime")
    ranked = _rank("regime avaliacao", [scattered, phrase]).ranked
    assert ranked[0].candidate is phrase


# 3
def test_close_terms_beat_distant_terms() -> None:
    close = _cand("regime xy avaliacao")
    distant = _cand("regime xy zz ww qq avaliacao")
    ranked = _rank("regime avaliacao", [distant, close]).ranked
    assert ranked[0].candidate is close


# 4
def test_correct_order_beats_reverse_when_other_signals_equal() -> None:
    forward = _cand("regime xy avaliacao")
    reverse = _cand("avaliacao xy regime")
    result = _rank("regime avaliacao", [reverse, forward])
    assert result.ranked[0].candidate is forward


# 5
def test_table_row_beats_generic_paragraph_with_lower_coverage() -> None:
    table_row = _cand("regime avaliacao data", structure="table_row")
    paragraph = _cand(
        "avaliacao avaliacao avaliacao regime regime regime texto longo", raw=5.0
    )
    ranked = _rank("regime avaliacao data", [paragraph, table_row]).ranked
    assert ranked[0].candidate is table_row


# 6
def test_table_row_does_not_beat_paragraph_with_higher_coverage() -> None:
    table_row = _cand("regime avaliacao", structure="table_row")
    paragraph = _cand("regime avaliacao data extra completa")
    ranked = _rank("regime avaliacao data extra", [table_row, paragraph]).ranked
    assert ranked[0].candidate is paragraph


# 7
def test_title_helps_break_ties() -> None:
    with_title = _cand("regime avaliacao", title="Regime")
    without_title = _cand("regime avaliacao", title="Outro assunto")
    ranked = _rank("regime avaliacao", [without_title, with_title]).ranked
    assert ranked[0].candidate is with_title


# 8
def test_title_alone_does_not_make_chunk_relevant() -> None:
    title_only = _cand("texto totalmente irrelevante sem termos", title="regime avaliacao")
    real = _cand("regime avaliacao presentes", title="Outro")
    result = _rank("regime avaliacao", [title_only, real])
    assert [rc.candidate for rc in result.ranked] == [real]


# 9
def test_section_title_helps_break_ties() -> None:
    with_section = _cand("regime avaliacao", section="Regime")
    without_section = _cand("regime avaliacao", section="Outro")
    ranked = _rank("regime avaliacao", [without_section, with_section]).ranked
    assert ranked[0].candidate is with_section


# 10
def test_long_chunk_does_not_win_by_repetition() -> None:
    short = _cand("regime avaliacao", raw=0.05)
    long_repeated = _cand("regime avaliacao " * 200, raw=8.0)
    ranked = _rank("regime avaliacao", [long_repeated, short]).ranked
    assert ranked[0].candidate is short


# 11
def test_raw_fts_is_auxiliary_signal() -> None:
    low = _cand("regime avaliacao", raw=0.01, document_id=UUID(int=1))
    high = _cand("regime avaliacao", raw=5.0, document_id=UUID(int=2))
    # Em igualdade de conteúdo, o FTS mais alto desempata para cima.
    ranked = _rank("regime avaliacao", [low, high]).ranked
    assert ranked[0].candidate is high
    # Mas cobertura superior vence FTS superior.
    richer = _cand("regime avaliacao exames", raw=0.01)
    poorer = _cand("regime apenas", raw=9.0)
    ranked2 = _rank("regime avaliacao exames", [poorer, richer]).ranked
    assert ranked2[0].candidate is richer


# 12
def test_exact_strategy_beats_reduced_and_in_equality() -> None:
    exact = _cand("regime avaliacao", strategy=LexicalQueryStrategy.EXACT, document_id=UUID(int=1))
    reduced_and = _cand(
        "regime avaliacao", strategy=LexicalQueryStrategy.REDUCED_AND, document_id=UUID(int=2)
    )
    ranked = _rank("regime avaliacao", [reduced_and, exact]).ranked
    assert ranked[0].candidate is exact


# 13
def test_reduced_and_beats_reduced_or_in_equality() -> None:
    reduced_and = _cand(
        "regime avaliacao", strategy=LexicalQueryStrategy.REDUCED_AND, document_id=UUID(int=1)
    )
    reduced_or = _cand(
        "regime avaliacao", strategy=LexicalQueryStrategy.REDUCED_OR, document_id=UUID(int=2)
    )
    ranked = _rank("regime avaliacao", [reduced_or, reduced_and]).ranked
    assert ranked[0].candidate is reduced_and


def test_ranking_weights_sum_to_one() -> None:
    assert math.isclose(_WEIGHT_SUM, 1.0, rel_tol=1e-9)


# 14 & 15
def test_score_is_finite_and_bounded() -> None:
    for content in ("regime avaliacao", "x", "regime " * 500, "sem termos aqui"):
        candidate = _cand(content, raw=10.0)
        score = compute_score(_features("regime avaliacao exames", candidate))
        assert math.isfinite(score)
        assert 0.0 <= score <= 1.0


# 16
def test_score_is_deterministic() -> None:
    candidate = _cand("regime avaliacao exames")
    first = compute_score(_features("regime avaliacao", candidate))
    second = compute_score(_features("regime avaliacao", candidate))
    assert first == second


# 17
def test_final_tie_is_stable_by_document_id() -> None:
    a = _cand("regime avaliacao", document_id=UUID(int=3), chunk_id=UUID(int=30))
    b = _cand("regime avaliacao", document_id=UUID(int=1), chunk_id=UUID(int=10))
    c = _cand("regime avaliacao", document_id=UUID(int=2), chunk_id=UUID(int=20))
    ranked = _rank("regime avaliacao", [a, b, c]).ranked
    ids = [rc.candidate.document_id for rc in ranked]
    assert ids == [UUID(int=1), UUID(int=2), UUID(int=3)]


# 18
def test_structure_type_null_is_supported() -> None:
    candidate = _cand("regime avaliacao", structure=None)
    ranked = _rank("regime avaliacao", [candidate]).ranked
    assert ranked[0].candidate is candidate


# 19
def test_section_title_null_is_supported() -> None:
    candidate = _cand("regime avaliacao", section=None)
    features = _features("regime avaliacao", candidate)
    assert features.section_overlap == 0.0


# 20
def test_standard_ordinal_improves_coverage() -> None:
    candidate = _cand("exames 2.ª chamada")
    features = _features("exames segunda chamada", candidate)
    assert features.coverage == 1.0
    assert "ord:2" in features.matched_terms


# 21
def test_ambiguous_ocr_gets_no_invented_ordinal() -> None:
    candidate = _cand("exames 12 chamada")
    features = _features("exames segunda chamada", candidate)
    assert "ord:2" not in features.matched_terms
    assert features.coverage < 1.0


# 22a — evidência complementar é preservada, não eliminada por subconjunto.
def test_complementary_evidence_is_preserved_not_dominated() -> None:
    """Dois chunks elegíveis em que os termos de um são subconjunto próprio
    dos do outro: o mais fraco desce no ranking, mas continua a ser
    evidência — a antiga dominância por subconjunto apagava-o."""
    strong = _cand("regime avaliacao exames finais", document_id=UUID(int=1))
    complementary = _cand("regime de avaliacao contínua", document_id=UUID(int=2))
    result = _rank("regime avaliacao exames", [strong, complementary])
    kept = [rc.candidate for rc in result.ranked]
    assert kept == [strong, complementary]
    assert result.excluded == ()


# 22b — um candidato sem qualquer correspondência é excluído por ausência de
# correspondência, não pelo limiar: as causas são distintas e tipadas.
def test_candidate_without_content_match_is_excluded_before_scoring() -> None:
    weak = _cand("palavra totalmente diferente sem relacao")
    result = _rank("regime avaliacao exames", [weak])
    assert result.ranked == ()  # o melhor NÃO sobrevive automaticamente
    assert [item.reason for item in result.excluded] == [
        ExclusionReason.NO_CONTENT_MATCH
    ]
    # Excluído antes da pontuação: os sinais auxiliares nem existem.
    assert result.excluded[0].score is None


# 22c — todos os candidatos podem ser removidos (o answering recai em
# insufficient_evidence, não gera sobre coincidência fraca).
def test_all_candidates_can_be_removed() -> None:
    candidates = [
        _cand("texto sem relacao alguma com a pergunta"),
        _cand("regime apenas mencionado uma vez aqui"),
    ]
    result = _rank("regime avaliacao exames", candidates)
    assert result.ranked == ()
    assert result.excluded_count(ExclusionReason.NO_CONTENT_MATCH) == 1
    assert result.excluded_count(ExclusionReason.INSUFFICIENT_COVERAGE) == 1


# 22d — a frase exata deixa de ser imune ao limiar: o piso aplica-se a todos
# os candidatos elegíveis, incluindo o melhor.
def test_exact_phrase_is_not_exempt_from_threshold() -> None:
    exact = _cand("o regime de avaliacao consta aqui")
    result = _rank("regime avaliacao", [exact], min_relevance=0.99)
    assert result.ranked == ()
    assert [item.reason for item in result.excluded] == [
        ExclusionReason.BELOW_THRESHOLD
    ]
    # Excluído depois da pontuação: o score fica registado para auditoria.
    assert result.excluded[0].score is not None


# 23
def test_single_term_query_keeps_candidates() -> None:
    candidate = _cand("matricula aberta")
    result = _rank("matricula", [candidate])
    assert [rc.candidate for rc in result.ranked] == [candidate]


# 24
def test_no_candidates_yields_empty_and_covered_candidate_is_kept() -> None:
    assert _rank("regime avaliacao", []).ranked == ()
    non_empty = _rank("regime avaliacao", [_cand("regime avaliacao presente")]).ranked
    assert len(non_empty) == 1


# --- Intervalos explícitos participam na cobertura (Momento 4, M4) -----------


def test_range_marker_contributes_to_coverage() -> None:
    candidate = _cand("exames de 1 a 12 de fevereiro")
    features = _features("exames 1 a 12", candidate)
    assert "rng:1-12" in features.matched_terms


def test_range_zero_padding_is_equivalent_in_coverage() -> None:
    # "01 a 12" (pergunta) cobre integralmente "1 a 12" (conteúdo): o mesmo
    # marcador de intervalo, seja qual for a forma textual.
    features = _features("periodo 01 a 12", _cand("periodo de 1 a 12"))
    assert features.coverage == 1.0
    assert "rng:1-12" in features.matched_terms


def test_compact_range_form_matches_spaced_content() -> None:
    # "01a12" na pergunta ⇄ "1 a 12" no conteúdo.
    features = _features("periodo inscricoes 01a12", _cand("periodo de inscricoes 1 a 12"))
    assert features.coverage == 1.0
    assert "rng:1-12" in features.matched_terms


def test_range_participates_in_exact_phrase_and_order() -> None:
    """O marcador é uma unidade posicional: "periodo 01a12" forma frase
    exata dentro de "periodo de 1 a 12" e mantém a ordem."""
    features = _features("periodo 01a12", _cand("periodo de 1 a 12"))
    assert features.exact_phrase == 1.0
    assert features.ordered == 1.0


def test_range_marker_occupies_a_single_position_for_proximity() -> None:
    """O intervalo conta como **um** termo adjacente ao anterior: se os
    endpoints ocupassem posições próprias, o span seria maior e a
    proximidade cairia."""
    features = _features("periodo 01a12", _cand("periodo 1 a 12"))
    assert features.proximity == 1.0
    assert features.compactness == 1.0


def test_correct_range_outranks_neighbouring_range() -> None:
    correct = _cand("periodo de inscricoes 1 a 12", document_id=UUID(int=1))
    neighbour = _cand("periodo de inscricoes 1 a 13", document_id=UUID(int=2))
    ranked = _rank("periodo inscricoes 01a12", [neighbour, correct]).ranked
    assert ranked[0].candidate is correct
    assert "rng:1-12" in ranked[0].features.matched_terms


def test_number_run_never_matches_a_range() -> None:
    # "0509" continua ambíguo: nunca corresponde ao intervalo 5 a 9.
    features = _features("semana 0509", _cand("semana de 5 a 9 de outubro"))
    assert "rng:5-9" not in features.matched_terms
    assert features.coverage < 1.0
