"""Reconstrução determinística de linhas a partir de palavras OCR.

Camada pura, sem OCR, sem base de dados e sem heurísticas semânticas:
recebe as palavras (com geometria) devolvidas pelo motor OCR e produz o
texto da página linha a linha, preservando a ordem de leitura e a
relação horizontal entre campos de tabelas institucionais simples.

Regras:

1. as palavras são agrupadas por (block, paragraph, line) e as linhas
   são emitidas por essa ordem — a ordem vertical do Tesseract;
2. dentro de cada linha, as palavras são ordenadas pela posição
   horizontal (left);
3. palavras próximas são separadas por um espaço;
4. um intervalo horizontal significativamente maior do que a largura
   média dos caracteres da linha gera o separador de coluna " | " —
   medida relativa, nunca uma quantidade fixa de pixels, porque a escala
   depende da resolução da renderização;
5. nenhuma palavra é alterada, removida, reordenada semanticamente ou
   inventada; a reconstrução representa o layout, não interpreta a tabela.

Exemplo pretendido para uma tabela simples de duas colunas:

    Primeiro dia de aulas do 1.º semestre | 05 de outubro de 2026
"""

from collections.abc import Sequence
from statistics import median

from app.services.ocr_engine import OcrWord

COLUMN_SEPARATOR = " | "

# Um intervalo é considerado separador de coluna quando excede este
# múltiplo da largura média de carácter observada na própria linha.
COLUMN_GAP_CHAR_WIDTH_FACTOR = 3.0

# Salvaguarda inferior: linhas com caracteres muito estreitos (ou larguras
# degeneradas) não devem transformar espaços normais em colunas.
MIN_COLUMN_GAP_FRACTION_OF_HEIGHT = 1.0


def _line_char_width(words: Sequence[OcrWord]) -> float:
    """Largura média de carácter da linha: mediana de width/len(text)
    por palavra — relativa à resolução, estável a outliers."""
    ratios = [word.width / max(1, len(word.text)) for word in words]
    return max(1.0, median(ratios))


def _line_height(words: Sequence[OcrWord]) -> float:
    """Altura mediana das palavras da linha (salvaguarda relativa)."""
    return max(1.0, median(word.height for word in words))


def reconstruct_lines(words: Sequence[OcrWord]) -> str:
    """Reconstrói o texto da página a partir das palavras OCR.

    Determinística: a mesma entrada produz sempre a mesma saída.
    """
    if not words:
        return ""
    lines: dict[tuple[int, int, int], list[OcrWord]] = {}
    for word in words:
        lines.setdefault((word.block, word.paragraph, word.line), []).append(word)

    rendered: list[str] = []
    for key in sorted(lines):
        line_words = sorted(lines[key], key=lambda word: (word.left, word.top, word.text))
        char_width = _line_char_width(line_words)
        line_height = _line_height(line_words)
        column_gap_threshold = max(
            COLUMN_GAP_CHAR_WIDTH_FACTOR * char_width,
            MIN_COLUMN_GAP_FRACTION_OF_HEIGHT * line_height,
        )
        parts: list[str] = [line_words[0].text]
        for previous, current in zip(line_words, line_words[1:], strict=False):
            gap = current.left - (previous.left + previous.width)
            parts.append(COLUMN_SEPARATOR if gap > column_gap_threshold else " ")
            parts.append(current.text)
        rendered.append("".join(parts))
    return "\n".join(rendered)
