"""Segmentação documental estruturada, determinística e local.

O texto persistido é dividido primeiro por páginas (``"\f"``) e depois em
unidades observáveis: títulos, parágrafos, linhas de tabela e itens de lista.
Linhas de tabela pequenas nunca são fundidas entre si. O fallback por
caracteres é usado exclusivamente quando uma unidade individual excede o
limite e nunca atravessa a unidade ou a página.

Todo chunk mantém o invariante:

``content == extracted_text[start_char:end_char]``.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from app.core.document_structure import (
    CHARACTER_FALLBACK_STRATEGY,
    STRUCTURED_STRATEGY,
    ChunkingStrategy,
    StructureType,
)
from app.core.text_normalization import normalize_text

PAGE_SEPARATOR = "\f"
COLUMN_SEPARATOR = " | "

_LINE_BREAK_RE = re.compile(r"\r\n|\r|\n")
_BLANK_LINE_GAP_RE = re.compile(r"(?:\r\n|\r|\n)[ \t]*(?:\r\n|\r|\n)")
_LIST_ITEM_RE = re.compile(r"^(?:[-*•]\s+|\d+[.)]\s+|[A-Za-z][)]\s+)")
_MARKDOWN_HEADING_RE = re.compile(r"^#{1,6}\s+\S")
_NUMBERED_HEADING_RE = re.compile(r"^\d+(?:\.\d+)+(?:[.)])?\s+\S")


@dataclass(frozen=True)
class StructuredUnit:
    """Unidade contígua do texto original antes do empacotamento."""

    start_char: int
    end_char: int
    page_number: int
    structure_type: StructureType
    section_title: str | None
    text: str


@dataclass(frozen=True)
class ChunkData:
    """Segmento do texto original, ainda sem identidade na base de dados."""

    chunk_index: int
    content: str
    normalized_content: str
    content_sha256: str
    start_char: int
    end_char: int
    page_number: int
    section_title: str | None
    structure_type: StructureType
    chunking_strategy: ChunkingStrategy


@dataclass(frozen=True)
class _LineSpan:
    start_char: int
    end_char: int
    text: str

    @property
    def blank(self) -> bool:
        return not self.text


def chunk_text(text: str, chunk_size: int, overlap: int) -> list[ChunkData]:
    """Segmenta ``text`` sem atravessar páginas ou unidades estruturais."""

    _validate_parameters(chunk_size, overlap)
    units = _structured_units(text)
    chunks: list[ChunkData] = []
    pending: list[StructuredUnit] = []

    def flush_pending() -> None:
        if not pending:
            return
        structure_type: StructureType
        if pending[0].structure_type == "list_item":
            structure_type = "list_item" if len(pending) == 1 else "list_block"
        elif all(unit.structure_type == pending[0].structure_type for unit in pending):
            structure_type = pending[0].structure_type
        else:
            structure_type = "mixed"
        _append_regular_chunk(
            chunks,
            text,
            pending[0].start_char,
            pending[-1].end_char,
            pending[0].page_number,
            pending[0].section_title,
            structure_type,
        )
        pending.clear()

    for unit in units:
        if unit.end_char - unit.start_char > chunk_size:
            flush_pending()
            _append_fallback_chunks(chunks, text, unit, chunk_size, overlap)
            continue

        if unit.structure_type in {"heading", "table_row"}:
            flush_pending()
            _append_regular_chunk(
                chunks,
                text,
                unit.start_char,
                unit.end_char,
                unit.page_number,
                unit.section_title,
                unit.structure_type,
            )
            continue

        if pending and not _units_are_compatible(text, pending[-1], unit):
            flush_pending()
        if pending and unit.end_char - pending[0].start_char > chunk_size:
            flush_pending()
        pending.append(unit)

    flush_pending()
    return [
        ChunkData(
            chunk_index=index,
            content=chunk.content,
            normalized_content=chunk.normalized_content,
            content_sha256=chunk.content_sha256,
            start_char=chunk.start_char,
            end_char=chunk.end_char,
            page_number=chunk.page_number,
            section_title=chunk.section_title,
            structure_type=chunk.structure_type,
            chunking_strategy=chunk.chunking_strategy,
        )
        for index, chunk in enumerate(chunks)
    ]


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


def _page_spans(text: str) -> list[tuple[int, int, int]]:
    spans: list[tuple[int, int, int]] = []
    start = 0
    page_number = 1
    for index, character in enumerate(text):
        if character != PAGE_SEPARATOR:
            continue
        spans.append((start, index, page_number))
        start = index + 1
        page_number += 1
    spans.append((start, len(text), page_number))
    return spans


def _line_spans(text: str, start: int, end: int) -> list[_LineSpan]:
    lines: list[_LineSpan] = []
    position = start
    for separator in _LINE_BREAK_RE.finditer(text, start, end):
        trimmed = _trim_region(text, position, separator.start())
        if trimmed is None:
            lines.append(_LineSpan(position, position, ""))
        else:
            line_start, line_end = trimmed
            lines.append(_LineSpan(line_start, line_end, text[line_start:line_end]))
        position = separator.end()
    trimmed = _trim_region(text, position, end)
    if trimmed is None:
        if position < end or not lines:
            lines.append(_LineSpan(position, position, ""))
    else:
        line_start, line_end = trimmed
        lines.append(_LineSpan(line_start, line_end, text[line_start:line_end]))
    return lines


def _is_heading(
    line: str,
    *,
    previous_blank: bool,
    next_blank: bool,
    has_nonblank_after: bool,
) -> bool:
    stripped = line.strip()
    if _MARKDOWN_HEADING_RE.match(stripped):
        return True
    if _NUMBERED_HEADING_RE.match(stripped):
        return True
    if len(stripped) <= 120 and stripped.endswith(":"):
        return True
    letters = [character for character in stripped if character.isalpha()]
    if (
        3 <= len(letters)
        and len(stripped) <= 120
        and sum(character.isupper() for character in letters) / len(letters) >= 0.8
    ):
        return True
    words = stripped.split()
    return (
        previous_blank
        and next_blank
        and has_nonblank_after
        and 1 <= len(words) <= 8
        and len(stripped) <= 80
        and not stripped.endswith((".", "!", "?", ";", ","))
    )


def _classify_lines(lines: list[_LineSpan]) -> list[StructureType | None]:
    has_nonblank_after = [False] * len(lines)
    seen_nonblank = False
    for index in range(len(lines) - 1, -1, -1):
        has_nonblank_after[index] = seen_nonblank
        if not lines[index].blank:
            seen_nonblank = True

    classifications: list[StructureType | None] = []
    for index, line in enumerate(lines):
        if line.blank:
            classifications.append(None)
            continue
        stripped = line.text.strip()
        if COLUMN_SEPARATOR in stripped:
            classifications.append("table_row")
            continue
        if _LIST_ITEM_RE.match(stripped):
            classifications.append("list_item")
            continue
        previous_blank = index == 0 or lines[index - 1].blank
        next_blank = index + 1 < len(lines) and lines[index + 1].blank
        classifications.append(
            "heading"
            if _is_heading(
                stripped,
                previous_blank=previous_blank,
                next_blank=next_blank,
                has_nonblank_after=has_nonblank_after[index],
            )
            else "paragraph"
        )
    return classifications


def _page_units(
    text: str,
    start: int,
    end: int,
    page_number: int,
) -> list[StructuredUnit]:
    lines = _line_spans(text, start, end)
    classifications = _classify_lines(lines)
    units: list[StructuredUnit] = []
    section_title: str | None = None
    index = 0
    while index < len(lines):
        line = lines[index]
        structure_type = classifications[index]
        if structure_type is None:
            index += 1
            continue
        if structure_type == "paragraph":
            paragraph_start = line.start_char
            paragraph_end = line.end_char
            next_index = index + 1
            while (
                next_index < len(lines)
                and classifications[next_index] == "paragraph"
            ):
                paragraph_end = lines[next_index].end_char
                next_index += 1
            units.append(
                StructuredUnit(
                    start_char=paragraph_start,
                    end_char=paragraph_end,
                    page_number=page_number,
                    structure_type="paragraph",
                    section_title=section_title,
                    text=text[paragraph_start:paragraph_end],
                )
            )
            index = next_index
            continue

        observed_title = line.text if structure_type == "heading" else section_title
        units.append(
            StructuredUnit(
                start_char=line.start_char,
                end_char=line.end_char,
                page_number=page_number,
                structure_type=structure_type,
                section_title=observed_title,
                text=text[line.start_char : line.end_char],
            )
        )
        if structure_type == "heading":
            section_title = line.text
        index += 1
    return units


def _structured_units(text: str) -> list[StructuredUnit]:
    units: list[StructuredUnit] = []
    for start, end, page_number in _page_spans(text):
        units.extend(_page_units(text, start, end, page_number))
    return units


def _units_are_compatible(
    text: str,
    previous: StructuredUnit,
    current: StructuredUnit,
) -> bool:
    if (
        previous.page_number != current.page_number
        or previous.section_title != current.section_title
        or previous.structure_type != current.structure_type
    ):
        return False
    if previous.structure_type == "list_item":
        gap = text[previous.end_char : current.start_char]
        return not _BLANK_LINE_GAP_RE.search(gap)
    return previous.structure_type == "paragraph"


def _append_regular_chunk(
    chunks: list[ChunkData],
    text: str,
    start: int,
    end: int,
    page_number: int,
    section_title: str | None,
    structure_type: StructureType,
) -> None:
    trimmed = _trim_region(text, start, end)
    if trimmed is None:
        return
    start_char, end_char = trimmed
    chunks.append(
        _build_chunk(
            len(chunks),
            text,
            start_char,
            end_char,
            page_number,
            section_title,
            structure_type,
            STRUCTURED_STRATEGY,
        )
    )


def _append_fallback_chunks(
    chunks: list[ChunkData],
    text: str,
    unit: StructuredUnit,
    chunk_size: int,
    overlap: int,
) -> None:
    for start, end in _split_long_unit(
        text,
        unit.start_char,
        unit.end_char,
        chunk_size,
        overlap,
    ):
        trimmed = _trim_region(text, start, end)
        if trimmed is None:
            continue
        start_char, end_char = trimmed
        chunks.append(
            _build_chunk(
                len(chunks),
                text,
                start_char,
                end_char,
                unit.page_number,
                unit.section_title,
                "fallback_fragment",
                CHARACTER_FALLBACK_STRATEGY,
            )
        )


def _build_chunk(
    chunk_index: int,
    text: str,
    start_char: int,
    end_char: int,
    page_number: int,
    section_title: str | None,
    structure_type: StructureType,
    chunking_strategy: ChunkingStrategy,
) -> ChunkData:
    content = text[start_char:end_char]
    return ChunkData(
        chunk_index=chunk_index,
        content=content,
        normalized_content=normalize_text(content),
        content_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        start_char=start_char,
        end_char=end_char,
        page_number=page_number,
        section_title=section_title,
        structure_type=structure_type,
        chunking_strategy=chunking_strategy,
    )


def _split_long_unit(
    text: str,
    start: int,
    end: int,
    chunk_size: int,
    overlap: int,
) -> list[tuple[int, int]]:
    regions: list[tuple[int, int]] = []
    position = start
    while position < end:
        window_end = min(position + chunk_size, end)
        if window_end == end:
            regions.append((position, end))
            break
        cut = _preferred_cut(text, position, window_end, overlap)
        regions.append((position, cut))
        next_position = cut - overlap
        if next_position <= position:
            next_position = min(position + 1, end)
        position = next_position
    return regions


def _preferred_cut(text: str, start: int, window_end: int, overlap: int) -> int:
    # Preferência explícita: quebra de linha, depois espaço, depois o
    # limite da janela. O próximo início tem sempre de avançar.
    lower_bound = start + overlap
    for matcher in (_LINE_BREAK_RE, re.compile(r"[ \t]")):
        matches = list(matcher.finditer(text, lower_bound, window_end))
        if matches:
            return matches[-1].end()
    return window_end


def _trim_region(text: str, start: int, end: int) -> tuple[int, int] | None:
    segment = text[start:end]
    left_trimmed = segment.lstrip()
    if not left_trimmed:
        return None
    trimmed_start = start + (len(segment) - len(left_trimmed))
    trimmed_end = trimmed_start + len(left_trimmed.rstrip())
    return trimmed_start, trimmed_end
