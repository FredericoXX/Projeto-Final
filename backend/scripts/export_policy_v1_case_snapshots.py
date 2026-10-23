"""Bind human-authored cases to corpus snapshots without running a retriever or LLM."""

import argparse
import json
from pathlib import Path

from sqlalchemy import select

from app.core.config import settings
from app.database.session import SessionLocal
from app.evaluation.policy_v1.executor import EvaluationCaseSet
from app.evaluation.snapshot_builder import build_evaluation_snapshot
from app.models.institution import Institution


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.cases.resolve() == args.output.resolve():
        parser.error("use a different output path; never overwrite the original cases")
    cases = EvaluationCaseSet.model_validate_json(args.cases.read_text(encoding="utf-8"))
    with SessionLocal() as db:
        institution = db.scalar(
            select(Institution).where(Institution.code == cases.institution_code)
        )
        if institution is None:
            parser.error("institution not found")
        bound = []
        for case in cases.cases:
            if case.family is None or case.source_kind is None:
                parser.error(f"case {case.case_id}: supply family and source_kind first")
            snapshot = build_evaluation_snapshot(
                db,
                institution_id=institution.id,
                language=case.language,
                reference_date=case.reference_date,
                requester_role=case.requester_role,
                official_only=case.official_only,
                top_k=settings.answering_default_top_k,
            )
            bound.append(case.model_copy(update={"expected_snapshot_id": snapshot.snapshot_id}))
        payload = cases.model_copy(update={"cases": bound}).model_dump(mode="json")
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
