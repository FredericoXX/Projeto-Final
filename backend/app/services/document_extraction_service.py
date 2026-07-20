"""Extração de texto de ficheiros de documentos (PDF, TXT, Markdown).

Camada sem base de dados: recebe um caminho já resolvido pelo
armazenamento e devolve texto + metadados de extração. Qualquer falha é
convertida em ExtractionError com uma mensagem curta e segura — sem
traceback, caminhos ou detalhes internos — adequada para ficar em
document_versions.processing_error; os detalhes técnicos vão apenas
para o logging.

PDFs são analisados página a página:

- páginas com texto nativo suficiente usam esse texto (com preservação
  de layout quando o pypdf o suportar, e fallback seguro);
- páginas sem texto pesquisável mas com conteúdo visual passam por OCR
  local (Tesseract), com renderização limitada (DPI e pixels) e
  reconstrução determinística de linhas/colunas simples;
- páginas intencionalmente vazias (sem texto e sem imagens) permanecem
  vazias — nunca se inventa texto;
- a ordem das páginas e o separador PAGE_SEPARATOR nunca mudam.

Heurística de decisão por página (determinística e conservadora):

1. caracteres úteis nativos >= DOCUMENT_OCR_MIN_NATIVE_CHARS -> nativa;
2. senão, se a página tem imagens -> candidata a OCR;
3. senão, se tem algum texto residual (capa, número de página) -> nativa;
4. senão -> página vazia legítima.

O OCR nunca corre em páginas com texto nativo suficiente e o runtime só
é verificado quando alguma página o exige.
"""

import logging
import math
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader

from app.core.config import settings
from app.services.ocr_engine import (
    OcrEngine,
    OcrEngineError,
    OcrLanguageError,
    OcrTimeoutError,
    OcrUnavailableError,
    TesseractOcrEngine,
)
from app.services.ocr_line_reconstruction import reconstruct_lines

logger = logging.getLogger(__name__)

# Separador entre páginas no texto extraído de PDFs (form feed): preserva
# os limites de página sem inventar marcadores próprios.
PAGE_SEPARATOR = "\f"

NO_TEXT_MESSAGE = "No extractable text was found in this document."
UNDECODABLE_TEXT_MESSAGE = "The file could not be decoded as UTF-8 text."
UNREADABLE_PDF_MESSAGE = "The PDF file could not be read."

OCR_DISABLED_MESSAGE = "OCR is required for this document but is disabled."
OCR_UNAVAILABLE_MESSAGE = "OCR is required but the local OCR runtime is unavailable."
OCR_TIMEOUT_MESSAGE = "OCR processing timed out."
OCR_EMPTY_MESSAGE = "OCR could not extract usable text from one or more required pages."
OCR_PAGE_LIMIT_MESSAGE = "The document exceeds the configured OCR page limit."
OCR_LANGUAGE_MESSAGE = "OCR language data for this document is not installed."
OCR_FAILED_MESSAGE = "OCR processing failed for this document."

LOW_QUALITY_WARNING = "OCR completed, but the extracted text may require manual review."

EXTRACTION_METHOD_NATIVE = "native"
EXTRACTION_METHOD_OCR = "ocr"
EXTRACTION_METHOD_MIXED = "mixed"

EXTRACTION_QUALITY_HIGH = "high"
EXTRACTION_QUALITY_MEDIUM = "medium"
EXTRACTION_QUALITY_LOW = "low"

PAGE_METHOD_NATIVE = "native"
PAGE_METHOD_OCR = "ocr"
PAGE_METHOD_EMPTY = "empty"

# Acima desta confiança média o OCR da página é considerado "high";
# abaixo de DOCUMENT_OCR_MIN_CONFIDENCE é "low"; entre ambos, "medium".
HIGH_CONFIDENCE_THRESHOLD = 80.0

# Mapeamento mínimo idioma do documento -> dados de idioma Tesseract.
# Idiomas sem mapeamento usam DOCUMENT_OCR_LANGUAGES (fallback explícito);
# nunca se inventam códigos Tesseract.
_TESSERACT_LANGUAGES: dict[str, str] = {
    "pt": "por",
    "en": "eng",
}


class ExtractionError(Exception):
    """Falha de extração com mensagem segura para expor em processing_error."""


@dataclass(frozen=True)
class PageExtractionDetail:
    """Metadados de uma página — nunca texto integral, imagens ou caminhos."""

    page_number: int
    method: str
    native_characters: int
    extracted_characters: int
    ocr_confidence: float | None
    quality: str
    warning: str | None


@dataclass(frozen=True)
class ExtractionResult:
    text: str
    # None para formatos sem conceito de página (TXT/Markdown).
    page_count: int | None
    # Defaults seguros (native/high): equivalem a uma extração nativa
    # simples e mantêm compatível a construção usada em testes antigos.
    extraction_method: str = EXTRACTION_METHOD_NATIVE
    extraction_quality: str = EXTRACTION_QUALITY_HIGH
    extraction_warning: str | None = None
    page_details: tuple[PageExtractionDetail, ...] = ()


def resolve_tesseract_language(document_language: str | None) -> str:
    """Idioma Tesseract derivado do idioma persistido do documento.

    Usa o subtag primário ("pt-pt" -> "pt"); sem mapeamento conhecido,
    aplica o fallback configurado em DOCUMENT_OCR_LANGUAGES.
    """
    if document_language:
        primary = document_language.strip().lower().split("-")[0]
        mapped = _TESSERACT_LANGUAGES.get(primary)
        if mapped is not None:
            return mapped
    return settings.document_ocr_languages


def extract_text(
    file_path: Path,
    mime_type: str,
    *,
    document_language: str | None = None,
    ocr_engine: OcrEngine | None = None,
) -> ExtractionResult:
    if mime_type == "application/pdf":
        return _extract_pdf(
            file_path, document_language=document_language, ocr_engine=ocr_engine
        )
    return _extract_plain_text(file_path)


# ---------------------------------------------------------------------------
# PDF: análise por página
# ---------------------------------------------------------------------------


def _useful_characters(text: str) -> int:
    """Caracteres úteis: tudo o que não é whitespace."""
    return len("".join(text.split()))


def _page_has_images(page: object) -> bool:
    """Deteção leve de conteúdo visual: XObjects de subtipo Image nos
    recursos da página. Qualquer erro estrutural conta como "sem imagem"
    (a heurística é conservadora; a decisão final continua nos limiares)."""
    try:
        resources = page.get("/Resources")  # type: ignore[attr-defined]
        if resources is None:
            return False
        xobjects = resources.get_object().get("/XObject")
        if xobjects is None:
            return False
        for reference in xobjects.get_object().values():
            if reference.get_object().get("/Subtype") == "/Image":
                return True
    except Exception:
        return False
    return False


def _native_page_text(page: object) -> str:
    """Texto nativo com preservação de layout quando suportado; fallback
    seguro para o modo simples quando o modo layout falhar."""
    try:
        text = page.extract_text(extraction_mode="layout")  # type: ignore[attr-defined]
    except Exception:
        text = None
    if text is None or not text.strip():
        try:
            fallback = page.extract_text()  # type: ignore[attr-defined]
        except Exception:
            return text or ""
        # O modo layout pode legitimamente devolver vazio numa página sem
        # texto; só se usa o fallback quando ele acrescenta conteúdo.
        if fallback and fallback.strip():
            return fallback
    return text or ""


def capped_render_scale(
    width_points: float, height_points: float, dpi: int, max_pixels: int
) -> float:
    """Escala de renderização limitada: parte de dpi/72 e reduz o
    necessário para a página nunca exceder max_pixels."""
    scale = dpi / 72.0
    width_points = max(1.0, width_points)
    height_points = max(1.0, height_points)
    pixels = width_points * height_points * scale * scale
    if pixels > max_pixels:
        scale = math.sqrt(max_pixels / (width_points * height_points))
    return scale


def _render_page_image(file_path: Path, page_index: int):
    """Renderiza apenas a página pedida via pypdfium2, com DPI e pixels
    limitados; a imagem é descartada pelo chamador logo após o OCR."""
    # Import tardio: só quando há OCR a fazer. Sem stubs de tipos
    # publicados; o comportamento é validado pelos testes.
    import pypdfium2 as pdfium  # type: ignore[import-untyped]

    document = pdfium.PdfDocument(str(file_path))
    try:
        page = document[page_index]
        width_points, height_points = page.get_size()
        scale = capped_render_scale(
            width_points,
            height_points,
            settings.document_ocr_dpi,
            settings.document_ocr_max_pixels_per_page,
        )
        bitmap = page.render(scale=scale)
        try:
            return bitmap.to_pil()
        finally:
            bitmap.close()
    finally:
        document.close()


@dataclass(frozen=True)
class _PagePlan:
    page_number: int
    native_text: str
    native_characters: int
    method: str  # PAGE_METHOD_*


def _plan_pages(reader: PdfReader) -> list[_PagePlan]:
    plans: list[_PagePlan] = []
    minimum = settings.document_ocr_min_native_chars
    for index, page in enumerate(reader.pages):
        native_text = _native_page_text(page)
        useful = _useful_characters(native_text)
        if useful >= minimum:
            method = PAGE_METHOD_NATIVE
        elif _page_has_images(page):
            method = PAGE_METHOD_OCR
        elif useful > 0:
            # Pouco texto sem conteúdo visual (capa, número de página):
            # preserva-se o texto nativo, nunca se força OCR.
            method = PAGE_METHOD_NATIVE
        else:
            method = PAGE_METHOD_EMPTY
        plans.append(
            _PagePlan(
                page_number=index + 1,
                native_text=native_text,
                native_characters=useful,
                method=method,
            )
        )
    return plans


def _page_quality(confidence: float | None) -> str:
    if confidence is None:
        return EXTRACTION_QUALITY_LOW
    if confidence < settings.document_ocr_min_confidence:
        return EXTRACTION_QUALITY_LOW
    if confidence >= HIGH_CONFIDENCE_THRESHOLD:
        return EXTRACTION_QUALITY_HIGH
    return EXTRACTION_QUALITY_MEDIUM


_QUALITY_ORDER = {
    EXTRACTION_QUALITY_HIGH: 0,
    EXTRACTION_QUALITY_MEDIUM: 1,
    EXTRACTION_QUALITY_LOW: 2,
}


def _aggregate_quality(details: list[PageExtractionDetail]) -> str:
    """Regra conservadora e documentada: a qualidade agregada é a pior
    qualidade entre as páginas com conteúdo."""
    relevant = [d for d in details if d.method != PAGE_METHOD_EMPTY]
    if not relevant:
        return EXTRACTION_QUALITY_HIGH
    return max(relevant, key=lambda d: _QUALITY_ORDER[d.quality]).quality


def _aggregate_method(details: list[PageExtractionDetail]) -> str:
    """Método agregado sobre as páginas com conteúdo; páginas vazias não
    transformam, sozinhas, native em mixed."""
    methods = {d.method for d in details if d.method != PAGE_METHOD_EMPTY}
    if methods == {PAGE_METHOD_OCR}:
        return EXTRACTION_METHOD_OCR
    if PAGE_METHOD_OCR in methods:
        return EXTRACTION_METHOD_MIXED
    return EXTRACTION_METHOD_NATIVE


def _run_ocr_for_page(
    file_path: Path,
    plan: _PagePlan,
    engine: OcrEngine,
    tesseract_language: str,
) -> tuple[str, float | None]:
    try:
        image = _render_page_image(file_path, plan.page_number - 1)
    except ExtractionError:
        raise
    except Exception as exc:
        logger.error(
            "PDF page render failed: page=%d error_type=%s",
            plan.page_number,
            type(exc).__name__,
        )
        raise ExtractionError(UNREADABLE_PDF_MESSAGE) from None
    try:
        result = engine.recognize(image, tesseract_language)
    except OcrTimeoutError:
        raise ExtractionError(OCR_TIMEOUT_MESSAGE) from None
    except OcrLanguageError:
        raise ExtractionError(OCR_LANGUAGE_MESSAGE) from None
    except OcrUnavailableError:
        raise ExtractionError(OCR_UNAVAILABLE_MESSAGE) from None
    except OcrEngineError as exc:
        logger.error(
            "OCR failed: page=%d error_type=%s", plan.page_number, type(exc).__name__
        )
        raise ExtractionError(OCR_FAILED_MESSAGE) from None
    finally:
        # A imagem nunca fica em memória além do estritamente necessário.
        image.close()
    return reconstruct_lines(result.words), result.mean_confidence


def _extract_pdf(
    file_path: Path,
    *,
    document_language: str | None,
    ocr_engine: OcrEngine | None,
) -> ExtractionResult:
    try:
        # PdfReader lê a estrutura a partir do handle e carrega as páginas
        # à medida que são pedidas, sem exigir o ficheiro inteiro em memória.
        with file_path.open("rb") as handle:
            reader = PdfReader(handle)
            plans = _plan_pages(reader)
    except Exception as exc:
        logger.error("PDF extraction failed: error_type=%s", type(exc).__name__)
        raise ExtractionError(UNREADABLE_PDF_MESSAGE) from None

    ocr_pages = [plan for plan in plans if plan.method == PAGE_METHOD_OCR]
    engine: OcrEngine | None = None
    tesseract_language = resolve_tesseract_language(document_language)
    if ocr_pages:
        if not settings.document_ocr_enabled:
            raise ExtractionError(OCR_DISABLED_MESSAGE)
        if len(ocr_pages) > settings.document_ocr_max_pages:
            raise ExtractionError(OCR_PAGE_LIMIT_MESSAGE)
        engine = ocr_engine if ocr_engine is not None else TesseractOcrEngine(
            command=settings.document_ocr_command,
            timeout_seconds=settings.document_ocr_timeout_seconds,
        )
        # O runtime só é verificado aqui — quando o OCR é mesmo necessário.
        if not engine.is_available():
            raise ExtractionError(OCR_UNAVAILABLE_MESSAGE)

    page_texts: list[str] = []
    details: list[PageExtractionDetail] = []
    for plan in plans:
        if plan.method == PAGE_METHOD_OCR:
            assert engine is not None
            text, confidence = _run_ocr_for_page(file_path, plan, engine, tesseract_language)
            if not text.strip():
                # Página que exigia OCR sem texto utilizável: falha, nunca
                # uma extração parcial escondida como completa.
                raise ExtractionError(OCR_EMPTY_MESSAGE)
            quality = _page_quality(confidence)
            details.append(
                PageExtractionDetail(
                    page_number=plan.page_number,
                    method=PAGE_METHOD_OCR,
                    native_characters=plan.native_characters,
                    extracted_characters=_useful_characters(text),
                    ocr_confidence=confidence,
                    quality=quality,
                    warning=(
                        LOW_QUALITY_WARNING
                        if quality == EXTRACTION_QUALITY_LOW
                        else None
                    ),
                )
            )
            page_texts.append(text)
        elif plan.method == PAGE_METHOD_NATIVE:
            details.append(
                PageExtractionDetail(
                    page_number=plan.page_number,
                    method=PAGE_METHOD_NATIVE,
                    native_characters=plan.native_characters,
                    extracted_characters=plan.native_characters,
                    ocr_confidence=None,
                    quality=EXTRACTION_QUALITY_HIGH,
                    warning=None,
                )
            )
            page_texts.append(plan.native_text)
        else:
            details.append(
                PageExtractionDetail(
                    page_number=plan.page_number,
                    method=PAGE_METHOD_EMPTY,
                    native_characters=0,
                    extracted_characters=0,
                    ocr_confidence=None,
                    quality=EXTRACTION_QUALITY_HIGH,
                    warning=None,
                )
            )
            page_texts.append("")

    text = PAGE_SEPARATOR.join(page_texts)
    if not text.strip():
        # PDF sem qualquer página com texto utilizável.
        raise ExtractionError(NO_TEXT_MESSAGE)

    quality = _aggregate_quality(details)
    return ExtractionResult(
        text=text,
        page_count=len(plans),
        extraction_method=_aggregate_method(details),
        extraction_quality=quality,
        extraction_warning=(
            LOW_QUALITY_WARNING if quality == EXTRACTION_QUALITY_LOW else None
        ),
        page_details=tuple(details),
    )


# ---------------------------------------------------------------------------
# TXT / Markdown (inalterados na substância)
# ---------------------------------------------------------------------------


def _extract_plain_text(file_path: Path) -> ExtractionResult:
    raw = file_path.read_bytes()
    try:
        # utf-8-sig aceita UTF-8 com ou sem BOM.
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ExtractionError(UNDECODABLE_TEXT_MESSAGE) from exc

    if not text.strip():
        raise ExtractionError(NO_TEXT_MESSAGE)
    return ExtractionResult(
        text=text,
        page_count=None,
        extraction_method=EXTRACTION_METHOD_NATIVE,
        extraction_quality=EXTRACTION_QUALITY_HIGH,
        extraction_warning=None,
        page_details=(),
    )
