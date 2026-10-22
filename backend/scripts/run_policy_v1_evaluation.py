"""Executor preparado da avaliação da política de decisão v1.7.

Uso (a partir de backend/):

    python -m scripts.run_policy_v1_evaluation --cases CASES.json \\
        --commit SHA --output RESULTADOS.json \\
        [--adjudication ADJ.json --freeze-manifest MANIFEST.json] [--formal]

Dois modos:

- **ensaio de desenvolvimento** (omissão): só aceita conjuntos ``policy-v1-dev*``
  — o conjunto reservado nunca é consultado para afinação — e só corre em
  ``ENVIRONMENT`` ``development``/``test``. O relatório é marcado como ensaio,
  não como avaliação.
- **formal** (``--formal``): exige que o ficheiro de casos e a adjudicação
  correspondam a um manifesto de congelamento **completo** (corpus, manifesto,
  rótulos, catálogo, política, esquema, prompts e configuração) e que o
  catálogo ativo na base de dados seja o congelado. Sem isso, recusa.

Corre três execuções numeradas para cada condição com modelo (B0 incluído) e
uma para P-oráculo (só com adjudicação verificada). Os packets de cada execução
são arquivados no relatório, com o respetivo digest. Falhas técnicas e
denominadores ficam explícitos.

Este script **não** cria rótulos e não foi executado como avaliação formal
neste repositório: o corpus P2, a adjudicação e o protocolo não estão
congelados.
"""

import argparse
import json
import platform
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.answering.dependencies import get_answer_generator
from app.core.config import MOCK_PROVIDER_ENVIRONMENTS, settings
from app.database.session import SessionLocal
from app.decision.definitions import DEFINITIONS_VERSION, RULES_VERSION
from app.decision.estimators.dependencies import get_dimension_estimator
from app.decision.messages import MESSAGE_VERSION
from app.decision.policy import POLICY_VERSION
from app.evaluation.policy_v1.artifacts import (
    artifact_digests,
    catalog_bytes,
    catalog_snapshot,
    corpus_bytes,
    git_state,
    verify_code_artifacts,
    verify_formal_freeze,
)
from app.evaluation.policy_v1.attribution import attribute_errors
from app.evaluation.policy_v1.conditions import (
    B1_PROMPT_VERSION,
    CaseOutcome,
    Condition,
    Limits,
    run_oracle,
)
from app.evaluation.policy_v1.config import EVALUATION_CONFIG
from app.evaluation.policy_v1.executor import EvaluationCaseSet, run_case
from app.evaluation.policy_v1.freeze import FreezeError, verify_artifact
from app.evaluation.policy_v1.labels import LabelSet, MessageRatingSet, verified_adjudication
from app.evaluation.policy_v1.metrics import compute_metrics, estimation_errors, paired_comparison
from app.evaluation.policy_v1.runs import RUN_NUMBERS, summarize
from app.models.decision_catalog import InstitutionDecisionCatalog
from app.models.institution import Institution
from app.retrieval.dependencies import get_retriever

COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
EXIT_USAGE = 2
EXIT_INVALID = 3
EXIT_NOT_FROZEN = 5
EXIT_REFUSED = 6


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="run_policy_v1_evaluation")
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--adjudication", type=Path)
    parser.add_argument("--freeze-manifest", type=Path)
    parser.add_argument("--corpus-manifest", type=Path)
    # Avaliações humanas da qualidade da mensagem (M7); nunca produzidas por modelo.
    parser.add_argument("--message-ratings", type=Path)
    parser.add_argument("--formal", action="store_true")
    args = parser.parse_args(argv)
    if not COMMIT_PATTERN.match(args.commit):
        sys.stderr.write("--commit must be a full 40-character SHA\n")
        return EXIT_USAGE

    raw_cases = args.cases.read_bytes()
    cases = EvaluationCaseSet.model_validate(json.loads(raw_cases))
    manifest = _read(args.freeze_manifest) if args.freeze_manifest else None
    adjudication = LabelSet.model_validate(_read(args.adjudication)) if args.adjudication else None

    if args.formal:
        if manifest is None or adjudication is None or args.corpus_manifest is None:
            sys.stderr.write(
                "formal evaluation requires --freeze-manifest, --adjudication and "
                "--corpus-manifest\n"
            )
            return EXIT_NOT_FROZEN
        # A verificação completa só é possível depois de ler o catálogo ativo
        # da base de dados: corre logo a seguir, antes de qualquer caso.
    else:
        if settings.environment not in MOCK_PROVIDER_ENVIRONMENTS:
            sys.stderr.write("development trials only run in development/test environments\n")
            return EXIT_REFUSED
        if not cases.set_id.startswith("policy-v1-dev"):
            # O conjunto reservado nunca é usado para afinação.
            sys.stderr.write("development trials only accept policy-v1-dev case sets\n")
            return EXIT_REFUSED

    ratings = (
        MessageRatingSet.model_validate(_read(args.message_ratings))
        if args.message_ratings
        else None
    )
    oracle_labels = None
    limits = Limits(settings.answering_max_context_chars, settings.answering_max_answer_chars)
    outcomes: list[CaseOutcome] = []
    packets: list[dict[str, Any]] = []
    with SessionLocal() as db:
        institution = db.scalar(
            select(Institution).where(Institution.code == cases.institution_code)
        )
        if institution is None:
            sys.stderr.write("institution not found\n")
            return EXIT_INVALID
        catalog = db.scalar(
            select(InstitutionDecisionCatalog).where(
                InstitutionDecisionCatalog.institution_id == institution.id,
                InstitutionDecisionCatalog.is_active.is_(True),
            )
        )
        if catalog is None:
            sys.stderr.write("institution has no active decision catalog\n")
            return EXIT_INVALID
        catalog_payload: dict[str, Any] = catalog_snapshot(catalog)
        try:
            if args.formal:
                assert manifest is not None and adjudication is not None
                head, clean = git_state(REPOSITORY_ROOT)
                # Todos os artefactos — os gerados a partir do código e o
                # catálogo ativo —, o commit e a árvore de trabalho.
                verify_formal_freeze(
                    manifest,
                    cases_payload=json.loads(raw_cases),
                    corpus_manifest_payload=_read(args.corpus_manifest),
                    adjudication=adjudication,
                    catalog_payload=catalog_payload,
                    commit=args.commit,
                    head_commit=head or "",
                    working_tree_clean=clean,
                )
            if adjudication is not None and manifest is not None:
                oracle_labels = verified_adjudication(adjudication, manifest)
                # O P-oráculo usa a política, os casos e o catálogo: todos têm
                # de ser os congelados, também fora do modo formal.
                verify_artifact(manifest, "corpus", corpus_bytes(json.loads(raw_cases)))
                verify_artifact(manifest, "catalog", catalog_bytes(catalog_payload))
                verify_code_artifacts(manifest)
        except FreezeError as exc:
            sys.stderr.write(f"{exc}\n")
            return EXIT_NOT_FROZEN
        from app.evaluation.policy_v1.baseline_openai import OpenAIBaselineModel

        retriever = get_retriever()
        generator = get_answer_generator()
        baseline = OpenAIBaselineModel()
        for run_number in RUN_NUMBERS:
            for case in cases.cases:
                run = run_case(
                    db,
                    case,
                    run_number=run_number,
                    institution_id=institution.id,
                    catalog=catalog,
                    retriever=retriever,
                    estimator_factory=get_dimension_estimator,
                    generator=generator,
                    baseline_model=baseline,
                    limits=limits,
                    b0_top_k=settings.answering_default_top_k,
                )
                db.rollback()
                outcomes.extend(run.outcomes)
                packets.extend(
                    {"digest": packet.digest, **packet.to_dict()} for packet in run.packets.values()
                )
    if oracle_labels is not None:
        dates = {case.case_id: case.reference_date for case in cases.cases}
        for labels in oracle_labels.cases:
            outcomes.append(
                run_oracle(labels, catalog=catalog_payload, reference_date=dates[labels.case_id])
            )

    grouped: dict[tuple[str, Condition], list[CaseOutcome]] = defaultdict(list)
    for outcome in outcomes:
        grouped[(outcome.case_id, outcome.condition)].append(outcome)
    summaries: dict[Condition, dict[str, Any]] = defaultdict(dict)
    for (case_id, condition), items in grouped.items():
        summaries[condition][case_id] = summarize(items)

    metrics: dict[str, Any] = {"status": "not_computed_without_adjudication"}
    if oracle_labels is not None:
        gold = {case.case_id: case for case in oracle_labels.cases}
        admissible: dict[str, frozenset[str]] = {}
        for packet in packets:
            if packet["family"] == "p_e2e" and packet["run_number"] == 1:
                admissible[packet["case_id"]] = frozenset(
                    p["evidence_id"] for p in packet["passages"]
                )
        metrics = {
            condition.value: compute_metrics(by_case, gold, admissible, ratings)
            for condition, by_case in summaries.items()
        }
        metrics["estimation_errors_p_e2e"] = estimation_errors(summaries[Condition.P_E2E], gold)
        metrics["error_attribution_p_e2e"] = [
            attribution.as_dict()
            for attribution in attribute_errors(
                summaries[Condition.P_E2E],
                gold,
                services=catalog_payload["services"],
                catalog_version=catalog_payload["version"],
                reference_dates={case.case_id: case.reference_date for case in cases.cases},
            )
        ]
        metrics["paired_p_e2e_vs_b0"] = paired_comparison(
            summaries[Condition.P_E2E], summaries[Condition.B0], gold
        )

    report = {
        "mode": "formal" if args.formal else "development_trial",
        "status": "avaliação formal" if args.formal else "ensaio de desenvolvimento, não avaliação",
        "set_id": cases.set_id,
        "corpus": cases.corpus,
        "code_commit": args.commit,
        "python_version": platform.python_version(),
        "versions": {
            "policy": POLICY_VERSION,
            "definitions": DEFINITIONS_VERSION,
            "rules": RULES_VERSION,
            "messages": MESSAGE_VERSION,
            "b1_prompt": B1_PROMPT_VERSION,
        },
        "config": EVALUATION_CONFIG,
        "code_artifact_digests": artifact_digests(),
        "packets": packets,
        "outcomes": [outcome.as_dict() for outcome in outcomes],
        "metrics": metrics,
    }
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2, default=str) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
