"""Exporta o inventário documental da instituição para congelar como ``manifest``.

Uso (a partir de backend/):

    python -m scripts.export_policy_v1_corpus_inventory \\
        --institution-code CODE --output INVENTARIO.json

Escreve os bytes canónicos do inventário (sem BOM e sem newline final), prontos
para ``freeze_policy_v1_artifacts --artifact manifest=VERSION=INVENTARIO.json``.
Só lê a base de dados: não congela, não corre a avaliação e não escreve
conteúdo dos documentos — apenas identificadores, metadados e hashes.
"""

import argparse
import sys
from pathlib import Path

from sqlalchemy import select

from app.database.session import SessionLocal
from app.evaluation.policy_v1.corpus_inventory import (
    collect_corpus_inventory,
    corpus_inventory_bytes,
)
from app.models.institution import Institution

EXIT_INVALID = 3


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="export_policy_v1_corpus_inventory")
    parser.add_argument("--institution-code", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    with SessionLocal() as db:
        institution_id = db.scalar(
            select(Institution.id).where(Institution.code == args.institution_code)
        )
        if institution_id is None:
            sys.stderr.write("institution not found\n")
            return EXIT_INVALID
        data = corpus_inventory_bytes(collect_corpus_inventory(db, institution_id))
    args.output.write_bytes(data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
