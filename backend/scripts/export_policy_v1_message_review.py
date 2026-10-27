"""Exporta, de um relatório arquivado, o pacote de revisão humana das mensagens (M7).

Uso (a partir de backend/):

    python -m scripts.export_policy_v1_message_review --report RELATORIO.json \\
        --output-dir DIR

Escreve em ``DIR`` três ficheiros (:mod:`app.evaluation.policy_v1.message_review`):

- ``review-material.md`` — o material apresentado ao avaliador. **Contém
  conteúdo dos documentos consultados e as mensagens produzidas**: fica no
  ambiente autorizado e não vai para logs, issues nem repositórios;
- ``ratings-draft.json`` — o rascunho a preencher, com a identidade exata de
  cada mensagem e todos os juízos a ``"pending"``;
- ``review-manifest.json`` — a proveniência da exportação.

Só lê o relatório: não abre a base de dados, não importa a configuração da
aplicação, não chama modelos e não gera
juízos, justificações, ações preferidas ou adjudicações. Recusa escrever sobre
ficheiros existentes. No terminal escreve apenas contagens.

Códigos de saída: 0 sucesso; 2 argumentos ou ficheiros existentes; 3 relatório
inválido.
"""

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from app.evaluation.policy_v1.artifacts import git_state
from app.evaluation.policy_v1.message_review import build_review_package
from app.evaluation.policy_v1.report import ReportError, load_collection_report

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
EXIT_USAGE = 2
EXIT_INVALID = 3


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="export_policy_v1_message_review")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        data = args.report.read_bytes()
    except OSError as exc:
        sys.stderr.write(f"cannot read the report: {type(exc).__name__}\n")
        return EXIT_USAGE
    try:
        archived = load_collection_report(data)
    except ReportError as exc:
        sys.stderr.write(f"{exc}\n")
        return EXIT_INVALID
    package = build_review_package(
        archived, data, exported_at=datetime.now(UTC), export_git=git_state(REPOSITORY_ROOT)
    )
    targets = {name: args.output_dir / name for name in package.files}
    if args.report.resolve() in {path.resolve() for path in targets.values()}:
        sys.stderr.write("the review package must not replace the report\n")
        return EXIT_USAGE
    existing = sorted(name for name, path in targets.items() if path.exists())
    if existing:
        sys.stderr.write(f"refusing to overwrite existing files: {', '.join(existing)}\n")
        return EXIT_USAGE
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, content in package.files.items():
        with targets[name].open("xb") as handle:
            handle.write(content)
    sys.stdout.write(json.dumps({"items": package.items, "excluded": package.excluded}) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
