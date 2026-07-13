"""Segmentação determinística do texto extraído em chunks.

Camada pura, sem base de dados, LLM, tokenizer ou fornecedor externo:
recebe texto e devolve segmentos com offsets sobre o texto original,
sempre com o mesmo resultado para o mesmo input.

Estratégia:

1. o texto é dividido em parágrafos (separados por linhas em branco),
   preservando a ordem original;
2. parágrafos consecutivos são agrupados no mesmo chunk enquanto o
   intervalo total não exceder chunk_size — os cortes preferem sempre as
   quebras de parágrafo;
3. um parágrafo maior do que chunk_size é cortado por limite de
   caracteres, preferindo a última quebra de linha ou espaço dentro da
   janela, com sobreposição de `overlap` caracteres entre cortes
   consecutivos (decisão técnica documentada: a sobreposição aplica-se
   aos cortes forçados dentro de um parágrafo grande; entre chunks
   alinhados a parágrafos o corte é a própria quebra de parágrafo);
4. nenhum chunk excede chunk_size, nenhum chunk é vazio ou composto
   apenas por espaços, e content == texto_original[start_char:end_char]
   (end_char exclusivo).

O conteúdo nunca é resumido, reordenado ou alterado semanticamente.
"""

import hashlib
import re
from dataclasses import dataclass

from app.core.text_normalization import normalize_text

_PARAGRAPH_SEPARATOR_RE = re.compile(r"\n\s*\n")


@dataclass(frozen=True)
class ChunkData:
    """Um segmento do texto original, ainda sem identidade na base de dados."""

    chunk_index: int
    content: str
    normalized_content: str
    content_sha256: str
    start_char: int
    end_char: int


def chunk_text(text: str, chunk_size: int, overlap: int) -> list[ChunkData]:
    """Divide ``text`` em chunks determinísticos de, no máximo, ``chunk_size``
    caracteres, com ``overlap`` caracteres de sobreposição nos cortes
    forçados. Texto vazio ou só com espaços devolve uma lista vazia."""
    _validate_parameters(chunk_size, overlap)

    regions: list[tuple[int, int]] = []
    pack_start: int | None = None
    pack_end = 0

    for paragraph_start, paragraph_end in _paragraph_spans(text):
        if paragraph_end - paragraph_start > chunk_size:
            # Parágrafo maior do que o limite: fecha o agrupamento em curso
            # e corta o parágrafo por janelas de caracteres.
            if pack_start is not None:
                regions.append((pack_start, pack_end))
                pack_start = None
            regions.extend(
                _split_long_paragraph(text, paragraph_start, paragraph_end, chunk_size, overlap)
            )
        elif pack_start is None:
            pack_start, pack_end = paragraph_start, paragraph_end
        elif paragraph_end - pack_start <= chunk_size:
            # O parágrafo cabe no chunk em curso (o intervalo inclui a
            # própria quebra de parágrafo, preservada no content).
            pack_end = paragraph_end
        else:
            regions.append((pack_start, pack_end))
            pack_start, pack_end = paragraph_start, paragraph_end

    if pack_start is not None:
        regions.append((pack_start, pack_end))

    chunks: list[ChunkData] = []
    for region_start, region_end in regions:
        trimmed = _trim_region(text, region_start, region_end)
        if trimmed is None:
            continue
        start_char, end_char = trimmed
        content = text[start_char:end_char]
        chunks.append(
            ChunkData(
                chunk_index=len(chunks),
                content=content,
                normalized_content=normalize_text(content),
                content_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
                start_char=start_char,
                end_char=end_char,
            )
        )
    return chunks


def _validate_parameters(chunk_size: int, overlap: int) -> None:
    if chunk_size <= 0:
        msg = "chunk_size must be greater than zero"
        raise ValueError(msg)
    if overlap < 0:
        msg = "overlap must not be negative"
        raise ValueError(msg)
    if overlap >= chunk_size:
        msg = "overlap must be smaller than chunk_size"
        raise ValueError(msg)


def _paragraph_spans(text: str) -> list[tuple[int, int]]:
    """Intervalos [start, end) dos parágrafos não vazios, já sem espaços
    nas extremidades, pela ordem original."""
    raw_spans: list[tuple[int, int]] = []
    position = 0
    for separator in _PARAGRAPH_SEPARATOR_RE.finditer(text):
        raw_spans.append((position, separator.start()))
        position = separator.end()
    raw_spans.append((position, len(text)))

    spans: list[tuple[int, int]] = []
    for span_start, span_end in raw_spans:
        trimmed = _trim_region(text, span_start, span_end)
        if trimmed is not None:
            spans.append(trimmed)
    return spans


def _split_long_paragraph(
    text: str,
    start: int,
    end: int,
    chunk_size: int,
    overlap: int,
) -> list[tuple[int, int]]:
    """Corta [start, end) em janelas de até chunk_size caracteres,
    preferindo terminar na última quebra de linha ou espaço da janela e
    recuando `overlap` caracteres entre cortes consecutivos."""
    regions: list[tuple[int, int]] = []
    position = start
    while position < end:
        window_end = min(position + chunk_size, end)
        if window_end == end:
            regions.append((position, end))
            break
        cut = _preferred_cut(text, position, window_end, overlap)
        regions.append((position, cut))
        position = cut - overlap
    return regions


def _preferred_cut(text: str, start: int, window_end: int, overlap: int) -> int:
    """Posição de corte dentro da janela: depois do último whitespace que
    ainda garante progresso (o próximo início, cut - overlap, tem de
    avançar); sem whitespace utilizável, corta no limite da janela."""
    for index in range(window_end - 1, start + overlap - 1, -1):
        if text[index].isspace():
            return index + 1
    return window_end


def _trim_region(text: str, start: int, end: int) -> tuple[int, int] | None:
    """Encolhe [start, end) até aos limites sem whitespace; None se o
    intervalo não tiver conteúdo útil."""
    segment = text[start:end]
    left_trimmed = segment.lstrip()
    if not left_trimmed:
        return None
    trimmed_start = start + (len(segment) - len(left_trimmed))
    trimmed_end = trimmed_start + len(left_trimmed.rstrip())
    return trimmed_start, trimmed_end
