"""Testes unitários do planeador de consultas lexicais progressivas.

Camada pura, sem base de dados: o planeador recebe a consulta já
normalizada (normalize_text) e o idioma resolvido, e produz variantes
ordenadas sem executar SQL.
"""

from app.core.text_normalization import normalize_text
from app.retrieval.query_planning import (
    MAX_INFORMATIVE_TERMS,
    LexicalQueryStrategy,
    extract_informative_terms,
    plan_lexical_query,
)


def _plan(query: str, language: str = "pt"):
    return plan_lexical_query(normalize_text(query), language)


def _strategies(query: str, language: str = "pt") -> list[str]:
    return [variant.strategy.value for variant in _plan(query, language).variants]


def _variant(query: str, strategy: LexicalQueryStrategy, language: str = "pt") -> str:
    plan = _plan(query, language)
    for variant in plan.variants:
        if variant.strategy is strategy:
            return variant.websearch_input
    raise AssertionError(f"strategy {strategy} not planned for {query!r}")


# --- Extração de termos ------------------------------------------------------


def test_portuguese_natural_question_keeps_informative_terms() -> None:
    terms = extract_informative_terms(normalize_text("Quando começam as aulas?"), "pt")
    assert terms == ("comecam", "aulas")


def test_portuguese_exam_period_question() -> None:
    terms = extract_informative_terms(normalize_text("Qual é o período dos exames?"), "pt")
    assert terms == ("periodo", "exames")


def test_portuguese_payment_question() -> None:
    terms = extract_informative_terms(
        normalize_text("Até quando devo pagar a primeira prestação?"), "pt"
    )
    assert terms == ("pagar", "primeira", "prestacao")


def test_english_documents_question() -> None:
    terms = extract_informative_terms(
        normalize_text("What documents are required for international students?"), "en"
    )
    assert terms == ("documents", "required", "international", "students")


def test_english_functional_terms_are_removed() -> None:
    terms = extract_informative_terms(
        normalize_text("When is the International Office open?"), "en"
    )
    assert terms == ("international", "office", "open")


def test_informative_institutional_words_are_never_removed() -> None:
    for word, language in [
        ("matricula", "pt"),
        ("aulas", "pt"),
        ("exames", "pt"),
        ("biblioteca", "pt"),
        ("periodo", "pt"),
        ("prestacao", "pt"),
        ("documentos", "pt"),
        ("registration", "en"),
        ("students", "en"),
        ("office", "en"),
        ("deadline", "en"),
    ]:
        assert extract_informative_terms(word, language) == (word,)


def test_duplicates_removed_preserving_order() -> None:
    terms = extract_informative_terms("aulas exames aulas exames aulas", "pt")
    assert terms == ("aulas", "exames")


def test_numbers_and_years_are_preserved() -> None:
    terms = extract_informative_terms(
        normalize_text("As aulas iniciam a 21 de setembro de 2026"), "pt"
    )
    assert terms == ("aulas", "iniciam", "21", "setembro", "2026")


def test_punctuation_and_single_letters_are_ignored() -> None:
    terms = extract_informative_terms("aulas!!! ... b ??? exames", "pt")
    assert terms == ("aulas", "exames")


def test_stopword_only_query_yields_no_terms() -> None:
    assert extract_informative_terms(normalize_text("Qual é o que?"), "pt") == ()


def test_unicode_tokens_are_preserved() -> None:
    # A normalização remove acentos latinos; outros alfabetos permanecem
    # e continuam a ser tokens válidos.
    terms = extract_informative_terms(normalize_text("Πανεπιστήμιο aulas"), "pt")
    assert terms == ("πανεπιστημιο", "aulas")


def test_long_query_respects_term_limit() -> None:
    long_query = " ".join(f"termo{i}" for i in range(50))
    terms = extract_informative_terms(long_query, "pt")
    assert len(terms) == MAX_INFORMATIVE_TERMS
    assert terms == tuple(f"termo{i}" for i in range(MAX_INFORMATIVE_TERMS))


def test_extraction_is_deterministic() -> None:
    query = normalize_text("Quando começam as aulas do primeiro semestre de 2026?")
    first = extract_informative_terms(query, "pt")
    second = extract_informative_terms(query, "pt")
    assert first == second


# --- Plano de variantes -------------------------------------------------------


def test_plan_for_natural_question_has_three_ordered_strategies() -> None:
    assert _strategies("Quando começam as aulas?") == ["exact", "reduced_and", "reduced_or"]
    assert _variant("Quando começam as aulas?", LexicalQueryStrategy.EXACT) == (
        "quando comecam as aulas?"
    )
    assert _variant("Quando começam as aulas?", LexicalQueryStrategy.REDUCED_AND) == (
        "comecam aulas"
    )
    assert _variant("Quando começam as aulas?", LexicalQueryStrategy.REDUCED_OR) == (
        "comecam OR aulas"
    )


def test_single_keyword_plans_only_exact() -> None:
    # Nenhum token é removido: as variantes reduzidas seriam idênticas.
    assert _strategies("aulas") == ["exact"]


def test_keywords_without_functional_terms_add_only_reduced_or() -> None:
    # "aulas setembro" já é conjuntivo na exact; só a disjuntiva difere.
    assert _strategies("aulas setembro") == ["exact", "reduced_or"]


def test_single_informative_term_skips_reduced_or() -> None:
    # Com um único termo, OR e AND são a mesma consulta.
    assert _strategies("Quando começam?") == ["exact", "reduced_and"]


def test_stopword_only_query_plans_no_variants() -> None:
    # Sem termos informativos num idioma com lista própria não há nada
    # pesquisável: o plano fica vazio e nenhuma consulta é executada —
    # "O que é?" nunca pode corresponder a um documento por coincidência
    # das próprias palavras funcionais.
    assert _strategies("Qual é o que?") == []
    assert _strategies("O que é?") == []


def test_quoted_stopword_only_query_keeps_exact() -> None:
    # Uma frase citada é uma intenção explícita: mantém a variante exact
    # mesmo quando composta por termos funcionais.
    assert _strategies('"o que é"') == ["exact"]


def test_language_without_functional_list_plans_only_exact() -> None:
    # Idioma suportado sem lista própria: nunca se aplica a lista de
    # outro idioma.
    assert _strategies("Quando começam as aulas?", language="fr") == ["exact"]


def test_regional_language_code_uses_primary_subtag_list() -> None:
    assert _strategies("Quando começam as aulas?", language="pt-pt") == [
        "exact",
        "reduced_and",
        "reduced_or",
    ]


# --- Sintaxe avançada preservada -----------------------------------------------


def test_quoted_phrase_plans_only_exact() -> None:
    plan = _plan('"primeiro semestre" aulas')
    assert [v.strategy.value for v in plan.variants] == ["exact"]
    assert plan.variants[0].websearch_input == '"primeiro semestre" aulas'


def test_negated_term_plans_only_exact() -> None:
    # A relaxação nunca pode transformar "matricula -propinas" numa
    # pesquisa que também encontre "propinas".
    plan = _plan("matricula -propinas")
    assert [v.strategy.value for v in plan.variants] == ["exact"]
    assert plan.variants[0].websearch_input == "matricula -propinas"


def test_or_operator_plans_only_exact() -> None:
    plan = _plan("aulas OR exames")
    assert [v.strategy.value for v in plan.variants] == ["exact"]
    # normalize_text já converteu para minúsculas; websearch_to_tsquery
    # reconhece "or" sem distinção de maiúsculas.
    assert plan.variants[0].websearch_input == "aulas or exames"


def test_hyphenated_word_is_not_treated_as_negation() -> None:
    assert _strategies("As aulas iniciam-se em setembro") == [
        "exact",
        "reduced_and",
        "reduced_or",
    ]


def test_plan_is_deterministic() -> None:
    query = "Quando começam as aulas do primeiro semestre?"
    assert _plan(query) == _plan(query)
