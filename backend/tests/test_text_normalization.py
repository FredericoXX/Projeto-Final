"""Testes da normalização determinística de texto (normalized_content).

Camada pura, sem base de dados: garante que a normalização é previsível
e estável, porque o valor gerado fica persistido em document_chunks e
será usado por estratégias futuras de pesquisa.
"""

from app.core.text_normalization import normalize_text


def test_collapses_repeated_spaces_and_tabs() -> None:
    assert normalize_text("a  b\t\tc   d") == "a b c d"


def test_collapses_newlines_into_single_space() -> None:
    assert normalize_text("linha um\nlinha dois\r\nlinha três") == "linha um linha dois linha tres"


def test_strips_leading_and_trailing_whitespace() -> None:
    assert normalize_text("   texto   ") == "texto"


def test_lowercases_text() -> None:
    assert normalize_text("MAIÚSCULAS E Minúsculas") == "maiusculas e minusculas"


def test_removes_accents_consistently() -> None:
    assert normalize_text("Matrícula e Inscrição") == "matricula e inscricao"
    # Formas Unicode compostas (NFC) e decompostas (NFD) do mesmo texto
    # normalizam para o mesmo valor.
    composed = "Matrícula"
    decomposed = "Matrícula"
    assert normalize_text(composed) == normalize_text(decomposed) == "matricula"


def test_documented_example() -> None:
    assert normalize_text("  Matrícula   e\nInscrição  ") == "matricula e inscricao"


def test_unicode_text_is_preserved_without_marks() -> None:
    # Caracteres não latinos mantêm-se; apenas marcas combinantes caem.
    assert normalize_text("Πανεπιστήμιο") == "πανεπιστημιο"
    assert normalize_text("çãoÇÃO") == "caocao"


def test_portuguese_sentence() -> None:
    assert (
        normalize_text("O período de matrícula decorre em Setembro.")
        == "o periodo de matricula decorre em setembro."
    )


def test_english_sentence() -> None:
    assert (
        normalize_text("Enrollment   opens in\nSeptember.")
        == "enrollment opens in september."
    )


def test_empty_and_whitespace_only() -> None:
    assert normalize_text("") == ""
    assert normalize_text(" \n\t ") == ""


def test_is_deterministic() -> None:
    text = "  Matrícula   e\nInscrição — ÉPOCA especial\t2026  "
    first = normalize_text(text)
    second = normalize_text(text)
    assert first == second
    # Normalizar um valor já normalizado não o altera (idempotência).
    assert normalize_text(first) == first
