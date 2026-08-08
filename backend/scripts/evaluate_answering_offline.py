"""Avaliação offline determinística do answering (Momento 5, Fase 2).

Uso (a partir de backend/):

    python -m scripts.evaluate_answering_offline \
        --output ../reports/offline.json \
        [--overwrite] [--commit-sha SHA]

Executa os casos sintéticos do corpus aprovado através da camada real de
answering, apura as métricas automáticas A1–A8 e escreve um relatório
JSON de forma atómica. **Não é baseline**: é output de execução. A
baseline oficial e o caminho versionado pertencem à Fase 3.

Nunca chama o fornecedor real, nunca lê ou escreve na base de dados nem
no `storage/` de desenvolvimento.

Códigos de saída:

0 — avaliação concluída;
2 — argumentos ou caminho de saída inválidos;
3 — corpus ou rubrica inválidos;
4 — `commit_sha` ausente, indeterminável ou inválido;
8 — falha ao escrever o relatório;
9 — destino já existe sem --overwrite.
"""

import argparse
import os
import re
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_INVALID_ASSETS = 3
EXIT_COMMIT_SHA = 4
EXIT_WRITE_FAILED = 8
EXIT_OUTPUT_EXISTS = 9

# Caminhos que o relatório nunca pode ocupar: o storage de
# desenvolvimento, os artefactos aprovados da Fase 1 e o diretório do Git.
FORBIDDEN_OUTPUT_PARTS: tuple[tuple[str, ...], ...] = (
    ("storage",),
    ("backend", "evaluation"),
    (".git",),
)

COMMIT_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")


class CommitShaError(RuntimeError):
    """O SHA do commit não pôde ser determinado ou é inválido."""


def _default_repository_root() -> Path:
    # scripts/ vive em backend/scripts; a raiz do repositório é dois
    # níveis acima deste ficheiro.
    return Path(__file__).resolve().parents[2]


def _error(message: str) -> None:
    # Erros controlados: mensagem curta em stderr, sem traceback e sem
    # qualquer valor de credencial.
    print(f"error: {message}", file=sys.stderr)


def neutralise_provider_environment() -> None:
    """Torna indisponível qualquer credencial de fornecedor.

    Tem de correr **antes** do primeiro import que carregue
    `app.core.config.settings`. As variáveis de ambiente precedem o
    `env_file` na resolução das Settings, e o `env_file` configurado é um
    caminho absoluto — mudar de diretoria de trabalho não bastaria. Com
    isto, a chave nunca fica disponível em `settings`, e o provider ativo
    passa a um valor que nenhum adaptador reconhece.
    """
    os.environ["OPENAI_API_KEY"] = ""
    os.environ["OPENAI_MODEL"] = ""
    os.environ["ANSWER_GENERATOR_PROVIDER"] = "offline-disabled"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="evaluate_answering_offline",
        description="Avaliação offline determinística do answering (população P1).",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--commit-sha", type=str, default=None)
    return parser


def resolve_commit_sha(provided: str | None, repository_root: Path) -> str:
    """Devolve o SHA completo, ou levanta — nunca devolve `None`.

    Um relatório sem proveniência não serve para comparar execuções, por
    isso a ausência é erro explícito e não um campo nulo.
    """
    if provided is not None:
        candidate = provided.strip().lower()
    else:
        try:
            completed = subprocess.run(  # noqa: S603 - comando fixo, sem entrada externa
                ["git", "rev-parse", "HEAD"],
                cwd=repository_root,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            msg = "git is not available to determine the commit SHA"
            raise CommitShaError(msg) from exc
        if completed.returncode != 0:
            msg = "git could not determine the commit SHA"
            raise CommitShaError(msg)
        candidate = completed.stdout.strip().lower()
    if not COMMIT_SHA_PATTERN.match(candidate):
        msg = "the commit SHA must be a full 40-character hexadecimal value"
        raise CommitShaError(msg)
    return candidate


def _is_inside(base: Path, candidate: Path) -> bool:
    try:
        candidate.relative_to(base)
    except ValueError:
        return False
    return True


def validate_output_path(
    output: Path, repository_root: Path, overwrite: bool
) -> tuple[Path | None, int]:
    resolved = (output if output.is_absolute() else Path.cwd() / output).resolve()
    root = repository_root.resolve()
    if resolved.suffix != ".json":
        _error("--output must end with '.json'")
        return None, EXIT_USAGE
    for parts in FORBIDDEN_OUTPUT_PARTS:
        if _is_inside(root.joinpath(*parts), resolved):
            _error(f"--output must not be inside {'/'.join(parts)}/")
            return None, EXIT_USAGE
    if not resolved.parent.is_dir():
        _error("the parent directory of --output does not exist")
        return None, EXIT_USAGE
    if resolved.is_dir():
        _error("--output points to a directory")
        return None, EXIT_USAGE
    if resolved.exists() and not overwrite:
        _error("the output file already exists; pass --overwrite to replace it")
        return None, EXIT_OUTPUT_EXISTS
    return resolved, EXIT_OK


def main(
    argv: list[str] | None = None,
    *,
    repository_root: Path | None = None,
    clock: Callable[[], datetime] | None = None,
) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if exc.code is not None else EXIT_USAGE

    root = repository_root if repository_root is not None else _default_repository_root()
    output_path, exit_code = validate_output_path(args.output, root, args.overwrite)
    if output_path is None:
        return exit_code

    # Resolvido antes de qualquer execução: sem proveniência não se
    # produz relatório nenhum.
    try:
        commit_sha = resolve_commit_sha(args.commit_sha, root)
    except CommitShaError as exc:
        _error(str(exc))
        return EXIT_COMMIT_SHA

    # A neutralização precede o primeiro import de `app`; daí os imports
    # tardios abaixo serem deliberados e não um descuido de estilo.
    neutralise_provider_environment()

    from pydantic import ValidationError

    from app.evaluation.assets import AssetValidationError
    from app.evaluation.results import (
        REPORT_SCHEMA_VERSION,
        EvaluationReport,
        ExecutionMetadata,
        atomic_write_text,
        compute_result_digest,
        report_file_text,
    )
    from app.evaluation.runner import run_offline_evaluation

    try:
        results = run_offline_evaluation()
    except (AssetValidationError, ValidationError) as exc:
        _error(f"the evaluation assets are invalid: {type(exc).__name__}")
        return EXIT_INVALID_ASSETS

    results_payload = results.model_dump(mode="json")
    executed_at = (clock() if clock is not None else datetime.now(UTC)).isoformat()
    report = EvaluationReport(
        report_schema_version=REPORT_SCHEMA_VERSION,
        results=results,
        result_digest=compute_result_digest(results_payload),
        execution_metadata=ExecutionMetadata(
            executed_at=executed_at,
            commit_sha=commit_sha,
            output_path=output_path.as_posix(),
        ),
    )

    try:
        atomic_write_text(
            output_path,
            report_file_text(report.model_dump(mode="json")),
            overwrite=args.overwrite,
        )
    except FileExistsError:
        # A verificação prévia é apenas conveniência: a decisão vinculativa
        # é a da publicação, que vê o destino tal como está nesse instante.
        _error("the output file already exists; pass --overwrite to replace it")
        return EXIT_OUTPUT_EXISTS
    except OSError:
        _error("failed to write the report file")
        return EXIT_WRITE_FAILED

    # Terminal: apenas contagens, digest e caminho — nunca conteúdo de
    # casos, perguntas, respostas ou credenciais.
    print(f"offline evaluation completed: cases={results.case_count}")
    print(f"population={results.population}")
    print(f"result_digest={report.result_digest}")
    print(f"report={output_path.as_posix()}")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
