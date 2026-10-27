"""Recolha técnica sintética da avaliação v1, sem base de dados — só para testes.

Constrói um relatório ``policy_v1_report_2`` com as mesmas funções da recolha:
as condições sobre packets, a agregação (:func:`compute_report_metrics`) e a
construção do relatório. Os modelos são doubles determinísticos.

Tudo aqui é **sintético e técnico**: os casos, os "rótulos", as mensagens e os
"juízos" servem para fixar o comportamento do código. Não são anotações humanas
nem resultados da tese, e não entram em nenhum conjunto de avaliação.
"""

import json
import os
import subprocess
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from app.decision.contracts import RequestConstraint, ScopeClass
from app.decision.dimensions import ExcludedByValidity, TemporalDiagnostic
from app.decision.estimators.base import (
    AssessmentRequest,
    EstimationError,
    ItemDraft,
    RequestAnalysis,
)
from app.decision.estimators.base import EvidenceAssessment as Assessment
from app.evaluation.policy_v1.artifacts import (
    catalog_bytes,
    code_artifacts,
    config_payload,
    corpus_bytes,
)
from app.evaluation.policy_v1.conditions import (
    BaselineResponse,
    CaseOutcome,
    Condition,
    run_b0,
    run_b1_composition,
    run_b1_full,
    run_oracle,
    run_p_e2e,
    run_without_diagnostic,
)
from app.evaluation.policy_v1.corpus_inventory import corpus_inventory_bytes
from app.evaluation.policy_v1.executor import EvaluationCaseSet
from app.evaluation.policy_v1.freeze import (
    FrozenArtifact,
    build_freeze_manifest,
    canonical_bytes,
    sha256,
)
from app.evaluation.policy_v1.labels import LabelSet, label_set_bytes
from app.evaluation.policy_v1.packets import EvidencePacket, PacketPassage
from app.evaluation.policy_v1.report import (
    build_collection_report,
    compute_report_metrics,
    report_bytes,
    summarize_outcomes,
)
from app.evaluation.policy_v1.runs import RUN_NUMBERS
from tests.decision_support import RecordingGenerator, ScriptedEstimator, analysis, support_by_title
from tests.test_policy_v1_evaluation import CATALOG, LIMITS, _case
from tests.test_policy_v1_evaluation_audit import COMMIT, CORPUS_INVENTORY

BACKEND = Path(__file__).resolve().parents[1]
COLLECTION_ID = "00000000-0000-4000-8000-0000000c0111"
#: O único segmento do inventário sintético (``CORPUS_INVENTORY``).
INVENTORY_CHUNK = CORPUS_INVENTORY["documents"][0]["versions"][0]["chunks"][0]["chunk_id"]
REFERENCE = "2026-10-01"
#: Campos acrescentados por ``policy_v1_report_2``; sem eles, o formato antigo.
PROVENANCE_FIELDS = ("report_schema_version", "collection_id", "collected_at", "git", "runtime")
LEGACY_VERSION_KEYS = ("policy", "definitions", "rules", "messages", "b1_prompt")

Passage = tuple[str, str, str, date | None, date | None]


@dataclass
class _Spec:
    """Um caso sintético: o que cada família de packet recebe e o que os doubles devolvem."""

    case: dict[str, Any]
    labels: dict[str, Any]
    analysis: RequestAnalysis
    assess: Callable[[AssessmentRequest], Assessment]
    passages: tuple[Passage, ...] = ()
    #: Passagens que só A-sem-filtro recebe (C9/C10 relaxadas).
    expired: tuple[Passage, ...] = ()
    diagnostic: TemporalDiagnostic = field(default_factory=TemporalDiagnostic)
    #: Execuções em que a avaliação do estimador falha (falha técnica).
    failing_runs: frozenset[int] = frozenset()
    baseline: Callable[[int], BaselineResponse] = lambda run: BaselineResponse(
        "abstain", "Não encontrei informação suficiente.", (), None
    )


def _case_payload(case_id: str, query: str, family: str, source_kind: str) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "query": query,
        "language": "pt",
        "reference_date": REFERENCE,
        "requester_role": "student",
        "family": family,
        "source_kind": source_kind,
        "expected_snapshot_id": f"synthetic-snapshot-{case_id}",
    }


_REGULATION: Passage = (
    "E1",
    "Regulamento de matrículas (sintético)",
    "O prazo de matrícula termina a 30 de setembro.",
    None,
    None,
)
_OLD_CALENDAR: Passage = (
    "E2",
    "Calendário antigo (sintético)",
    "O prazo de matrícula terminava a 1 de setembro.",
    date(2025, 1, 1),
    date(2025, 12, 31),
)
_OLD_DIAGNOSTIC = TemporalDiagnostic(
    excluded=(
        ExcludedByValidity(
            "00000000-0000-4000-8000-0000000000d1",
            "Calendário antigo (sintético)",
            date(2025, 1, 1),
            date(2025, 12, 31),
        ),
    )
)


def _failing(request: AssessmentRequest) -> Assessment:
    raise EstimationError("timeout")


def specs() -> list[_Spec]:
    answer = BaselineResponse("answer", "Resposta sintética do modelo B1.", ("E1",), None)
    abstain = BaselineResponse("abstain", "Não encontrei informação suficiente.", (), None)
    escalate = BaselineResponse(
        "escalate", "Contacte os Serviços Académicos (sintético).", (), "academic-office"
    )
    return [
        # Fonte real (sintética para o teste), resposta suportada; B1-plena instável.
        _Spec(
            case=_case_payload("DEV-01", "Qual é o prazo de matrícula?", "F01", "real"),
            labels=_case("DEV-01"),
            analysis=analysis(),
            assess=support_by_title({"I1": "matrículas"}),
            passages=(_REGULATION,),
            expired=(_OLD_CALENDAR,),
            baseline=lambda run: abstain if run == 2 else answer,
        ),
        # Suporte parcial; falha técnica do estimador na execução principal.
        _Spec(
            case=_case_payload(
                "DEV-02", "Qual é o prazo de matrícula e o valor da propina?", "F05", "synthetic"
            ),
            labels=_case(
                "DEV-02",
                d4={"sufficiency": "partial", "partial_misleading": False},
                d6={"has_competent_service": False, "service_id": None},
            ),
            analysis=analysis(
                items=(ItemDraft("I1", "prazo de matrícula"), ItemDraft("I2", "valor da propina")),
                topic="fees",
            ),
            assess=support_by_title({"I1": "matrículas"}, partial_misleading=False),
            passages=(_REGULATION,),
            failing_runs=frozenset({1}),
            baseline=lambda run: answer,
        ),
        # Só informação fora de vigor: abstenção com aviso temporal.
        _Spec(
            case=_case_payload("DEV-03", "Qual é o prazo das propinas?", "F02", "real"),
            labels=_case(
                "DEV-03",
                d4={"sufficiency": "none", "partial_misleading": None},
                d6={"has_competent_service": False, "service_id": None},
                acceptable_actions=["abstain"],
            ),
            analysis=analysis(topic="fees"),
            assess=support_by_title({}),
            expired=(_OLD_CALENDAR,),
            diagnostic=_OLD_DIAGNOSTIC,
        ),
        # Dado pessoal: encaminhamento preferido; o B0 responde.
        _Spec(
            case=_case_payload("DEV-04", "Qual é a minha nota a Matemática?", "F11", "real"),
            labels=_case(
                "DEV-04",
                d2={"constraints": ["personal_data_required"]},
                d3={
                    "specificity": None,
                    "materiality": None,
                    "disambiguation": None,
                    "coverage": None,
                },
                d4={"sufficiency": None, "partial_misleading": None},
                d5={"unresolvable_conflict": None},
                acceptable_actions=["escalate", "abstain"],
                preferred_action="escalate",
            ),
            analysis=analysis(
                scope=ScopeClass.IN_SCOPE,
                constraints=frozenset({RequestConstraint.PERSONAL_DATA_REQUIRED}),
                procedure_item=ItemDraft("P1", "como consultar o prazo"),
            ),
            assess=support_by_title({"P1": "matrículas"}),
            passages=(_REGULATION,),
            baseline=lambda run: escalate,
        ),
        # F14, sintético e sempre em separado: nada admissível para o papel.
        _Spec(
            case=_case_payload("DEV-05", "Quais são as normas internas?", "F14", "synthetic"),
            labels=_case(
                "DEV-05",
                d4={"sufficiency": "none", "partial_misleading": None},
                acceptable_actions=["abstain", "escalate"],
            ),
            analysis=analysis(),
            assess=support_by_title({}),
        ),
    ]


def _packet(spec: _Spec, family: str, run: int, case_index: int) -> EvidencePacket:
    case = spec.case
    passages = spec.passages + (spec.expired if family == "b0_without_validity_filter" else ())
    return EvidencePacket(
        case_id=case["case_id"],
        family=family,  # type: ignore[arg-type]
        run_number=run,
        query=case["query"],
        language="pt",
        reference_date=date.fromisoformat(REFERENCE),
        requester_role="student",
        catalog=CATALOG,
        passages=tuple(
            PacketPassage(
                evidence_id=evidence_id,
                chunk_id=f"00000000-0000-4000-8000-{case_index:04d}{index:08d}",
                document_id=f"00000000-0000-4000-8000-{case_index:04d}{index + 100:08d}",
                document_version_id=f"00000000-0000-4000-8000-{case_index:04d}{index + 200:08d}",
                document_title=title,
                chunk_index=0,
                content=content,
                content_sha256=sha256(content.encode()),
                official_source=True,
                source_url=None,
                language="pt",
                valid_from=valid_from,
                valid_until=valid_until,
            )
            for index, (evidence_id, title, content, valid_from, valid_until) in enumerate(
                passages, start=1
            )
        ),
        diagnostic=spec.diagnostic if family == "p_e2e" else TemporalDiagnostic(),
        retrieval={
            "eligibility_policy": "RetrievalEligibility",
            "conditions": [],
            "access_policy_version": "document_role_access_v1",
        },
        snapshot_id=case["expected_snapshot_id"],
        corpus_digest="0" * 64,
    )


class _Baseline:
    def __init__(self, response: BaselineResponse) -> None:
        self.response = response

    def respond(self, system_prompt: str, user_prompt: str) -> BaselineResponse:
        return self.response


def collect(
    all_specs: Iterable[_Spec],
) -> tuple[list[EvidencePacket], list[CaseOutcome]]:
    """As execuções numeradas pela ordem do executor, sobre packets sintéticos."""
    chosen = list(all_specs)
    generator = RecordingGenerator()
    packets: list[EvidencePacket] = []
    outcomes: list[CaseOutcome] = []
    for run in RUN_NUMBERS:
        for case_index, spec in enumerate(chosen, start=1):
            b0 = _packet(spec, "b0", run, case_index)
            no_filter = _packet(spec, "b0_without_validity_filter", run, case_index)
            p_e2e = _packet(spec, "p_e2e", run, case_index)
            outcomes.append(run_b0(b0, generator, LIMITS))
            outcomes.append(run_b0(no_filter, generator, LIMITS, condition=Condition.A_NO_FILTER))
            estimator = ScriptedEstimator(
                result=spec.analysis,
                assess_with=_failing if run in spec.failing_runs else spec.assess,
            )
            result = run_p_e2e(p_e2e, spec.analysis, estimator, generator, LIMITS)
            baseline = _Baseline(spec.baseline(run))
            outcomes.append(result.outcome)
            outcomes.append(run_without_diagnostic(p_e2e, result, generator, LIMITS))
            outcomes.append(run_b1_full(p_e2e, baseline))
            outcomes.append(run_b1_composition(p_e2e, result, baseline))
            packets += [b0, no_filter, p_e2e]
    return packets, outcomes


@dataclass
class SyntheticCollection:
    report: dict[str, Any]
    cases: dict[str, Any]
    adjudication: dict[str, Any]
    manifest: dict[str, Any]
    inventory: dict[str, Any]

    def write(self, directory: Path, *, report: dict[str, Any] | None = None) -> dict[str, Path]:
        directory.mkdir(parents=True, exist_ok=True)
        paths = {
            name: directory / f"{name}.json"
            for name in ("report", "cases", "adjudication", "freeze-manifest", "inventory")
        }
        paths["report"].write_bytes(report_bytes(report or self.report))
        paths["cases"].write_text(json.dumps(self.cases, ensure_ascii=False), encoding="utf-8")
        paths["adjudication"].write_text(
            json.dumps(self.adjudication, ensure_ascii=False), encoding="utf-8"
        )
        paths["freeze-manifest"].write_text(json.dumps(self.manifest), encoding="utf-8")
        paths["inventory"].write_bytes(corpus_inventory_bytes(self.inventory))
        return paths


def _trace(labels: dict[str, Any], case: dict[str, Any]) -> dict[str, Any]:
    """Traço de anotação **técnico**, coerente com os rótulos e com o inventário."""
    sufficiency = labels["d4"]["sufficiency"]
    supported = {"full": [True], "partial": [True, False], "none": [False]}.get(sufficiency, [])
    return {
        "family": case["family"],
        "source_kind": case["source_kind"],
        "snapshot_id": case["expected_snapshot_id"],
        "rationale": "Fixture técnica sintética; não é uma anotação humana nem científica.",
        "items": [
            {
                "item_id": f"I{index}",
                "label": f"item sintético {index}",
                "supported": flag,
                "evidence_ids": [INVENTORY_CHUNK] if flag else [],
            }
            for index, flag in enumerate(supported, start=1)
        ],
    }


def build_collection(
    *,
    set_id: str = "policy-v1-dev",
    mode: str = "development_trial",
    with_adjudication: bool = True,
    traced: bool = False,
    adjudication_set_id: str | None = None,
) -> SyntheticCollection:
    """Uma recolha técnica completa, com adjudicação e congelamento sintéticos.

    ``traced`` acrescenta aos rótulos o traço exigido pela avaliação formal.
    ``adjudication_set_id`` dá à adjudicação outro conjunto, com todos os digests
    coerentes — só para testar a recusa dessa incompatibilidade.
    """
    chosen = specs()
    if traced:
        for spec in chosen:
            spec.labels = {**spec.labels, "trace": _trace(spec.labels, spec.case)}
    cases = {
        "schema_version": "policy_v1_cases_1",
        "set_id": set_id,
        "corpus": "P2",
        "institution_code": "SYN",
        "cases": [spec.case for spec in chosen],
    }
    case_set = EvaluationCaseSet.model_validate(cases)
    adjudication = LabelSet.model_validate(
        {
            "schema_version": "policy_v1_labels_2",
            "set_id": adjudication_set_id or set_id,
            "annotator": {
                "annotator_id": "SYN-ADJ",
                "role": "adjudication",
                "adjudicators": ["SYN-A1", "SYN-A2"],
            },
            "cases": [spec.labels for spec in chosen],
        }
    )
    files = {
        "corpus": corpus_bytes(cases),
        "manifest": corpus_inventory_bytes(CORPUS_INVENTORY),
        "labels": label_set_bytes(adjudication),
        "catalog": catalog_bytes(CATALOG),
    }
    manifest = build_freeze_manifest(
        [*(FrozenArtifact(name, "v1", data) for name, data in files.items()), *code_artifacts()],
        code_commit=COMMIT,
    )
    packets, outcomes = collect(chosen)
    metrics: dict[str, Any] = {"status": "not_computed_without_adjudication"}
    if with_adjudication:
        dates = {case.case_id: case.reference_date for case in case_set.cases}
        outcomes += [
            run_oracle(labels, catalog=CATALOG, reference_date=dates[labels.case_id])
            for labels in adjudication.cases
        ]
        metrics = compute_report_metrics(
            case_set.cases,
            summarize_outcomes(outcomes),
            {labels.case_id: labels for labels in adjudication.cases},
            {packet.digest: packet for packet in packets},
            CATALOG,
            ratings=None,
            formal=mode == "formal",
        )
    raw_cases = json.dumps(cases).encode()
    raw_adjudication = adjudication.model_dump_json().encode()
    report = build_collection_report(
        formal=mode == "formal",
        cases=case_set,
        collection_id=COLLECTION_ID,
        collected_at=datetime(2026, 10, 27, 12, 0, tzinfo=UTC),
        code_commit=COMMIT,
        git=(COMMIT, True),
        runtime=config_payload()["runtime"],
        inputs={
            "cases": {"file_sha256": sha256(raw_cases), "frozen_sha256": sha256(files["corpus"])},
            "adjudication": {
                "file_sha256": sha256(raw_adjudication),
                "frozen_sha256": sha256(files["labels"]),
            }
            if with_adjudication
            else None,
            # Os bytes que ``SyntheticCollection.write`` escreve no ficheiro.
            "freeze_manifest": {
                "file_sha256": sha256(json.dumps(manifest).encode()),
                "frozen_sha256": sha256(canonical_bytes(manifest)),
                "code_commit": COMMIT,
            },
            "corpus_inventory": {"frozen_sha256": sha256(files["manifest"])},
            "catalog": {"frozen_sha256": sha256(files["catalog"]), "snapshot": CATALOG},
        },
        packets=packets,
        outcomes=outcomes,
        metrics=metrics,
    )
    return SyntheticCollection(
        report=json.loads(report_bytes(report)),
        cases=cases,
        adjudication=adjudication.model_dump(mode="json"),
        manifest=manifest,
        inventory=CORPUS_INVENTORY,
    )


def legacy_report(report: dict[str, Any]) -> dict[str, Any]:
    """O mesmo relatório no formato anterior a ``policy_v1_report_2``."""
    legacy = {
        key: value
        for key, value in report.items()
        if key not in PROVENANCE_FIELDS and key != "inputs"
    }
    legacy["versions"] = {key: report["versions"][key] for key in LEGACY_VERSION_KEYS}
    return legacy


def fill_draft(
    draft: dict[str, Any],
    *,
    rater: str = "SYN-R1",
    acceptable: Callable[[dict[str, Any]], bool] = lambda item: True,
) -> dict[str, Any]:
    """Preenche um rascunho como um avaliador faria — **fixture técnica**, não juízo."""
    from app.evaluation.policy_v1.message_ratings import (
        BOUND_RATINGS_SCHEMA_VERSION,
        RUBRIC_CRITERIA,
    )

    filled = json.loads(json.dumps(draft))
    filled["schema_version"] = BOUND_RATINGS_SCHEMA_VERSION
    filled["provenance"] = {"kind": "one_rater_per_message", "raters": [rater]}
    for item in filled["ratings"]:
        verdict = acceptable(item)
        item["rater_id"] = rater
        item["acceptable"] = verdict
        item["criteria"] = dict.fromkeys(RUBRIC_CRITERIA, verdict)
    return filled


#: Arranque de um processo sem configuração da aplicação, sem driver de base de
#: dados, sem SDK de fornecedores e sem rede: um import ou uma ligação falham, em
#: vez de passarem despercebidos. Bloquear ``app.core.config`` torna o teste
#: independente de existir, ou não, um ``.env`` na máquina.
OFFLINE_BOOT = """
import socket
import sys

for name in ("app.core.config", "psycopg", "psycopg2", "openai"):
    sys.modules[name] = None


def _no_network(*args, **kwargs):
    raise OSError("network disabled in the offline rescoring test")


socket.socket.connect = _no_network
socket.create_connection = _no_network
import importlib

code = importlib.import_module(sys.argv[1]).main(sys.argv[2:])
watched = (
    "app.database.session",
    "app.answering.providers.openai",
    "app.decision.estimators.providers.openai",
    "app.evaluation.policy_v1.baseline_openai",
)
loaded = [name for name in watched if name in sys.modules]
sys.stderr.write("LOADED:" + ",".join(loaded) + "\\n")
raise SystemExit(code)
"""


#: Configuração operacional que a reanálise não pode exigir.
OPERATIONAL_SETTINGS = ("DATABASE_URL", "TEST_DATABASE_URL", "JWT_SECRET_KEY", "OPENAI_API_KEY")


def run_offline(
    argv: list[str], *, module: str = "scripts.score_policy_v1_report"
) -> subprocess.CompletedProcess[str]:
    """Um comando offline num processo isolado, sem configuração operacional."""
    env = {key: value for key, value in os.environ.items() if key not in OPERATIONAL_SETTINGS}
    return subprocess.run(
        [sys.executable, "-c", OFFLINE_BOOT, module, *argv],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=300,
        check=False,
    )


def score_argv(
    paths: dict[str, Path],
    output: Path,
    *,
    ratings: Path | None = None,
    inventory: bool = False,
    formal: bool = False,
) -> list[str]:
    argv = [
        "--report",
        str(paths["report"]),
        "--cases",
        str(paths["cases"]),
        "--adjudication",
        str(paths["adjudication"]),
        "--freeze-manifest",
        str(paths["freeze-manifest"]),
        "--output",
        str(output),
    ]
    if ratings is not None:
        argv += ["--message-ratings", str(ratings)]
    if inventory:
        argv += ["--corpus-inventory", str(paths["inventory"])]
    if formal:
        argv.append("--formal")
    return argv
