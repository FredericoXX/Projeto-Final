"""Motor OCR local e substituível (Tesseract).

Abstração fina sobre o runtime OCR: o serviço de extração depende apenas
do contrato OcrEngine, o que permite injetar motores falsos nos testes
(sem processos externos), simular timeout, indisponibilidade, confiança
baixa e resultados vazios.

Regras estruturais:

- totalmente local e offline: nenhum serviço externo, nenhuma rede,
  nenhum download de modelos em runtime;
- o executável nunca é verificado no import da aplicação — apenas quando
  o OCR é de facto necessário (is_available);
- nunca se usa shell=True nem se constroem comandos com o nome original
  do ficheiro (o pytesseract invoca o executável com argumentos);
- mensagens das exceções são internas e curtas; o stderr do Tesseract
  nunca é propagado para fora deste módulo (fica apenas o tipo no log).
"""

import logging
import shutil
from dataclasses import dataclass
from statistics import mean
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from PIL.Image import Image

logger = logging.getLogger(__name__)

DEFAULT_TESSERACT_COMMAND = "tesseract"


class OcrEngineError(Exception):
    """Falha controlada do runtime OCR (mensagem interna, nunca exposta)."""


class OcrUnavailableError(OcrEngineError):
    """O runtime OCR não está instalado ou não é executável."""


class OcrTimeoutError(OcrEngineError):
    """O OCR excedeu o tempo limite configurado."""


class OcrLanguageError(OcrEngineError):
    """Os dados de idioma configurados não estão instalados."""


@dataclass(frozen=True)
class OcrWord:
    """Uma palavra reconhecida, com geometria e confiança válidas."""

    text: str
    confidence: float
    block: int
    paragraph: int
    line: int
    left: int
    top: int
    width: int
    height: int


@dataclass(frozen=True)
class OcrPageResult:
    """Palavras válidas de uma página e a confiança média (None sem palavras)."""

    words: tuple[OcrWord, ...]
    mean_confidence: float | None


class OcrEngine(Protocol):
    """Contrato mínimo que o serviço de extração usa."""

    def is_available(self) -> bool: ...

    def recognize(self, image: "Image", language: str) -> OcrPageResult: ...


def build_page_result(words: tuple[OcrWord, ...]) -> OcrPageResult:
    """Constrói o resultado da página; a confiança média considera apenas
    palavras válidas (tokens vazios e confianças inválidas já foram
    filtrados em _parse_words)."""
    confidences = [word.confidence for word in words]
    return OcrPageResult(
        words=words,
        mean_confidence=round(mean(confidences), 1) if confidences else None,
    )


def _parse_words(data: dict[str, list[object]]) -> tuple[OcrWord, ...]:
    """Converte a saída tabular do Tesseract em OcrWord, ignorando tokens
    vazios e valores de confiança inválidos (ex.: -1 em linhas
    estruturais ou valores não numéricos)."""
    words: list[OcrWord] = []
    texts = data.get("text", [])
    for index in range(len(texts)):
        raw_text = str(texts[index]).strip()
        if not raw_text:
            continue
        try:
            confidence = float(str(data["conf"][index]))
            block = int(str(data["block_num"][index]))
            paragraph = int(str(data["par_num"][index]))
            line = int(str(data["line_num"][index]))
            left = int(str(data["left"][index]))
            top = int(str(data["top"][index]))
            width = int(str(data["width"][index]))
            height = int(str(data["height"][index]))
        except (KeyError, IndexError, ValueError):
            continue
        if confidence < 0 or confidence > 100:
            continue
        words.append(
            OcrWord(
                text=raw_text,
                confidence=confidence,
                block=block,
                paragraph=paragraph,
                line=line,
                left=left,
                top=top,
                width=width,
                height=height,
            )
        )
    return tuple(words)


class TesseractOcrEngine:
    """Execução local do Tesseract via pytesseract (sem shell=True).

    O import do pytesseract acontece apenas dentro dos métodos: importar
    este módulo — ou arrancar a aplicação — nunca toca no executável.
    """

    def __init__(self, *, command: str | None, timeout_seconds: int) -> None:
        self._command = (command or "").strip() or DEFAULT_TESSERACT_COMMAND
        self._timeout_seconds = timeout_seconds

    def is_available(self) -> bool:
        return shutil.which(self._command) is not None

    def recognize(self, image: "Image", language: str) -> OcrPageResult:
        # Import tardio: nunca no arranque da aplicação. Sem stubs de
        # tipos publicados; o acesso é validado pelos testes.
        import pytesseract  # type: ignore[import-untyped]

        pytesseract.pytesseract.tesseract_cmd = self._command
        try:
            data = pytesseract.image_to_data(
                image,
                lang=language,
                timeout=self._timeout_seconds,
                output_type=pytesseract.Output.DICT,
            )
        except pytesseract.TesseractNotFoundError:
            raise OcrUnavailableError("ocr runtime not found") from None
        except pytesseract.TesseractError as exc:
            # TesseractError herda de RuntimeError: tem de ser tratado
            # primeiro. Nunca propagar o stderr do executável.
            message = str(exc).lower()
            if "language" in message or "tessdata" in message:
                raise OcrLanguageError("ocr language data unavailable") from None
            logger.error("OCR failed: error_type=%s", type(exc).__name__)
            raise OcrEngineError("ocr runtime error") from None
        except RuntimeError as exc:
            # O pytesseract sinaliza timeout com RuntimeError simples.
            if "timeout" in str(exc).lower():
                raise OcrTimeoutError("ocr timed out") from None
            logger.error("OCR failed: error_type=%s", type(exc).__name__)
            raise OcrEngineError("ocr runtime error") from None
        return build_page_result(_parse_words(data))
