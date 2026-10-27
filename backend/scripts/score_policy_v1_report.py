"""Reanálise offline de um relatório arquivado da avaliação da política v1.7.

Uso (a partir de backend/):

    python -m scripts.score_policy_v1_report --report RELATORIO.json \\
        --cases CASES.json --adjudication ADJ.json \\
        --freeze-manifest DIR/freeze-manifest.json --output ANALISE.json \\
        [--message-ratings AVALIACOES.json] [--corpus-inventory DIR/manifest.json] \\
        [--formal]

Recalcula as métricas sobre as respostas **já recolhidas** — nenhuma chamada a
modelos. Não abre ligação à base de dados, não usa rede, não instancia clientes
de fornecedores, não precisa de chaves e não importa a configuração da aplicação
(dispensa ``.env``, ``DATABASE_URL`` e ``JWT_SECRET_KEY``): lê apenas os
ficheiros indicados (e o estado do Git local, para registar o commit da
análise). A lógica e a lista das
verificações estão em :mod:`app.evaluation.policy_v1.rescoring`.

- ``--report`` — o relatório escrito por ``scripts.run_policy_v1_evaluation``;
  nunca é alterado nem sobrescrito.
- ``--cases``, ``--adjudication`` — os ficheiros de casos e a adjudicação
  identificada; têm de corresponder ao congelamento e à recolha.
- ``--freeze-manifest`` — o manifesto completo de ``freeze_policy_v1_artifacts``.
- ``--message-ratings`` — opcional: juízos humanos M7 vinculados às mensagens
  desta recolha (``policy_v1_message_ratings_2``). Sem eles, M7 fica não medida.
- ``--corpus-inventory`` — opcional; obrigatório com ``--formal``: o inventário
  documental congelado (``manifest.json`` do diretório de congelamento).
- ``--output`` — a análise; tem de ser um caminho novo, diferente das entradas.
- ``--formal`` — só para uma recolha formal ``policy_v1_report_2``, com árvore de
  trabalho limpa e o mesmo código; sem ele, a análise é de desenvolvimento e só
  aceita conjuntos ``policy-v1-dev*``.

Códigos de saída: 0 sucesso; 2 argumentos ou caminho de saída; 3 ficheiro
inválido; 5 entradas que não correspondem à recolha ou ao congelamento; 6 modo
recusado; 7 avaliações humanas recusadas.

Escreve no terminal apenas o modo, o nível de verificação e o estado de M7 —
nunca pedidos, mensagens ou conteúdo documental.
"""

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from app.evaluation.policy_v1.artifacts import git_state
from app.evaluation.policy_v1.report import report_bytes
from app.evaluation.policy_v1.rescoring import (
    AnalysisGit,
    RescoringError,
    RescoringInputs,
    rescore,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
EXIT_USAGE = 2
EXIT_CODES = {"invalid": 3, "provenance": 5, "refused": 6, "ratings": 7}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="score_policy_v1_report")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--adjudication", type=Path, required=True)
    parser.add_argument("--freeze-manifest", type=Path, required=True)
    parser.add_argument("--message-ratings", type=Path)
    parser.add_argument("--corpus-inventory", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--formal", action="store_true")
    args = parser.parse_args(argv)

    sources = [
        path
        for path in (
            args.report,
            args.cases,
            args.adjudication,
            args.freeze_manifest,
            args.message_ratings,
            args.corpus_inventory,
        )
        if path is not None
    ]
    if args.output.resolve() in {path.resolve() for path in sources}:
        sys.stderr.write("the output must not be one of the input files\n")
        return EXIT_USAGE
    if args.output.exists():
        sys.stderr.write("refusing to overwrite an existing file\n")
        return EXIT_USAGE
    try:
        inputs = RescoringInputs(
            report=args.report.read_bytes(),
            cases=args.cases.read_bytes(),
            adjudication=args.adjudication.read_bytes(),
            freeze_manifest=args.freeze_manifest.read_bytes(),
            message_ratings=args.message_ratings.read_bytes() if args.message_ratings else None,
            corpus_inventory=(
                args.corpus_inventory.read_bytes() if args.corpus_inventory else None
            ),
            report_name=args.report.name,
        )
    except OSError as exc:
        sys.stderr.write(f"cannot read an input file: {type(exc).__name__}\n")
        return EXIT_USAGE
    head, clean = git_state(REPOSITORY_ROOT)
    try:
        analysis = rescore(
            inputs,
            formal=args.formal,
            git=AnalysisGit(head, clean),
            analyzed_at=datetime.now(UTC),
        )
    except RescoringError as exc:
        sys.stderr.write(f"{exc}\n")
        return EXIT_CODES[exc.kind]
    # Criação exclusiva: nunca sobrescreve, nem um ficheiro que entretanto apareça.
    with args.output.open("xb") as handle:
        handle.write(report_bytes(analysis))
    summary = {
        "mode": analysis["mode"],
        "verification_level": analysis["verification"]["level"],
        "collection_metrics_reproduction": analysis["collection_metrics_reproduction"]["status"],
        "m7": analysis["message_ratings"]["status"],
    }
    sys.stdout.write(json.dumps(summary) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
