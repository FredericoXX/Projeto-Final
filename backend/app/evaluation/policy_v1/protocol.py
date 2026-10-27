"""Checks required before formal evaluation, with no annotation generation.

The M7 rubric checks that used to live here (``validate_message_ratings``) now
bind every rating to its archived message:
:func:`app.evaluation.policy_v1.message_ratings.bind_ratings`.
"""

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

from app.decision.contracts import ScopeClass
from app.evaluation.policy_v1.freeze import FreezeError
from app.evaluation.policy_v1.labels import LabelSet

if TYPE_CHECKING:
    from app.evaluation.policy_v1.cases import EvaluationCase, EvaluationCaseSet


def _allowed_chunks(case: "EvaluationCase", inventory: Mapping[str, Any]) -> set[str]:
    allowed: set[str] = set()
    for document in inventory["documents"]:
        if not document["is_active"] or document["language"] != case.language:
            continue
        if case.official_only and not document["official_source"]:
            continue
        if document["access_roles"] and case.requester_role not in document["access_roles"]:
            continue
        reference = case.reference_date.isoformat()
        if document["valid_from"] and document["valid_from"] > reference:
            continue
        if document["valid_until"] and document["valid_until"] < reference:
            continue
        processed = [v for v in document["versions"] if v["processing_status"] == "processed"]
        if not processed:
            continue
        version = max(processed, key=lambda v: v["version_number"])
        allowed.update(
            chunk["chunk_id"] for chunk in version["chunks"] if chunk["language"] == case.language
        )
    return allowed


def verify_same_case_set(cases: "EvaluationCaseSet", labels: LabelSet) -> None:
    """Os rótulos pertencem ao conjunto de casos: o mesmo ``set_id``.

    Os mesmos ``case_id`` não chegam: identificadores como ``C1`` repetem-se
    entre conjuntos, e uma adjudicação de outro conjunto não julgou estes casos.
    """
    if labels.set_id != cases.set_id:
        raise FreezeError("the adjudication belongs to another case set")


def validate_formal_annotations(
    cases: Sequence["EvaluationCase"], labels: LabelSet, inventory: Mapping[str, Any]
) -> None:
    """Require traceable human labels, same cases, and admissible chunk references.

    Missing metadata is permitted only in legacy development fixtures. It
    cannot silently enter a formal run or a newly frozen scientific dataset.
    """
    by_id = {case.case_id: case for case in cases}
    if len(by_id) != len(cases) or set(by_id) != {case.case_id for case in labels.cases}:
        raise FreezeError("cases and adjudication must have the same complete unique ids")
    for label in labels.cases:
        case = by_id[label.case_id]
        trace = label.trace
        if trace is None or case.family is None or case.source_kind is None:
            raise FreezeError(
                f"case {case.case_id}: family, source_kind and human trace are required"
            )
        if (
            trace.family != case.family
            or trace.source_kind != case.source_kind
            or trace.snapshot_id != case.expected_snapshot_id
        ):
            raise FreezeError(f"case {case.case_id}: case metadata and human trace disagree")
        documentary = label.d1.scope is ScopeClass.IN_SCOPE and not label.d2.constraints
        if documentary and not trace.items:
            raise FreezeError(f"case {case.case_id}: documentary labels require annotated items")
        if label.d3.materiality and len(trace.readings) < 2:
            raise FreezeError(
                f"case {case.case_id}: material ambiguity requires annotated readings"
            )
        if label.d5.unresolvable_conflict and not trace.conflicts:
            raise FreezeError(
                f"case {case.case_id}: conflict requires evidence and shared conditions"
            )
        item_ids = {item.item_id for item in trace.items}
        if any(conflict.item_id not in item_ids for conflict in trace.conflicts):
            raise FreezeError(f"case {case.case_id}: conflict refers to an unknown item")
        allowed = _allowed_chunks(case, inventory)
        referenced = {
            evidence_id
            for collection in (trace.items, trace.readings, trace.conflicts)
            for item in collection
            for evidence_id in item.evidence_ids
        }
        if not referenced <= allowed:
            raise FreezeError(
                f"case {case.case_id}: annotation cites inadmissible or unknown chunks"
            )


def stratum(case: "EvaluationCase") -> str:
    """F14 is always separate; synthetic sources never enter the real stratum."""
    if case.family == "F14":
        return f"F14_{case.source_kind or 'unclassified'}"
    if case.source_kind == "synthetic":
        return "synthetic"
    if case.source_kind == "real":
        return "real"
    return "unclassified_dev"
