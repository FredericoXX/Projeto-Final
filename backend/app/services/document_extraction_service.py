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
2. senão, inspeciona imagens diretas/aninhadas/inline e desenho vetorial;
3. quando necessário, uma renderização pequena distingue conteúdo visual
   de uma página aproximadamente vazia;
4. pouco texto sem outro conteúdo visual permanece nativo;
5. conteúdo visual relevante ou análise inconclusiva -> candidata a OCR;
6. só uma página visualmente vazia permanece vazia.

O OCR nunca corre em páginas com texto nativo suficiente e o runtime só
é verificado quando alguma página o exige.
"""

import logging
import math
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from PIL import Image
from pypdf import PdfReader
from pypdf.generic import ContentStream

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

# A decisão visual usa uma renderização pequena e independente da imagem
# normal do OCR. Assim, a página só é renderizada em alta resolução quando
# o OCR for realmente necessário.
VISUAL_DETECTION_DPI = 72
VISUAL_DETECTION_MAX_PIXELS = 1_000_000

# Ignora a moldura exterior, pequenas diferenças de branco/compressão e
# ruído isolado. Uma página é aproximadamente vazia quando, depois do crop,
# no máximo 0,1% dos pixels difere significativamente da cor de fundo modal.
VISUAL_DETECTION_MARGIN_FRACTION = 0.02
VISUAL_BACKGROUND_TOLERANCE = 18
VISUAL_CONTENT_RATIO_THRESHOLD = 0.001

# Operadores PDF que pintam conteúdo não textual. XObjects ``Do`` são
# percorridos pelos resources sem descodificar imagens; INLINE IMAGE é
# emitido pelo parser do pypdf para BI/EI.
_VISUAL_DRAWING_OPERATORS = frozenset(
    {
        b"INLINE IMAGE",
        b"S",
        b"s",
        b"f",
        b"F",
        b"f*",
        b"B",
        b"B*",
        b"b",
        b"b*",
        b"sh",
    }
)

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


class _VisualState(Enum):
    FILLED = "filled"
    BLANK = "blank"
    INCONCLUSIVE = "inconclusive"


def _inspect_structural_visual_content(page: object) -> _VisualState:
    """Inspeciona conteúdo visual sem confundir uma falha com ausência.

    Percorre os resources e Form XObjects sem descodificar os pixels das
    imagens. Os content streams acrescentam imagens inline e desenho
    vetorial. Ciclos de referência são ignorados de forma determinística.
    """

    def inspect_container(
        container: object,
        pdf: object,
        visited: set[int],
        *,
        is_page: bool,
    ) -> _VisualState:
        resolved = container.get_object()  # type: ignore[attr-defined]
        identity = id(resolved)
        if identity in visited:
            return _VisualState.BLANK
        visited.add(identity)

        resources = resolved.get("/Resources")  # type: ignore[attr-defined]
        if resources is not None:
            resource_dict = resources.get_object()
            xobjects = resource_dict.get("/XObject")
            if xobjects is not None:
                for reference in xobjects.get_object().values():
                    xobject = reference.get_object()
                    subtype = xobject.get("/Subtype")
                    if subtype == "/Image":
                        return _VisualState.FILLED
                    if subtype == "/Form" and inspect_container(
                        xobject, pdf, visited, is_page=False
                    ) == _VisualState.FILLED:
                        return _VisualState.FILLED

        contents = (
            resolved.get_contents()  # type: ignore[attr-defined]
            if is_page
            else ContentStream(resolved, pdf)
        )
        if contents is not None and any(
            operator in _VISUAL_DRAWING_OPERATORS
            for _operands, operator in contents.operations
        ):
            return _VisualState.FILLED
        return _VisualState.BLANK

    try:
        pdf = page.pdf  # type: ignore[attr-defined]
        return inspect_container(page, pdf, set(), is_page=True)
    except Exception as exc:
        logger.warning(
            "PDF structural visual inspection was inconclusive: error_type=%s",
            type(exc).__name__,
        )
        return _VisualState.INCONCLUSIVE


def is_approximately_blank(image: Image.Image) -> bool:
    """Determina, de forma pura, se uma renderização não tem conteúdo útil.

    A cor modal da área interior é usada como fundo, tolerando páginas
    off-white e compressão. A margem exterior é ignorada e uma proporção
    mínima de outliers não transforma ruído isolado em conteúdo.
    """
    grayscale = image.convert("L")
    cropped: Image.Image | None = None
    try:
        width, height = grayscale.size
        margin_x = min(width // 4, int(width * VISUAL_DETECTION_MARGIN_FRACTION))
        margin_y = min(height // 4, int(height * VISUAL_DETECTION_MARGIN_FRACTION))
        if width - 2 * margin_x <= 0 or height - 2 * margin_y <= 0:
            return True
        cropped = grayscale.crop((margin_x, margin_y, width - margin_x, height - margin_y))
        histogram = cropped.histogram()
        total_pixels = cropped.width * cropped.height
        if total_pixels == 0:
            return True
        background = max(range(256), key=histogram.__getitem__)
        content_pixels = sum(
            count
            for value, count in enumerate(histogram)
            if abs(value - background) > VISUAL_BACKGROUND_TOLERANCE
        )
        return content_pixels / total_pixels <= VISUAL_CONTENT_RATIO_THRESHOLD
    finally:
        if cropped is not None:
            cropped.close()
        grayscale.close()


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


def _render_page_image(
    file_path: Path,
    page_index: int,
    *,
    dpi: int | None = None,
    max_pixels: int | None = None,
) -> Image.Image:
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
            dpi if dpi is not None else settings.document_ocr_dpi,
            (
                max_pixels
                if max_pixels is not None
                else settings.document_ocr_max_pixels_per_page
            ),
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


def _rendered_visual_state(file_path: Path, page_index: int) -> _VisualState:
    """Classifica uma página por preview limitado; nunca deixa a imagem aberta."""
    try:
        image = _render_page_image(
            file_path,
            page_index,
            dpi=VISUAL_DETECTION_DPI,
            max_pixels=VISUAL_DETECTION_MAX_PIXELS,
        )
    except Exception as exc:
        logger.warning(
            "PDF visual page inspection was inconclusive: page=%d error_type=%s",
            page_index + 1,
            type(exc).__name__,
        )
        return _VisualState.INCONCLUSIVE
    try:
        return (
            _VisualState.BLANK
            if is_approximately_blank(image)
            else _VisualState.FILLED
        )
    finally:
        image.close()


def _classify_insufficient_page(
    file_path: Path,
    page_index: int,
    page: object,
    native_characters: int,
) -> str:
    structural = _inspect_structural_visual_content(page)

    # Se a estrutura é conclusivamente apenas texto residual, preserva-o
    # sem o duplicar por OCR. Páginas sem texto ainda recebem a verificação
    # visual, para cobrir conteúdo que o parser estrutural não reconheceu.
    if structural == _VisualState.BLANK and native_characters > 0:
        return PAGE_METHOD_NATIVE

    visual = _rendered_visual_state(file_path, page_index)
    if visual == _VisualState.FILLED:
        return PAGE_METHOD_OCR
    if visual == _VisualState.BLANK:
        return PAGE_METHOD_NATIVE if native_characters > 0 else PAGE_METHOD_EMPTY

    # Nunca transformar uma falha estrutural/de renderização em prova de
    # página vazia. O caminho OCR aplicará os limites e erros seguros normais.
    return PAGE_METHOD_OCR


def _plan_pages(reader: PdfReader, file_path: Path) -> list[_PagePlan]:
    plans: list[_PagePlan] = []
    minimum = settings.document_ocr_min_native_chars
    for index, page in enumerate(reader.pages):
        native_text = _native_page_text(page)
        useful = _useful_characters(native_text)
        if useful >= minimum:
            method = PAGE_METHOD_NATIVE
        else:
            method = _classify_insufficient_page(file_path, index, page, useful)
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
            plans = _plan_pages(reader, file_path)
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
