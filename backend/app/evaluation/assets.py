"""Localização, carregamento e rastreio de dados proibidos nos artefactos.

Funciona sem `.env`, base de dados, rede, storage ou credenciais: só
depende da biblioteca padrão, do Pydantic e de
`app.evaluation.contracts`.

Limite declarado da verificação automática
-----------------------------------------
`scan_forbidden_data` procura **padrões técnicos objetivos** — caminhos
locais, chaves, tokens, JWT, private keys, credenciais em URL, URLs fora
do domínio sintético autorizado e identificadores técnicos (UUID, digests
hexadecimais, endereços de correio e endereços IP).

Não consegue provar que um texto em prosa é sintético: não reconhece
nomes, documentos, perguntas ou datas de instituições reais escritos em
linguagem natural. **Não substitui a revisão humana do conteúdo**, que se
mantém como critério de paragem da Fase 1. Por isso o módulo não contém
listas de nomes de instituições concretas: dariam aparência de prova a
uma verificação que não a tem.

Os achados registam o nome do padrão, o caminho JSON e o comprimento da
ocorrência — **nunca o valor encontrado**, que poderia ser um segredo e
acabaria nos logs da CI.
"""

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Final
from urllib.parse import urlsplit

from app.evaluation.contracts import Corpus, Rubric

EVALUATION_DIR: Final = Path(__file__).resolve().parents[2] / "evaluation"
CORPUS_PATH: Final = EVALUATION_DIR / "corpus.v1.json"
CORPUS_SCHEMA_PATH: Final = EVALUATION_DIR / "corpus.schema.json"
RUBRIC_PATH: Final = EVALUATION_DIR / "rubric.v1.json"
RUBRIC_SCHEMA_PATH: Final = EVALUATION_DIR / "rubric.schema.json"

ALLOWED_URL_HOST: Final = "example.invalid"

_FORBIDDEN_PATTERNS: Final[tuple[tuple[str, re.Pattern[str]], ...]] = (
    # Caminho local Windows (C:\... ou C:/...). O lookbehind evita o
    # falso positivo de "https://", onde "s://" imitaria uma unidade.
    ("windows_path", re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/][^\s\"']")),
    ("windows_unc_path", re.compile(r"(?<![A-Za-z0-9])\\\\[A-Za-z0-9_.$-]+\\")),
    # Caminhos Linux e macOS por raiz conhecida.
    (
        "unix_path",
        re.compile(
            r"(?<![A-Za-z0-9])/(?:home|root|etc|var|usr|opt|tmp|mnt|srv|proc)/",
        ),
    ),
    (
        "macos_path",
        re.compile(r"(?<![A-Za-z0-9])/(?:Users|Volumes|Library|Applications|private)/"),
    ),
    ("private_key", re.compile(r"-----BEGIN (?:[A-Z][A-Z ]*)?PRIVATE KEY-----")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")),
    (
        "api_key_or_token",
        re.compile(
            r"\b(?:sk|rk|pk)-[A-Za-z0-9_-]{16,}\b"
            r"|\bAKIA[0-9A-Z]{16}\b"
            r"|\bAIza[0-9A-Za-z_-]{20,}\b"
            r"|\bgh[pousr]_[A-Za-z0-9]{20,}\b"
            r"|\bxox[baprs]-[A-Za-z0-9-]{10,}\b"
        ),
    ),
    # DSN ou URL com credenciais embutidas (esquema://utilizador:segredo@).
    (
        "credentials_in_url",
        re.compile(r"\b[A-Za-z][A-Za-z0-9+.-]*://[^\s/:@]+:[^\s/@]+@"),
    ),
    (
        "uuid",
        re.compile(
            r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
            r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
        ),
    ),
    ("hex_digest", re.compile(r"\b(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})\b")),
    ("email_address", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    (
        "ip_address",
        re.compile(
            r"\b(?:(?:25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9]?[0-9])\.){3}"
            r"(?:25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9]?[0-9])\b"
        ),
    ),
)

_URL_PATTERN: Final = re.compile(r"\bhttps?://[^\s\"'<>]+")


class AssetValidationError(Exception):
    """Um artefacto de avaliação contém dados proibidos.

    A mensagem descreve o padrão e o local; nunca o valor encontrado.
    """


@dataclass(frozen=True)
class ForbiddenDataFinding:
    """Ocorrência de um padrão proibido, sem reproduzir o valor."""

    pattern_name: str
    location: str
    match_length: int


def _escape_pointer_token(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")


def _iter_strings(value: object, pointer: str = "") -> Iterator[tuple[str, str]]:
    """Percorre os valores de string já decodificados do artefacto."""
    if isinstance(value, str):
        yield pointer or "/", value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _iter_strings(item, f"{pointer}/{_escape_pointer_token(str(key))}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _iter_strings(item, f"{pointer}/{index}")


def _url_is_allowed(url: str) -> bool:
    host = urlsplit(url).hostname
    if host is None:
        return False
    return host == ALLOWED_URL_HOST or host.endswith(f".{ALLOWED_URL_HOST}")


def scan_forbidden_data(payload: object) -> tuple[ForbiddenDataFinding, ...]:
    """Procura padrões técnicos proibidos nos valores de string do payload."""
    findings: list[ForbiddenDataFinding] = []
    for location, text in _iter_strings(payload):
        for pattern_name, pattern in _FORBIDDEN_PATTERNS:
            for match in pattern.finditer(text):
                findings.append(
                    ForbiddenDataFinding(pattern_name, location, len(match.group(0)))
                )
        for match in _URL_PATTERN.finditer(text):
            if not _url_is_allowed(match.group(0)):
                findings.append(
                    ForbiddenDataFinding("url_outside_allowlist", location, len(match.group(0)))
                )
    return tuple(findings)


def reject_forbidden_data(payload: object, *, source: str) -> None:
    """Levanta `AssetValidationError` se houver dados proibidos."""
    findings = scan_forbidden_data(payload)
    if not findings:
        return
    detail = "; ".join(
        f"{finding.pattern_name} em {finding.location} (comprimento {finding.match_length})"
        for finding in findings
    )
    msg = f"{source}: {len(findings)} ocorrência(s) de dados proibidos: {detail}"
    raise AssetValidationError(msg)


def validate_corpus_payload(payload: object, *, source: str = "<memória>") -> Corpus:
    """Valida um payload de corpus já carregado (usado também nos testes)."""
    reject_forbidden_data(payload, source=source)
    return Corpus.model_validate(payload)


def validate_rubric_payload(payload: object, *, source: str = "<memória>") -> Rubric:
    """Valida um payload de rubrica já carregado (usado também nos testes)."""
    reject_forbidden_data(payload, source=source)
    return Rubric.model_validate(payload)


def _read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def load_corpus() -> Corpus:
    """Carrega e valida integralmente `backend/evaluation/corpus.v1.json`."""
    return validate_corpus_payload(_read_json(CORPUS_PATH), source=CORPUS_PATH.name)


def load_rubric() -> Rubric:
    """Carrega e valida integralmente `backend/evaluation/rubric.v1.json`."""
    return validate_rubric_payload(_read_json(RUBRIC_PATH), source=RUBRIC_PATH.name)
