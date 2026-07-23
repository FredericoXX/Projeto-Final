"""Reconstrução visual determinística de palavras OCR.

A ordem ``block/paragraph/line`` do Tesseract não é usada para reconstruir
o texto: blocos diferentes podem representar colunas da mesma linha. Esta
camada pura agrupa palavras pela geometria vertical, ordena-as por ``left``
e identifica separações de coluna por medidas relativas à própria linha.

Nenhuma regra procura datas, eventos ou vocabulário institucional. O texto
reconhecido é preservado; a reconstrução apenas acrescenta espaços, quebras
de linha e o separador observável ``" | "``.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from statistics import median

from app.services.ocr_engine import OcrWord

COLUMN_SEPARATOR = " | "

VERTICAL_OVERLAP_FRACTION = 0.45
VERTICAL_CENTER_DISTANCE_FACTOR = 0.35
COLUMN_GAP_CHAR_WIDTH_FACTOR = 3.0
MIN_COLUMN_GAP_FRACTION_OF_HEIGHT = 1.0
COLUMN_GAP_OUTLIER_FACTOR = 2.75
MULTILINE_VERTICAL_GAP_FACTOR = 0.8
MULTILINE_LEFT_ALIGNMENT_FACTOR = 0.6
MULTILINE_RIGHT_ALIGNMENT_FRACTION = 0.35


@dataclass(frozen=True)
class VisualWord:
    """Palavra OCR saneada apenas para cálculos geométricos."""

    text: str
    confidence: float
    left: int
    top: int
    width: int
    height: int
    ordinal: int

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def bottom(self) -> int:
        return self.top + self.height

    @property
    def center_y(self) -> float:
        return self.top + self.height / 2


@dataclass(frozen=True)
class VisualLine:
    """Linha visual individual antes da associação multilinha."""

    top: int
    bottom: int
    left: int
    right: int
    height: float
    words: tuple[VisualWord, ...]
    text: str
    column_count: int
    column_breaks: tuple[int, ...]


@dataclass(frozen=True)
class StructuredLine:
    """Linha final, que pode representar uma continuação multilinha segura."""

    top: int
    bottom: int
    left: int
    right: int
    height: float
    words: tuple[VisualWord, ...]
    text: str
    column_count: int
    source_line_count: int


@dataclass
class _LineBuilder:
    words: list[VisualWord]

    @property
    def center_y(self) -> float:
        return median(word.center_y for word in self.words)

    @property
    def height(self) -> float:
        return max(1.0, median(word.height for word in self.words))

    @property
    def top(self) -> int:
        return min(word.top for word in self.words)

    @property
    def bottom(self) -> int:
        return max(word.bottom for word in self.words)


def _to_visual_words(words: Sequence[OcrWord]) -> list[VisualWord]:
    visual: list[VisualWord] = []
    for ordinal, word in enumerate(words):
        if not word.text or not word.text.strip():
            continue
        if not math.isfinite(word.confidence) or not 0 <= word.confidence <= 100:
            continue
        # Coordenadas anómalas nunca eliminam texto reconhecido. Para a
        # geometria, origens negativas são limitadas a zero e dimensões
        # degeneradas recebem a menor dimensão positiva possível.
        visual.append(
            VisualWord(
                text=word.text,
                confidence=word.confidence,
                left=max(0, word.left),
                top=max(0, word.top),
                width=max(1, word.width),
                height=max(1, word.height),
                ordinal=ordinal,
            )
        )
    return visual


def _vertical_metrics(word: VisualWord, line: _LineBuilder) -> tuple[float, float]:
    intersection = max(0, min(word.bottom, line.bottom) - max(word.top, line.top))
    overlap = intersection / max(1.0, min(float(word.height), line.height))
    center_distance = abs(word.center_y - line.center_y) / max(
        1.0, median((float(word.height), line.height))
    )
    return overlap, center_distance


def _belongs_to_line(word: VisualWord, line: _LineBuilder) -> tuple[float, float] | None:
    overlap, center_distance = _vertical_metrics(word, line)
    if (
        overlap >= VERTICAL_OVERLAP_FRACTION
        or center_distance <= VERTICAL_CENTER_DISTANCE_FACTOR
    ):
        return overlap, center_distance
    return None


def _line_char_width(words: Sequence[VisualWord]) -> float:
    ratios = [word.width / max(1, len(word.text)) for word in words]
    return max(1.0, median(ratios))


def _line_height(words: Sequence[VisualWord]) -> float:
    return max(1.0, median(word.height for word in words))


def _column_breaks(words: Sequence[VisualWord]) -> tuple[int, ...]:
    if len(words) < 2:
        return ()
    char_width = _line_char_width(words)
    line_height = _line_height(words)
    gaps = [
        current.left - previous.right
        for previous, current in zip(words, words[1:], strict=False)
    ]
    base_threshold = max(
        COLUMN_GAP_CHAR_WIDTH_FACTOR * char_width,
        MIN_COLUMN_GAP_FRACTION_OF_HEIGHT * line_height,
    )
    normal_gaps = [gap for gap in gaps if 0 <= gap <= base_threshold]
    typical_gap = median(normal_gaps) if normal_gaps else char_width
    threshold = max(base_threshold, COLUMN_GAP_OUTLIER_FACTOR * typical_gap)
    return tuple(index for index, gap in enumerate(gaps, start=1) if gap > threshold)


def _render_line(words: Sequence[VisualWord]) -> VisualLine:
    ordered = tuple(
        sorted(words, key=lambda word: (word.left, word.top, word.ordinal, word.text))
    )
    breaks = _column_breaks(ordered)
    break_set = set(breaks)
    parts: list[str] = [ordered[0].text]
    for index, word in enumerate(ordered[1:], start=1):
        parts.append(COLUMN_SEPARATOR if index in break_set else " ")
        parts.append(word.text)
    return VisualLine(
        top=min(word.top for word in ordered),
        bottom=max(word.bottom for word in ordered),
        left=min(word.left for word in ordered),
        right=max(word.right for word in ordered),
        height=_line_height(ordered),
        words=ordered,
        text="".join(parts),
        column_count=len(breaks) + 1,
        column_breaks=breaks,
    )


def reconstruct_visual_lines(words: Sequence[OcrWord]) -> tuple[VisualLine, ...]:
    """Agrupa palavras em linhas pela geometria, ignorando IDs do Tesseract."""

    visual_words = _to_visual_words(words)
    if not visual_words:
        return ()
    ordered = sorted(
        visual_words,
        key=lambda word: (word.center_y, word.top, word.left, word.ordinal, word.text),
    )
    builders: list[_LineBuilder] = []
    for word in ordered:
        candidates: list[tuple[float, float, int]] = []
        for index, line in enumerate(builders):
            metrics = _belongs_to_line(word, line)
            if metrics is not None:
                overlap, center_distance = metrics
                candidates.append((-overlap, center_distance, index))
        if not candidates:
            builders.append(_LineBuilder([word]))
            continue
        _, _, best_index = min(candidates)
        builders[best_index].words.append(word)

    lines = [_render_line(builder.words) for builder in builders]
    return tuple(
        sorted(
            lines,
            key=lambda line: (
                median(word.center_y for word in line.words),
                line.top,
                line.left,
                line.text,
            ),
        )
    )


def _as_structured(line: VisualLine) -> StructuredLine:
    return StructuredLine(
        top=line.top,
        bottom=line.bottom,
        left=line.left,
        right=line.right,
        height=line.height,
        words=line.words,
        text=line.text,
        column_count=line.column_count,
        source_line_count=1,
    )


def _can_merge_multiline(previous: StructuredLine, current: VisualLine) -> bool:
    """Heurística geométrica conservadora para uma célula esquerda multilinha."""

    if (
        previous.column_count != 1
        or previous.source_line_count != 1
        or current.column_count < 2
        or not current.column_breaks
        or len(previous.words) < 2
    ):
        return False
    scale = max(1.0, median((previous.height, current.height)))
    vertical_gap = max(0, current.top - previous.bottom)
    if vertical_gap > MULTILINE_VERTICAL_GAP_FACTOR * scale:
        return False
    if abs(previous.left - current.left) > MULTILINE_LEFT_ALIGNMENT_FACTOR * scale:
        return False

    first_column = current.words[: current.column_breaks[0]]
    if not first_column:
        return False
    first_left = first_column[0].left
    first_right = max(word.right for word in first_column)
    first_width = max(1, first_right - first_left)
    right_tolerance = max(
        scale,
        MULTILINE_RIGHT_ALIGNMENT_FRACTION * first_width,
    )
    return (
        previous.right >= first_left + first_width * 0.45
        and abs(previous.right - first_right) <= right_tolerance
    )


def reconstruct_structured_lines(words: Sequence[OcrWord]) -> tuple[StructuredLine, ...]:
    """Produz linhas finais e associa uma continuação apenas com forte geometria."""

    structured: list[StructuredLine] = []
    for line in reconstruct_visual_lines(words):
        if structured and _can_merge_multiline(structured[-1], line):
            previous = structured[-1]
            structured[-1] = StructuredLine(
                top=previous.top,
                bottom=line.bottom,
                left=min(previous.left, line.left),
                right=max(previous.right, line.right),
                height=median((previous.height, line.height)),
                words=previous.words + line.words,
                text=f"{previous.text} {line.text}",
                column_count=line.column_count,
                source_line_count=2,
            )
        else:
            structured.append(_as_structured(line))
    return tuple(structured)


def reconstruct_lines(words: Sequence[OcrWord]) -> str:
    """Reconstrói texto auditável; a mesma entrada produz sempre a mesma saída."""

    return "\n".join(line.text for line in reconstruct_structured_lines(words))
