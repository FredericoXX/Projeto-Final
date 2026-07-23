"""Testes sintéticos da reconstrução visual, sem Tesseract ou I/O."""

from app.services.ocr_engine import OcrWord
from app.services.ocr_line_reconstruction import (
    reconstruct_lines,
    reconstruct_structured_lines,
)


def _word(
    text: str,
    left: int,
    top: int,
    *,
    width: int | None = None,
    height: int = 20,
    confidence: float = 95.0,
    block: int = 1,
    paragraph: int = 1,
    line: int = 1,
) -> OcrWord:
    return OcrWord(
        text=text,
        confidence=confidence,
        block=block,
        paragraph=paragraph,
        line=line,
        left=left,
        top=top,
        width=width if width is not None else max(10, len(text) * 10),
        height=height,
    )


def test_words_from_different_blocks_share_visual_line() -> None:
    words = (
        _word("Campo", 0, 10, block=8),
        _word("associado", 70, 10, block=2),
    )
    assert reconstruct_lines(words) == "Campo associado"


def test_distinct_visual_lines_are_not_mixed() -> None:
    words = (_word("primeira", 0, 0), _word("segunda", 0, 35))
    assert reconstruct_lines(words) == "primeira\nsegunda"


def test_lines_are_sorted_vertically() -> None:
    words = (
        _word("terceira", 0, 80),
        _word("primeira", 0, 0),
        _word("segunda", 0, 40),
    )
    assert reconstruct_lines(words).splitlines() == ["primeira", "segunda", "terceira"]


def test_words_are_sorted_horizontally() -> None:
    words = (_word("direita", 100, 0), _word("esquerda", 0, 0))
    assert reconstruct_lines(words) == "esquerda direita"


def test_two_blocks_on_same_row_create_column_separator() -> None:
    words = (
        _word("Evento", 0, 0, width=60, block=1),
        _word("sintético", 70, 0, width=90, block=1),
        _word("05", 500, 0, width=20, block=2),
        _word("outubro", 530, 0, width=70, block=2),
    )
    assert reconstruct_lines(words) == "Evento sintético | 05 outubro"


def test_left_block_is_not_emitted_entirely_before_right_block() -> None:
    words = (
        _word("Evento-A", 0, 0, width=80, block=1),
        _word("Evento-B", 0, 40, width=80, block=1),
        _word("Data-A", 500, 0, width=60, block=2),
        _word("Data-B", 500, 40, width=60, block=2),
    )
    assert reconstruct_lines(words).splitlines() == [
        "Evento-A | Data-A",
        "Evento-B | Data-B",
    ]


def test_multiple_table_rows_preserve_row_association() -> None:
    words = tuple(
        word
        for top, event, date in (
            (0, "Integração", "2030-10-05"),
            (40, "Abertura", "2030-10-12"),
            (80, "Encerramento", "2030-10-19"),
        )
        for word in (
            _word(event, 0, top, width=120, block=1),
            _word(date, 600, top, width=100, block=2),
        )
    )
    assert reconstruct_lines(words).splitlines() == [
        "Integração | 2030-10-05",
        "Abertura | 2030-10-12",
        "Encerramento | 2030-10-19",
    ]


def test_normal_gap_uses_space() -> None:
    assert reconstruct_lines((_word("um", 0, 0, width=20), _word("campo", 30, 0))) == (
        "um campo"
    )


def test_large_gap_uses_column_separator() -> None:
    assert reconstruct_lines((_word("um", 0, 0, width=20), _word("campo", 300, 0))) == (
        "um | campo"
    )


def test_geometry_rule_is_resolution_independent() -> None:
    base = (
        _word("Evento", 0, 0, width=60),
        _word("2035", 400, 0, width=40),
    )
    scaled = (
        _word("Evento", 0, 0, width=180, height=60),
        _word("2035", 1200, 0, width=120, height=60),
    )
    assert reconstruct_lines(base) == reconstruct_lines(scaled) == "Evento | 2035"


def test_different_word_heights_can_share_line() -> None:
    words = (
        _word("alto", 0, 0, width=40, height=30),
        _word("baixo", 50, 5, width=50, height=18),
    )
    assert reconstruct_lines(words) == "alto baixo"


def test_overlapping_word_boxes_are_safe() -> None:
    words = (
        _word("sobre", 0, 0, width=70),
        _word("posto", 60, 0, width=50),
    )
    assert reconstruct_lines(words) == "sobre posto"


def test_empty_tokens_are_ignored() -> None:
    words = (_word("", 0, 0), _word("   ", 10, 0), _word("válido", 20, 0))
    assert reconstruct_lines(words) == "válido"


def test_empty_input_returns_empty_text() -> None:
    assert reconstruct_lines(()) == ""
    assert reconstruct_structured_lines(()) == ()


def test_invalid_confidence_is_ignored() -> None:
    words = (
        _word("inválido", 0, 0, confidence=-1),
        _word("também", 30, 0, confidence=float("nan")),
        _word("válido", 60, 0),
    )
    assert reconstruct_lines(words) == "válido"


def test_negative_or_degenerate_geometry_is_handled_safely() -> None:
    words = (
        _word("primeiro", -20, -10, width=-4, height=-2),
        _word("segundo", 2, -5, width=0, height=0),
    )
    assert reconstruct_lines(words) == "primeiro segundo"


def test_reconstruction_is_deterministic() -> None:
    words = (
        _word("B", 500, 40, block=2),
        _word("A", 0, 40, block=1),
        _word("Título", 0, 0, block=9),
    )
    assert reconstruct_lines(words) == reconstruct_lines(words)


def test_column_detection_does_not_search_for_dates() -> None:
    close = (_word("evento", 0, 0, width=60), _word("05-10-2037", 70, 0, width=100))
    assert reconstruct_lines(close) == "evento 05-10-2037"


def test_recognized_text_is_not_corrected() -> None:
    words = (_word("cod1go", 0, 0, width=60), _word("sintetico", 70, 0, width=90))
    assert reconstruct_lines(words) == "cod1go sintetico"


def test_original_word_tokens_are_preserved() -> None:
    words = (_word("OCR-2038", 0, 0), _word("çãoÜ", 100, 0))
    rendered = reconstruct_lines(words)
    assert "OCR-2038" in rendered
    assert "çãoÜ" in rendered


def test_multiline_left_cell_merges_with_geometric_evidence() -> None:
    words = (
        _word("Evento", 0, 0, width=60),
        _word("prolongado", 70, 0, width=130),
        _word("continuação", 0, 21, width=200),
        _word("Período", 600, 21, width=70),
    )
    lines = reconstruct_structured_lines(words)
    assert len(lines) == 1
    assert lines[0].source_line_count == 2
    assert lines[0].text == "Evento prolongado continuação | Período"


def test_uncertain_multiline_candidate_remains_separate() -> None:
    words = (
        _word("Evento", 0, 0, width=60),
        _word("prolongado", 70, 0, width=130),
        _word("continuação", 0, 60, width=200),
        _word("Período", 600, 60, width=70),
    )
    assert reconstruct_lines(words) == "Evento prolongado\ncontinuação | Período"
