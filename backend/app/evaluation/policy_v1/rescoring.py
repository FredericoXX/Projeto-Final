"""Reanálise offline de uma recolha arquivada da avaliação da política v1.

A recolha (``scripts/run_policy_v1_evaluation.py``) chama os modelos uma vez e
arquiva as respostas. Esta reanálise recalcula as métricas sobre **essas mesmas
respostas**, sem base de dados, sem rede, sem clientes de modelos, sem chaves
de fornecedores e sem a configuração da aplicação (``app.core.config``): só lê
bytes já fornecidos. Não consulta o estado atual da base
para substituir os snapshots arquivados.

O que verifica, antes de calcular
---------------------------------

- **o relatório** — contrato tipado, digest de cada packet recalculado,
  estimativas por condição, coerência entre packets e resultados, execuções
  numeradas completas
  (:func:`~app.evaluation.policy_v1.report.load_collection_report`);
- **o manifesto de congelamento** — contrato, receita desta implementação,
  completude e, por fim, que é o manifesto que a recolha leu;
- **os casos** — mesmo conjunto, metadados e pedidos dos packets; num relatório
  ``policy_v1_report_2``, os mesmos bytes congelados que a recolha registou;
- **a adjudicação** — identificada, completa para os mesmos casos e igual à
  congelada (``verified_adjudication``) e, quando a recolha a usou, à registada;
- **o congelamento** — a recolha correu os artefactos de código congelados; o
  catálogo, o inventário documental e a configuração registados são os
  congelados;
- **o código da análise** — a mesma política (P-oráculo e replay) e a mesma
  configuração da avaliação (métricas, comparações, limiares) que a recolha;
- **as avaliações M7** — cada juízo aponta para a mensagem exata desta recolha
  (:func:`~app.evaluation.policy_v1.message_ratings.bind_ratings`).

Uma incompatibilidade é recusada, nunca contornada. O que um relatório antigo
não registou é declarado em ``verification.unverifiable``; nada é inventado e a
conformidade formal nunca é atribuída retroativamente.

O que calcula
-------------

As métricas pela **mesma** função da recolha
(:func:`~app.evaluation.policy_v1.report.compute_report_metrics`), com a
primeira execução numerada como principal e o modo da recolha. Calcula-as
primeiro sem juízos humanos e compara-as com as arquivadas
(``collection_metrics_reproduction``); só depois aplica os juízos M7. Sem
juízos, M7 permanece não medida. ``case_traces`` liga cada caso à adjudicação,
ao packet, às estimativas, à regra, à mensagem, ao juízo humano e à pertença a
cada métrica, com as falhas técnicas à parte.
"""

import json
import platform
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any, Final, Literal, NoReturn

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.evaluation.policy_v1.artifacts import (
    CODE_ARTIFACTS,
    artifact_digests,
    catalog_bytes,
    corpus_bytes,
)
from app.evaluation.policy_v1.cases import EvaluationCase, EvaluationCaseSet
from app.evaluation.policy_v1.conditions import CaseOutcome, Condition, run_oracle
from app.evaluation.policy_v1.config import EVALUATION_CONFIG
from app.evaluation.policy_v1.corpus_inventory import corpus_inventory_bytes
from app.evaluation.policy_v1.freeze import (
    FREEZE_RECIPE_VERSION,
    REQUIRED_ARTIFACTS,
    FreezeError,
    canonical_bytes,
    sha256,
    verify_artifact,
    verify_freeze_recipe,
)
from app.evaluation.policy_v1.labels import (
    CaseLabels,
    LabelSet,
    label_set_bytes,
    verified_adjudication,
)
from app.evaluation.policy_v1.message_ratings import (
    BOUND_RATINGS_SCHEMA_VERSION,
    LEGACY_RATINGS_SCHEMA_VERSION,
    RATINGS_DRAFT_SCHEMA_VERSION,
    BoundMessageRating,
    BoundMessageRatingSet,
    RatingBindingError,
    SourceReport,
    bind_ratings,
    message_sha256,
    outcome_id,
    unrateable_reason,
)
from app.evaluation.policy_v1.metrics import (
    citation_admissibility,
    dimension_pairs,
    rate_membership,
)
from app.evaluation.policy_v1.packets import EvidencePacket
from app.evaluation.policy_v1.protocol import (
    stratum,
    validate_formal_annotations,
    verify_same_case_set,
)
from app.evaluation.policy_v1.report import (
    ArchivedCollection,
    CollectionReport,
    ReportError,
    case_metadata,
    compute_report_metrics,
    describe_validation_error,
    in_primary_scope,
    load_collection_report,
    summarize_outcomes,
    versions_payload,
)
from app.evaluation.policy_v1.runs import CaseSummary

ANALYSIS_SCHEMA_VERSION: Final = "policy_v1_analysis_1"

#: Artefactos de código que não dependem do ambiente. O ``config`` congelado
#: inclui a configuração de execução (modelos, limites), que a análise não
#: precisa de ter: compara-se a configuração da avaliação e o digest registado.
_ENVIRONMENT_FREE_ARTIFACTS: Final = ("policy", "schema", "prompts")
_MAX_DIFFERENCES: Final = 50

ErrorKind = Literal["invalid", "provenance", "refused", "ratings"]


class FrozenArtifactEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str
    sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    bytes: Annotated[int, Field(ge=0)]


class FreezeManifestContract(BaseModel):
    """O manifesto escrito por ``freeze_policy_v1_artifacts`` (``build_freeze_manifest``)."""

    model_config = ConfigDict(extra="forbid")

    recipe_version: str
    python_version: str
    code_commit: str
    complete: bool
    missing_artifacts: list[str]
    artifacts: dict[str, FrozenArtifactEntry]
    #: Acrescentado pelo script de congelamento; relatório, nunca correção.
    non_nfc_strings: dict[str, list[str]] = {}


class RescoringError(ValueError):
    """A reanálise não pode ser feita com estas entradas.

    ``kind``: ``invalid`` (ficheiro que não respeita o contrato), ``provenance``
    (entradas que não correspondem à recolha ou ao congelamento), ``refused``
    (modo pedido não admissível) ou ``ratings`` (avaliações M7 recusadas).
    """

    def __init__(self, kind: ErrorKind, message: str) -> None:
        super().__init__(message)
        self.kind = kind


@dataclass(frozen=True)
class RescoringInputs:
    """Os bytes exatos de cada ficheiro, lidos uma vez."""

    report: bytes
    cases: bytes
    adjudication: bytes
    freeze_manifest: bytes
    message_ratings: bytes | None = None
    corpus_inventory: bytes | None = None
    #: Só o nome do ficheiro, para o registo; nunca o caminho local.
    report_name: str | None = None


@dataclass(frozen=True)
class AnalysisGit:
    """Estado do repositório onde a análise corre (``git_state``)."""

    head: str | None
    working_tree_clean: bool


def _fail(kind: ErrorKind, message: str) -> NoReturn:
    raise RescoringError(kind, message)


def _json(data: bytes, what: str) -> Any:
    try:
        return json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        _fail("invalid", f"the {what} file is not valid UTF-8 JSON")


def _model[M: BaseModel](model: type[M], payload: Any, what: str) -> M:
    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        _fail("invalid", f"invalid {what}: {describe_validation_error(exc)}")


def _ratings(data: bytes | None) -> BoundMessageRatingSet | None:
    if data is None:
        return None
    payload = _json(data, "message ratings")
    version = payload.get("schema_version") if isinstance(payload, dict) else None
    if version == RATINGS_DRAFT_SCHEMA_VERSION:
        _fail("ratings", "this is a review draft, not a completed rating set")
    if version == LEGACY_RATINGS_SCHEMA_VERSION:
        _fail(
            "ratings",
            "v1 ratings identify only case and condition, not the rated text; "
            "export a review package and rate the archived messages",
        )
    if version != BOUND_RATINGS_SCHEMA_VERSION:
        _fail("ratings", f"message ratings must use {BOUND_RATINGS_SCHEMA_VERSION}")
    try:
        return BoundMessageRatingSet.model_validate(payload)
    except ValidationError as exc:
        _fail("ratings", f"invalid message ratings: {describe_validation_error(exc)}")


def _frozen_digest(manifest: Mapping[str, Any], name: str) -> str | None:
    entry = manifest.get("artifacts", {}).get(name)
    return entry.get("sha256") if isinstance(entry, Mapping) else None


def _normalized(value: Any) -> Any:
    """A forma JSON de um valor, como o executor a arquiva."""
    return json.loads(json.dumps(value, default=str))


def _differences(expected: Any, observed: Any, path: str, found: list[str]) -> None:
    if len(found) >= _MAX_DIFFERENCES:
        return
    if isinstance(expected, dict) and isinstance(observed, dict):
        for key in sorted(set(expected) | set(observed)):
            if key not in expected or key not in observed:
                found.append(f"{path}.{key}")
            else:
                _differences(expected[key], observed[key], f"{path}.{key}", found)
    elif isinstance(expected, list) and isinstance(observed, list):
        if len(expected) != len(observed):
            found.append(f"{path}[len]")
            return
        for index, (left, right) in enumerate(zip(expected, observed, strict=True)):
            _differences(left, right, f"{path}[{index}]", found)
    elif expected != observed:
        found.append(path)


def _reproduction(recomputed: Mapping[str, Any], archived: Mapping[str, Any]) -> dict[str, Any]:
    if archived == {"status": "not_computed_without_adjudication"}:
        return {"status": "not_computed_at_collection", "differences": []}
    found: list[str] = []
    _differences(archived, _normalized(recomputed), "$", found)
    return {
        "status": "identical" if not found else "differs",
        "differences": found,
        "compared": "metrics recomputed without human ratings against the archived metrics",
    }


# ---------------------------------------------------------------------------
# Verificações
# ---------------------------------------------------------------------------


def _verify_manifest(payload: Any, checks: dict[str, str]) -> dict[str, Any]:
    """O manifesto de congelamento em si: contrato, receita e completude."""
    contract = _model(FreezeManifestContract, payload, "freeze manifest")
    try:
        verify_freeze_recipe(payload)
    except FreezeError as exc:
        _fail("provenance", str(exc))
    if (
        not contract.complete
        or contract.missing_artifacts
        or set(REQUIRED_ARTIFACTS) - set(contract.artifacts)
    ):
        _fail("provenance", "the freeze manifest is incomplete")
    checks["freeze_manifest_contract"] = "verified"
    checks["freeze_recipe"] = FREEZE_RECIPE_VERSION
    return dict(payload)


def _verify_cases(
    archived: ArchivedCollection,
    cases: EvaluationCaseSet,
    frozen_cases: bytes,
    checks: dict[str, str],
) -> None:
    report = archived.report
    if (report.set_id, report.corpus) != (cases.set_id, cases.corpus):
        _fail("provenance", "the case file belongs to another case set")
    if report.inputs is not None:
        if sha256(frozen_cases) != report.inputs.cases.frozen_sha256:
            _fail("provenance", "the case file differs from the one the collection used")
        checks["cases_vs_collection"] = "verified_by_digest"
    else:
        checks["cases_vs_collection"] = "consistency_only"
    expected = sorted(case_metadata(cases.cases), key=lambda entry: entry["case_id"])
    recorded = sorted(
        (entry.model_dump(mode="json") for entry in report.case_metadata),
        key=lambda entry: entry["case_id"],
    )
    if expected != recorded:
        _fail("provenance", "the case metadata of the collection differs from the case file")
    by_id = {case.case_id: case for case in cases.cases}
    for packet in archived.packets.values():
        case = by_id[packet.case_id]
        if (packet.query, packet.language, packet.reference_date, packet.requester_role) != (
            case.query,
            case.language,
            case.reference_date,
            case.requester_role,
        ):
            _fail("provenance", f"case {case.case_id}: an archived packet differs from the case")
        if case.expected_snapshot_id is not None and packet.snapshot_id != (
            case.expected_snapshot_id
        ):
            _fail("provenance", f"case {case.case_id}: a packet comes from another snapshot")
    checks["packets_vs_cases"] = "verified"


def _verify_adjudication(
    report: CollectionReport,
    cases: EvaluationCaseSet,
    adjudication: LabelSet,
    manifest: Mapping[str, Any],
    frozen_cases: bytes,
    checks: dict[str, str],
    unverifiable: list[str],
) -> None:
    try:
        # O relatório e os casos já têm o mesmo set_id (_verify_cases).
        verify_same_case_set(cases, adjudication)
        verify_artifact(manifest, "corpus", frozen_cases)
        verified_adjudication(adjudication, manifest)
    except FreezeError as exc:
        _fail("provenance", str(exc))
    checks["adjudication_set_vs_cases"] = "same"
    checks["cases_vs_freeze"] = "verified"
    checks["adjudication_vs_freeze"] = "verified"
    if {label.case_id for label in adjudication.cases} != {case.case_id for case in cases.cases}:
        _fail("provenance", "cases and adjudication must have the same complete unique ids")
    if report.inputs is None:
        checks["adjudication_vs_collection"] = "not_recorded"
        unverifiable.append("adjudication_used_in_collection")
    elif report.inputs.adjudication is None:
        checks["adjudication_vs_collection"] = "not_used_in_collection"
    elif report.inputs.adjudication.frozen_sha256 != sha256(label_set_bytes(adjudication)):
        _fail("provenance", "the adjudication differs from the one the collection used")
    else:
        checks["adjudication_vs_collection"] = "verified_by_digest"


def _verify_freeze(
    archived: ArchivedCollection,
    manifest: Mapping[str, Any],
    manifest_file_sha256: str,
    inventory: bytes | None,
    checks: dict[str, str],
    unverifiable: list[str],
) -> dict[str, Any]:
    """Código, catálogo, inventário e configuração da recolha contra o congelado.

    Devolve o snapshot do catálogo usado na recolha.
    """
    report = archived.report
    for name in CODE_ARTIFACTS:
        if report.code_artifact_digests[name] != _frozen_digest(manifest, name):
            _fail("provenance", f"the collection did not run the frozen {name} artifact")
    checks["collection_code_vs_freeze"] = "verified"

    carried = {canonical_bytes(dict(packet.catalog)) for packet in archived.packets.values()}
    if report.inputs is not None:
        catalog = dict(report.inputs.catalog.snapshot)
        if carried - {canonical_bytes(catalog)}:
            _fail("provenance", "an archived packet carries another catalog")
        expected_catalog = report.inputs.catalog.frozen_sha256
    else:
        if len(carried) != 1:
            _fail("provenance", "the archived packets must carry exactly one catalog")
        catalog = dict(next(iter(archived.packets.values())).catalog)
        expected_catalog = None
    try:
        catalog_data = catalog_bytes(catalog)
        if expected_catalog is not None and sha256(catalog_data) != expected_catalog:
            _fail("provenance", "the recorded catalog does not match its digest")
        verify_artifact(manifest, "catalog", catalog_data)
    except FreezeError as exc:
        _fail("provenance", str(exc))
    checks["catalog_vs_freeze"] = "verified"

    if report.inputs is not None:
        if report.inputs.corpus_inventory.frozen_sha256 != _frozen_digest(manifest, "manifest"):
            _fail("provenance", "the documentary inventory of the collection is not the frozen one")
        checks["corpus_inventory_vs_freeze"] = "verified_by_digest"
    else:
        checks["corpus_inventory_vs_freeze"] = "not_recorded"
        unverifiable.append("corpus_inventory")
    if inventory is not None:
        try:
            verify_artifact(manifest, "manifest", inventory)
        except FreezeError as exc:
            _fail("provenance", str(exc))
        checks["corpus_inventory_file"] = "verified"

    if report.config != EVALUATION_CONFIG:
        _fail(
            "provenance",
            "the evaluation configuration of the collection differs from the analysis code",
        )
    checks["evaluation_config_vs_analysis"] = "same"
    if report.runtime is not None:
        recorded = canonical_bytes({"evaluation": report.config, "runtime": report.runtime})
        if sha256(recorded) != report.code_artifact_digests["config"]:
            _fail("provenance", "the recorded runtime configuration does not match its digest")
        checks["runtime_configuration"] = "verified_by_digest"
    else:
        checks["runtime_configuration"] = "not_recorded"
        unverifiable.append("runtime_configuration")

    checks["collection_commit_vs_freeze"] = (
        "same" if manifest.get("code_commit") == report.code_commit else "differs"
    )
    if report.git is None:
        checks["collection_git"] = "not_recorded"
        unverifiable.append("collection_git_state")
    elif report.git.head == report.code_commit and report.git.working_tree_clean:
        checks["collection_git"] = "clean_at_declared_commit"
    else:
        checks["collection_git"] = "not_clean_or_other_head"

    # Por último, a identidade: o manifesto fornecido é o que a recolha leu. Os
    # bytes canónicos do conteúdo decidem; os do ficheiro só distinguem uma
    # reformatação.
    if report.inputs is None:
        checks["freeze_manifest_vs_collection"] = "not_recorded"
        unverifiable.append("freeze_manifest_used_in_collection")
    elif report.inputs.freeze_manifest is None:
        checks["freeze_manifest_vs_collection"] = "not_used_in_collection"
    elif sha256(canonical_bytes(dict(manifest))) != report.inputs.freeze_manifest.frozen_sha256:
        _fail("provenance", "the freeze manifest differs from the one the collection used")
    elif manifest_file_sha256 == report.inputs.freeze_manifest.file_sha256:
        checks["freeze_manifest_vs_collection"] = "verified_by_digest"
    else:
        checks["freeze_manifest_vs_collection"] = "verified_by_content"
    return catalog


def _oracle_outcomes(
    archived: ArchivedCollection,
    adjudication: LabelSet,
    cases: EvaluationCaseSet,
    catalog: Mapping[str, Any],
) -> tuple[list[CaseOutcome], str]:
    """Os resultados de P-oráculo: os arquivados, confirmados por replay, ou —
    numa recolha feita sem adjudicação — calculados agora pela mesma política."""
    dates = {case.case_id: case.reference_date for case in cases.cases}
    try:
        recomputed = {
            labels.case_id: run_oracle(
                labels, catalog=catalog, reference_date=dates[labels.case_id]
            )
            for labels in adjudication.cases
        }
    except ValueError as exc:
        _fail("provenance", f"P-oráculo cannot run on this adjudication: {exc}")
    archived_oracle = {
        outcome.case_id: outcome
        for outcome in archived.outcomes
        if outcome.condition is Condition.P_ORACLE
    }
    if not archived_oracle:
        return [*archived.outcomes, *recomputed.values()], "computed_offline"
    for case_id, outcome in archived_oracle.items():
        replayed = recomputed[case_id]
        if (outcome.action, outcome.rule, outcome.destination_service_id) != (
            replayed.action,
            replayed.rule,
            replayed.destination_service_id,
        ):
            _fail(
                "provenance",
                f"case {case_id}: the archived P-oráculo outcome does not follow "
                "from this adjudication and policy",
            )
    return list(archived.outcomes), "archived"


# ---------------------------------------------------------------------------
# Rastos por caso
# ---------------------------------------------------------------------------


def _adjudication_trace(labels: CaseLabels) -> dict[str, Any]:
    trace = labels.trace
    return {
        "preferred_action": labels.preferred_action.value,
        "acceptable_actions": sorted(action.value for action in labels.acceptable_actions),
        "d6_service_id": labels.d6.service_id,
        "evidence_chunk_ids": None
        if trace is None
        else sorted(
            {
                evidence_id
                for collection in (trace.items, trace.readings, trace.conflicts)
                for item in collection
                for evidence_id in item.evidence_ids
            }
        ),
    }


def _primary_trace(
    outcome: CaseOutcome,
    packets: Mapping[str, EvidencePacket],
    archived_id: str | None,
) -> dict[str, Any]:
    packet = packets.get(outcome.packet_digest) if outcome.packet_digest else None
    return {
        "run_number": outcome.run_number,
        "outcome_id": archived_id,
        "action": outcome.action,
        "rule": outcome.rule,
        "destination_service_id": outcome.destination_service_id,
        "failure": outcome.failure,
        "temporal_notice_shown": outcome.temporal_notice_shown,
        "packet_digest": outcome.packet_digest,
        "packet_documents": []
        if packet is None
        else [
            {
                "evidence_id": passage.evidence_id,
                "document_id": passage.document_id,
                "document_version_id": passage.document_version_id,
                "chunk_id": passage.chunk_id,
            }
            for passage in packet.passages
        ],
        "message_sha256": None if outcome.message is None else message_sha256(outcome.message),
        "citations": citation_admissibility(outcome, packets),
    }


def _case_traces(
    cases: Sequence[EvaluationCase],
    outcomes: Sequence[CaseOutcome],
    summaries: Mapping[Condition, Mapping[str, CaseSummary]],
    gold: Mapping[str, CaseLabels],
    packets: Mapping[str, EvidencePacket],
    archived_ids: Mapping[tuple[str, str, int], str],
    ratings: Mapping[tuple[str, str], BoundMessageRating],
    *,
    collection_formal: bool,
) -> dict[str, Any]:
    runs: dict[tuple[str, Condition], list[CaseOutcome]] = defaultdict(list)
    for outcome in outcomes:
        runs[(outcome.case_id, outcome.condition)].append(outcome)
    traces: dict[str, Any] = {}
    for case in sorted(cases, key=lambda item: item.case_id):
        conditions: dict[str, Any] = {}
        for condition, by_case in summaries.items():
            summary = by_case.get(case.case_id)
            if summary is None:
                continue
            primary = summary.primary
            key = (case.case_id, condition.value, primary.run_number)
            rating = ratings.get((case.case_id, condition.value))
            entry: dict[str, Any] = {
                "primary": _primary_trace(primary, packets, archived_ids.get(key)),
                "metric_membership": rate_membership(summary, gold[case.case_id], packets),
                "message_rating": None
                if rating is None
                else {
                    "rater_id": rating.rater_id,
                    "acceptable": rating.acceptable,
                    "criteria": rating.criteria.model_dump(),
                },
                "runs": [
                    {"run_number": item.run_number, "action": item.action, "failure": item.failure}
                    for item in sorted(
                        runs[(case.case_id, condition)], key=lambda item: item.run_number
                    )
                ],
                "modal_action": summary.modal_action,
                "unstable": summary.unstable,
                "failures": summary.failures,
            }
            if primary.estimates is not None and condition in (
                Condition.P_E2E,
                Condition.A_NO_DIAGNOSTIC,
            ):
                entry["dimensions"] = dimension_pairs(gold[case.case_id], primary.estimates)
            conditions[condition.value] = entry
        traces[case.case_id] = {
            "family": case.family,
            "source_kind": case.source_kind,
            "stratum": stratum(case),
            "primary_scope": in_primary_scope(case, formal=collection_formal),
            "reference_date": case.reference_date.isoformat(),
            "requester_role": case.requester_role,
            "expected_snapshot_id": case.expected_snapshot_id,
            "adjudication": _adjudication_trace(gold[case.case_id]),
            "conditions": dict(sorted(conditions.items())),
        }
    return traces


# ---------------------------------------------------------------------------
# Reanálise
# ---------------------------------------------------------------------------


def rescore(
    inputs: RescoringInputs, *, formal: bool, git: AnalysisGit, analyzed_at: datetime
) -> dict[str, Any]:
    """A análise offline de uma recolha arquivada, ou :class:`RescoringError`."""
    try:
        archived = load_collection_report(inputs.report)
    except ReportError as exc:
        _fail("invalid", str(exc))
    report = archived.report
    cases_payload = _json(inputs.cases, "cases")
    cases = _model(EvaluationCaseSet, cases_payload, "cases")
    adjudication = _model(LabelSet, _json(inputs.adjudication, "adjudication"), "adjudication")
    checks: dict[str, str] = {}
    unverifiable: list[str] = []
    manifest = _verify_manifest(_json(inputs.freeze_manifest, "freeze manifest"), checks)
    ratings = _ratings(inputs.message_ratings)
    inventory_payload: Any = None
    inventory: bytes | None = None
    if inputs.corpus_inventory is not None:
        inventory_payload = _json(inputs.corpus_inventory, "corpus inventory")
        try:
            inventory = corpus_inventory_bytes(inventory_payload)
        except FreezeError as exc:
            _fail("invalid", str(exc))
    try:
        frozen_cases = corpus_bytes(cases_payload)
    except FreezeError as exc:
        _fail("invalid", str(exc))

    _verify_cases(archived, cases, frozen_cases, checks)
    _verify_adjudication(report, cases, adjudication, manifest, frozen_cases, checks, unverifiable)
    catalog = _verify_freeze(
        archived, manifest, sha256(inputs.freeze_manifest), inventory, checks, unverifiable
    )

    current = artifact_digests(_ENVIRONMENT_FREE_ARTIFACTS)
    compatibility = {
        name: "same" if current[name] == report.code_artifact_digests[name] else "differs"
        for name in _ENVIRONMENT_FREE_ARTIFACTS
    }
    compatibility["evaluation_config"] = "same"
    if compatibility["policy"] != "same":
        _fail(
            "provenance",
            "the analysis code runs another policy than the collection; "
            "P-oráculo and the replay would not be the same",
        )

    if formal:
        if report.mode != "formal":
            _fail("refused", "a development trial cannot be reanalysed formally")
        if report.legacy or report.inputs is None:
            _fail("refused", "a report without policy_v1_report_2 provenance is never formal")
        reasons = [
            reason
            for reason, failed in (
                ("the freeze commit differs", checks["collection_commit_vs_freeze"] != "same"),
                (
                    "the collection did not record its freeze manifest",
                    report.inputs.freeze_manifest is None,
                ),
                (
                    "the collection did not run on a clean tree at its declared commit",
                    checks["collection_git"] != "clean_at_declared_commit",
                ),
                ("the collection did not use the adjudication", report.inputs.adjudication is None),
                (
                    "formal reanalysis requires a clean working tree",
                    git.head is None or not git.working_tree_clean,
                ),
                (
                    "the analysis schemas or prompts differ from the collection",
                    "differs" in compatibility.values(),
                ),
                ("formal reanalysis requires --corpus-inventory", inventory_payload is None),
            )
            if failed
        ]
        if reasons:
            _fail("refused", "; ".join(reasons))
        try:
            validate_formal_annotations(cases.cases, adjudication, inventory_payload)
        except FreezeError as exc:
            _fail("provenance", str(exc))
    elif not cases.set_id.startswith("policy-v1-dev"):
        # O conjunto reservado nunca é usado para afinação.
        _fail("refused", "development reanalysis only accepts policy-v1-dev case sets")

    outcomes, oracle_source = _oracle_outcomes(archived, adjudication, cases, catalog)
    if formal and oracle_source != "archived":
        _fail("refused", "a formal collection archives its P-oráculo outcomes")

    report_sha256 = sha256(inputs.report)
    index = archived.outcome_index()
    families = {
        case.case_id: case.family
        or next(
            (
                label.trace.family
                for label in adjudication.cases
                if label.case_id == case.case_id and label.trace is not None
            ),
            None,
        )
        for case in cases.cases
    }
    if ratings is not None:
        try:
            bind_ratings(
                ratings,
                source=SourceReport(
                    collection_id=report.collection_id, report_sha256=report_sha256
                ),
                set_id=cases.set_id,
                outcomes=index,
                families=families,
            )
        except RatingBindingError as exc:
            _fail("ratings", str(exc))

    summaries = summarize_outcomes(outcomes)
    gold = {label.case_id: label for label in adjudication.cases}
    collection_formal = report.mode == "formal"

    def metrics_with(rating_set: BoundMessageRatingSet | None) -> dict[str, Any]:
        return compute_report_metrics(
            cases.cases,
            summaries,
            gold,
            archived.packets,
            catalog,
            ratings=rating_set,
            formal=collection_formal,
        )

    reproduced = metrics_with(None)
    reproduction = _reproduction(reproduced, report.metrics)
    if formal and reproduction["status"] == "differs":
        _fail("refused", "the analysis code does not reproduce the archived collection metrics")
    metrics = reproduced if ratings is None else metrics_with(ratings)

    rated = {} if ratings is None else {(r.case_id, r.condition): r for r in ratings.ratings}
    rateable = [outcome for outcome in outcomes if unrateable_reason(outcome) is None]
    archived_ids = {key: outcome_id(raw) for key, (_, raw) in index.items()}

    if report.legacy:
        level = "legacy_partial"
        conformance = "not attributed: the legacy report records no collection provenance"
    elif formal:
        level = "full"
        conformance = "verified at reanalysis against the complete freeze"
    else:
        level = "full"
        conformance = "not claimed: development reanalysis"
    return {
        "analysis_schema_version": ANALYSIS_SCHEMA_VERSION,
        "mode": "formal_reanalysis" if formal else "development_reanalysis",
        "status": (
            "reanálise offline formal de uma recolha formal; nenhuma nova chamada aos modelos"
            if formal
            else "reanálise offline de desenvolvimento, não avaliação; "
            "nenhuma nova chamada aos modelos"
        ),
        "source_report": {
            "file_name": inputs.report_name,
            "file_sha256": report_sha256,
            "report_schema_version": report.report_schema_version,
            "collection_id": report.collection_id,
            "collected_at": (
                None if report.collected_at is None else report.collected_at.isoformat()
            ),
            "mode": report.mode,
            "set_id": report.set_id,
            "collection_commit": report.code_commit,
            "collection_git": None if report.git is None else report.git.model_dump(),
            "collection_versions": report.versions,
            "collection_runtime": report.runtime,
            "collection_code_artifact_digests": report.code_artifact_digests,
        },
        "analysis": {
            "analyzed_at": analyzed_at.isoformat(),
            "code_commit": git.head,
            "working_tree_clean": git.working_tree_clean,
            "python_version": platform.python_version(),
            "code_artifact_digests": {name: current[name] for name in _ENVIRONMENT_FREE_ARTIFACTS},
            "evaluation_config_sha256": sha256(canonical_bytes(EVALUATION_CONFIG)),
            "versions": versions_payload(),
        },
        "inputs": {
            "cases": {
                "file_sha256": sha256(inputs.cases),
                "frozen_sha256": sha256(frozen_cases),
            },
            "adjudication": {
                "file_sha256": sha256(inputs.adjudication),
                "frozen_sha256": sha256(label_set_bytes(adjudication)),
            },
            "freeze_manifest": {
                "file_sha256": sha256(inputs.freeze_manifest),
                "code_commit": manifest.get("code_commit"),
                "recipe_version": manifest.get("recipe_version"),
                "python_version": manifest.get("python_version"),
            },
            "corpus_inventory": None
            if inputs.corpus_inventory is None or inventory is None
            else {
                "file_sha256": sha256(inputs.corpus_inventory),
                "frozen_sha256": sha256(inventory),
            },
            "message_ratings": None
            if inputs.message_ratings is None
            else {
                "file_sha256": sha256(inputs.message_ratings),
                "schema_version": BOUND_RATINGS_SCHEMA_VERSION,
            },
        },
        "verification": {
            "level": level,
            "checks": checks,
            "unverifiable": unverifiable,
            "formal_conformance": conformance,
        },
        "compatibility": compatibility,
        "p_oracle": {"source": oracle_source},
        "collection_metrics_reproduction": reproduction,
        "message_ratings": {"status": "not_provided", "m7": "not_measured"}
        if ratings is None
        else {
            # Um ficheiro válido sem juízos não mede nada: M7 fica não medida.
            "status": "bound_to_archived_messages" if ratings.ratings else "no_judgments",
            "provenance": ratings.provenance.model_dump(),
            "ratings": len(ratings.ratings),
            "by_condition": dict(sorted(Counter(r.condition for r in ratings.ratings).items())),
            "unrated_primary_messages": sum(
                1 for o in rateable if (o.case_id, o.condition.value) not in rated
            ),
        },
        "case_traces": _case_traces(
            cases.cases,
            outcomes,
            summaries,
            gold,
            archived.packets,
            archived_ids,
            rated,
            collection_formal=collection_formal,
        ),
        "metrics": metrics,
    }
