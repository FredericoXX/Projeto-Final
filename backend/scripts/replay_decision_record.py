"""Replay das decisões arquivadas da política experimental v1.7.

Uso (a partir de backend/):

    python -m scripts.replay_decision_record [--record-id UUID] [--limit N]

Relê ``decision_records`` com ``status='decided'``, reconstrói as entradas
validadas da política a partir do registo e volta a aplicar
:func:`app.decision.policy.decide`. Reporta, por registo, se a ação, a regra e
a razão coincidem com as arquivadas — e, quando não coincidem, se a versão da
política mudou entretanto.

Lê a base de dados configurada em ``DATABASE_URL``; não escreve nada. Não
imprime conteúdo do registo, só identificadores e o resultado da comparação.
"""

import argparse
import json
import sys
import uuid

from sqlalchemy import select

from app.database.session import SessionLocal
from app.decision.dimensions import policy_input_from_dict
from app.decision.policy import POLICY_VERSION, decide
from app.models.decision_record import DecisionRecord


def replay(record: DecisionRecord) -> dict[str, object]:
    replayed = decide(policy_input_from_dict(record.record["policy_input"]))
    archived = record.record["decision"]
    return {
        "record_id": str(record.id),
        "archived_policy_version": record.policy_version,
        "current_policy_version": POLICY_VERSION,
        "matches": replayed.as_dict() == archived,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="replay_decision_record")
    parser.add_argument("--record-id", type=uuid.UUID)
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args(argv)
    statement = select(DecisionRecord).where(DecisionRecord.status == "decided")
    if args.record_id is not None:
        statement = statement.where(DecisionRecord.id == args.record_id)
    with SessionLocal() as db:
        records = db.scalars(statement.order_by(DecisionRecord.created_at).limit(args.limit))
        results = [replay(record) for record in records]
    sys.stdout.write(json.dumps({"replayed": results}, indent=2) + "\n")
    return 0 if all(result["matches"] for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
