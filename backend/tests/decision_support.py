"""Suporte técnico aos testes da política de decisão v1.7.

Tudo aqui é **sintético e técnico**: doubles determinísticos, documentos
inventados e catálogos de teste. Não é anotação científica nem um conjunto de
avaliação — serve para fixar o comportamento do código.

O :class:`ScriptedEstimator` não "estima" nada: devolve a análise fixada por
cada teste e calcula a avaliação com uma função também fixada pelo teste. É o
double determinístico previsto pela v1.7 para os testes; o estimador real é o
adaptador configurável em desenvolvimento.
"""

import io
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

from fastapi.testclient import TestClient

from app.answering.base import AnsweringContext, GeneratedAnswer
from app.decision.contracts import RequestConstraint, ScopeClass
from app.decision.dimensions import EstimateOrigin, Specificity
from app.decision.estimators.base import (
    AnalysisRequest,
    AssessmentRequest,
    ConflictDraft,
    EstimationUsage,
    EstimatorIdentity,
    EvidenceAssessment,
    ItemDraft,
    ItemSupportDraft,
    ReadingDraft,
    RequestAnalysis,
)
from tests.role_support import create_account_and_login
from tests.test_role_separation import _create_admin, _create_institution

DEFAULT_CATALOG = {
    "scope_description": (
        "Atendimento académico sintético: matrículas, inscrições, propinas, "
        "avaliação e calendário escolar."
    ),
    "topics": [
        {"code": "enrolment", "label": "Matrículas e inscrições"},
        {"code": "grades", "label": "Avaliação e notas"},
        {"code": "fees", "label": "Propinas"},
    ],
    "services": [
        {
            "service_id": "academic-office",
            "name": "Serviços Académicos (sintético)",
            "email": "academicos@example.org",
            "topics": ["enrolment", "grades"],
        }
    ],
}


def analysis(
    *,
    scope: ScopeClass = ScopeClass.IN_SCOPE,
    constraints: frozenset[RequestConstraint] = frozenset(),
    specificity: Specificity = Specificity.SPECIFIED,
    ambiguity_material: bool = False,
    user_can_distinguish: bool = False,
    readings: tuple[ReadingDraft, ...] = (),
    items: tuple[ItemDraft, ...] = (ItemDraft("I1", "prazo de matrícula"),),
    topic: str | None = "enrolment",
    procedure_item: ItemDraft | None = None,
) -> RequestAnalysis:
    return RequestAnalysis(
        scope=scope,
        constraints=constraints,
        specificity=specificity,
        ambiguity_material=ambiguity_material,
        user_can_distinguish=user_can_distinguish,
        readings=readings,
        items=items,
        topic=topic,
        procedure_item=procedure_item,
    )


def ids_with_title(request: AssessmentRequest, fragment: str) -> frozenset[str]:
    """Evidências cujo título contém o fragmento — regra **do teste**, não do sistema."""
    return frozenset(
        passage.evidence_id for passage in request.passages if fragment in passage.document_title
    )


def support_by_title(
    mapping: dict[str, str],
    *,
    partial_misleading: bool | None = None,
    coverage: dict[str, str] | None = None,
    conflicts: tuple[tuple[str, tuple[str, ...], bool], ...] = (),
) -> Callable[[AssessmentRequest], EvidenceAssessment]:
    """Avaliação fixada pelo teste: item → fragmento de título que o suporta."""

    def assess(request: AssessmentRequest) -> EvidenceAssessment:
        supports = []
        for item in request.items:
            evidence = (
                ids_with_title(request, mapping[item.item_id])
                if item.item_id in mapping
                else frozenset()
            )
            supports.append(
                ItemSupportDraft(
                    item_id=item.item_id, supported=bool(evidence), evidence_ids=evidence
                )
            )
        supported = sum(1 for support in supports if support.supported)
        partial = 0 < supported < len(supports)
        covering = coverage or {}
        return EvidenceAssessment(
            reading_coverage={
                reading.reading_id: (
                    ids_with_title(request, covering[reading.reading_id])
                    if reading.reading_id in covering
                    else frozenset()
                )
                for reading in request.readings
            },
            item_support=tuple(supports),
            partial_misleading=partial_misleading if partial else None,
            conflicts=tuple(
                ConflictDraft(
                    item_id=item_id,
                    evidence_ids=tuple(
                        sorted(
                            eid
                            for fragment in fragments
                            for eid in ids_with_title(request, fragment)
                        )
                    ),
                    resolvable=resolvable,
                )
                for item_id, fragments, resolvable in conflicts
            ),
        )

    return assess


@dataclass
class ScriptedEstimator:
    """Double determinístico do estimador, com registo das chamadas."""

    result: RequestAnalysis
    assess_with: Callable[[AssessmentRequest], EvidenceAssessment] = field(
        default=lambda request: support_by_title({})(request)
    )
    analysis_calls: list[AnalysisRequest] = field(default_factory=list)
    assessment_calls: list[AssessmentRequest] = field(default_factory=list)
    fail_with: Exception | None = None
    _usage: EstimationUsage = field(default_factory=EstimationUsage)

    @property
    def identity(self) -> EstimatorIdentity:
        return EstimatorIdentity(
            provider="scripted-test-double",
            model=None,
            analysis_prompt_version="test",
            assessment_prompt_version="test",
            definitions_version="test",
            origin=EstimateOrigin.TEST_DOUBLE,
        )

    @property
    def usage(self) -> EstimationUsage:
        return self._usage

    def analyze(self, request: AnalysisRequest) -> RequestAnalysis:
        self._usage.attempts += 1
        self.analysis_calls.append(request)
        if self.fail_with is not None:
            raise self.fail_with
        return self.result

    def assess(self, request: AssessmentRequest) -> EvidenceAssessment:
        self._usage.attempts += 1
        self.assessment_calls.append(request)
        return self.assess_with(request)


class RecordingGenerator:
    """Gerador falso: cita a primeira evidência de cada item, por ordem."""

    def __init__(self, cite: Callable[[AnsweringContext], tuple[str, ...]] | None = None) -> None:
        self.calls: list[AnsweringContext] = []
        self.cite = cite

    def generate(self, context: AnsweringContext) -> GeneratedAnswer:
        self.calls.append(context)
        cited = (
            self.cite(context)
            if self.cite is not None
            else tuple(entry.evidence_id for entry in context.evidence)
        )
        return GeneratedAnswer(answer="Resposta sintética fundamentada.", cited_evidence_ids=cited)


@dataclass
class World:
    """Uma instituição sintética com admin, gestor documental e aluno."""

    institution_id: str
    admin: dict[str, str]
    manager: dict[str, str]
    student: dict[str, str]
    student_id: str

    def document(
        self,
        client: TestClient,
        title: str,
        content: str,
        *,
        access_roles: list[str] | None = None,
        valid_from: date | None = None,
        valid_until: date | None = None,
    ) -> tuple[dict, dict]:
        payload: dict = {
            "title": title,
            "language": "pt",
            "official_source": True,
            "access_roles": access_roles or [],
        }
        if valid_from is not None:
            payload["valid_from"] = valid_from.isoformat()
        if valid_until is not None:
            payload["valid_until"] = valid_until.isoformat()
        document = client.post("/api/v1/documents", json=payload, headers=self.manager)
        assert document.status_code == 201, document.text
        version = client.post(
            f"/api/v1/documents/{document.json()['id']}/versions",
            files={"file": (f"{uuid.uuid4().hex}.txt", io.BytesIO(content.encode()), "text/plain")},
            headers=self.manager,
        )
        assert version.status_code == 201, version.text
        assert version.json()["processing_status"] == "processed"
        return document.json(), version.json()

    def conversation(self, client: TestClient, headers: dict[str, str] | None = None) -> str:
        response = client.post(
            "/api/v1/conversations", json={"title": "Política"}, headers=headers or self.student
        )
        assert response.status_code == 201, response.text
        return response.json()["id"]


def make_world(client: TestClient, *, catalog: dict | None = DEFAULT_CATALOG) -> World:
    institution_id = _create_institution(client)
    admin, _ = _create_admin(client, institution_id)
    manager, _ = create_account_and_login(client, admin, role="knowledge_manager")
    student, student_id = create_account_and_login(client, admin, role="student")
    if catalog is not None:
        published = client.put("/api/v1/decision/catalog", json=catalog, headers=admin)
        assert published.status_code == 201, published.text
    return World(institution_id, admin, manager, student, student_id)


def decide(client: TestClient, conversation_id: str, headers: dict[str, str], **payload: object):
    body: dict = {"query": "Qual é o prazo de matrícula?"}
    body.update(payload)
    return client.post(
        f"/api/v1/conversations/{conversation_id}/decide", json=body, headers=headers
    )
