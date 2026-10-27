"""Execução de um caso do conjunto de avaliação da política v1, por execução.

Liga a base de dados (recuperação, snapshot) às condições puras sobre packets.
Usado pelo script ``scripts/run_policy_v1_evaluation.py`` e pelos testes; não
é importado pela aplicação.

Papéis simulados existem **só aqui**: o papel de cada caso vem do ficheiro de
casos e entra na recuperação offline, nunca na API. O isolamento institucional
e a autorização por papel (C13) aplicam-se exatamente como em operação; a
ablação A-sem-filtro relaxa apenas C9/C10, e só em ``development``/``test``.

O contrato dos casos vive em :mod:`app.evaluation.policy_v1.cases`, sem
configuração nem base de dados; os seus nomes continuam importáveis daqui.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.answering.base import AnswerGenerator, ContextEvidence
from app.answering.context import select_evidence
from app.core.config import MOCK_PROVIDER_ENVIRONMENTS, settings
from app.decision.contracts import ScopeClass
from app.decision.estimators.base import (
    AnalysisRequest,
    CatalogTopicView,
    DimensionEstimator,
    RequestAnalysis,
    validate_analysis,
)
from app.documents.retrievability import (
    DOCUMENT_ACCESS_POLICY_VERSION,
    RELAXABLE_CONDITIONS,
    RetrievalEligibility,
)
from app.evaluation.policy_v1.artifacts import catalog_snapshot
from app.evaluation.policy_v1.cases import (
    CASES_SCHEMA_VERSION as CASES_SCHEMA_VERSION,
)
from app.evaluation.policy_v1.cases import EvaluationCase
from app.evaluation.policy_v1.cases import (
    EvaluationCaseSet as EvaluationCaseSet,
)
from app.evaluation.policy_v1.conditions import (
    BaselineModel,
    CaseOutcome,
    Condition,
    Limits,
    PEndToEndResult,
    run_b0,
    run_b1_composition,
    run_b1_full,
    run_p_e2e,
    run_without_diagnostic,
)
from app.evaluation.policy_v1.packets import EvidencePacket, PacketPassage
from app.evaluation.snapshot_builder import build_evaluation_snapshot
from app.models.decision_catalog import InstitutionDecisionCatalog
from app.retrieval.base import RetrievalContext, RetrievalQuery, Retriever
from app.services.decision_service import gather_evidence


@dataclass(frozen=True)
class CaseRun:
    """Tudo o que uma execução produziu para um caso."""

    case_id: str
    run_number: int
    packets: dict[str, EvidencePacket]
    outcomes: list[CaseOutcome] = field(default_factory=list)


def _b0_packet(
    db: Session,
    retriever: Retriever,
    case: EvaluationCase,
    *,
    institution_id: UUID,
    run_number: int,
    catalog: dict[str, Any],
    top_k: int,
    limits: Limits,
    relax_validity: bool,
    snapshot: tuple[str | None, str | None],
) -> EvidencePacket:
    if relax_validity and settings.environment not in MOCK_PROVIDER_ENVIRONMENTS:
        msg = "A-sem-filtro only runs in an isolated development/test environment"
        raise RuntimeError(msg)
    context = RetrievalContext(
        institution_id=institution_id,
        language=case.language,
        reference_date=case.reference_date,
        requester_role=case.requester_role,
        relaxed_conditions=RELAXABLE_CONDITIONS if relax_validity else frozenset(),
    )
    result = retriever.search(
        db, RetrievalQuery.from_text(case.query), context, top_k, case.official_only
    )
    entries = select_evidence(
        result.evidence, limits.max_context_chars, query=case.query, language=case.language
    )
    return EvidencePacket(
        case_id=case.case_id,
        family="b0_without_validity_filter" if relax_validity else "b0",
        run_number=run_number,
        query=case.query,
        language=case.language,
        reference_date=case.reference_date,
        requester_role=case.requester_role,
        catalog=catalog,
        passages=tuple(PacketPassage.from_entry(entry) for entry in entries),
        retrieval={
            "retriever": type(retriever).__name__,
            "top_k": top_k,
            "official_only": case.official_only,
            "relaxed_conditions": sorted(context.relaxed_conditions),
            "max_context_chars": limits.max_context_chars,
        },
        snapshot_id=snapshot[0],
        corpus_digest=snapshot[1],
    )


def _p_e2e_packet(
    db: Session,
    retriever: Retriever,
    case: EvaluationCase,
    analysis: RequestAnalysis,
    *,
    institution_id: UUID,
    run_number: int,
    catalog: dict[str, Any],
    snapshot: tuple[str | None, str | None],
) -> EvidencePacket:
    context = RetrievalContext(
        institution_id=institution_id,
        language=case.language,
        reference_date=case.reference_date,
        requester_role=case.requester_role,
    )
    in_scope = analysis.scope is ScopeClass.IN_SCOPE
    entries: tuple[ContextEvidence, ...] = ()
    diagnostic = None
    queries = per_reading = 0
    if in_scope and (not analysis.constraints or analysis.procedure_item is not None):
        query = (
            analysis.procedure_item.label
            if analysis.constraints and analysis.procedure_item is not None
            else case.query
        )
        gathered = gather_evidence(
            db,
            retriever,
            analysis=analysis,
            query=query,
            context=context,
            official_only=case.official_only,
            language=case.language,
            institution_name="",
            with_diagnostic=not analysis.constraints,
        )
        entries, diagnostic = gathered.entries, gathered.diagnostic
        queries, per_reading = gathered.queries, int(gathered.per_reading)
    packet_kwargs: dict[str, Any] = {}
    if diagnostic is not None:
        packet_kwargs["diagnostic"] = diagnostic
    return EvidencePacket(
        case_id=case.case_id,
        family="p_e2e",
        run_number=run_number,
        query=case.query,
        language=case.language,
        reference_date=case.reference_date,
        requester_role=case.requester_role,
        catalog=catalog,
        passages=tuple(PacketPassage.from_entry(entry) for entry in entries),
        retrieval={
            "retriever": type(retriever).__name__,
            "top_k": settings.decision_retrieval_top_k,
            "official_only": case.official_only,
            "queries": queries,
            "per_reading": bool(per_reading),
            "eligibility_policy": RetrievalEligibility.name,
            "conditions": list(RetrievalEligibility.condition_names),
            "access_policy_version": DOCUMENT_ACCESS_POLICY_VERSION,
            "max_context_chars": settings.answering_max_context_chars,
        },
        snapshot_id=snapshot[0],
        corpus_digest=snapshot[1],
        **packet_kwargs,
    )


def run_case(
    db: Session,
    case: EvaluationCase,
    *,
    run_number: int,
    institution_id: UUID,
    catalog: InstitutionDecisionCatalog,
    retriever: Retriever,
    estimator_factory: Callable[[], DimensionEstimator],
    generator: AnswerGenerator,
    baseline_model: BaselineModel,
    limits: Limits,
    b0_top_k: int,
) -> CaseRun:
    """Uma execução numerada de um caso, em todas as condições com modelo.

    O packet ``p_e2e`` é construído uma vez por execução e entregue, igual, a
    P-e2e, A-sem-diagnóstico, B1-plena e B1-composição.
    """
    catalog_payload = catalog_snapshot(catalog)
    snapshot = build_evaluation_snapshot(
        db,
        institution_id=institution_id,
        language=case.language,
        reference_date=case.reference_date,
        top_k=b0_top_k,
        official_only=case.official_only,
        # O corpus do snapshot é o que o papel simulado do caso pode ver: o
        # mesmo universo de onde saem as passagens dos packets.
        requester_role=case.requester_role,
    )
    identity = (snapshot.snapshot_id, snapshot.corpus_digest)
    if case.expected_snapshot_id is not None and snapshot.snapshot_id != case.expected_snapshot_id:
        raise ValueError(f"case {case.case_id}: the corpus snapshot differs from its annotation")
    run = CaseRun(case_id=case.case_id, run_number=run_number, packets={})

    b0 = _b0_packet(
        db,
        retriever,
        case,
        institution_id=institution_id,
        run_number=run_number,
        catalog=catalog_payload,
        top_k=b0_top_k,
        limits=limits,
        relax_validity=False,
        snapshot=identity,
    )
    no_filter = _b0_packet(
        db,
        retriever,
        case,
        institution_id=institution_id,
        run_number=run_number,
        catalog=catalog_payload,
        top_k=b0_top_k,
        limits=limits,
        relax_validity=True,
        snapshot=identity,
    )
    run.packets["b0"] = b0
    run.packets["b0_without_validity_filter"] = no_filter
    run.outcomes.append(run_b0(b0, generator, limits))
    run.outcomes.append(run_b0(no_filter, generator, limits, condition=Condition.A_NO_FILTER))

    estimator = estimator_factory()
    topics = tuple(CatalogTopicView(t["code"], t["label"]) for t in catalog.topics)
    try:
        analysis = estimator.analyze(
            AnalysisRequest(
                query=case.query,
                language=case.language,
                reference_date=case.reference_date,
                requester_role=case.requester_role,
                scope_description=catalog.scope_description,
                topics=topics,
            )
        )
        validate_analysis(analysis, [topic.code for topic in topics])
    except Exception as exc:
        # Falha técnica da análise: registada em cada condição dependente, nunca
        # convertida numa ação.
        reason = getattr(exc, "reason_code", None) or type(exc).__name__
        for condition in (
            Condition.P_E2E,
            Condition.A_NO_DIAGNOSTIC,
            Condition.B1_FULL,
            Condition.B1_COMPOSITION,
        ):
            run.outcomes.append(
                CaseOutcome(
                    case_id=case.case_id,
                    condition=condition,
                    run_number=run_number,
                    action=None,
                    rule=None,
                    message=None,
                    cited_evidence_ids=(),
                    destination_service_id=None,
                    failure=f"analysis:{reason}",
                    packet_digest=None,
                    duration_ms=0,
                )
            )
        return run
    packet = _p_e2e_packet(
        db,
        retriever,
        case,
        analysis,
        institution_id=institution_id,
        run_number=run_number,
        catalog=catalog_payload,
        snapshot=identity,
    )
    run.packets["p_e2e"] = packet
    p_e2e: PEndToEndResult = run_p_e2e(packet, analysis, estimator, generator, limits)
    run.outcomes.append(p_e2e.outcome)
    run.outcomes.append(run_without_diagnostic(packet, p_e2e, generator, limits))
    run.outcomes.append(run_b1_full(packet, baseline_model))
    run.outcomes.append(run_b1_composition(packet, p_e2e, baseline_model))
    return run
