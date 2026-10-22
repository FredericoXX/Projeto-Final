"""Receita de congelamento reproduzível do conjunto de avaliação da política v1.

A receita, tal como a v1.7 a fixa:

1. validar os casos e ordená-los por ``case_id`` (IDs únicos obrigatórios);
2. serializar com ``json.dumps(sort_keys=True, ensure_ascii=False,
   separators=(",", ":"), allow_nan=False)``;
3. codificar em UTF-8, **sem BOM e sem newline final**;
4. preservar a ordem de todos os outros arrays;
5. **não** normalizar Unicode silenciosamente — strings fora de NFC são
   reportadas, nunca alteradas;
6. arquivar os bytes e calcular SHA-256.

Cada artefacto — corpus, manifesto, rótulos, política, esquema, prompts,
configuração e catálogo institucional — tem identidade e digest próprios. O
manifesto de congelamento regista ainda a versão da receita, a versão do Python
e o commit do código.

Difere de :func:`app.evaluation.results.canonical_json` num ponto deliberado:
``allow_nan=False``. Um ``NaN`` não é JSON válido e não pode entrar num
artefacto congelado.
"""

import hashlib
import json
import platform
import unicodedata
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

FREEZE_RECIPE_VERSION: Final = "policy_v1_freeze_recipe_1"

#: Artefactos que um congelamento completo tem de identificar.
REQUIRED_ARTIFACTS: Final = (
    "corpus",
    "manifest",
    "labels",
    "policy",
    "schema",
    "prompts",
    "config",
    # O catálogo institucional (âmbito D1 e serviços D6) decide R02–R05, R07,
    # R08, R11, R12 e o destino: sem ele congelado, o mesmo congelamento podia
    # produzir outra decisão.
    "catalog",
)


class FreezeError(ValueError):
    """O artefacto não pode ser congelado tal como está."""


def canonical_bytes(payload: Any) -> bytes:
    """Bytes canónicos de qualquer artefacto: a receita sem a ordenação de casos."""
    try:
        text = json.dumps(
            payload,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        )
    except ValueError as exc:
        msg = "artifact contains values that are not valid JSON (NaN or infinity)"
        raise FreezeError(msg) from exc
    return text.encode("utf-8")


def freeze_cases(cases: Sequence[Mapping[str, Any]]) -> bytes:
    """Bytes congelados de uma lista de casos, ordenada por ``case_id``."""
    ids = [case.get("case_id") for case in cases]
    if any(not isinstance(case_id, str) or not case_id for case_id in ids):
        msg = "every case needs a non-empty string case_id"
        raise FreezeError(msg)
    if len(set(ids)) != len(ids):
        msg = "case_id values must be unique"
        raise FreezeError(msg)
    ordered = sorted(cases, key=lambda case: case["case_id"])
    return canonical_bytes(ordered)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _strings(value: Any, path: str = "$") -> Iterator[tuple[str, str]]:
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, Mapping):
        for key, item in value.items():
            yield from _strings(key, f"{path}.<key>")
            yield from _strings(item, f"{path}.{key}")
    elif isinstance(value, list | tuple):
        for index, item in enumerate(value):
            yield from _strings(item, f"{path}[{index}]")


def non_nfc_strings(payload: Any) -> list[str]:
    """Caminhos de strings que não estão em NFC. Relatório, nunca correção."""
    return [path for path, text in _strings(payload) if unicodedata.normalize("NFC", text) != text]


@dataclass(frozen=True)
class FrozenArtifact:
    name: str
    version: str
    data: bytes

    @property
    def digest(self) -> str:
        return sha256(self.data)


def build_freeze_manifest(
    artifacts: Sequence[FrozenArtifact], *, code_commit: str
) -> dict[str, Any]:
    """Manifesto com a identidade de cada artefacto e do ambiente de congelamento."""
    names = [artifact.name for artifact in artifacts]
    if len(set(names)) != len(names):
        msg = "artifact names must be unique"
        raise FreezeError(msg)
    missing = sorted(set(REQUIRED_ARTIFACTS) - set(names))
    return {
        "recipe_version": FREEZE_RECIPE_VERSION,
        "python_version": platform.python_version(),
        "code_commit": code_commit,
        "complete": not missing,
        "missing_artifacts": missing,
        "artifacts": {
            artifact.name: {
                "version": artifact.version,
                "sha256": artifact.digest,
                "bytes": len(artifact.data),
            }
            for artifact in artifacts
        },
    }


def verify_artifact(manifest: Mapping[str, Any], name: str, data: bytes) -> None:
    """Confirma que ``data`` é exatamente o artefacto congelado ``name``."""
    entry = manifest.get("artifacts", {}).get(name)
    if entry is None:
        msg = f"artifact {name} is not part of the freeze manifest"
        raise FreezeError(msg)
    if entry["sha256"] != sha256(data):
        msg = f"artifact {name} does not match its frozen digest"
        raise FreezeError(msg)
