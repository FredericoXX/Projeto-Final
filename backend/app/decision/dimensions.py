"""Contratos tipados das dimensões D0–D6 da política de decisão v1.7.

Este módulo descreve **o que** a política recebe e devolve, sem decidir nada:
as regras R01–R12 vivem em :mod:`app.decision.policy`. Os valores serializados
reutilizam os de :mod:`app.decision.contracts` sempre que existem.

As sete dimensões, e o que cada uma **não** é
--------------------------------------------

- **D0 — admissibilidade documental** (:class:`AdmissibilityAssessment`):
  que evidências podem fundamentar a resposta, segundo ``RetrievalEligibility``
  (C1–C11) e a autorização documental por papel. Não é correspondência lexical
  (``app.retrieval.eligibility``), nem suficiência, nem ambiguidade.
- **D1 — âmbito** (``ScopeClass``): relativo ao domínio configurado da
  instituição; não à capacidade técnica.
- **D2 — restrições do pedido**: um conjunto, vazio quando não há restrições.
- **D3 — especificidade** (:class:`SpecificityAssessment`): leituras
  plausíveis, materialidade, possibilidade de o utilizador as distinguir e
  suporte admissível de cada leitura. Um pedido geral **não** é
  automaticamente ambíguo.
- **D4 — suporte e suficiência** (:class:`SupportAssessment`): suporte por item
  do pedido. Relevância temática e número de passagens não provam suporte.
- **D5 — conflito** (:class:`ConflictAssessment`): incompatibilidade não
  resolúvel sobre o mesmo item e nas mesmas condições. Diferenças de população,
  ou uma regra geral e uma específica coerentes, **não** são conflito. Não há
  hierarquia jurídica documental.
- **D6 — destino competente** (:class:`DestinationResolution`): resulta de um
  catálogo institucional versionado. Um destino genérico não prova competência.

Validação: D0 antes de D3, D4 e D5
----------------------------------

:class:`PolicyInput` recusa, na construção, qualquer leitura, item ou conflito
que cite uma evidência fora do conjunto admissível de D0. É essa verificação
que garante que a cobertura de uma leitura e o suporte de um item só contam
com evidência admissível — independentemente de o estimador o ter respeitado.

Origem das estimativas
----------------------

Cada dimensão estimada transporta :class:`EstimateOrigin`. Uma estimativa que
falha **não** é preenchida com um valor por omissão: a falha é técnica e é
tratada fora da política (ver :mod:`app.decision.estimators.base`).

Módulo puro: só biblioteca padrão e os contratos de decisão.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import Any, Final

from app.decision.contracts import (
    AnswerabilityClass,
    DecisionOutcome,
    RequestConstraint,
    ScopeClass,
)

#: Limites da pergunta fechada de CLARIFY: a v1.7 apresenta duas ou três
#: leituras materiais.
MIN_CLARIFY_READINGS: Final = 2
MAX_CLARIFY_READINGS: Final = 3


class PolicyInputError(ValueError):
    """Entradas da política incoerentes — erro de programação ou de validação.

    Nunca é convertido numa ação: uma entrada inválida não é ``ABSTAIN``.
    """


class EstimateOrigin(StrEnum):
    """De onde veio o valor de uma dimensão."""

    #: Estimador com modelo de linguagem (adaptador real).
    MODEL = "model"
    #: Double determinístico, apenas em testes.
    TEST_DOUBLE = "test_double"
    #: Dimensões humanas adjudicadas — só a condição P-oráculo as usa.
    HUMAN_ADJUDICATED = "human_adjudicated"
    #: Calculado deterministicamente pelo backend (D0, D6).
    BACKEND = "backend"


class Specificity(StrEnum):
    """D3: o pedido identifica aquilo que pede?"""

    SPECIFIED = "specified"
    UNDERSPECIFIED = "underspecified"


class RuleId(StrEnum):
    """As doze regras terminais da política v1.7."""

    R01 = "R01"
    R02 = "R02"
    R03 = "R03"
    R04 = "R04"
    R05 = "R05"
    R06 = "R06"
    R07 = "R07"
    R08 = "R08"
    R09 = "R09"
    R10 = "R10"
    R11 = "R11"
    R12 = "R12"


def _require_text(value: str, *, name: str, max_length: int = 300) -> None:
    if not isinstance(value, str) or not value.strip():
        msg = f"{name} must be a non-empty string"
        raise PolicyInputError(msg)
    if len(value) > max_length:
        msg = f"{name} must be at most {max_length} characters"
        raise PolicyInputError(msg)


# ---------------------------------------------------------------------------
# D0
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AdmissibilityAssessment:
    """D0: o conjunto de evidências admissíveis e o contexto que o decidiu.

    ``evidence_ids`` são os identificadores (E1, E2, ...) das passagens que
    passaram ``RetrievalEligibility`` e a autorização por papel. É o único
    universo que D3, D4 e D5 podem referir.
    """

    evidence_ids: frozenset[str]
    eligibility_policy: str
    conditions: tuple[str, ...]
    requester_role: str
    access_policy_version: str
    reference_date: date
    origin: EstimateOrigin = EstimateOrigin.BACKEND


# ---------------------------------------------------------------------------
# D3
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Reading:
    """Uma leitura plausível do pedido e a evidência admissível que a cobre."""

    reading_id: str
    label: str
    supporting_evidence_ids: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        _require_text(self.reading_id, name="reading_id", max_length=32)
        _require_text(self.label, name="reading label")

    @property
    def covered(self) -> bool:
        return bool(self.supporting_evidence_ids)


@dataclass(frozen=True)
class SpecificityAssessment:
    """D3: especificidade, leituras, materialidade e distinguibilidade.

    ``ambiguity_material`` diz se as leituras levam a respostas materialmente
    diferentes; ``user_can_distinguish`` se o utilizador consegue escolher
    entre elas. Um pedido ``SPECIFIED`` não tem ambiguidade material.
    """

    specificity: Specificity
    readings: tuple[Reading, ...] = ()
    ambiguity_material: bool = False
    user_can_distinguish: bool = False
    origin: EstimateOrigin = EstimateOrigin.MODEL

    def __post_init__(self) -> None:
        ids = [reading.reading_id for reading in self.readings]
        if len(set(ids)) != len(ids):
            msg = "reading ids must be unique"
            raise PolicyInputError(msg)
        if self.specificity is Specificity.SPECIFIED and self.ambiguity_material:
            msg = "a specified request cannot carry material ambiguity"
            raise PolicyInputError(msg)
        if self.ambiguity_material and len(self.readings) < MIN_CLARIFY_READINGS:
            msg = "material ambiguity requires at least two plausible readings"
            raise PolicyInputError(msg)

    @property
    def materially_ambiguous(self) -> bool:
        return self.specificity is Specificity.UNDERSPECIFIED and self.ambiguity_material

    @property
    def all_readings_covered(self) -> bool:
        return bool(self.readings) and all(reading.covered for reading in self.readings)

    @property
    def clarifiable(self) -> bool:
        """As três condições de R06, mais o limite da pergunta fechada."""
        return (
            self.materially_ambiguous
            and self.user_can_distinguish
            and self.all_readings_covered
            and MIN_CLARIFY_READINGS <= len(self.readings) <= MAX_CLARIFY_READINGS
        )


# ---------------------------------------------------------------------------
# D4
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ItemSupport:
    """Um item do pedido e o suporte **completo** que a evidência lhe dá."""

    item_id: str
    label: str
    supported: bool
    evidence_ids: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        _require_text(self.item_id, name="item_id", max_length=32)
        _require_text(self.label, name="item label")
        if self.supported and not self.evidence_ids:
            msg = "a supported item must name its supporting evidence"
            raise PolicyInputError(msg)
        if not self.supported and self.evidence_ids:
            msg = "an unsupported item cannot name supporting evidence"
            raise PolicyInputError(msg)


@dataclass(frozen=True)
class SupportAssessment:
    """D4: suporte por item; a suficiência é derivada, nunca estimada à parte.

    ``partial_misleading`` só tem sentido com suficiência parcial: diz se
    responder apenas à parte suportada induziria o utilizador em erro.
    """

    items: tuple[ItemSupport, ...]
    partial_misleading: bool | None = None
    origin: EstimateOrigin = EstimateOrigin.MODEL

    def __post_init__(self) -> None:
        if not self.items:
            msg = "a support assessment requires at least one request item"
            raise PolicyInputError(msg)
        ids = [item.item_id for item in self.items]
        if len(set(ids)) != len(ids):
            msg = "item ids must be unique"
            raise PolicyInputError(msg)
        partial = self.sufficiency is AnswerabilityClass.PARTIALLY_ANSWERABLE
        if partial and self.partial_misleading is None:
            msg = "partial support requires an explicit partial_misleading judgement"
            raise PolicyInputError(msg)
        if not partial and self.partial_misleading is not None:
            msg = "partial_misleading only applies to partial support"
            raise PolicyInputError(msg)

    @property
    def sufficiency(self) -> AnswerabilityClass:
        supported = sum(1 for item in self.items if item.supported)
        if supported == len(self.items):
            return AnswerabilityClass.FULLY_ANSWERABLE
        if supported:
            return AnswerabilityClass.PARTIALLY_ANSWERABLE
        return AnswerabilityClass.NOT_ANSWERABLE

    @property
    def supported_items(self) -> tuple[ItemSupport, ...]:
        return tuple(item for item in self.items if item.supported)

    @property
    def unsupported_items(self) -> tuple[ItemSupport, ...]:
        return tuple(item for item in self.items if not item.supported)


# ---------------------------------------------------------------------------
# D5
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EvidenceConflict:
    """Orientações incompatíveis sobre o mesmo item, nas mesmas condições."""

    item_id: str
    evidence_ids: tuple[str, ...]
    resolvable: bool

    def __post_init__(self) -> None:
        if len(set(self.evidence_ids)) < 2:
            msg = "a conflict involves at least two distinct pieces of evidence"
            raise PolicyInputError(msg)


@dataclass(frozen=True)
class ConflictAssessment:
    """D5: conflitos detetados; vazio quando não há conflito."""

    conflicts: tuple[EvidenceConflict, ...] = ()
    origin: EstimateOrigin = EstimateOrigin.MODEL

    @property
    def unresolvable(self) -> tuple[EvidenceConflict, ...]:
        return tuple(conflict for conflict in self.conflicts if not conflict.resolvable)

    @property
    def has_unresolvable_conflict(self) -> bool:
        return bool(self.unresolvable)


# ---------------------------------------------------------------------------
# D6
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CompetentService:
    """Serviço do catálogo com competência declarada para o tema do pedido."""

    service_id: str
    name: str
    email: str | None
    url: str | None

    def __post_init__(self) -> None:
        _require_text(self.service_id, name="service_id", max_length=64)
        _require_text(self.name, name="service name", max_length=255)
        if self.email is None and self.url is None:
            msg = "a competent service needs at least one contact"
            raise PolicyInputError(msg)


@dataclass(frozen=True)
class DestinationResolution:
    """D6: o serviço competente, ou a ausência dele, e o catálogo usado."""

    service: CompetentService | None
    topic: str | None
    catalog_version: int
    origin: EstimateOrigin = EstimateOrigin.BACKEND

    @property
    def has_competent_service(self) -> bool:
        return self.service is not None


# ---------------------------------------------------------------------------
# Diagnóstico temporal — informa a mensagem, nunca a ação
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ExcludedByValidity:
    """Documento relevante, autorizado, excluído só por não estar em vigor."""

    document_id: str
    document_title: str
    valid_from: date | None
    valid_until: date | None


@dataclass(frozen=True)
class TemporalDiagnostic:
    """Evidência relevante excluída por validade na data de referência.

    Vazio quando nada foi encontrado. A ausência de resultados **não** autoriza
    concluir que a informação está desatualizada. Ter documentos excluídos
    também não basta para o aviso: ver :func:`only_outside_validity_found`.
    """

    excluded: tuple[ExcludedByValidity, ...] = ()


def current_supporting_evidence(policy_input: "PolicyInput") -> frozenset[str]:
    """Evidência admissível (vigente) que suporta um item, cobre uma leitura ou
    entra num conflito — isto é, informação vigente **efetivamente encontrada**
    para o pedido, e não apenas recuperada."""
    found: set[str] = set()
    if policy_input.support is not None:
        for item in policy_input.support.items:
            found.update(item.evidence_ids)
    if policy_input.specificity is not None:
        for reading in policy_input.specificity.readings:
            found.update(reading.supporting_evidence_ids)
    if policy_input.conflict is not None:
        for conflict in policy_input.conflict.conflicts:
            found.update(conflict.evidence_ids)
    return frozenset(found)


def only_outside_validity_found(policy_input: "PolicyInput") -> bool:
    """A condição do aviso temporal da v1.7: "só foi encontrada informação
    caducada" — há documentos relevantes excluídos por validade **e** nenhuma
    evidência vigente suporta, cobre ou contradiz o pedido. Altera a mensagem,
    nunca a ação."""
    return bool(policy_input.diagnostic.excluded) and not current_supporting_evidence(policy_input)


# ---------------------------------------------------------------------------
# Entrada e resultado da política
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PolicyInput:
    """Entradas validadas da política.

    D3, D4 e D5 são ``None`` quando a decisão termina cedo (D1 fora de âmbito,
    D2 com restrições) e não foram recolhidas. A política recusa com
    :class:`PolicyInputError` se uma regra precisar de uma dimensão ausente.
    """

    scope: ScopeClass
    constraints: frozenset[RequestConstraint]
    admissibility: AdmissibilityAssessment
    destination: DestinationResolution
    reference_date: date
    specificity: SpecificityAssessment | None = None
    support: SupportAssessment | None = None
    conflict: ConflictAssessment | None = None
    diagnostic: TemporalDiagnostic = field(default_factory=TemporalDiagnostic)
    scope_origin: EstimateOrigin = EstimateOrigin.MODEL
    constraints_origin: EstimateOrigin = EstimateOrigin.MODEL

    def __post_init__(self) -> None:
        if self.admissibility.reference_date != self.reference_date:
            msg = "D0 must be evaluated at the decision reference date"
            raise PolicyInputError(msg)
        admissible = self.admissibility.evidence_ids
        cited: set[str] = set()
        if self.specificity is not None:
            for reading in self.specificity.readings:
                cited.update(reading.supporting_evidence_ids)
        if self.support is not None:
            for item in self.support.items:
                cited.update(item.evidence_ids)
        if self.conflict is not None:
            item_ids = (
                {item.item_id for item in self.support.items} if self.support is not None else set()
            )
            for conflict in self.conflict.conflicts:
                cited.update(conflict.evidence_ids)
                if conflict.item_id not in item_ids:
                    msg = "a conflict must refer to an item of the request"
                    raise PolicyInputError(msg)
        unknown = cited - admissible
        if unknown:
            # D0 antes de D3/D4/D5: só evidência admissível conta como suporte.
            msg = f"{len(unknown)} evidence reference(s) are not admissible under D0"
            raise PolicyInputError(msg)


@dataclass(frozen=True)
class DecisionFact:
    """Um facto que a regra aplicada usou, com a dimensão de onde veio."""

    dimension: str
    name: str
    value: Any

    def as_dict(self) -> dict[str, Any]:
        return {"dimension": self.dimension, "name": self.name, "value": self.value}


@dataclass(frozen=True)
class DecisionReason:
    """Razão reconstruível: a regra e os factos que a satisfizeram.

    Não contém raciocínio de nenhum modelo: só factos estruturados e a regra.
    """

    rule: RuleId
    facts: tuple[DecisionFact, ...]

    def as_dict(self) -> dict[str, Any]:
        return {"rule": self.rule.value, "facts": [fact.as_dict() for fact in self.facts]}


@dataclass(frozen=True)
class PolicyDecision:
    """O que a política decidiu, e tudo o que a mensagem precisa de saber."""

    action: DecisionOutcome
    rule: RuleId
    reason: DecisionReason
    policy_version: str
    answer_item_ids: tuple[str, ...] = ()
    gap_item_ids: tuple[str, ...] = ()
    clarify_reading_ids: tuple[str, ...] = ()
    conflict_evidence_ids: tuple[str, ...] = ()
    destination: CompetentService | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "action": self.action.value,
            "rule": self.rule.value,
            "policy_version": self.policy_version,
            "reason": self.reason.as_dict(),
            "answer_item_ids": list(self.answer_item_ids),
            "gap_item_ids": list(self.gap_item_ids),
            "clarify_reading_ids": list(self.clarify_reading_ids),
            "conflict_evidence_ids": list(self.conflict_evidence_ids),
            "destination_service_id": (
                None if self.destination is None else self.destination.service_id
            ),
        }


# ---------------------------------------------------------------------------
# Serialização das entradas (auditoria e replay)
# ---------------------------------------------------------------------------


def _date(value: date | None) -> str | None:
    return None if value is None else value.isoformat()


def policy_input_to_dict(value: PolicyInput) -> dict[str, Any]:
    """Forma JSON das entradas, suficiente para refazer a decisão (replay)."""
    specificity = value.specificity
    support = value.support
    conflict = value.conflict
    destination = value.destination
    return {
        "scope": {"value": value.scope.value, "origin": value.scope_origin.value},
        "constraints": {
            "value": sorted(constraint.value for constraint in value.constraints),
            "origin": value.constraints_origin.value,
        },
        "admissibility": {
            "evidence_ids": sorted(value.admissibility.evidence_ids),
            "eligibility_policy": value.admissibility.eligibility_policy,
            "conditions": list(value.admissibility.conditions),
            "requester_role": value.admissibility.requester_role,
            "access_policy_version": value.admissibility.access_policy_version,
            "reference_date": value.admissibility.reference_date.isoformat(),
            "origin": value.admissibility.origin.value,
        },
        "specificity": None
        if specificity is None
        else {
            "specificity": specificity.specificity.value,
            "readings": [
                {
                    "reading_id": reading.reading_id,
                    "label": reading.label,
                    "supporting_evidence_ids": sorted(reading.supporting_evidence_ids),
                }
                for reading in specificity.readings
            ],
            "ambiguity_material": specificity.ambiguity_material,
            "user_can_distinguish": specificity.user_can_distinguish,
            "origin": specificity.origin.value,
        },
        "support": None
        if support is None
        else {
            "items": [
                {
                    "item_id": item.item_id,
                    "label": item.label,
                    "supported": item.supported,
                    "evidence_ids": sorted(item.evidence_ids),
                }
                for item in support.items
            ],
            "partial_misleading": support.partial_misleading,
            "origin": support.origin.value,
        },
        "conflict": None
        if conflict is None
        else {
            "conflicts": [
                {
                    "item_id": item.item_id,
                    "evidence_ids": list(item.evidence_ids),
                    "resolvable": item.resolvable,
                }
                for item in conflict.conflicts
            ],
            "origin": conflict.origin.value,
        },
        "destination": {
            "service": None
            if destination.service is None
            else {
                "service_id": destination.service.service_id,
                "name": destination.service.name,
                "email": destination.service.email,
                "url": destination.service.url,
            },
            "topic": destination.topic,
            "catalog_version": destination.catalog_version,
            "origin": destination.origin.value,
        },
        "diagnostic": {
            "excluded": [
                {
                    "document_id": item.document_id,
                    "document_title": item.document_title,
                    "valid_from": _date(item.valid_from),
                    "valid_until": _date(item.valid_until),
                }
                for item in value.diagnostic.excluded
            ]
        },
        "reference_date": value.reference_date.isoformat(),
    }


def _parse_date(value: str | None) -> date | None:
    return None if value is None else date.fromisoformat(value)


def policy_input_from_dict(payload: Mapping[str, Any]) -> PolicyInput:
    """Reconstrói as entradas a partir de :func:`policy_input_to_dict`."""
    admissibility = payload["admissibility"]
    specificity = payload.get("specificity")
    support = payload.get("support")
    conflict = payload.get("conflict")
    destination = payload["destination"]
    service = destination.get("service")
    return PolicyInput(
        scope=ScopeClass(payload["scope"]["value"]),
        scope_origin=EstimateOrigin(payload["scope"]["origin"]),
        constraints=frozenset(
            RequestConstraint(value) for value in payload["constraints"]["value"]
        ),
        constraints_origin=EstimateOrigin(payload["constraints"]["origin"]),
        admissibility=AdmissibilityAssessment(
            evidence_ids=frozenset(admissibility["evidence_ids"]),
            eligibility_policy=admissibility["eligibility_policy"],
            conditions=tuple(admissibility["conditions"]),
            requester_role=admissibility["requester_role"],
            access_policy_version=admissibility["access_policy_version"],
            reference_date=date.fromisoformat(admissibility["reference_date"]),
            origin=EstimateOrigin(admissibility["origin"]),
        ),
        specificity=None
        if specificity is None
        else SpecificityAssessment(
            specificity=Specificity(specificity["specificity"]),
            readings=tuple(
                Reading(
                    reading_id=reading["reading_id"],
                    label=reading["label"],
                    supporting_evidence_ids=frozenset(reading["supporting_evidence_ids"]),
                )
                for reading in specificity["readings"]
            ),
            ambiguity_material=specificity["ambiguity_material"],
            user_can_distinguish=specificity["user_can_distinguish"],
            origin=EstimateOrigin(specificity["origin"]),
        ),
        support=None
        if support is None
        else SupportAssessment(
            items=tuple(
                ItemSupport(
                    item_id=item["item_id"],
                    label=item["label"],
                    supported=item["supported"],
                    evidence_ids=frozenset(item["evidence_ids"]),
                )
                for item in support["items"]
            ),
            partial_misleading=support["partial_misleading"],
            origin=EstimateOrigin(support["origin"]),
        ),
        conflict=None
        if conflict is None
        else ConflictAssessment(
            conflicts=tuple(
                EvidenceConflict(
                    item_id=item["item_id"],
                    evidence_ids=tuple(item["evidence_ids"]),
                    resolvable=item["resolvable"],
                )
                for item in conflict["conflicts"]
            ),
            origin=EstimateOrigin(conflict["origin"]),
        ),
        destination=DestinationResolution(
            service=None
            if service is None
            else CompetentService(
                service_id=service["service_id"],
                name=service["name"],
                email=service["email"],
                url=service["url"],
            ),
            topic=destination["topic"],
            catalog_version=destination["catalog_version"],
            origin=EstimateOrigin(destination["origin"]),
        ),
        diagnostic=TemporalDiagnostic(
            excluded=tuple(
                ExcludedByValidity(
                    document_id=item["document_id"],
                    document_title=item["document_title"],
                    valid_from=_parse_date(item["valid_from"]),
                    valid_until=_parse_date(item["valid_until"]),
                )
                for item in payload["diagnostic"]["excluded"]
            )
        ),
        reference_date=date.fromisoformat(payload["reference_date"]),
    )
