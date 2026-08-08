"""Produz a baseline versionada do Momento 5 (Fase 3).

Uso (a partir de backend/):

    python -m scripts.build_moment05_baseline \
        --output ../docs/relatorios/moment-05-baseline-p1.json \
        [--overwrite] [--commit-sha SHA]

Invoca o entrypoint da Fase 2 **duas vezes**, para uma diretoria
temporária, lê os dois relatórios que ele escreveu, confirma R1 e compõe
a baseline em torno de um deles. Nada aqui reexecuta a avaliação nem
recalcula o `result_digest`: a Fase 3 consome a saída da Fase 2 tal como
ela a produz, e o código da Fase 2 fica intacto.

O JSON é a **única fonte primária** da baseline. D9 torna o resumo em
Markdown opcional e ele não é produzido.

A política de caminhos, a resolução do `commit_sha` e a neutralização do
fornecedor são as do entrypoint da Fase 2, reutilizadas em vez de
duplicadas: duas cópias da mesma política acabariam por divergir.

Códigos de saída: os mesmos da Fase 2 — 0, 2, 3, 4, 8 e 9.
"""

import argparse
import json
import sys
import tempfile
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from scripts.evaluate_answering_offline import (
    EXIT_COMMIT_SHA,
    EXIT_OK,
    EXIT_OUTPUT_EXISTS,
    EXIT_USAGE,
    EXIT_WRITE_FAILED,
    CommitShaError,
    neutralise_provider_environment,
    resolve_commit_sha,
    validate_output_path,
)
from scripts.evaluate_answering_offline import main as evaluate_offline

REPRODUCIBILITY_RUNS = 2


def _default_repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _error(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="build_moment05_baseline",
        description="Baseline estrutural offline (P1) do Momento 5.",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--commit-sha", type=str, default=None)
    return parser


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
    json_path, exit_code = validate_output_path(args.output, root, args.overwrite)
    if json_path is None:
        return exit_code

    try:
        commit_sha = resolve_commit_sha(args.commit_sha, root)
    except CommitShaError as exc:
        _error(str(exc))
        return EXIT_COMMIT_SHA

    # Precede o primeiro import de `app`, como na Fase 2.
    neutralise_provider_environment()

    from app.evaluation.baseline import build_baseline
    from app.evaluation.results import EvaluationReport, atomic_write_text, report_file_text

    # Caminho relativo ao repositório: um caminho absoluto colocaria um
    # caminho local de máquina dentro de um artefacto versionado.
    try:
        relative_output = json_path.relative_to(root.resolve()).as_posix()
    except ValueError:
        relative_output = json_path.name

    reports: list[EvaluationReport] = []
    with tempfile.TemporaryDirectory(prefix="moment05-baseline-") as temporary:
        for run in range(1, REPRODUCIBILITY_RUNS + 1):
            run_output = Path(temporary) / f"run-{run}.json"
            # O entrypoint da Fase 2 valida os artefactos e devolve os seus
            # próprios códigos de saída; propagamo-los sem os reinterpretar.
            exit_code = evaluate_offline(
                ["--output", str(run_output), "--commit-sha", commit_sha],
                repository_root=root,
                clock=clock,
            )
            if exit_code != EXIT_OK:
                _error(f"the phase 2 evaluation failed on run {run}")
                return exit_code
            reports.append(
                EvaluationReport.model_validate(
                    json.loads(run_output.read_text(encoding="utf-8"))
                )
            )

    baseline = build_baseline(reports[0], reports[1], output_path=relative_output)
    payload = baseline.model_dump(mode="json")
    try:
        atomic_write_text(json_path, report_file_text(payload), overwrite=args.overwrite)
    except FileExistsError:
        _error("the output file already exists; pass --overwrite to replace it")
        return EXIT_OUTPUT_EXISTS
    except OSError:
        _error("failed to write the baseline file")
        return EXIT_WRITE_FAILED

    reproducibility = baseline.reproducibility
    print(f"baseline built: population={baseline.report.results.population}")
    print(f"cases={baseline.report.results.case_count}")
    print(f"result_digest={baseline.report.result_digest}")
    print(
        "r1_reproducible="
        f"{str(reproducibility.results_identical and reproducibility.digest_identical).lower()}"
    )
    print(f"behavioural_defects={len(baseline.findings.behavioural_defects)}")
    print(f"baseline={relative_output}")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
