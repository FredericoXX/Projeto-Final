"""Extração de texto de ficheiros de documentos (PDF, TXT, Markdown).

Camada pura, sem base de dados: recebe um caminho já resolvido pelo
armazenamento e devolve texto + contagem de páginas. Qualquer falha é
convertida em ExtractionError com uma mensagem curta e segura — sem
traceback, caminhos ou detalhes internos — adequada para ficar em
document_versions.processing_error; os detalhes técnicos vão apenas
para o logging.
"""

import logging
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader

logger = logging.getLogger(__name__)

# Separador entre páginas no texto extraído de PDFs (form feed): preserva
# os limites de página sem inventar marcadores próprios.
PAGE_SEPARATOR = "\f"

NO_TEXT_MESSAGE = "No extractable text was found. OCR is not available in this prototype."
UNDECODABLE_TEXT_MESSAGE = "The file could not be decoded as UTF-8 text."
UNREADABLE_PDF_MESSAGE = "The PDF file could not be read."


class ExtractionError(Exception):
    """Falha de extração com mensagem segura para expor em processing_error."""


@dataclass(frozen=True)
class ExtractionResult:
    text: str
    # None para formatos sem conceito de página (TXT/Markdown).
    page_count: int | None


def extract_text(file_path: Path, mime_type: str) -> ExtractionResult:
    if mime_type == "application/pdf":
        return _extract_pdf(file_path)
    return _extract_plain_text(file_path)


def _extract_pdf(file_path: Path) -> ExtractionResult:
    try:
        # PdfReader lê a estrutura a partir do handle e carrega as páginas
        # à medida que são pedidas, sem exigir o ficheiro inteiro em memória.
        with file_path.open("rb") as handle:
            reader = PdfReader(handle)
            pages = [page.extract_text() or "" for page in reader.pages]
    except Exception as exc:
        logger.error("PDF extraction failed: error_type=%s", type(exc).__name__)
        raise ExtractionError(UNREADABLE_PDF_MESSAGE) from None

    text = PAGE_SEPARATOR.join(pages)
    if not text.strip():
        # PDF só com imagens/digitalizado: sem OCR neste protótipo,
        # não há nada a extrair.
        raise ExtractionError(NO_TEXT_MESSAGE)
    return ExtractionResult(text=text, page_count=len(pages))


def _extract_plain_text(file_path: Path) -> ExtractionResult:
    raw = file_path.read_bytes()
    try:
        # utf-8-sig aceita UTF-8 com ou sem BOM.
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ExtractionError(UNDECODABLE_TEXT_MESSAGE) from exc

    if not text.strip():
        raise ExtractionError(NO_TEXT_MESSAGE)
    return ExtractionResult(text=text, page_count=None)
