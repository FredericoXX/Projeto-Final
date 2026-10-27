"""Relatório de recolha da avaliação da política v1: contrato, construção e agregação.

O executor (``scripts/run_policy_v1_evaluation.py``) chama os modelos **uma
vez** e arquiva o que obteve num relatório. A reanálise offline
(``scripts/score_policy_v1_report.py``) e a exportação para revisão humana
(``scripts/export_policy_v1_message_review.py``) releem esse relatório sem base
de dados, sem rede e sem modelos. As três partilham este módulo:

- :class:`CollectionReport` e :func:`load_collection_report` — o contrato tipado
  do relatório arquivado e a reconstrução, a partir dele, dos packets e dos
  resultados, com a condição e a execução originais;
- :func:`summarize_outcomes` e :func:`compute_report_metrics` — a **única**
  agregação das métricas, hipóteses, comparações emparelhadas, erros de
  estimação e atribuição por replay;
- :func:`build_collection_report` e :func:`report_bytes` — a forma e os bytes do
  relatório escrito pelo executor.

Versões do relatório
--------------------

- sem ``report_schema_version`` — o formato anterior (até à ``main`` em
  ``f2c1b36``). Não regista identidade da recolha, digests das entradas,
  inventário documental, snapshot do catálogo, configuração de execução nem
  estado do Git. A reanálise aceita-o com verificação parcial declarada e nunca
  como formal.
- ``policy_v1_report_2`` — acrescenta ``collection_id``, ``collected_at``, o
  estado do Git observado na recolha (``git``), a configuração de execução
  (``runtime``) e os digests de todas as entradas (``inputs``).

O relatório contém os pedidos, as passagens dos documentos consultados e as
mensagens produzidas: pertence ao ambiente autorizado e não é versionado.
"""

import json
import platform
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Annotated, Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.decision.contracts import RequestConstraint, ScopeClass
from app.decision.definitions import DEFINITIONS_VERSION, RULES_VERSION
from app.decision.dimensions import (
    EstimateOrigin,
    Specificity,
    policy_input_from_dict,
    policy_input_to_dict,
)
from app.decision.messages import MESSAGE_VERSION
from app.decision.policy import POLICY_VERSION
from app.evaluation.policy_v1.annotation_contracts import Family, SourceKind
from app.evaluation.policy_v1.artifacts import CODE_ARTIFACTS, artifact_digests
from app.evaluation.policy_v1.attribution import attribute_errors
from app.evaluation.policy_v1.cases import (
    CASES_SCHEMA_VERSION,
    EvaluationCase,
    EvaluationCaseSet,
)
from app.evaluation.policy_v1.conditions import (
    B1_PROMPT_VERSION,
    MODEL_CONDITIONS,
    CaseOutcome,
    Condition,
)
from app.evaluation.policy_v1.config import EVALUATION_CONFIG, EVALUATION_CONFIG_VERSION
from app.evaluation.policy_v1.hypotheses import hypotheses_report
from app.evaluation.policy_v1.labels import LABELS_SCHEMA_VERSION, CaseLabels
from app.evaluation.policy_v1.message_ratings import (
    BOUND_RATINGS_SCHEMA_VERSION,
    MESSAGE_IDENTITY_VERSION,
    RatingSet,
)
from app.evaluation.policy_v1.metrics import (
    compute_metrics,
    configured_paired_comparisons,
    estimation_errors,
)
from app.evaluation.policy_v1.packets import PACKET_VERSION, EvidencePacket, PacketFamily
from app.evaluation.policy_v1.protocol import stratum
from app.evaluation.policy_v1.runs import RUN_NUMBERS, CaseSummary, run_numbers, summarize

REPORT_SCHEMA_VERSION: Final = "policy_v1_report_2"

#: A família de packet que cada condição recebe (``packets.py``).
PACKET_FAMILY: Final[Mapping[Condition, PacketFamily]] = {
    Condition.B0: "b0",
    Condition.A_NO_FILTER: "b0_without_validity_filter",
    Condition.P_E2E: "p_e2e",
    Condition.A_NO_DIAGNOSTIC: "p_e2e",
    Condition.B1_FULL: "p_e2e",
    Condition.B1_COMPOSITION: "p_e2e",
}

Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Commit = Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
CollectionId = Annotated[
    str, Field(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
]
Action = Literal["answer", "clarify", "abstain", "escalate"]


class ReportError(ValueError):
    """O relatório arquivado não respeita o contrato ou não é coerente."""


def describe_validation_error(exc: ValidationError, *, limit: int = 3) -> str:
    """Onde e porquê um ficheiro falhou a validação — sem os valores lidos.

    Os valores podem ser pedidos, mensagens ou excertos documentais; só a
    localização e a mensagem genérica do Pydantic são reportadas.
    """
    details = [
        f"{'.'.join(str(part) for part in error['loc']) or '$'}: {error['msg']}"
        for error in exc.errors(include_input=False, include_url=False)[:limit]
    ]
    return f"{exc.error_count()} error(s): " + "; ".join(details)


def versions_payload() -> dict[str, str]:
    """Versões de tudo o que determina a recolha e a sua leitura."""
    return {
        "policy": POLICY_VERSION,
        "definitions": DEFINITIONS_VERSION,
        "rules": RULES_VERSION,
        "messages": MESSAGE_VERSION,
        "b1_prompt": B1_PROMPT_VERSION,
        "packet": PACKET_VERSION,
        "cases_schema": CASES_SCHEMA_VERSION,
        "labels_schema": LABELS_SCHEMA_VERSION,
        "message_ratings_schema": BOUND_RATINGS_SCHEMA_VERSION,
        "message_identity": MESSAGE_IDENTITY_VERSION,
        "evaluation_config": EVALUATION_CONFIG_VERSION,
        "report_schema": REPORT_SCHEMA_VERSION,
    }


# ---------------------------------------------------------------------------
# Contrato do relatório arquivado
# ---------------------------------------------------------------------------


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ArchivedPassage(_Strict):
    evidence_id: Annotated[str, Field(min_length=1)]
    chunk_id: str
    document_id: str
    document_version_id: str
    document_title: str
    chunk_index: int
    content: str
    content_sha256: Sha256
    official_source: bool
    source_url: str | None
    language: str
    valid_from: date | None
    valid_until: date | None


class ArchivedDiagnosticItem(_Strict):
    document_id: str
    document_title: str
    valid_from: date | None
    valid_until: date | None


class ArchivedPacket(_Strict):
    """Um packet arquivado: o digest e os campos de ``EvidencePacket.to_dict``."""

    digest: Sha256
    packet_version: Literal["policy_v1_packet_1"]
    case_id: Annotated[str, Field(min_length=1, max_length=64)]
    family: PacketFamily
    run_number: Annotated[int, Field(ge=1)]
    query: str
    language: str
    reference_date: date
    requester_role: str
    catalog: dict[str, Any]
    passages: list[ArchivedPassage]
    diagnostic: list[ArchivedDiagnosticItem]
    retrieval: dict[str, Any]
    snapshot_id: str | None
    corpus_digest: str | None


class _StrictJson(BaseModel):
    """Tipos JSON estritos: ``"false"``, ``0`` ou ``1`` nunca passam por booleanos,
    nem ``"1"`` por inteiro. Os enumerados aceitam só o seu valor exato."""

    model_config = ConfigDict(extra="forbid", strict=True)


Origin = Annotated[EstimateOrigin, Field(strict=False)]


class _ScopeInput(_StrictJson):
    value: Annotated[ScopeClass, Field(strict=False)]
    origin: Origin


class _ConstraintsInput(_StrictJson):
    value: list[Annotated[RequestConstraint, Field(strict=False)]]
    origin: Origin


class _AdmissibilityInput(_StrictJson):
    evidence_ids: list[str]
    eligibility_policy: str
    conditions: list[str]
    requester_role: str
    access_policy_version: str
    reference_date: str
    origin: Origin


class _ReadingInput(_StrictJson):
    reading_id: str
    label: str
    supporting_evidence_ids: list[str]


class _SpecificityInput(_StrictJson):
    specificity: Annotated[Specificity, Field(strict=False)]
    readings: list[_ReadingInput]
    ambiguity_material: bool
    user_can_distinguish: bool
    origin: Origin


class _ItemInput(_StrictJson):
    item_id: str
    label: str
    supported: bool
    evidence_ids: list[str]


class _SupportInput(_StrictJson):
    items: list[_ItemInput]
    partial_misleading: bool | None
    origin: Origin


class _ConflictItemInput(_StrictJson):
    item_id: str
    evidence_ids: list[str]
    resolvable: bool


class _ConflictInput(_StrictJson):
    conflicts: list[_ConflictItemInput]
    origin: Origin


class _ServiceInput(_StrictJson):
    service_id: str
    name: str
    email: str | None
    url: str | None


class _DestinationInput(_StrictJson):
    service: _ServiceInput | None
    topic: str | None
    catalog_version: int
    origin: Origin


class _ExcludedInput(_StrictJson):
    document_id: str
    document_title: str
    valid_from: str | None
    valid_until: str | None


class _DiagnosticInput(_StrictJson):
    excluded: list[_ExcludedInput]


class ArchivedPolicyInput(_StrictJson):
    """As entradas da política arquivadas por P-e2e e A-sem-diagnóstico.

    Espelha campo a campo :func:`app.decision.dimensions.policy_input_to_dict`,
    com tipos estritos. As dataclasses de ``PolicyInput`` não validam tipos: sem
    este contrato, ``"supported": "false"`` reconstruía-se como suporte
    verdadeiro. As datas são verificadas pela reconstrução e pelo round-trip.
    """

    scope: _ScopeInput
    constraints: _ConstraintsInput
    admissibility: _AdmissibilityInput
    specificity: _SpecificityInput | None
    support: _SupportInput | None
    conflict: _ConflictInput | None
    destination: _DestinationInput
    diagnostic: _DiagnosticInput
    reference_date: str


#: Condições cujos resultados arquivam as entradas validadas da política.
_POLICY_ESTIMATES: Final = frozenset({Condition.P_E2E, Condition.A_NO_DIAGNOSTIC})
#: Condições sem estimativas: o B0, A-sem-filtro e P-oráculo não estimam
#: dimensões. B1-plena e B1-composição arquivam as do modelo, em forma livre.
_WITHOUT_ESTIMATES: Final = frozenset({Condition.B0, Condition.A_NO_FILTER, Condition.P_ORACLE})


class ArchivedOutcome(_Strict):
    """Um resultado arquivado (``CaseOutcome.as_dict``)."""

    case_id: Annotated[str, Field(min_length=1, max_length=64)]
    condition: Condition
    run_number: Annotated[int, Field(ge=1)]
    action: Action | None
    rule: str | None
    message: str | None
    cited_evidence_ids: list[str]
    destination_service_id: str | None
    failure: str | None
    packet_digest: Sha256 | None
    duration_ms: Annotated[int, Field(ge=0)]
    estimates: dict[str, Any] | None
    usage: dict[str, Any]
    temporal_notice_shown: bool | None

    @model_validator(mode="after")
    def failure_is_not_an_action(self) -> "ArchivedOutcome":
        # Falhas técnicas nunca são convertidas numa ação nem trazem mensagem.
        if (self.action is None) != (self.failure is not None):
            raise ValueError("an outcome has either an action or a technical failure")
        if self.failure is not None and (
            self.message is not None or self.cited_evidence_ids or self.destination_service_id
        ):
            raise ValueError("a technical failure carries no message, citations or destination")
        return self

    @model_validator(mode="after")
    def estimates_follow_the_condition(self) -> "ArchivedOutcome":
        # P-e2e e A-sem-diagnóstico arquivam as entradas da política, que M8, M9
        # e os rastos releem; validá-las aqui transforma um arquivo malformado
        # numa recusa controlada, em vez de um erro a meio do cálculo.
        where = self.condition.value
        if self.failure is not None or self.condition in _WITHOUT_ESTIMATES:
            if self.estimates is not None:
                raise ValueError(f"{where}: this outcome carries no estimates")
        elif self.condition in _POLICY_ESTIMATES:
            if self.estimates is None:
                raise ValueError(f"{where}: the policy inputs are required")
            # Tipos estritos primeiro; só depois a reconstrução e o round-trip.
            try:
                ArchivedPolicyInput.model_validate(self.estimates)
            except ValidationError as exc:
                details = describe_validation_error(exc)
                raise ValueError(f"{where}: invalid policy inputs ({details})") from exc
            try:
                restored = policy_input_to_dict(policy_input_from_dict(self.estimates))
            except (KeyError, TypeError, ValueError, AttributeError) as exc:
                raise ValueError(f"{where}: the estimates are not valid policy inputs") from exc
            if json.loads(json.dumps(restored)) != self.estimates:
                raise ValueError(f"{where}: the estimates are not canonical policy inputs")
        return self

    def to_outcome(self) -> CaseOutcome:
        return CaseOutcome(
            case_id=self.case_id,
            condition=self.condition,
            run_number=self.run_number,
            action=self.action,
            rule=self.rule,
            message=self.message,
            cited_evidence_ids=tuple(self.cited_evidence_ids),
            destination_service_id=self.destination_service_id,
            failure=self.failure,
            packet_digest=self.packet_digest,
            duration_ms=self.duration_ms,
            estimates=self.estimates,
            usage=self.usage,
            temporal_notice_shown=self.temporal_notice_shown,
        )


class CaseMetadataEntry(_Strict):
    case_id: Annotated[str, Field(min_length=1, max_length=64)]
    family: Family | None
    source_kind: SourceKind | None
    stratum: str
    expected_snapshot_id: str | None


class GitState(_Strict):
    """O estado observado do repositório na recolha (``git_state``)."""

    head: Commit | None
    working_tree_clean: bool


class FileDigest(_Strict):
    #: SHA-256 dos bytes do ficheiro tal como foi lido.
    file_sha256: Sha256
    #: SHA-256 dos bytes congelados (receita de ``freeze.py``) do mesmo conteúdo.
    frozen_sha256: Sha256


class ManifestDigest(_Strict):
    file_sha256: Sha256
    #: SHA-256 dos bytes canónicos do conteúdo (``canonical_bytes``): identifica
    #: o manifesto independentemente da formatação do ficheiro.
    frozen_sha256: Sha256
    code_commit: str | None


class InventoryDigest(_Strict):
    #: Inventário documental lido da base antes do primeiro caso e de novo antes
    #: do relatório; o executor recusa escrever se os dois diferirem.
    frozen_sha256: Sha256


class CatalogRecord(_Strict):
    frozen_sha256: Sha256
    snapshot: dict[str, Any]


class CollectionInputs(_Strict):
    cases: FileDigest
    adjudication: FileDigest | None
    freeze_manifest: ManifestDigest | None
    corpus_inventory: InventoryDigest
    catalog: CatalogRecord


#: Campos que só existem a partir de ``policy_v1_report_2``.
_PROVENANCE_FIELDS: Final = ("collection_id", "collected_at", "git", "runtime", "inputs")


class CollectionReport(_Strict):
    """O relatório escrito pelo executor, numa das versões suportadas."""

    report_schema_version: Literal["policy_v1_report_2"] | None = None
    collection_id: CollectionId | None = None
    collected_at: datetime | None = None
    mode: Literal["formal", "development_trial"]
    status: str
    set_id: Annotated[str, Field(min_length=1, max_length=64)]
    corpus: Literal["P2"]
    #: O commit declarado com ``--commit``; o observado está em ``git``.
    code_commit: Commit
    git: GitState | None = None
    python_version: str
    versions: dict[str, str]
    config: dict[str, Any]
    runtime: dict[str, Any] | None = None
    inputs: CollectionInputs | None = None
    case_metadata: list[CaseMetadataEntry]
    code_artifact_digests: dict[str, Sha256]
    packets: list[ArchivedPacket]
    outcomes: list[ArchivedOutcome]
    metrics: dict[str, Any]

    @model_validator(mode="after")
    def versioned(self) -> "CollectionReport":
        present = [getattr(self, name) is not None for name in _PROVENANCE_FIELDS]
        if self.report_schema_version is None and any(present):
            raise ValueError("provenance fields require report_schema_version")
        if self.report_schema_version is not None and not all(present):
            raise ValueError(f"{self.report_schema_version} requires {list(_PROVENANCE_FIELDS)}")
        if set(self.code_artifact_digests) != set(CODE_ARTIFACTS):
            raise ValueError(f"code_artifact_digests must name exactly {list(CODE_ARTIFACTS)}")
        ids = [entry.case_id for entry in self.case_metadata]
        if len(set(ids)) != len(ids):
            raise ValueError("case_metadata ids must be unique")
        digests = [packet.digest for packet in self.packets]
        if len(set(digests)) != len(digests):
            raise ValueError("packet digests must be unique")
        keys = [(o.case_id, o.condition, o.run_number) for o in self.outcomes]
        if len(set(keys)) != len(keys):
            raise ValueError("one outcome per case, condition and run")
        return self

    @property
    def legacy(self) -> bool:
        return self.report_schema_version is None


@dataclass(frozen=True)
class ArchivedCollection:
    """Um relatório validado e o que dele se reconstrói, sem base de dados."""

    report: CollectionReport
    #: Os resultados como objetos JSON arquivados, pela ordem do relatório.
    raw_outcomes: tuple[Mapping[str, Any], ...]
    outcomes: tuple[CaseOutcome, ...]
    packets: Mapping[str, EvidencePacket]

    def outcome_index(self) -> dict[tuple[str, str, int], tuple[CaseOutcome, Mapping[str, Any]]]:
        return {
            (outcome.case_id, outcome.condition.value, outcome.run_number): (outcome, raw)
            for outcome, raw in zip(self.outcomes, self.raw_outcomes, strict=True)
        }


def _check_structure(report: CollectionReport, packets: Mapping[str, EvidencePacket]) -> None:
    """Coerência interna: packets ↔ resultados, execuções numeradas, completude."""
    case_ids = {entry.case_id for entry in report.case_metadata}
    for packet in packets.values():
        if packet.case_id not in case_ids:
            raise ReportError(f"a packet refers to an unknown case {packet.case_id}")
        if packet.run_number not in RUN_NUMBERS:
            raise ReportError(f"case {packet.case_id}: unexpected packet run {packet.run_number}")
    oracle_cases: set[str] = set()
    for outcome in report.outcomes:
        where = f"case {outcome.case_id} ({outcome.condition.value}, run {outcome.run_number})"
        if outcome.case_id not in case_ids:
            raise ReportError(f"{where}: unknown case")
        if outcome.run_number not in run_numbers(outcome.condition):
            raise ReportError(f"{where}: unexpected run number")
        if outcome.condition is Condition.P_ORACLE:
            oracle_cases.add(outcome.case_id)
            if outcome.packet_digest is not None:
                raise ReportError(f"{where}: P-oráculo receives no packet")
            continue
        if outcome.packet_digest is None:
            if outcome.failure is None:
                raise ReportError(f"{where}: a produced action needs its packet")
            continue
        received = packets.get(outcome.packet_digest)
        if received is None:
            raise ReportError(f"{where}: its packet is not archived")
        if (received.case_id, received.run_number, received.family) != (
            outcome.case_id,
            outcome.run_number,
            PACKET_FAMILY[outcome.condition],
        ):
            raise ReportError(f"{where}: its packet belongs to another case, run or family")
    present = {(o.case_id, o.condition, o.run_number) for o in report.outcomes}
    missing = [
        (case_id, condition.value, run)
        for case_id in sorted(case_ids)
        for condition in MODEL_CONDITIONS
        for run in RUN_NUMBERS
        if (case_id, condition, run) not in present
    ]
    if missing:
        raise ReportError(f"incomplete collection: {len(missing)} outcome(s) missing")
    if oracle_cases and oracle_cases != case_ids:
        raise ReportError("P-oráculo outcomes must cover every case or none")


def load_collection_report(data: bytes) -> ArchivedCollection:
    """Valida um relatório arquivado e reconstrói packets e resultados.

    O digest de cada packet é recalculado a partir do conteúdo arquivado e tem de
    ser o registado: um packet alterado é recusado.
    """
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReportError("the report is not valid UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise ReportError("the report must be a JSON object")
    if "analysis_schema_version" in payload:
        raise ReportError("this is an offline analysis, not a collection report")
    try:
        report = CollectionReport.model_validate(payload)
    except ValidationError as exc:
        raise ReportError(f"invalid collection report: {describe_validation_error(exc)}") from exc
    packets: dict[str, EvidencePacket] = {}
    for raw in payload["packets"]:
        content = {key: value for key, value in raw.items() if key != "digest"}
        try:
            packet = EvidencePacket.from_dict(content)
        except (KeyError, TypeError, ValueError) as exc:
            raise ReportError("an archived packet cannot be restored") from exc
        if packet.digest != raw["digest"]:
            msg = f"case {packet.case_id}: an archived packet does not match its digest"
            raise ReportError(msg)
        packets[packet.digest] = packet
    _check_structure(report, packets)
    return ArchivedCollection(
        report=report,
        raw_outcomes=tuple(payload["outcomes"]),
        outcomes=tuple(outcome.to_outcome() for outcome in report.outcomes),
        packets=packets,
    )


# ---------------------------------------------------------------------------
# Agregação — partilhada pela recolha e pela reanálise
# ---------------------------------------------------------------------------


def case_metadata(cases: Sequence[EvaluationCase]) -> list[dict[str, Any]]:
    return [
        {
            "case_id": case.case_id,
            "family": case.family,
            "source_kind": case.source_kind,
            "stratum": stratum(case),
            "expected_snapshot_id": case.expected_snapshot_id,
        }
        for case in cases
    ]


def in_primary_scope(case: EvaluationCase, *, formal: bool) -> bool:
    """Agregado principal: fontes reais, F14 excluído; fixtures sem classificação
    só em desenvolvimento."""
    return stratum(case) == "real" or (not formal and stratum(case) == "unclassified_dev")


def summarize_outcomes(
    outcomes: Sequence[CaseOutcome],
) -> dict[Condition, dict[str, CaseSummary]]:
    """Agrega as execuções numeradas por condição e caso (``runs.summarize``)."""
    grouped: dict[tuple[str, Condition], list[CaseOutcome]] = defaultdict(list)
    for outcome in outcomes:
        grouped[(outcome.case_id, outcome.condition)].append(outcome)
    summaries: dict[Condition, dict[str, CaseSummary]] = defaultdict(dict)
    for (case_id, condition), items in grouped.items():
        summaries[condition][case_id] = summarize(items)
    return dict(summaries)


def compute_report_metrics(
    cases: Sequence[EvaluationCase],
    summaries: Mapping[Condition, Mapping[str, CaseSummary]],
    gold: Mapping[str, CaseLabels],
    packets: Mapping[str, EvidencePacket],
    catalog: Mapping[str, Any],
    *,
    ratings: RatingSet | None,
    formal: bool,
) -> dict[str, Any]:
    """As métricas do relatório: por condição no agregado principal, por estrato e
    por família, hipóteses, comparações emparelhadas, M8 e M9.

    ``formal`` é o modo **da recolha**: decide se as fixtures sem classificação
    entram no agregado principal. Cada resultado é lido no packet que a sua
    condição recebeu: os identificadores de evidência só têm sentido dentro dele.
    """
    case_by_id = {case.case_id: case for case in cases}
    primary_ids = {case.case_id for case in cases if in_primary_scope(case, formal=formal)}
    primary = {
        condition: {key: value for key, value in by_case.items() if key in primary_ids}
        for condition, by_case in summaries.items()
    }
    metrics: dict[str, Any] = {
        condition.value: compute_metrics(by_case, gold, packets, ratings)
        for condition, by_case in primary.items()
    }
    metrics["primary_scope"] = "real sources, F14 excluded; unclassified fixtures only in dev"
    metrics["by_stratum"] = {}
    metrics["by_family"] = {}
    for field, groups in (
        ("by_stratum", {stratum(case) for case in cases}),
        (
            "by_family",
            {f"{case.family or 'unclassified_dev'}:{stratum(case)}" for case in cases},
        ),
    ):
        for group in sorted(groups):
            ids = {
                case_id
                for case_id, case in case_by_id.items()
                if (
                    stratum(case)
                    if field == "by_stratum"
                    else f"{case.family or 'unclassified_dev'}:{stratum(case)}"
                )
                == group
            }
            metrics[field][group] = {
                condition.value: compute_metrics(
                    {key: value for key, value in by_case.items() if key in ids},
                    gold,
                    packets,
                    ratings,
                )
                for condition, by_case in summaries.items()
            }
            if field == "by_stratum":
                group_summaries = {
                    condition: {key: value for key, value in by_case.items() if key in ids}
                    for condition, by_case in summaries.items()
                }
                metrics[field][group]["hypotheses"] = hypotheses_report(
                    group_summaries,
                    gold,
                    margin=EVALUATION_CONFIG["thresholds"]["difference_margin_percentage_points"]
                    / 100,
                    margin_justified=EVALUATION_CONFIG["analysis"][
                        "non_inferiority_margin_justified"
                    ],
                )
                metrics[field][group]["paired_comparisons"] = configured_paired_comparisons(
                    group_summaries, gold, packets=packets, ratings=ratings
                )
    metrics["estimation_errors_p_e2e"] = estimation_errors(primary[Condition.P_E2E], gold)
    metrics["error_attribution_p_e2e"] = [
        attribution.as_dict()
        for attribution in attribute_errors(
            primary[Condition.P_E2E],
            gold,
            services=catalog["services"],
            catalog_version=catalog["version"],
            reference_dates={case.case_id: case.reference_date for case in cases},
        )
    ]
    metrics["error_attribution_metric_id"] = "M9"
    metrics["hypotheses"] = hypotheses_report(
        primary,
        gold,
        margin=EVALUATION_CONFIG["thresholds"]["difference_margin_percentage_points"] / 100,
        margin_justified=EVALUATION_CONFIG["analysis"]["non_inferiority_margin_justified"],
    )
    metrics["paired_comparisons"] = configured_paired_comparisons(
        primary, gold, packets=packets, ratings=ratings
    )
    return metrics


# ---------------------------------------------------------------------------
# Construção do relatório pela recolha
# ---------------------------------------------------------------------------


def build_collection_report(
    *,
    formal: bool,
    cases: EvaluationCaseSet,
    collection_id: str,
    collected_at: datetime,
    code_commit: str,
    git: tuple[str | None, bool],
    runtime: Mapping[str, Any],
    inputs: Mapping[str, Any],
    packets: Sequence[EvidencePacket],
    outcomes: Sequence[CaseOutcome],
    metrics: Mapping[str, Any],
) -> dict[str, Any]:
    """O relatório ``policy_v1_report_2`` de uma recolha."""
    return {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "collection_id": collection_id,
        "collected_at": collected_at.isoformat(),
        "mode": "formal" if formal else "development_trial",
        "status": "avaliação formal" if formal else "ensaio de desenvolvimento, não avaliação",
        "set_id": cases.set_id,
        "corpus": cases.corpus,
        "code_commit": code_commit,
        "git": {"head": git[0], "working_tree_clean": git[1]},
        "python_version": platform.python_version(),
        "versions": versions_payload(),
        "config": EVALUATION_CONFIG,
        "runtime": dict(runtime),
        "inputs": dict(inputs),
        "case_metadata": case_metadata(cases.cases),
        "code_artifact_digests": artifact_digests(),
        "packets": [{"digest": packet.digest, **packet.to_dict()} for packet in packets],
        "outcomes": [outcome.as_dict() for outcome in outcomes],
        "metrics": dict(metrics),
    }


def report_bytes(report: Mapping[str, Any]) -> bytes:
    """Os bytes arquivados de um relatório (UTF-8, chaves ordenadas, newline final)."""
    text = json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2, default=str)
    return (text + "\n").encode("utf-8")
