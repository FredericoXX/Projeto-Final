"""Ferramenta de rótulos do conjunto de avaliação da política v1 (P2).

Implementação equivalente e documentada do ``p2_labels_tool.py`` referido pela
política v1.7, cujo original não está disponível a este repositório. A lógica
vive em :mod:`app.evaluation.policy_v1.labels`; este script só lê e escreve
ficheiros.

Uso (a partir de backend/):

    python -m scripts.p2_labels_tool schema --output ../docs/evaluation/policy-v1/labels.schema.json
    python -m scripts.p2_labels_tool schema --kind message-ratings \
        --output ../docs/evaluation/policy-v1/message-ratings.schema.json
    python -m scripts.p2_labels_tool check A1.json A2.json [--output relatorio.json]
    python -m scripts.p2_labels_tool oracle --adjudication ADJ.json --cases CASES.json \\
        --freeze-manifest MANIFEST.json --catalog CATALOG.json --output oraculo.json

- ``schema`` escreve o esquema JSON de um contrato (``--kind``; por omissão os
  rótulos): ``labels``, ``cases``, ``message-ratings`` (juízos M7 vinculados às
  mensagens), ``message-ratings-draft`` (rascunho exportado para revisão) ou
  ``collection-report`` (relatório da recolha). Os ficheiros versionados em
  ``docs/evaluation/policy-v1/`` são gerados assim, e um teste falha se
  divergirem dos modelos.
- ``check`` valida os dois ficheiros, exige IDs únicos e conjuntos iguais,
  reporta aplicabilidade assimétrica, N, acordo bruto, κ quando aplicável,
  matriz de desacordos e IC. **Não** calcula ações nem preenche rótulos. Trocar
  A1 por A2 produz o mesmo relatório.
- ``oracle`` só aceita uma adjudicação identificada cujo digest corresponde ao
  manifesto de congelamento, um ficheiro de casos igual ao corpus congelado,
  um catálogo igual ao congelado e
  uma política, esquema, prompts e configuração iguais aos congelados; devolve
  a ação da política para cada caso
  (condição P-oráculo). A data de referência é a de cada caso no ficheiro de
  casos congelado (``--cases``).

Nenhum modelo cria rótulos humanos, e esta ferramenta não os cria.

Códigos de saída: 0 sucesso; 2 argumentos; 3 ficheiro inválido; 4 conjuntos
não comparáveis; 5 congelamento não verificado.
"""

import argparse
import json
import sys
from pathlib import Path

from pydantic import BaseModel, ValidationError

from app.evaluation.policy_v1.artifacts import (
    catalog_bytes,
    corpus_bytes,
    verify_code_artifacts,
)
from app.evaluation.policy_v1.cases import EvaluationCaseSet
from app.evaluation.policy_v1.conditions import run_oracle
from app.evaluation.policy_v1.freeze import FreezeError, verify_artifact
from app.evaluation.policy_v1.labels import (
    LabelCheckError,
    LabelSet,
    check_agreement,
    verified_adjudication,
)
from app.evaluation.policy_v1.protocol import verify_same_case_set

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_INVALID = 3
EXIT_NOT_COMPARABLE = 4
EXIT_NOT_FROZEN = 5


def _read(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(payload: object, output: Path | None) -> None:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if output is None:
        sys.stdout.write(text)
    else:
        output.write_text(text, encoding="utf-8", newline="\n")


def contract_schema(kind: str) -> dict:
    from app.evaluation.policy_v1.message_ratings import (
        BoundMessageRatingSet,
        MessageRatingDraft,
    )
    from app.evaluation.policy_v1.report import CollectionReport

    models: dict[str, type[BaseModel]] = {
        "labels": LabelSet,
        "cases": EvaluationCaseSet,
        "message-ratings": BoundMessageRatingSet,
        "message-ratings-draft": MessageRatingDraft,
        "collection-report": CollectionReport,
    }
    schema = models[kind].model_json_schema()
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    return schema


#: Os contratos com esquema JSON versionado em ``docs/evaluation/policy-v1/``.
SCHEMA_KINDS = ("labels", "cases", "message-ratings", "message-ratings-draft", "collection-report")


def labels_schema() -> dict:
    return contract_schema("labels")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="p2_labels_tool")
    sub = parser.add_subparsers(dest="command", required=True)
    schema = sub.add_parser("schema")
    schema.add_argument("--kind", choices=SCHEMA_KINDS, default="labels")
    schema.add_argument("--output", type=Path)
    check = sub.add_parser("check")
    check.add_argument("first", type=Path)
    check.add_argument("second", type=Path)
    check.add_argument("--output", type=Path)
    oracle = sub.add_parser("oracle")
    oracle.add_argument("--adjudication", type=Path, required=True)
    oracle.add_argument("--freeze-manifest", type=Path, required=True)
    oracle.add_argument("--catalog", type=Path, required=True)
    oracle.add_argument("--cases", type=Path, required=True)
    oracle.add_argument("--output", type=Path)
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return EXIT_USAGE

    if args.command == "schema":
        # A ordem dos campos dos modelos é preservada: é a dos ficheiros versionados.
        text = json.dumps(contract_schema(args.kind), ensure_ascii=False, indent=2) + "\n"
        if args.output is None:
            sys.stdout.write(text)
        else:
            args.output.write_text(text, encoding="utf-8", newline="\n")
        return EXIT_OK

    try:
        if args.command == "check":
            first = LabelSet.model_validate(_read(args.first))
            second = LabelSet.model_validate(_read(args.second))
        else:
            adjudication = LabelSet.model_validate(_read(args.adjudication))
            cases = EvaluationCaseSet.model_validate(_read(args.cases))
            manifest = _read(args.freeze_manifest)
            catalog = _read(args.catalog)
    except (OSError, ValueError, ValidationError) as exc:
        sys.stderr.write(f"invalid input: {type(exc).__name__}\n")
        return EXIT_INVALID

    if args.command == "check":
        try:
            _write(check_agreement(first, second), args.output)
        except LabelCheckError as exc:
            sys.stderr.write(f"{exc}\n")
            return EXIT_NOT_COMPARABLE
        return EXIT_OK

    try:
        verify_same_case_set(cases, adjudication)
    except FreezeError as exc:
        sys.stderr.write(f"{exc}\n")
        return EXIT_NOT_COMPARABLE
    try:
        verified = verified_adjudication(adjudication, manifest)  # type: ignore[arg-type]
        # Os casos e a política usados pelo P-oráculo têm de ser os congelados.
        verify_artifact(manifest, "corpus", corpus_bytes(_read(args.cases)))  # type: ignore[arg-type]
        # E o catálogo D6: um serviço a mais ou a menos muda R04/R05 e o destino.
        verify_artifact(manifest, "catalog", catalog_bytes(catalog))  # type: ignore[arg-type]
        verify_code_artifacts(manifest)  # type: ignore[arg-type]
    except FreezeError as exc:
        sys.stderr.write(f"{exc}\n")
        return EXIT_NOT_FROZEN
    dates = {case.case_id: case.reference_date for case in cases.cases}
    missing = sorted(case.case_id for case in verified.cases if case.case_id not in dates)
    if missing:
        sys.stderr.write(f"{len(missing)} adjudicated case(s) are not in the case set\n")
        return EXIT_NOT_COMPARABLE
    outcomes = [
        run_oracle(case, catalog=catalog, reference_date=dates[case.case_id]).as_dict()  # type: ignore[arg-type]
        for case in sorted(verified.cases, key=lambda case: case.case_id)
    ]
    _write({"condition": "P-oráculo", "outcomes": outcomes}, args.output)
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
