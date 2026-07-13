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
