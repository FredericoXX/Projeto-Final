"""Testes unitários do suporte OCR na extração de documentos.

Tudo sintético e offline: o motor OCR é um fake injetável (nenhum
processo externo), os PDFs digitalizados são imagens geradas em runtime
e o único teste que executa o Tesseract real é o smoke test — ignorado
localmente quando o executável não existe, mas obrigatório no CI.
"""

import io
import json
import os
import shutil
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont

from app.core.config import settings
from app.core.text_normalization import normalize_text
from app.services import document_extraction_service
from app.services.document_extraction_service import (
    EXTRACTION_METHOD_MIXED,
    EXTRACTION_METHOD_NATIVE,
    EXTRACTION_METHOD_OCR,
    EXTRACTION_QUALITY_HIGH,
    EXTRACTION_QUALITY_LOW,
    EXTRACTION_QUALITY_MEDIUM,
    LOW_QUALITY_WARNING,
    OCR_DISABLED_MESSAGE,
    OCR_EMPTY_MESSAGE,
    OCR_FAILED_MESSAGE,
    OCR_PAGE_LIMIT_MESSAGE,
    OCR_TIMEOUT_MESSAGE,
    OCR_UNAVAILABLE_MESSAGE,
    PAGE_SEPARATOR,
    ExtractionError,
    capped_render_scale,
    extract_text,
    resolve_tesseract_language,
)
from app.services.ocr_engine import (
    OcrEngineError,
    OcrPageResult,
    OcrTimeoutError,
    OcrWord,
    _parse_words,
    build_page_result,
)
from app.services.ocr_line_reconstruction import reconstruct_lines
from tests.pdf_utils import build_pdf

# ASCII deliberado: o gerador manual de PDFs dos testes não declara
# encoding Unicode, e acentos fariam roundtrips mojibake no pypdf.
NATIVE_TEXT = "Regulamento sintetico com texto nativo suficiente para nao precisar de OCR."


def _word(
    text: str,
    left: int,
    *,
    confidence: float = 95.0,
    block: int = 1,
    paragraph: int = 1,
    line: int = 1,
    top: int = 0,
    width: int | None = None,
    height: int = 20,
) -> OcrWord:
    return OcrWord(
        text=text,
        confidence=confidence,
        block=block,
        paragraph=paragraph,
        line=line,
        left=left,
        top=top,
        width=width if width is not None else 10 * len(text),
        height=height,
    )


class FakeOcrEngine:
    """Motor OCR falso: devolve páginas pré-definidas, sem processos."""

    def __init__(
        self,
        pages: list[OcrPageResult] | None = None,
        *,
        available: bool = True,
        error: Exception | None = None,
    ) -> None:
        self.pages = list(pages or [])
        self.available = available
        self.error = error
        self.languages: list[str] = []
        self.availability_checks = 0
        self.recognize_calls = 0

    def is_available(self) -> bool:
        self.availability_checks += 1
        return self.available

    def recognize(self, image: object, language: str) -> OcrPageResult:
        self.recognize_calls += 1
        self.languages.append(language)
        if self.error is not None:
            raise self.error
        if self.pages:
            return self.pages.pop(0)
        return build_page_result((_word("SINTETICO", 0), _word("2030", 200)))


def _scanned_pdf_bytes(page_count: int = 1) -> bytes:
    """PDF "digitalizado" sintético: páginas que são apenas imagens."""
    images = [Image.new("RGB", (200, 100), "white") for _ in range(page_count)]
    buffer = io.BytesIO()
    images[0].save(buffer, format="PDF", save_all=True, append_images=images[1:])
    for image in images:
        image.close()
    return buffer.getvalue()


def _mixed_pdf_bytes(tmp_path: Path) -> bytes:
    """PDF misto: página 1 com texto nativo, página 2 digitalizada."""
    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter()
    native = PdfReader(io.BytesIO(build_pdf([NATIVE_TEXT])))
    scanned = PdfReader(io.BytesIO(_scanned_pdf_bytes()))
    writer.add_page(native.pages[0])
    writer.add_page(scanned.pages[0])
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def _write(tmp_path: Path, name: str, content: bytes) -> Path:
    path = tmp_path / name
    path.write_bytes(content)
    return path


# --- Deteção por página e caminhos nativos ----------------------------------


def test_native_pdf_does_not_call_ocr(tmp_path: Path) -> None:
    engine = FakeOcrEngine()
    path = _write(tmp_path, "native.pdf", build_pdf([NATIVE_TEXT]))
    result = extract_text(path, "application/pdf", ocr_engine=engine)
    assert engine.recognize_calls == 0
    assert engine.availability_checks == 0  # runtime só é verificado quando necessário
    assert result.extraction_method == EXTRACTION_METHOD_NATIVE
    assert result.extraction_quality == EXTRACTION_QUALITY_HIGH


def test_native_pdf_preserves_page_count_and_separator(tmp_path: Path) -> None:
    engine = FakeOcrEngine()
    path = _write(tmp_path, "two.pdf", build_pdf([NATIVE_TEXT, NATIVE_TEXT + " Página 2."]))
    result = extract_text(path, "application/pdf", ocr_engine=engine)
    assert result.page_count == 2
    assert result.text.count(PAGE_SEPARATOR) == 1


def test_txt_extraction_is_unchanged(tmp_path: Path) -> None:
    path = _write(tmp_path, "notes.txt", "conteúdo simples".encode())
    result = extract_text(path, "text/plain")
    assert result.text == "conteúdo simples"
    assert result.page_count is None
    assert result.extraction_method == EXTRACTION_METHOD_NATIVE
    assert result.extraction_warning is None
    assert result.page_details == ()


def test_markdown_extraction_is_unchanged(tmp_path: Path) -> None:
    path = _write(tmp_path, "notes.md", b"# Titulo\n\nCorpo do documento.")
    result = extract_text(path, "text/markdown")
    assert "Titulo" in result.text
    assert result.extraction_method == EXTRACTION_METHOD_NATIVE


def test_scanned_pdf_calls_ocr(tmp_path: Path) -> None:
    engine = FakeOcrEngine()
    path = _write(tmp_path, "scanned.pdf", _scanned_pdf_bytes())
    result = extract_text(path, "application/pdf", ocr_engine=engine)
    assert engine.recognize_calls == 1
    assert result.extraction_method == EXTRACTION_METHOD_OCR
    assert "SINTETICO" in result.text


def test_mixed_pdf_runs_ocr_only_on_needed_page(tmp_path: Path) -> None:
    engine = FakeOcrEngine()
    path = _write(tmp_path, "mixed.pdf", _mixed_pdf_bytes(tmp_path))
    result = extract_text(path, "application/pdf", ocr_engine=engine)
    assert engine.recognize_calls == 1  # apenas a página digitalizada
    assert result.extraction_method == EXTRACTION_METHOD_MIXED
    assert result.page_count == 2
    pages = result.text.split(PAGE_SEPARATOR)
    assert "sintetico" in normalize_text(pages[0])
    assert "SINTETICO" in pages[1]
    assert result.page_details[0].method == "native"
    assert result.page_details[1].method == "ocr"


def test_legitimate_empty_page_produces_no_invented_text(tmp_path: Path) -> None:
    engine = FakeOcrEngine()
    path = _write(tmp_path, "with-empty.pdf", build_pdf([NATIVE_TEXT, ""]))
    result = extract_text(path, "application/pdf", ocr_engine=engine)
    assert engine.recognize_calls == 0
    pages = result.text.split(PAGE_SEPARATOR)
    assert pages[1] == ""
    assert result.page_details[1].method == "empty"
    # Páginas vazias não transformam, sozinhas, native noutro método.
    assert result.extraction_method == EXTRACTION_METHOD_NATIVE


# --- Falhas controladas ------------------------------------------------------


def test_ocr_disabled_fails_with_safe_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "document_ocr_enabled", False)
    path = _write(tmp_path, "scanned.pdf", _scanned_pdf_bytes())
    with pytest.raises(ExtractionError, match=OCR_DISABLED_MESSAGE):
        extract_text(path, "application/pdf", ocr_engine=FakeOcrEngine())


def test_missing_runtime_fails_with_safe_message(tmp_path: Path) -> None:
    path = _write(tmp_path, "scanned.pdf", _scanned_pdf_bytes())
    with pytest.raises(ExtractionError, match=OCR_UNAVAILABLE_MESSAGE):
        extract_text(path, "application/pdf", ocr_engine=FakeOcrEngine(available=False))


def test_ocr_language_mapping_pt_and_en(tmp_path: Path) -> None:
    for document_language, expected in (("pt", "por"), ("en", "eng"), ("pt-pt", "por")):
        engine = FakeOcrEngine()
        path = _write(tmp_path, f"scan-{expected}-{document_language}.pdf", _scanned_pdf_bytes())
        extract_text(
            path, "application/pdf", document_language=document_language, ocr_engine=engine
        )
        assert engine.languages == [expected]


def test_unmapped_language_uses_configured_fallback() -> None:
    assert resolve_tesseract_language("el") == settings.document_ocr_languages
    assert resolve_tesseract_language(None) == settings.document_ocr_languages


def test_timeout_is_converted_to_safe_message(tmp_path: Path) -> None:
    path = _write(tmp_path, "scanned.pdf", _scanned_pdf_bytes())
    engine = FakeOcrEngine(error=OcrTimeoutError("interno"))
    with pytest.raises(ExtractionError, match=OCR_TIMEOUT_MESSAGE):
        extract_text(path, "application/pdf", ocr_engine=engine)


def test_internal_error_does_not_expose_details(tmp_path: Path) -> None:
    path = _write(tmp_path, "scanned.pdf", _scanned_pdf_bytes())
    engine = FakeOcrEngine(error=OcrEngineError("stderr secreto com caminho C:/privado"))
    with pytest.raises(ExtractionError) as excinfo:
        extract_text(path, "application/pdf", ocr_engine=engine)
    assert str(excinfo.value) == OCR_FAILED_MESSAGE
    assert "secreto" not in str(excinfo.value)


def test_ocr_page_limit_is_enforced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "document_ocr_max_pages", 1)
    path = _write(tmp_path, "scanned2.pdf", _scanned_pdf_bytes(page_count=2))
    with pytest.raises(ExtractionError, match=OCR_PAGE_LIMIT_MESSAGE):
        extract_text(path, "application/pdf", ocr_engine=FakeOcrEngine())


def test_pixel_limit_caps_render_scale() -> None:
    unlimited = capped_render_scale(612, 792, 300, 25_000_000)
    assert unlimited == pytest.approx(300 / 72.0)
    capped = capped_render_scale(612, 792, 300, 1_000_000)
    assert capped < unlimited
    assert 612 * 792 * capped * capped <= 1_000_000 * 1.001


def test_empty_ocr_result_on_required_page_is_rejected(tmp_path: Path) -> None:
    path = _write(tmp_path, "scanned.pdf", _scanned_pdf_bytes())
    engine = FakeOcrEngine(pages=[build_page_result(())])
    with pytest.raises(ExtractionError, match=OCR_EMPTY_MESSAGE):
        extract_text(path, "application/pdf", ocr_engine=engine)


# --- Reconstrução determinística de linhas -----------------------------------


def test_reconstruction_orders_words_horizontally() -> None:
    words = (
        _word("dia", 90, width=30),
        _word("Primeiro", 0, width=80),
        _word("aulas", 130, width=50),
    )
    assert reconstruct_lines(words) == "Primeiro dia aulas"


def test_close_words_use_single_space_and_large_gap_becomes_column() -> None:
    left_cell = (_word("Evento", 0), _word("sintetico", 70))
    # Intervalo muito maior do que a largura média de carácter da linha.
    right_cell = (_word("05", 600, width=20), _word("de", 640, width=20),
                  _word("outubro", 680, width=70))
    line = reconstruct_lines(left_cell + right_cell)
    assert line == "Evento sintetico | 05 de outubro"


def test_synthetic_event_and_date_stay_on_same_line() -> None:
    words = (
        _word("Inicio", 0),
        _word("das", 80, width=30),
        _word("aulas", 120, width=50),
        _word("05", 700, width=20),
        _word("de", 740, width=20),
        _word("outubro", 780, width=70),
        _word("de", 870, width=20),
        _word("2030", 910, width=40),
    )
    lines = reconstruct_lines(words).splitlines()
    assert len(lines) == 1
    assert lines[0] == "Inicio das aulas | 05 de outubro de 2030"


def test_lines_keep_vertical_order() -> None:
    words = (
        _word("segunda", 0, line=2, top=40),
        _word("primeira", 0, line=1, top=0),
        _word("terceira", 0, block=2, line=1, top=80),
    )
    assert reconstruct_lines(words) == "primeira\nsegunda\nterceira"


def test_conflicting_vertical_coordinates_follow_logical_order() -> None:
    """A ordem vertical é a ordem lógica do Tesseract (block/paragraph/
    line), não o `top` bruto: com coordenadas conflitantes (ex.: colunas
    ou rotações ligeiras), prevalece a ordem de leitura do motor."""
    words = (
        _word("logicamente-primeira", 0, block=1, line=1, top=500),
        _word("logicamente-segunda", 0, block=2, line=1, top=10),
    )
    assert reconstruct_lines(words) == "logicamente-primeira\nlogicamente-segunda"


def test_mean_confidence_ignores_invalid_tokens() -> None:
    data: dict[str, list[object]] = {
        "text": ["ola", "", "  ", "mundo", "ruido"],
        "conf": ["90", "-1", "95", "70.5", "abc"],
        "block_num": ["1"] * 5,
        "par_num": ["1"] * 5,
        "line_num": ["1"] * 5,
        "left": ["0", "10", "20", "30", "40"],
        "top": ["0"] * 5,
        "width": ["30"] * 5,
        "height": ["20"] * 5,
    }
    words = _parse_words(data)
    assert [word.text for word in words] == ["ola", "mundo"]
    result = build_page_result(words)
    assert result.mean_confidence == pytest.approx(80.2, abs=0.1)


# --- Qualidade e agregação ----------------------------------------------------


def _scanned_with_confidence(tmp_path: Path, confidence: float, name: str):
    engine = FakeOcrEngine(
        pages=[build_page_result((_word("EVENTO", 0, confidence=confidence),
                                  _word("2030", 200, confidence=confidence)))]
    )
    path = _write(tmp_path, name, _scanned_pdf_bytes())
    return extract_text(path, "application/pdf", ocr_engine=engine)


def test_quality_high_medium_low(tmp_path: Path) -> None:
    assert (
        _scanned_with_confidence(tmp_path, 92.0, "high.pdf").extraction_quality
        == EXTRACTION_QUALITY_HIGH
    )
    assert (
        _scanned_with_confidence(tmp_path, 70.0, "medium.pdf").extraction_quality
        == EXTRACTION_QUALITY_MEDIUM
    )
    assert (
        _scanned_with_confidence(tmp_path, 30.0, "low.pdf").extraction_quality
        == EXTRACTION_QUALITY_LOW
    )


def test_low_quality_generates_warning_but_not_failure(tmp_path: Path) -> None:
    result = _scanned_with_confidence(tmp_path, 20.0, "warn.pdf")
    # Extração concluída (nenhuma exceção) com aviso persistível.
    assert result.extraction_warning == LOW_QUALITY_WARNING
    assert result.text
    assert result.page_details[0].warning == LOW_QUALITY_WARNING


def test_medium_and_high_quality_have_no_warning(tmp_path: Path) -> None:
    assert _scanned_with_confidence(tmp_path, 70.0, "m2.pdf").extraction_warning is None
    assert _scanned_with_confidence(tmp_path, 95.0, "h2.pdf").extraction_warning is None


def test_aggregate_method_native_ocr_mixed(tmp_path: Path) -> None:
    native = extract_text(
        _write(tmp_path, "agg-native.pdf", build_pdf([NATIVE_TEXT])),
        "application/pdf",
        ocr_engine=FakeOcrEngine(),
    )
    assert native.extraction_method == EXTRACTION_METHOD_NATIVE
    ocr = extract_text(
        _write(tmp_path, "agg-ocr.pdf", _scanned_pdf_bytes()),
        "application/pdf",
        ocr_engine=FakeOcrEngine(),
    )
    assert ocr.extraction_method == EXTRACTION_METHOD_OCR
    mixed = extract_text(
        _write(tmp_path, "agg-mixed.pdf", _mixed_pdf_bytes(tmp_path)),
        "application/pdf",
        ocr_engine=FakeOcrEngine(),
    )
    assert mixed.extraction_method == EXTRACTION_METHOD_MIXED


# --- Conteúdo dos metadados por página ----------------------------------------


def test_page_details_contain_no_full_text_and_no_paths(tmp_path: Path) -> None:
    engine = FakeOcrEngine(
        pages=[build_page_result((_word("CONTEUDOSECRETO", 0), _word("2030", 400)))]
    )
    path = _write(tmp_path, "details.pdf", _scanned_pdf_bytes())
    result = extract_text(path, "application/pdf", ocr_engine=engine)
    serialized = json.dumps([asdict(detail) for detail in result.page_details])
    assert "CONTEUDOSECRETO" in result.text
    assert "CONTEUDOSECRETO" not in serialized
    assert str(tmp_path) not in serialized
    assert "details.pdf" not in serialized
    expected_keys = {
        "page_number",
        "method",
        "native_characters",
        "extracted_characters",
        "ocr_confidence",
        "quality",
        "warning",
    }
    assert set(asdict(result.page_details[0])) == expected_keys


# --- Garantias estruturais -----------------------------------------------------


def test_application_imports_without_ocr_runtime() -> None:
    """O arranque da aplicação nunca importa nem verifica o runtime OCR."""
    code = (
        "import sys; import app.main; "
        "assert 'pytesseract' not in sys.modules, 'pytesseract importado no arranque'; "
        "assert 'pypdfium2' not in sys.modules, 'pypdfium2 importado no arranque'; "
        "print('ok')"
    )
    completed = subprocess.run(  # noqa: S603 — comando fixo, sem shell
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[1],
        timeout=120,
    )
    assert completed.returncode == 0, completed.stderr[-500:]
    assert "ok" in completed.stdout


def test_no_network_no_openai_no_downloads_no_shell_in_ocr_modules() -> None:
    """Análise por AST (código real, não docstrings): os módulos OCR não
    importam bibliotecas de rede/OpenAI e nenhuma chamada usa shell=."""
    import ast
    import inspect

    from app.services import ocr_engine, ocr_line_reconstruction

    forbidden_imports = {"httpx", "requests", "urllib", "openai", "socket"}
    for module in (document_extraction_service, ocr_engine, ocr_line_reconstruction):
        tree = ast.parse(inspect.getsource(module))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = {alias.name.split(".")[0] for alias in node.names}
                assert not (names & forbidden_imports), f"{module.__name__}: import {names}"
            elif isinstance(node, ast.ImportFrom):
                root = (node.module or "").split(".")[0]
                assert root not in forbidden_imports, f"{module.__name__}: from {node.module}"
            elif isinstance(node, ast.Call):
                for keyword in node.keywords:
                    assert keyword.arg != "shell", f"{module.__name__}: chamada com shell="


# --- Smoke test com o Tesseract real ------------------------------------------

_TESSERACT_PRESENT = shutil.which("tesseract") is not None
_RUNNING_IN_CI = os.environ.get("CI", "").lower() in {"1", "true"}

# Localmente o teste é ignorado quando o executável não existe; no CI o
# runtime é instalado pelo workflow e o teste NUNCA pode ser skipped —
# sem Tesseract no CI, falha (em vez de passar em silêncio).
requires_tesseract = pytest.mark.skipif(
    not _TESSERACT_PRESENT and not _RUNNING_IN_CI,
    reason="Tesseract não instalado localmente (obrigatório no CI)",
)


@requires_tesseract
def test_real_ocr_smoke_on_synthetic_scanned_pdf(tmp_path: Path) -> None:
    image = Image.new("RGB", (1600, 500), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=64)
    draw.text((60, 80), "AGENDA ACADEMICA 2030", fill="black", font=font)
    draw.text((60, 260), "EXAMES 05 OUTUBRO", fill="black", font=font)
    pdf_path = tmp_path / "smoke.pdf"
    image.save(pdf_path, format="PDF", resolution=150)
    image.close()

    result = extract_text(pdf_path, "application/pdf", document_language="pt")

    assert result.extraction_method == EXTRACTION_METHOD_OCR
    assert result.page_count == 1
    assert result.text.strip()
    normalized = normalize_text(result.text)
    # Tokens fundamentais normalizados — nunca comparação integral exata,
    # porque pequenas diferenças entre versões do Tesseract são aceitáveis.
    assert "2030" in normalized
    assert "agenda" in normalized
    assert "exames" in normalized
