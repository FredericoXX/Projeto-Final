"""D4.10a — carimba no conjunto de perguntas a identidade que ele declara.

Recalcula ``question_set_digest``, ``scenario_digest``, ``human_review_digest``,
``scenario_distribution`` e ``document_distribution`` a partir do conteúdo e
reescreve o ficheiro com esses campos.

Porque é que isto é um comando separado da selagem
--------------------------------------------------

Carimbar e selar respondem a perguntas diferentes. Este comando **deriva** a
identidade do conteúdo; a selagem **verifica** que a identidade carimbada ainda
corresponde ao conteúdo e recusa continuar quando não corresponde. Se fosse o
mesmo comando, a verificação seria circular: recalcularia o que acabou de
escrever e concordaria sempre consigo próprio.

Depois de a revisão humana ser feita, este comando volta a correr — o
``human_review_digest`` muda, e portanto muda também o ``protocol_digest``. É
esse o efeito pretendido: a validação passa a estar dentro da selagem, e não ao
lado dela.

Não executa a experiência: não gera embeddings, não corre retrieval, não julga
e não mede.
"""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final

from app.evaluation.d4_10_protocol import (
    ProtocolError,
    declared_identity,
    verify_question_set,
)

EXIT_OK: Final = 0
EXIT_GUARD_FAILED: Final = 4


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stamp_d4_10_question_set",
        description=(
            "D4.10a - recalcula e carimba os digests e as distribuicoes do "
            "conjunto de perguntas. Nao executa a experiencia."
        ),
    )
    parser.add_argument("--question-set", type=Path, required=True)
    parser.add_argument(
        "--check",
        action="store_true",
        help="nao escreve; falha se o carimbo estiver desatualizado",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        with args.question_set.open(encoding="utf-8") as handle:
            payload: dict[str, Any] = json.load(handle)
        verify_question_set(payload)
        identity = declared_identity(payload)
    except (ProtocolError, KeyError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_GUARD_FAILED

    stale = [field for field, value in identity.items() if payload.get(field) != value]
    if args.check:
        if stale:
            print(f"error: carimbo desatualizado: {sorted(stale)}", file=sys.stderr)
            return EXIT_GUARD_FAILED
        print("carimbo atualizado")
        return EXIT_OK

    payload.update(identity)
    with args.question_set.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")

    print(f"question_set_digest  : {identity['question_set_digest']}")
    print(f"scenario_digest      : {identity['scenario_digest']}")
    print(f"human_review_digest  : {identity['human_review_digest']}")
    print(f"campos atualizados   : {sorted(stale) or 'nenhum'}")
    print(f"escrito              : {args.question_set}")
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
