"""Congela os artefactos do conjunto de avaliação da política v1.

Uso (a partir de backend/):

    python -m scripts.freeze_policy_v1_artifacts \\
        --artifact corpus=VERSION=PATH --artifact labels=VERSION=PATH ... \\
        --commit SHA --output-dir DIR

Só ``corpus``, ``manifest``, ``labels`` e ``catalog`` (o snapshot do catálogo
institucional, com ``version``, ``scope_description``, ``topics`` e
``services``) são ficheiros. O ``manifest`` é o inventário documental exportado
da base por ``scripts.export_policy_v1_corpus_inventory``; um inventário que não
valide é recusado. ``policy``,
``schema``, ``prompts`` e ``config`` são **gerados a partir do código** em
execução (:mod:`app.evaluation.policy_v1.artifacts`) e não podem ser
fornecidos: é isso que permite verificar, mais tarde, que o código que corre é
o congelado. Aplica a receita de :mod:`app.evaluation.policy_v1.freeze` (os
casos e os rótulos são ordenados por ``case_id``; o resto mantém a ordem dos
arrays), escreve os bytes congelados em ``DIR/<nome>.json`` e um
``DIR/freeze-manifest.json`` com o SHA-256 de cada um, a versão da receita, a
versão do Python e o commit do código. Strings fora de NFC são reportadas,
nunca normalizadas. Recusa congelar com a árvore de trabalho por limpar ou com
um ``--commit`` diferente do ``HEAD``.

Não corre a avaliação nem cria rótulos. Recusa escrever sobre um diretório que
já tenha um manifesto.
"""

import argparse
import json
import re
import sys
from pathlib import Path

from app.evaluation.policy_v1.artifacts import (
    FILE_ARTIFACTS,
    code_artifacts,
    file_artifact_bytes,
    git_state,
)
from app.evaluation.policy_v1.freeze import (
    FreezeError,
    FrozenArtifact,
    build_freeze_manifest,
    non_nfc_strings,
)

COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="freeze_policy_v1_artifacts")
    parser.add_argument("--artifact", action="append", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    if not COMMIT_PATTERN.match(args.commit):
        sys.stderr.write("--commit must be a full 40-character SHA\n")
        return 4
    head, clean = git_state(REPOSITORY_ROOT)
    if head != args.commit or not clean:
        sys.stderr.write("--commit must be the current HEAD of a clean working tree\n")
        return 4
    if (args.output_dir / "freeze-manifest.json").exists():
        sys.stderr.write("a freeze manifest already exists in the output directory\n")
        return 9

    artifacts: list[FrozenArtifact] = []
    warnings: dict[str, list[str]] = {}
    for spec in args.artifact:
        try:
            name, version, path = spec.split("=", 2)
        except ValueError:
            sys.stderr.write("--artifact must be name=version=path\n")
            return 2
        if name not in FILE_ARTIFACTS:
            sys.stderr.write(f"{name}: only {', '.join(FILE_ARTIFACTS)} are supplied as files\n")
            return 2
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        non_nfc = non_nfc_strings(payload)
        if non_nfc:
            warnings[name] = non_nfc
        try:
            artifacts.append(
                FrozenArtifact(name=name, version=version, data=file_artifact_bytes(name, payload))
            )
        except (FreezeError, ValueError) as exc:
            sys.stderr.write(f"{name}: {type(exc).__name__}\n")
            return 3
    artifacts.extend(code_artifacts())

    manifest = build_freeze_manifest(artifacts, code_commit=args.commit)
    manifest["non_nfc_strings"] = warnings
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for artifact in artifacts:
        # Bytes exatos: sem BOM e sem newline final.
        (args.output_dir / f"{artifact.name}.json").write_bytes(artifact.data)
    (args.output_dir / "freeze-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    sys.stdout.write(json.dumps({"complete": manifest["complete"]}) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
