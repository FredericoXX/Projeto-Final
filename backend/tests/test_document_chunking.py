"""Testes unitários do chunker determinístico (document_chunking_service).

Camada pura, sem base de dados: valida a segmentação, os offsets sobre o
texto original, os checksums e o determinismo. O invariante central é
content == texto_original[start_char:end_char] para todos os chunks.
"""

import hashlib

import pytest

from app.services.document_chunking_service import ChunkData, chunk_text


def _assert_invariants(text: str, chunks: list[ChunkData], chunk_size: int) -> None:
    """Invariantes válidos para qualquer resultado do chunker."""
    for position, chunk in enumerate(chunks):
        assert chunk.chunk_index == position
        assert chunk.content
        assert chunk.content.strip()
        assert chunk.normalized_content
        assert 0 <= chunk.start_char < chunk.end_char <= len(text)
        assert chunk.end_char - chunk.start_char <= chunk_size
        assert chunk.content == text[chunk.start_char : chunk.end_char]
        assert chunk.content_sha256 == hashlib.sha256(chunk.content.encode("utf-8")).hexdigest()
        assert chunk.page_number > 0
        assert chunk.structure_type
        assert chunk.chunking_strategy in {"structured_v1", "character_fallback_v1"}
        assert "\f" not in chunk.content
    # A ordem original é preservada: os inícios são estritamente crescentes.
    starts = [chunk.start_char for chunk in chunks]
    assert starts == sorted(starts)


# --- Entradas vazias e parâmetros inválidos ---------------------------------


def test_empty_text_returns_no_chunks() -> None:
    assert chunk_text("", 100, 10) == []


def test_whitespace_only_text_returns_no_chunks() -> None:
    assert chunk_text("   \n\n \t  \n ", 100, 10) == []


def test_zero_chunk_size_is_rejected() -> None:
    with pytest.raises(ValueError, match="chunk_size"):
        chunk_text("texto", 0, 0)


def test_negative_chunk_size_is_rejected() -> None:
    with pytest.raises(ValueError, match="chunk_size"):
        chunk_text("texto", -5, 0)


def test_negative_overlap_is_rejected() -> None:
    with pytest.raises(ValueError, match="overlap"):
        chunk_text("texto", 100, -1)


def test_overlap_equal_to_chunk_size_is_rejected() -> None:
    with pytest.raises(ValueError, match="overlap"):
        chunk_text("texto", 100, 100)


def test_overlap_larger_than_chunk_size_is_rejected() -> None:
    with pytest.raises(ValueError, match="overlap"):
        chunk_text("texto", 100, 150)


# --- Tamanhos relativos a chunk_size -----------------------------------------


def test_text_smaller_than_chunk_size_yields_single_chunk() -> None:
    text = "um texto curto"
    chunks = chunk_text(text, 100, 10)
    assert len(chunks) == 1
    assert chunks[0].content == text
    assert chunks[0].start_char == 0
    assert chunks[0].end_char == len(text)
    _assert_invariants(text, chunks, 100)


def test_text_exactly_chunk_size_yields_single_chunk() -> None:
    text = "a" * 100
    chunks = chunk_text(text, 100, 10)
    assert len(chunks) == 1
    assert chunks[0].content == text
    _assert_invariants(text, chunks, 100)


def test_text_larger_than_chunk_size_is_split() -> None:
    text = "palavra " * 50  # 400 caracteres, um único parágrafo
    chunks = chunk_text(text, 100, 10)
    assert len(chunks) > 1
    _assert_invariants(text, chunks, 100)
    # Nada relevante se perde: a união dos intervalos cobre todo o texto útil.
    assert chunks[0].start_char == 0
    assert chunks[-1].end_char == len(text.rstrip())


def test_surrounding_whitespace_is_not_included_in_chunks() -> None:
    text = "   \n\n  conteúdo real  \n\n   "
    chunks = chunk_text(text, 100, 0)
    assert len(chunks) == 1
    assert chunks[0].content == "conteúdo real"
    _assert_invariants(text, chunks, 100)


# --- Parágrafos ----------------------------------------------------------------


def test_multiple_paragraphs_fitting_one_chunk_are_packed_together() -> None:
    text = "Primeiro parágrafo.\n\nSegundo parágrafo.\n\nTerceiro."
    chunks = chunk_text(text, 200, 20)
    assert len(chunks) == 1
    # A quebra de parágrafo original é preservada dentro do content.
    assert chunks[0].content == text
    _assert_invariants(text, chunks, 200)


def test_cut_prefers_paragraph_breaks() -> None:
    paragraph_a = "A" * 60
    paragraph_b = "B" * 60
    text = f"{paragraph_a}\n\n{paragraph_b}"
    chunks = chunk_text(text, 100, 10)
    # Nenhum chunk mistura os dois parágrafos: o corte caiu na quebra.
    assert len(chunks) == 2
    assert chunks[0].content == paragraph_a
    assert chunks[1].content == paragraph_b
    _assert_invariants(text, chunks, 100)


def test_paragraph_larger_than_chunk_size_is_split_by_char_limit() -> None:
    text = "palavra " * 200  # parágrafo único de 1600 caracteres
    chunks = chunk_text(text, 300, 50)
    assert len(chunks) >= 5
    _assert_invariants(text, chunks, 300)


def test_giant_paragraph_without_whitespace_uses_hard_cuts() -> None:
    text = "x" * 950
    chunks = chunk_text(text, 300, 50)
    _assert_invariants(text, chunks, 300)
    # Sem whitespace onde cortar, as janelas têm exatamente chunk_size e
    # recuam overlap caracteres: 0-300, 250-550, 500-800, 750-950.
    assert [(c.start_char, c.end_char) for c in chunks] == [
        (0, 300),
        (250, 550),
        (500, 800),
        (750, 950),
    ]


# --- Overlap ---------------------------------------------------------------------


def test_zero_overlap_produces_contiguous_windows() -> None:
    text = "x" * 250
    chunks = chunk_text(text, 100, 0)
    assert [(c.start_char, c.end_char) for c in chunks] == [(0, 100), (100, 200), (200, 250)]
    _assert_invariants(text, chunks, 100)


def test_valid_overlap_repeats_window_tail() -> None:
    text = "x" * 250
    chunks = chunk_text(text, 100, 20)
    assert [(c.start_char, c.end_char) for c in chunks] == [(0, 100), (80, 180), (160, 250)]
    # Cada chunk repete os últimos `overlap` caracteres do anterior.
    for previous, current in zip(chunks, chunks[1:], strict=False):
        assert current.start_char == previous.end_char - 20
    _assert_invariants(text, chunks, 100)


# --- Conteúdo, ordem e índices ------------------------------------------------


def test_no_empty_or_whitespace_only_chunks() -> None:
    text = "primeiro\n\n   \n\n\t\n\nsegundo\n\n \n\nterceiro"
    chunks = chunk_text(text, 12, 0)
    assert all(chunk.content.strip() for chunk in chunks)
    _assert_invariants(text, chunks, 12)


def test_order_and_sequential_indices() -> None:
    text = "\n\n".join(f"Parágrafo número {i}." for i in range(20))
    chunks = chunk_text(text, 60, 10)
    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))
    # A ordem do texto original mantém-se na sequência dos chunks.
    numbers = [chunk.content.split()[2] for chunk in chunks if "número" in chunk.content]
    assert numbers == sorted(numbers, key=lambda value: int(value.rstrip(".")))
    _assert_invariants(text, chunks, 60)


def test_offsets_reconstruct_original_content() -> None:
    text = "Regulamento Académico.\n\n" + ("Artigo primeiro. " * 30) + "\n\nDisposições finais."
    chunks = chunk_text(text, 120, 20)
    for chunk in chunks:
        assert text[chunk.start_char : chunk.end_char] == chunk.content
    _assert_invariants(text, chunks, 120)


def test_checksum_is_stable_for_same_content() -> None:
    text = "conteúdo estável"
    first = chunk_text(text, 100, 0)
    second = chunk_text(text, 100, 0)
    assert first[0].content_sha256 == second[0].content_sha256
    assert first[0].content_sha256 == hashlib.sha256(text.encode("utf-8")).hexdigest()


# --- Unicode e idiomas -----------------------------------------------------------


def test_unicode_content_is_preserved_exactly() -> None:
    text = "Émile — «çãoüß» 学生 🎓\n\nSegundo parágrafo com Ωmega."
    chunks = chunk_text(text, 40, 5)
    _assert_invariants(text, chunks, 40)
    assert "".join(text[c.start_char : c.end_char] for c in chunks).count("🎓") == 1


def test_portuguese_text() -> None:
    text = (
        "A matrícula decorre em setembro.\n\n"
        "Os estudantes devem submeter o requerimento na secretaria académica, "
        "acompanhado dos documentos exigidos pelo regulamento."
    )
    chunks = chunk_text(text, 80, 10)
    assert chunks
    _assert_invariants(text, chunks, 80)
    assert chunks[0].normalized_content.startswith("a matricula decorre")


def test_english_text() -> None:
    text = (
        "Enrollment opens in September.\n\n"
        "Students must submit the application form to the academic office, "
        "together with all documents required by the regulation."
    )
    chunks = chunk_text(text, 80, 10)
    assert chunks
    _assert_invariants(text, chunks, 80)
    assert chunks[0].normalized_content == "enrollment opens in september."


def test_chunking_is_deterministic() -> None:
    text = "\n\n".join(
        f"Parágrafo {i} com algum texto adicional para variar o tamanho " * (i % 4 + 1)
        for i in range(12)
    )
    first = chunk_text(text, 150, 30)
    second = chunk_text(text, 150, 30)
    assert first == second


# --- Páginas e estrutura ------------------------------------------------------


def test_multiple_pages_never_share_a_chunk() -> None:
    text = "Conteúdo da página um.\fConteúdo da página dois."
    chunks = chunk_text(text, 200, 20)
    assert [chunk.page_number for chunk in chunks] == [1, 2]
    assert [chunk.content for chunk in chunks] == [
        "Conteúdo da página um.",
        "Conteúdo da página dois.",
    ]
    assert [(chunk.start_char, chunk.end_char) for chunk in chunks] == [
        (0, text.index("\f")),
        (text.index("\f") + 1, len(text)),
    ]
    _assert_invariants(text, chunks, 200)


def test_empty_pages_generate_no_chunks_but_keep_page_numbers() -> None:
    text = "Página um\f   \fPágina três"
    chunks = chunk_text(text, 100, 10)
    assert [(chunk.page_number, chunk.content) for chunk in chunks] == [
        (1, "Página um"),
        (3, "Página três"),
    ]


def test_page_separator_is_not_content_or_gap_loss() -> None:
    text = "A\fB"
    chunks = chunk_text(text, 10, 2)
    assert all("\f" not in chunk.content for chunk in chunks)
    assert chunks[0].end_char + 1 == chunks[1].start_char


def test_small_table_row_stays_whole() -> None:
    text = "Primeiro evento | 05 de outubro de 2040"
    chunks = chunk_text(text, 100, 10)
    assert len(chunks) == 1
    assert chunks[0].content == text
    assert chunks[0].structure_type == "table_row"
    assert chunks[0].chunking_strategy == "structured_v1"


def test_table_rows_are_kept_as_separate_chunks() -> None:
    text = (
        "Evento A | 05 de outubro de 2040\n"
        "Evento B | 12 de outubro de 2040\n"
        "Evento C | 19 de outubro de 2040"
    )
    chunks = chunk_text(text, 500, 20)
    assert [chunk.content for chunk in chunks] == text.splitlines()
    assert [chunk.structure_type for chunk in chunks] == ["table_row"] * 3


def test_synthetic_event_and_date_remain_in_same_table_row() -> None:
    text = "Semana de integração | 05 a 09 de outubro de 2041"
    chunks = chunk_text(text, 80, 10)
    assert len(chunks) == 1
    assert "Semana de integração" in chunks[0].content
    assert "05 a 09 de outubro de 2041" in chunks[0].content


def test_heading_sets_section_title_without_copying_it_to_following_content() -> None:
    heading = "CALENDÁRIO SINTÉTICO 2042/2043"
    text = f"{heading}\n\nPrimeiro período letivo."
    chunks = chunk_text(text, 200, 20)
    assert [chunk.structure_type for chunk in chunks] == ["heading", "paragraph"]
    assert chunks[0].section_title == heading
    assert chunks[1].section_title == heading
    assert chunks[1].content == "Primeiro período letivo."
    assert heading not in chunks[1].content


def test_markdown_heading_is_recognized() -> None:
    chunks = chunk_text("# Secção sintética\n\nConteúdo da secção.", 100, 10)
    assert chunks[0].structure_type == "heading"
    assert chunks[1].section_title == "# Secção sintética"


def test_isolated_short_heading_is_recognized() -> None:
    heading = "Resumo do período"
    chunks = chunk_text(f"{heading}\n\nConteúdo completo da secção.", 100, 10)
    assert [chunk.structure_type for chunk in chunks] == ["heading", "paragraph"]
    assert chunks[1].section_title == heading


def test_short_first_line_of_wrapped_paragraph_is_not_assumed_heading() -> None:
    text = "Resumo breve\ncontinuação do mesmo parágrafo com pontuação."
    chunks = chunk_text(text, 200, 20)
    assert len(chunks) == 1
    assert chunks[0].structure_type == "paragraph"
    assert chunks[0].section_title is None
    assert chunks[0].content == text


def test_paragraphs_in_same_section_can_be_grouped() -> None:
    text = "Primeiro parágrafo.\n\nSegundo parágrafo."
    chunks = chunk_text(text, 200, 20)
    assert len(chunks) == 1
    assert chunks[0].structure_type == "paragraph"
    assert chunks[0].content == text


def test_heading_and_table_row_are_not_packed_together() -> None:
    text = "AGENDA 2044\nEvento sintético | Período sintético"
    chunks = chunk_text(text, 500, 20)
    assert [chunk.structure_type for chunk in chunks] == ["heading", "table_row"]


def test_list_markers_are_preserved_in_list_block() -> None:
    text = "- primeiro item\n- segundo item\n- terceiro item"
    chunks = chunk_text(text, 200, 20)
    assert len(chunks) == 1
    assert chunks[0].structure_type == "list_block"
    assert chunks[0].content == text


def test_single_list_item_keeps_list_item_type() -> None:
    chunks = chunk_text("1) item único", 100, 10)
    assert len(chunks) == 1
    assert chunks[0].structure_type == "list_item"
    assert chunks[0].content.startswith("1)")


def test_blank_line_separates_list_blocks() -> None:
    text = "- item A\n- item B\n\n- item C"
    chunks = chunk_text(text, 200, 20)
    assert [chunk.content for chunk in chunks] == ["- item A\n- item B", "- item C"]
    assert [chunk.structure_type for chunk in chunks] == ["list_block", "list_item"]


def test_large_unit_uses_character_fallback() -> None:
    text = "palavra " * 80
    chunks = chunk_text(text, 90, 15)
    assert len(chunks) > 1
    assert {chunk.structure_type for chunk in chunks} == {"fallback_fragment"}
    assert {chunk.chunking_strategy for chunk in chunks} == {
        "character_fallback_v1"
    }
    _assert_invariants(text, chunks, 90)


def test_large_table_row_uses_fallback_only_inside_that_row() -> None:
    long_row = f"{'evento ' * 30}| {'período ' * 30}"
    text = f"{long_row}\nLinha seguinte | valor"
    chunks = chunk_text(text, 100, 20)
    fallback = [chunk for chunk in chunks if chunk.chunking_strategy == "character_fallback_v1"]
    regular = [chunk for chunk in chunks if chunk.structure_type == "table_row"]
    assert len(fallback) > 1
    assert len(regular) == 1
    assert regular[0].content == "Linha seguinte | valor"
    assert all(chunk.end_char <= len(long_row) for chunk in fallback)


def test_fallback_overlap_stays_inside_same_unit() -> None:
    first = "x" * 250
    second = "Segundo parágrafo curto."
    text = f"{first}\n\n{second}"
    chunks = chunk_text(text, 100, 20)
    fallback = [chunk for chunk in chunks if chunk.structure_type == "fallback_fragment"]
    paragraph = [chunk for chunk in chunks if chunk.structure_type == "paragraph"]
    assert [(chunk.start_char, chunk.end_char) for chunk in fallback] == [
        (0, 100),
        (80, 180),
        (160, 250),
    ]
    assert len(paragraph) == 1
    assert paragraph[0].content == second
    assert fallback[-1].end_char < paragraph[0].start_char


def test_fallback_does_not_cross_page() -> None:
    text = f"{'a' * 180}\f{'b' * 180}"
    chunks = chunk_text(text, 80, 10)
    assert {chunk.page_number for chunk in chunks} == {1, 2}
    assert all("\f" not in chunk.content for chunk in chunks)
    assert all(
        set(chunk.content) <= ({"a"} if chunk.page_number == 1 else {"b"})
        for chunk in chunks
    )


def test_fallback_always_progresses_without_whitespace() -> None:
    chunks = chunk_text("z" * 1000, 37, 36)
    assert chunks
    assert chunks[-1].end_char == 1000
    assert all(
        current.start_char > previous.start_char
        for previous, current in zip(chunks, chunks[1:], strict=False)
    )


def test_crlf_offsets_and_content_are_exact() -> None:
    text = "Primeira linha.\r\nsegunda linha.\r\n\r\nTerceiro parágrafo."
    chunks = chunk_text(text, 200, 20)
    assert len(chunks) == 1
    assert chunks[0].content == text
    _assert_invariants(text, chunks, 200)


def test_ocr_column_separator_classifies_table_row() -> None:
    text = "Campo reconhecido | Valor reconhecido"
    assert chunk_text(text, 100, 10)[0].structure_type == "table_row"


def test_unknown_plain_structure_falls_back_to_paragraph() -> None:
    chunks = chunk_text("§§ bloco experimental sem marcador conhecido", 100, 10)
    assert len(chunks) == 1
    assert chunks[0].structure_type == "paragraph"
    assert chunks[0].chunking_strategy == "structured_v1"


def test_document_with_only_table_has_one_chunk_per_row() -> None:
    text = "A | 1\nB | 2\nC | 3"
    chunks = chunk_text(text, 100, 10)
    assert len(chunks) == 3
    assert all(chunk.structure_type == "table_row" for chunk in chunks)


def test_document_with_only_list_has_list_block() -> None:
    chunks = chunk_text("* alfa\n* beta\n* gama", 100, 10)
    assert len(chunks) == 1
    assert chunks[0].structure_type == "list_block"


def test_document_without_headings_uses_no_section_title() -> None:
    chunks = chunk_text("Texto normal.\n\nOutro parágrafo.", 100, 10)
    assert chunks
    assert all(chunk.section_title is None for chunk in chunks)
