"""Rótulos humanos do conjunto de avaliação da política v1 (P2).

Implementação equivalente, documentada, da ferramenta ``p2_labels_tool.py``
referida pela v1.7 — o ficheiro original não está disponível a este repositório.
Os modelos Pydantic são a fonte de verdade do esquema JSON dependente,
versionado em ``docs/evaluation/policy-v1/labels.schema.json``.

Princípios
----------

- **N/A é separado das categorias substantivas.** Cada campo rotulável tem
  aplicabilidade própria: ``None`` significa "não aplicável", e nunca é um valor
  dentro da lista de categorias. Ex.: ``partial_misleading`` só se aplica a
  suficiência parcial.
- **Materialidade, desambiguação e cobertura de D3 são campos distintos.**
- **Nenhum modelo cria rótulos.** Este módulo valida, compara e transporta
  rótulos escritos por pessoas; não sugere nem preenche valores.
- O modo ``check`` calcula acordo; **não** calcula ações nem preenche rótulos.
- O modo ``oracle`` só aceita uma **adjudicação identificada** cujo digest
  corresponde a um congelamento verificado.
"""

from collections.abc import Callable, Mapping, Sequence
from datetime import date
from typing import Annotated, Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.decision.contracts import DecisionOutcome, RequestConstraint, ScopeClass
from app.decision.dimensions import (
    AdmissibilityAssessment,
    CompetentService,
    ConflictAssessment,
    DestinationResolution,
    EstimateOrigin,
    EvidenceConflict,
    ItemSupport,
    PolicyInput,
    Reading,
    Specificity,
    SpecificityAssessment,
    SupportAssessment,
)
from app.evaluation.policy_v1.freeze import FreezeError, canonical_bytes, verify_artifact
from app.evaluation.policy_v1.statistics import cohen_kappa

LABELS_SCHEMA_VERSION: Final = "policy_v1_labels_1"

Sufficiency = Literal["full", "partial", "none"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ScopeLabel(_Strict):
    """D1. ``scope=None`` é N/A."""

    scope: ScopeClass | None


class ConstraintsLabel(_Strict):
    """D2. Lista vazia = sem restrições; ``None`` = N/A."""

    constraints: list[RequestConstraint] | None

    @model_validator(mode="after")
    def unique(self) -> "ConstraintsLabel":
        if self.constraints is not None and len(set(self.constraints)) != len(self.constraints):
            msg = "constraints must be unique"
            raise ValueError(msg)
        return self


class SpecificityLabel(_Strict):
    """D3, com materialidade, desambiguação e cobertura separadas.

    ``disambiguation`` (o utilizador consegue distinguir as leituras) e
    ``coverage`` (todas as leituras materiais têm evidência admissível) só se
    aplicam quando a ambiguidade é material.
    """

    specificity: Specificity | None
    materiality: bool | None
    disambiguation: bool | None
    coverage: bool | None

    @model_validator(mode="after")
    def dependent(self) -> "SpecificityLabel":
        if self.specificity is None:
            if any(v is not None for v in (self.materiality, self.disambiguation, self.coverage)):
                msg = "a non-applicable D3 has no sub-labels"
                raise ValueError(msg)
            return self
        if self.materiality is None:
            msg = "materiality is required when D3 applies"
            raise ValueError(msg)
        if self.specificity is Specificity.SPECIFIED and self.materiality:
            msg = "a specified request cannot have material ambiguity"
            raise ValueError(msg)
        if self.materiality and (self.disambiguation is None or self.coverage is None):
            msg = "disambiguation and coverage are required when ambiguity is material"
            raise ValueError(msg)
        if not self.materiality and (self.disambiguation is not None or self.coverage is not None):
            msg = "disambiguation and coverage only apply to material ambiguity"
            raise ValueError(msg)
        return self


class SupportLabel(_Strict):
    """D4. ``partial_misleading`` só se aplica a suficiência parcial."""

    sufficiency: Sufficiency | None
    partial_misleading: bool | None

    @model_validator(mode="after")
    def dependent(self) -> "SupportLabel":
        if (self.sufficiency == "partial") != (self.partial_misleading is not None):
            msg = "partial_misleading applies exactly when sufficiency is partial"
            raise ValueError(msg)
        return self


class ConflictLabel(_Strict):
    """D5. ``None`` = N/A."""

    unresolvable_conflict: bool | None


class DestinationLabel(_Strict):
    """D6. ``has_competent_service=None`` = N/A; ``service_id`` só com serviço."""

    has_competent_service: bool | None
    service_id: str | None

    @model_validator(mode="after")
    def dependent(self) -> "DestinationLabel":
        if (self.has_competent_service is True) != (self.service_id is not None):
            msg = "service_id is required exactly when a competent service exists"
            raise ValueError(msg)
        return self


class CaseLabels(_Strict):
    case_id: Annotated[str, Field(min_length=1, max_length=64)]
    d1: ScopeLabel
    d2: ConstraintsLabel
    d3: SpecificityLabel
    d4: SupportLabel
    d5: ConflictLabel
    d6: DestinationLabel
    acceptable_actions: Annotated[list[DecisionOutcome], Field(min_length=1)]


class AnnotatorIdentity(_Strict):
    annotator_id: Annotated[str, Field(min_length=1, max_length=64)]
    role: Literal["annotator", "adjudication"]
    #: Obrigatório numa adjudicação: quem adjudicou.
    adjudicators: list[str] = []

    @model_validator(mode="after")
    def identified(self) -> "AnnotatorIdentity":
        if self.role == "adjudication" and not self.adjudicators:
            msg = "an adjudication must identify its adjudicators"
            raise ValueError(msg)
        return self


class LabelSet(_Strict):
    schema_version: Literal["policy_v1_labels_1"]
    set_id: Annotated[str, Field(min_length=1, max_length=64)]
    annotator: AnnotatorIdentity
    cases: list[CaseLabels]

    @model_validator(mode="after")
    def unique_ids(self) -> "LabelSet":
        ids = [case.case_id for case in self.cases]
        if len(set(ids)) != len(ids):
            msg = "case_id values must be unique"
            raise ValueError(msg)
        return self


class MessageRating(_Strict):
    """Juízo humano sobre a mensagem da execução principal de um caso.

    A v1.7 pede a qualidade da mensagem mas o prompt não define critérios; o
    juízo é, por isso, um único "aceitável / não aceitável" de um avaliador
    humano identificado, com nota livre. Critérios mais finos dependem do
    documento da v1.7. Nenhum modelo produz estas avaliações.
    """

    case_id: Annotated[str, Field(min_length=1, max_length=64)]
    condition: Annotated[str, Field(min_length=1, max_length=32)]
    rater_id: Annotated[str, Field(min_length=1, max_length=64)]
    acceptable: bool
    notes: Annotated[str, Field(max_length=2000)] | None = None


class MessageRatingSet(_Strict):
    schema_version: Literal["policy_v1_message_ratings_1"]
    set_id: Annotated[str, Field(min_length=1, max_length=64)]
    ratings: list[MessageRating]

    @model_validator(mode="after")
    def one_rating_per_message(self) -> "MessageRatingSet":
        keys = [(rating.case_id, rating.condition) for rating in self.ratings]
        if len(set(keys)) != len(keys):
            msg = "one rating per case and condition"
            raise ValueError(msg)
        return self


def label_set_bytes(label_set: LabelSet) -> bytes:
    """Bytes congelados de um conjunto de rótulos (casos ordenados por id)."""
    payload = label_set.model_dump(mode="json")
    payload["cases"] = sorted(payload["cases"], key=lambda case: case["case_id"])
    return canonical_bytes(payload)


# ---------------------------------------------------------------------------
# Modo check — acordo entre anotadores
# ---------------------------------------------------------------------------

#: Campos comparados, um por juízo distinto. ``None`` é N/A.
LABEL_FIELDS: Final[Mapping[str, Callable[[CaseLabels], Any]]] = {
    "d1.scope": lambda c: c.d1.scope,
    "d2.constraints": lambda c: (
        None if c.d2.constraints is None else tuple(sorted(c.d2.constraints))
    ),
    "d3.specificity": lambda c: c.d3.specificity,
    "d3.materiality": lambda c: c.d3.materiality,
    "d3.disambiguation": lambda c: c.d3.disambiguation,
    "d3.coverage": lambda c: c.d3.coverage,
    "d4.sufficiency": lambda c: c.d4.sufficiency,
    "d4.partial_misleading": lambda c: c.d4.partial_misleading,
    "d5.unresolvable_conflict": lambda c: c.d5.unresolvable_conflict,
    "d6.has_competent_service": lambda c: c.d6.has_competent_service,
    "d6.service_id": lambda c: c.d6.service_id,
    "acceptable_actions": lambda c: tuple(sorted(a.value for a in c.acceptable_actions)),
}


class LabelCheckError(ValueError):
    """Os dois conjuntos de rótulos não são comparáveis."""


def check_agreement(first: LabelSet, second: LabelSet) -> dict[str, Any]:
    """Acordo entre dois anotadores. Não calcula ações nem altera rótulos.

    Exige conjuntos completos e iguais de ``case_id``. A aplicabilidade
    assimétrica (um anota, o outro marca N/A) é reportada por campo; o acordo
    substantivo usa apenas os casos em que ambos aplicaram o campo.
    """
    if first.set_id != second.set_id:
        msg = "label sets belong to different case sets"
        raise LabelCheckError(msg)
    by_id_a = {case.case_id: case for case in first.cases}
    by_id_b = {case.case_id: case for case in second.cases}
    if set(by_id_a) != set(by_id_b):
        msg = "label sets must cover exactly the same case ids"
        raise LabelCheckError(msg)
    case_ids = sorted(by_id_a)
    fields: dict[str, Any] = {}
    for name, read in LABEL_FIELDS.items():
        asymmetric = sorted(
            case_id
            for case_id in case_ids
            if (read(by_id_a[case_id]) is None) != (read(by_id_b[case_id]) is None)
        )
        both = [
            case_id
            for case_id in case_ids
            if read(by_id_a[case_id]) is not None and read(by_id_b[case_id]) is not None
        ]
        result = cohen_kappa(
            [_category(read(by_id_a[case_id])) for case_id in both],
            [_category(read(by_id_b[case_id])) for case_id in both],
        )
        fields[name] = {
            **result.as_dict(),
            "not_applicable_both": sum(
                1
                for case_id in case_ids
                if read(by_id_a[case_id]) is None and read(by_id_b[case_id]) is None
            ),
            "asymmetric_applicability": asymmetric,
        }
    return {
        "set_id": first.set_id,
        "n_cases": len(case_ids),
        "annotators": sorted([first.annotator.annotator_id, second.annotator.annotator_id]),
        "fields": fields,
        "symmetric_applicability": all(
            not field["asymmetric_applicability"] for field in fields.values()
        ),
    }


def _category(value: Any) -> str:
    if isinstance(value, tuple):
        return "+".join(str(item) for item in value) or "<empty>"
    return str(getattr(value, "value", value))


# ---------------------------------------------------------------------------
# Modo oracle — dimensões adjudicadas para a condição P-oráculo
# ---------------------------------------------------------------------------


def verified_adjudication(label_set: LabelSet, freeze_manifest: Mapping[str, Any]) -> LabelSet:
    """Só uma adjudicação identificada e congelada chega ao P-oráculo."""
    if label_set.annotator.role != "adjudication":
        msg = "the oracle only accepts an identified adjudication"
        raise FreezeError(msg)
    if not freeze_manifest.get("complete"):
        msg = "the freeze manifest is incomplete"
        raise FreezeError(msg)
    verify_artifact(freeze_manifest, "labels", label_set_bytes(label_set))
    return label_set


#: Identificadores abstratos de evidência do P-oráculo. As dimensões humanas
#: não se referem às passagens de uma execução; estes marcadores satisfazem a
#: validação D0 da mesma implementação da política sem as inventar.
ORACLE_EVIDENCE: Final = ("G1", "G2")


def oracle_policy_input(
    case: CaseLabels,
    *,
    services: Sequence[Mapping[str, Any]],
    catalog_version: int,
    reference_date: date,
) -> PolicyInput:
    """Traduz dimensões adjudicadas em entradas da **mesma** política."""
    if case.d1.scope is None or case.d2.constraints is None:
        msg = f"case {case.case_id}: D1 and D2 are required by the oracle"
        raise ValueError(msg)
    service = None
    if case.d6.has_competent_service:
        raw = next((s for s in services if s.get("service_id") == case.d6.service_id), None)
        if raw is None:
            msg = f"case {case.case_id}: service {case.d6.service_id} is not in the catalog"
            raise ValueError(msg)
        service = CompetentService(
            service_id=raw["service_id"],
            name=raw["name"],
            email=raw.get("email"),
            url=raw.get("url"),
        )
    origin = EstimateOrigin.HUMAN_ADJUDICATED
    specificity = support = conflict = None
    documentary = case.d3.specificity is not None and case.d4.sufficiency is not None
    if documentary:
        assert case.d3.specificity is not None
        material = bool(case.d3.materiality)
        readings: tuple[Reading, ...] = ()
        if material:
            readings = (
                Reading("L1", "reading 1", frozenset({"G1"})),
                Reading("L2", "reading 2", frozenset({"G2"}) if case.d3.coverage else frozenset()),
            )
        specificity = SpecificityAssessment(
            specificity=case.d3.specificity,
            readings=readings,
            ambiguity_material=material,
            user_can_distinguish=bool(case.d3.disambiguation),
            origin=origin,
        )
        sufficiency = case.d4.sufficiency
        items: tuple[ItemSupport, ...] = (
            ItemSupport(
                "I1",
                "item 1",
                sufficiency != "none",
                frozenset({"G1"}) if sufficiency != "none" else frozenset(),
            ),
        )
        if sufficiency == "partial":
            items = (*items, ItemSupport("I2", "item 2", False))
        support = SupportAssessment(
            items=items, partial_misleading=case.d4.partial_misleading, origin=origin
        )
        conflict = ConflictAssessment(
            conflicts=(EvidenceConflict("I1", ORACLE_EVIDENCE, resolvable=False),)
            if case.d5.unresolvable_conflict
            else (),
            origin=origin,
        )
    return PolicyInput(
        scope=case.d1.scope,
        scope_origin=origin,
        constraints=frozenset(case.d2.constraints),
        constraints_origin=origin,
        admissibility=AdmissibilityAssessment(
            evidence_ids=frozenset(ORACLE_EVIDENCE),
            eligibility_policy="oracle",
            conditions=(),
            requester_role="oracle",
            access_policy_version="oracle",
            reference_date=reference_date,
            origin=origin,
        ),
        destination=DestinationResolution(
            service=service,
            topic=case.d6.service_id,
            catalog_version=catalog_version,
            origin=origin,
        ),
        reference_date=reference_date,
        specificity=specificity,
        support=support,
        conflict=conflict,
    )
