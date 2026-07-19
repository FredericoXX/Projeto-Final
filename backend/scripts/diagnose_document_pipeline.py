"""Diagnóstico read-only do pipeline documental (CLI).

Uso (a partir de backend/):

    python -m scripts.diagnose_document_pipeline \
        --institution-id UUID \
        --questions-file PATH \
        --output ../docs/diagnostics/generated/relatorio.md \
        (--document-id UUID | --version-id UUID | --filename TEXT)

A ferramenta apenas lê a base de dados (transação PostgreSQL READ ONLY),
nunca chama o answering pipeline nem a OpenAI, e escreve o relatório de
forma atómica dentro de docs/diagnostics/generated/.

Códigos de saída:

0 — diagnóstico concluído (mesmo que tenha detetado falhas no pipeline);
2 — argumentos, caminhos ou ficheiro de perguntas inválidos;
3 — instituição não encontrada;
4 — documento não encontrado ou seleção por filename ambígua;
5 — versão não encontrada ou documento sem versões;
6 — versão selecionada sem extracted_text utilizável;
7 — erro controlado de acesso à base de dados;
8 — falha ao escrever o relatório;
9 — destino já existe sem --overwrite.
"""

import argparse
import logging
import os
import sys
import tempfile
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.diagnostics.document_pipeline import (
    DEFAULT_MAX_EXCERPT_CHARS,
    MAX_EXCERPT_CHARS,
    MIN_EXCERPT_CHARS,
    AmbiguousFilenameError,
    DiagnosticError,
    DiagnosticQuestion,
    DocumentSelectionError,
    InstitutionNotFoundError,
    QuestionsFileError,
    UnusableExtractedTextError,
    VersionSelectionError,
    parse_questions_json,
    render_json,
    render_markdown,
    run_diagnostic,
)
from app.retrieval.base import Retriever
from app.retrieval.dependencies import get_retriever

logger = logging.getLogger(__name__)

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_INSTITUTION_NOT_FOUND = 3
EXIT_DOCUMENT_NOT_FOUND = 4
EXIT_VERSION_NOT_FOUND = 5
EXIT_NO_EXTRACTED_TEXT = 6
EXIT_DATABASE_ERROR = 7
EXIT_WRITE_FAILED = 8
EXIT_OUTPUT_EXISTS = 9

GENERATED_DIR_PARTS = ("docs", "diagnostics", "generated")

_FORMAT_SUFFIXES = {"markdown": ".md", "json": ".json"}


def _default_repository_root() -> Path:
    # scripts/ vive em backend/scripts; a raiz do repositório é dois
    # níveis acima deste ficheiro.
    return Path(__file__).resolve().parents[2]


def _error(message: str) -> None:
    # Erros controlados: mensagem curta em stderr, sem traceback.
    print(f"error: {message}", file=sys.stderr)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="diagnose_document_pipeline",
        description="Diagnóstico read-only do pipeline documental.",
    )
    parser.add_argument("--institution-id", type=UUID, required=True)
    parser.add_argument("--questions-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    selector = parser.add_mutually_exclusive_group(required=True)
    selector.add_argument("--document-id", type=UUID)
    selector.add_argument("--version-id", type=UUID)
    selector.add_argument("--filename", type=str)
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument("--reference-date", type=date.fromisoformat, default=None)
    parser.add_argument("--top-k", type=int, default=5)
    official = parser.add_mutually_exclusive_group()
    official.add_argument("--official-only", action="store_true", default=None)
    official.add_argument("--include-non-official", action="store_true", default=None)
    parser.add_argument("--max-excerpt-chars", type=int, default=DEFAULT_MAX_EXCERPT_CHARS)
    parser.add_argument("--overwrite", action="store_true")
    return parser


def _resolve_inside(base: Path, candidate: Path) -> Path | None:
    """Resolve `candidate` e devolve o caminho apenas se ficar dentro de
    `base` (derrota `..`, symlinks e caminhos absolutos externos)."""
    resolved = (candidate if candidate.is_absolute() else Path.cwd() / candidate).resolve()
    try:
        resolved.relative_to(base.resolve())
    except ValueError:
        return None
    return resolved


def _validate_output_path(
    output: Path, report_format: str, repository_root: Path, overwrite: bool
) -> tuple[Path | None, int]:
    generated_dir = repository_root.joinpath(*GENERATED_DIR_PARTS)
    # A diretoria autorizada é criada antes do resolve() para que a
    # validação por caminho real funcione mesmo na primeira execução.
    try:
        generated_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        _error("could not create the reports directory")
        return None, EXIT_WRITE_FAILED
    resolved = _resolve_inside(generated_dir, output)
    if resolved is None or resolved == generated_dir.resolve():
        _error("--output must resolve to a file inside docs/diagnostics/generated/")
        return None, EXIT_USAGE
    expected_suffix = _FORMAT_SUFFIXES[report_format]
    if resolved.suffix != expected_suffix:
        _error(f"--output must end with '{expected_suffix}' for format '{report_format}'")
        return None, EXIT_USAGE
    if resolved.is_dir():
        _error("--output points to a directory")
        return None, EXIT_USAGE
    if resolved.exists() and not overwrite:
        _error("the output file already exists; pass --overwrite to replace it")
        return None, EXIT_OUTPUT_EXISTS
    return resolved, EXIT_OK


def _load_questions(
    questions_file: Path, repository_root: Path
) -> tuple[tuple[DiagnosticQuestion, ...] | None, int]:
    resolved = _resolve_inside(repository_root, questions_file)
    if resolved is None:
        _error("--questions-file must resolve to a file inside the repository root")
        return None, EXIT_USAGE
    if not resolved.is_file():
        _error("the questions file does not exist")
        return None, EXIT_USAGE
    try:
        raw = resolved.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        _error("the questions file could not be read as UTF-8 text")
        return None, EXIT_USAGE
    try:
        return parse_questions_json(raw), EXIT_OK
    except QuestionsFileError as exc:
        _error(str(exc))
        return None, EXIT_USAGE


def atomic_write(destination: Path, content: str) -> None:
    """Escrita atómica: ficheiro temporário na mesma diretoria, flush,
    fsync e os.replace; o temporário é removido em caso de falha."""
    handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=destination.parent,
        prefix=f".{destination.name}.",
        suffix=".tmp",
        delete=False,
    )
    temporary_path = Path(handle.name)
    try:
        with handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, destination)
    except OSError:
        temporary_path.unlink(missing_ok=True)
        raise


def main(
    argv: list[str] | None = None,
    *,
    session_factory: Callable[[], Session] | None = None,
    retriever: Retriever | None = None,
    repository_root: Path | None = None,
    clock: Callable[[], datetime] | None = None,
    writer: Callable[[Path, str], None] = atomic_write,
) -> int:
    logging.basicConfig(level=logging.INFO)
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        # argparse usa 2 para erros de utilização; preserva-se o contrato.
        return int(exc.code) if exc.code is not None else EXIT_USAGE

    if args.top_k < 1 or args.top_k > 20:
        _error("--top-k must be between 1 and 20")
        return EXIT_USAGE
    if not (MIN_EXCERPT_CHARS <= args.max_excerpt_chars <= MAX_EXCERPT_CHARS):
        _error(
            f"--max-excerpt-chars must be between {MIN_EXCERPT_CHARS} and {MAX_EXCERPT_CHARS}"
        )
        return EXIT_USAGE
    if args.filename is not None and not args.filename.strip():
        _error("--filename must not be empty")
        return EXIT_USAGE
    # --official-only é o comportamento padrão; --include-non-official
    # desativa o filtro de forma explícita (grupo mutuamente exclusivo).
    official_only = not bool(args.include_non_official)

    root = repository_root if repository_root is not None else _default_repository_root()
    questions, exit_code = _load_questions(args.questions_file, root)
    if questions is None:
        return exit_code
    output_path, exit_code = _validate_output_path(args.output, args.format, root, args.overwrite)
    if output_path is None:
        return exit_code

    if session_factory is None:
        from app.database.session import SessionLocal

        session_factory = SessionLocal
    active_retriever = retriever if retriever is not None else get_retriever()

    logger.info(
        "Document pipeline diagnostic started: institution_id=%s questions=%d",
        args.institution_id,
        len(questions),
    )
    db = session_factory()
    try:
        report = run_diagnostic(
            db,
            active_retriever,
            institution_id=args.institution_id,
            questions=questions,
            document_id=args.document_id,
            version_id=args.version_id,
            filename=args.filename,
            reference_date=args.reference_date,
            top_k=args.top_k,
            official_only=official_only,
            max_excerpt_chars=args.max_excerpt_chars,
            report_format=args.format,
            clock=clock,
        )
    except InstitutionNotFoundError as exc:
        _error(str(exc))
        return EXIT_INSTITUTION_NOT_FOUND
    except (DocumentSelectionError, AmbiguousFilenameError) as exc:
        _error(str(exc))
        return EXIT_DOCUMENT_NOT_FOUND
    except VersionSelectionError as exc:
        _error(str(exc))
        return EXIT_VERSION_NOT_FOUND
    except UnusableExtractedTextError as exc:
        _error(str(exc))
        return EXIT_NO_EXTRACTED_TEXT
    except SQLAlchemyError:
        # Nunca imprimir o erro do driver: pode conter URL/credenciais.
        logger.error("Document pipeline diagnostic failed: reason=database_error")
        _error("a controlled database error occurred; check connectivity and try again")
        return EXIT_DATABASE_ERROR
    except DiagnosticError as exc:
        _error(str(exc))
        return EXIT_USAGE
    finally:
        # A sessão é sempre encerrada, inclusive em caso de erro.
        db.close()

    content = render_markdown(report) if args.format == "markdown" else render_json(report)
    try:
        writer(output_path, content)
    except OSError:
        _error("failed to write the report file")
        return EXIT_WRITE_FAILED

    relative_output = output_path.relative_to(root.resolve())
    # Terminal: apenas estado resumido, IDs técnicos autorizados, número
    # de perguntas e caminho relativo — nunca excertos documentais.
    print(f"diagnostic completed: questions={len(questions)}")
    print(f"institution_id={report.institution.institution_id}")
    print(f"document_id={report.document.document_id}")
    print(f"selected_version_id={report.selected_version.version_id}")
    print(f"effective_retrieval_version_id={report.effective_retrieval_version.version_id}")
    print(f"report={relative_output.as_posix()}")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
