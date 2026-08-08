"""Testes do entrypoint da avaliação offline (Momento 5, Fase 2).

O relatório produzido aqui é output de execução, nunca baseline: é sempre
escrito em diretorias temporárias do teste.
"""

import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from app.evaluation.results import compute_result_digest
from scripts.evaluate_answering_offline import (
    EXIT_COMMIT_SHA,
    EXIT_OK,
    EXIT_OUTPUT_EXISTS,
    EXIT_USAGE,
    CommitShaError,
    main,
    resolve_commit_sha,
)

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = BACKEND_DIR.parent
VALID_SHA = "0123456789abcdef0123456789abcdef01234567"


# --- Anulação das fixtures de base de dados do conftest ------------------------


@pytest.fixture(scope="session", autouse=True)
def _override_get_db() -> None:
    """Anula a fixture homónima do conftest: aqui não há dependência de DB."""


@pytest.fixture(autouse=True)
def _clean_tables() -> None:
    """Anula a fixture homónima do conftest: aqui não há tabelas a truncar."""


@pytest.fixture(autouse=True)
def _restore_provider_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """O CLI neutraliza variáveis do fornecedor no processo.

    Registá-las no monkeypatch garante que o valor original é reposto no
    fim de cada teste, mesmo tendo sido o CLI a escrevê-las.
    """
    for name in ("OPENAI_API_KEY", "OPENAI_MODEL", "ANSWER_GENERATOR_PROVIDER"):
        monkeypatch.setenv(name, os.environ.get(name, ""))


def _clock() -> datetime:
    return datetime(2026, 8, 7, 12, 0, 0, tzinfo=UTC)


def _run(output: Path, *extra: str, root: Path | None = None) -> int:
    argv = ["--output", str(output), "--commit-sha", VALID_SHA, *extra]
    return main(argv, repository_root=root or REPOSITORY_ROOT, clock=_clock)


# --- Execução feliz ------------------------------------------------------------


def test_cli_writes_a_valid_report(tmp_path: Path) -> None:
    output = tmp_path / "offline.json"
    assert _run(output) == EXIT_OK

    report: dict[str, Any] = json.loads(output.read_text(encoding="utf-8"))
    assert report["report_schema_version"] == "1"
    assert report["results"]["population"] == "P1"
    assert report["results"]["case_count"] == 19
    assert report["execution_metadata"]["commit_sha"] == VALID_SHA
    assert report["execution_metadata"]["digest_algorithm"] == "sha256"
    assert report["execution_metadata"]["executed_at"] == _clock().isoformat()


def test_digest_in_the_file_is_verifiable_from_the_file(tmp_path: Path) -> None:
    output = tmp_path / "offline.json"
    assert _run(output) == EXIT_OK
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["result_digest"] == compute_result_digest(report["results"])


def test_two_runs_produce_the_same_digest(tmp_path: Path) -> None:
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    assert _run(first) == EXIT_OK
    assert _run(second) == EXIT_OK
    first_report = json.loads(first.read_text(encoding="utf-8"))
    second_report = json.loads(second.read_text(encoding="utf-8"))
    assert first_report["results"] == second_report["results"]
    assert first_report["result_digest"] == second_report["result_digest"]
    # O caminho de saída difere e não participa no digest.
    assert (
        first_report["execution_metadata"]["output_path"]
        != second_report["execution_metadata"]["output_path"]
    )


# --- Validação do caminho de saída ---------------------------------------------


def test_output_must_be_json(tmp_path: Path) -> None:
    assert _run(tmp_path / "relatorio.txt") == EXIT_USAGE


def test_output_parent_must_exist(tmp_path: Path) -> None:
    assert _run(tmp_path / "inexistente" / "offline.json") == EXIT_USAGE


@pytest.mark.parametrize(
    "relative",
    ["storage/offline.json", "backend/evaluation/offline.json", ".git/offline.json"],
)
def test_output_is_refused_in_protected_directories(relative: str) -> None:
    target = REPOSITORY_ROOT / relative
    assert _run(target) == EXIT_USAGE
    assert not target.exists()


def test_existing_output_is_not_overwritten_silently(tmp_path: Path) -> None:
    output = tmp_path / "offline.json"
    output.write_text("conteúdo anterior", encoding="utf-8")
    assert _run(output) == EXIT_OUTPUT_EXISTS
    assert output.read_text(encoding="utf-8") == "conteúdo anterior"


def test_overwrite_replaces_the_existing_report(tmp_path: Path) -> None:
    output = tmp_path / "offline.json"
    output.write_text("conteúdo anterior", encoding="utf-8")
    assert _run(output, "--overwrite") == EXIT_OK
    assert json.loads(output.read_text(encoding="utf-8"))["results"]["case_count"] == 19


def test_atomic_write_leaves_no_temporary_files(tmp_path: Path) -> None:
    output = tmp_path / "offline.json"
    assert _run(output) == EXIT_OK
    assert [path.name for path in tmp_path.iterdir()] == ["offline.json"]


def _publish_race(monkeypatch: pytest.MonkeyPatch, output: Path, content: str) -> None:
    """Faz aparecer `output` depois da validação e antes da publicação.

    `main` importa `report_file_text` já dentro da sua execução, pelo que
    substituir o atributo no módulo de origem intercepta exatamente o
    instante entre a validação do caminho e a escrita do relatório.
    """
    from app.evaluation import results as results_module

    original = results_module.report_file_text

    def _racing_report_file_text(payload: object) -> str:
        output.write_text(content, encoding="utf-8")
        return original(payload)

    monkeypatch.setattr(results_module, "report_file_text", _racing_report_file_text)


def test_concurrently_created_output_is_never_replaced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regressão: o destino nasce entre a validação e a publicação.

    A verificação prévia vê o caminho livre; outro processo cria lá um
    ficheiro; sem --overwrite a publicação tem de falhar e preservar o
    conteúdo alheio.
    """
    output = tmp_path / "offline.json"
    assert not output.exists()
    _publish_race(monkeypatch, output, "created-by-other-process")

    assert _run(output) == EXIT_OUTPUT_EXISTS
    assert output.read_text(encoding="utf-8") == "created-by-other-process"
    assert [path.name for path in tmp_path.iterdir()] == ["offline.json"]


def test_overwrite_still_replaces_a_concurrently_created_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "offline.json"
    _publish_race(monkeypatch, output, "created-by-other-process")

    assert _run(output, "--overwrite") == EXIT_OK
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["results"]["case_count"] == 19
    assert [path.name for path in tmp_path.iterdir()] == ["offline.json"]


# --- commit_sha obrigatório -----------------------------------------------------


@pytest.mark.parametrize("invalid", ["", "abc", "0123456789abcdef", "Z" * 40, "0" * 39])
def test_invalid_commit_sha_produces_no_report(tmp_path: Path, invalid: str) -> None:
    output = tmp_path / "offline.json"
    exit_code = main(
        ["--output", str(output), "--commit-sha", invalid],
        repository_root=REPOSITORY_ROOT,
        clock=_clock,
    )
    assert exit_code == EXIT_COMMIT_SHA
    assert not output.exists()


def test_commit_sha_is_read_from_git_when_omitted() -> None:
    resolved = resolve_commit_sha(None, REPOSITORY_ROOT)
    assert len(resolved) == 40
    assert resolved == resolved.lower()


def test_commit_sha_fails_outside_a_repository(tmp_path: Path) -> None:
    with pytest.raises(CommitShaError):
        resolve_commit_sha(None, tmp_path)


def test_uppercase_commit_sha_is_normalised() -> None:
    assert resolve_commit_sha(VALID_SHA.upper(), REPOSITORY_ROOT) == VALID_SHA


# --- Isolamento do fornecedor e da rede, em subprocesso -------------------------


_ISOLATION_SNIPPET = """
import builtins
import io
import os
import socket
import sys
from pathlib import Path

PROJECT_ROOT = Path.cwd().resolve().parent
STORAGE_ROOT = PROJECT_ROOT / "storage"


class IsolationBreach(RuntimeError):
    pass


def _blocked_network(*args, **kwargs):
    raise IsolationBreach("tentativa de acesso a rede")


class _BlockedSocket(socket.socket):
    def __init__(self, *args, **kwargs):
        raise IsolationBreach("tentativa de acesso a rede")


socket.socket = _BlockedSocket
socket.create_connection = _blocked_network

_real_open = builtins.open


def _guarded_open(file, *args, **kwargs):
    try:
        candidate = Path(os.fspath(file)).resolve()
    except TypeError:
        return _real_open(file, *args, **kwargs)
    if candidate == STORAGE_ROOT or STORAGE_ROOT in candidate.parents:
        raise IsolationBreach("tentativa de acesso ao storage de desenvolvimento")
    return _real_open(file, *args, **kwargs)


builtins.open = _guarded_open
io.open = _guarded_open

try:
    socket.socket()
except IsolationBreach:
    pass
else:
    raise SystemExit("guarda de rede inativa")

try:
    _guarded_open(STORAGE_ROOT / "sonda.txt")
except IsolationBreach:
    pass
else:
    raise SystemExit("guarda de storage inativa")

from scripts.evaluate_answering_offline import main

code = main(["--output", sys.argv[1], "--commit-sha", sys.argv[2]])
if code != 0:
    raise SystemExit("o CLI terminou com codigo " + str(code))

from app.core.config import settings

if settings.openai_api_key not in (None, ""):
    raise SystemExit("credencial do fornecedor disponivel em settings")
if settings.openai_model not in (None, ""):
    raise SystemExit("modelo do fornecedor disponivel em settings")
if settings.answer_generator_provider != "offline-disabled":
    raise SystemExit("provider ativo inesperado")

from app.answering.base import AnswerGeneratorUnavailableError
from app.answering.dependencies import get_answer_generator

try:
    get_answer_generator()
except AnswerGeneratorUnavailableError:
    pass
else:
    raise SystemExit("o provider ativo devolveu um gerador utilizavel")

print("ok")
"""


def test_cli_runs_without_provider_credentials_or_network(tmp_path: Path) -> None:
    """Prova, num processo limpo, o que o processo do pytest não pode.

    O subprocesso instala guardas de rede e de storage, corre o CLI e só
    depois inspeciona as Settings. Nenhuma credencial é impressa: as
    verificações comparam e falham com mensagem própria.
    """
    output = tmp_path / "offline.json"
    environment = {
        key: value
        for key, value in os.environ.items()
        if key not in {"OPENAI_API_KEY", "OPENAI_MODEL", "ANSWER_GENERATOR_PROVIDER"}
    }
    environment["PYTHONPATH"] = str(BACKEND_DIR)

    result = subprocess.run(  # noqa: S603 - comando fixo, sem entrada externa
        [sys.executable, "-c", _ISOLATION_SNIPPET, str(output), VALID_SHA],
        cwd=BACKEND_DIR,
        env=environment,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "ok" in result.stdout
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["results"]["case_count"] == 19
    assert report["result_digest"] == compute_result_digest(report["results"])
