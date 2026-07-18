"""Testes unitários do título automático de conversas.

Função pura e local: sem base de dados, sem rede e sem LLM — o módulo
não importa nenhum SDK nem cliente HTTP.
"""

import app.core.conversation_title as title_module
from app.core.conversation_title import MAX_TITLE_LENGTH, derive_conversation_title


def test_short_question_keeps_text_without_final_punctuation() -> None:
    assert derive_conversation_title("Quando começam as aulas?") == "Quando começam as aulas"


def test_expected_example_from_spec() -> None:
    assert (
        derive_conversation_title("Qual é o período dos exames da primeira época?")
        == "Qual é o período dos exames da primeira época"
    )


def test_trims_outer_whitespace() -> None:
    assert derive_conversation_title("   Horário da biblioteca   ") == "Horário da biblioteca"


def test_collapses_multiple_spaces_tabs_and_newlines() -> None:
    assert (
        derive_conversation_title("Pergunta   com\tespaços\ne\r\nlinhas")
        == "Pergunta com espaços e linhas"
    )


def test_preserves_accents_and_case() -> None:
    assert (
        derive_conversation_title("QUANDO Começam as AULAS de Época Especial?")
        == "QUANDO Começam as AULAS de Época Especial"
    )


def test_portuguese_and_english_are_preserved_without_translation() -> None:
    assert derive_conversation_title("Como recupero a palavra-passe?") == (
        "Como recupero a palavra-passe"
    )
    assert derive_conversation_title("When does registration begin?") == (
        "When does registration begin"
    )


def test_repeated_final_punctuation_is_removed() -> None:
    assert derive_conversation_title("Isto funciona???") == "Isto funciona"
    assert derive_conversation_title("Prazo!!!") == "Prazo"
    assert derive_conversation_title("A sério?!…") == "A sério"
    assert derive_conversation_title("Fim. ") == "Fim"


def test_internal_punctuation_is_preserved() -> None:
    assert (
        derive_conversation_title("Propinas: valores, prazos e multas?")
        == "Propinas: valores, prazos e multas"
    )


def test_punctuation_only_question_is_never_empty() -> None:
    # Uma pergunta válida nunca produz título vazio; só pontuação mantém
    # a própria pontuação.
    assert derive_conversation_title("???") == "???"


def test_unicode_and_emoji_are_preserved() -> None:
    assert derive_conversation_title("Πανεπιστήμιο aberto? 🎓") == "Πανεπιστήμιο aberto? 🎓"


def test_exactly_limit_is_not_truncated() -> None:
    question = "a" * MAX_TITLE_LENGTH
    assert derive_conversation_title(question) == question
    assert len(derive_conversation_title(question)) == MAX_TITLE_LENGTH


def test_above_limit_is_truncated_at_word_boundary_with_ellipsis() -> None:
    question = "palavra " * 30  # 239 caracteres úteis
    result = derive_conversation_title(question)
    assert len(result) <= MAX_TITLE_LENGTH
    assert result.endswith("…")
    # Corte por palavra: nunca termina a meio de "palavra".
    assert result.removesuffix("…").split(" ")[-1] == "palavra"


def test_single_word_longer_than_limit_gets_hard_cut() -> None:
    result = derive_conversation_title("x" * 200)
    assert len(result) == MAX_TITLE_LENGTH
    assert result.endswith("…")
    assert result[:-1] == "x" * (MAX_TITLE_LENGTH - 1)


def test_truncation_never_exceeds_limit() -> None:
    for size in (MAX_TITLE_LENGTH + 1, 100, 500, 1000):
        result = derive_conversation_title("Quando começam as aulas " * (size // 10))
        assert len(result) <= MAX_TITLE_LENGTH


def test_is_deterministic() -> None:
    question = "  Quando   começam as aulas de 2026?  "
    assert derive_conversation_title(question) == derive_conversation_title(question)


def test_module_has_no_external_calls() -> None:
    # Garantia estrutural: o módulo do título não importa SDKs, HTTP nem
    # SQLAlchemy — é uma função pura sobre strings.
    import inspect

    source = inspect.getsource(title_module)
    for forbidden in ("openai", "httpx", "requests", "sqlalchemy"):
        assert forbidden not in source
