"""Executor preparado da avaliação da política de decisão v1.7 — a recolha.

Uso (a partir de backend/):

    python -m scripts.run_policy_v1_evaluation --cases CASES.json \\
        --commit SHA --output RELATORIO.json \\
        [--adjudication ADJ.json --freeze-manifest MANIFEST.json] [--formal]

Dois modos:

- **ensaio de desenvolvimento** (omissão): só aceita conjuntos ``policy-v1-dev*``
  — o conjunto reservado nunca é consultado para afinação — e só corre em
  ``ENVIRONMENT`` ``development``/``test``. O relatório é marcado como ensaio,
  não como avaliação.
- **formal** (``--formal``): exige que o ficheiro de casos e a adjudicação
  correspondam a um manifesto de congelamento **completo** (corpus, manifesto,
  rótulos, catálogo, política, esquema, prompts e configuração) e que o
  catálogo ativo e o inventário documental da instituição, lidos da base de
  dados, sejam os congelados. Sem isso, recusa.

O inventário documental é recolhido outra vez antes de escrever o relatório: se
a base mudou durante a execução, o relatório não é escrito.

Corre três execuções numeradas para cada condição com modelo (B0 incluído) e
uma para P-oráculo (só com adjudicação verificada). Os packets de cada execução
são arquivados no relatório, com o respetivo digest. Falhas técnicas e
denominadores ficam explícitos.

A recolha chama os modelos **uma vez**. O relatório (``policy_v1_report_2``,
:mod:`app.evaluation.policy_v1.report`) regista a identidade da recolha, o
estado do Git, a configuração de execução e os digests de todas as entradas. Os
juízos humanos das mensagens (M7) não entram aqui: julgam mensagens que só
existem depois da recolha. Exportam-se com
``scripts.export_policy_v1_message_review`` e aplicam-se, sem novas chamadas aos
modelos, com ``scripts.score_policy_v1_report``. Por isso ``--message-ratings``
é recusado, e um relatório existente nunca é sobrescrito.

Este script **não** cria rótulos e não foi executado como avaliação formal
neste repositório: o corpus P2, a adjudicação e o protocolo não estão
congelados.
"""

import argparse
import json
import re
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.answering.dependencies import get_answer_generator
from app.core.config import MOCK_PROVIDER_ENVIRONMENTS, settings
from app.database.session import SessionLocal
from app.decision.estimators.dependencies import get_dimension_estimator
from app.evaluation.policy_v1.artifacts import (
    catalog_bytes,
    catalog_snapshot,
    config_payload,
    corpus_bytes,
    git_state,
    verify_code_artifacts,
    verify_formal_freeze,
)
from app.evaluation.policy_v1.conditions import CaseOutcome, Limits, run_oracle
from app.evaluation.policy_v1.corpus_inventory import (
    collect_corpus_inventory,
    corpus_inventory_bytes,
)
from app.evaluation.policy_v1.executor import EvaluationCaseSet, run_case
from app.evaluation.policy_v1.freeze import (
    FreezeError,
    canonical_bytes,
    sha256,
    verify_artifact,
)
from app.evaluation.policy_v1.labels import LabelSet, label_set_bytes, verified_adjudication
from app.evaluation.policy_v1.packets import EvidencePacket
from app.evaluation.policy_v1.protocol import (
    validate_formal_annotations,
    verify_same_case_set,
)
from app.evaluation.policy_v1.report import (
    build_collection_report,
    compute_report_metrics,
    report_bytes,
    summarize_outcomes,
)
from app.evaluation.policy_v1.runs import RUN_NUMBERS
from app.models.decision_catalog import InstitutionDecisionCatalog
from app.models.institution import Institution
from app.retrieval.dependencies import get_retriever

COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
EXIT_USAGE = 2
EXIT_INVALID = 3
EXIT_NOT_FROZEN = 5
EXIT_REFUSED = 6


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="run_policy_v1_evaluation")
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--adjudication", type=Path)
    parser.add_argument("--freeze-manifest", type=Path)
    # Mantido só para recusar: os juízos M7 aplicam-se offline ao relatório
    # arquivado (scripts.score_policy_v1_report), nunca a uma nova recolha.
    parser.add_argument("--message-ratings", type=Path)
    parser.add_argument("--formal", action="store_true")
    args = parser.parse_args(argv)
    if not COMMIT_PATTERN.match(args.commit):
        sys.stderr.write("--commit must be a full 40-character SHA\n")
        return EXIT_USAGE
    if args.message_ratings is not None:
        sys.stderr.write(
            "message ratings judge archived messages: apply them offline with "
            "scripts.score_policy_v1_report\n"
        )
        return EXIT_REFUSED
    if args.output.exists():
        # Um relatório arquivado é a única cópia das respostas recolhidas.
        sys.stderr.write("refusing to overwrite an existing report\n")
        return EXIT_USAGE

    raw_cases = args.cases.read_bytes()
    cases = EvaluationCaseSet.model_validate(json.loads(raw_cases))
    raw_manifest = args.freeze_manifest.read_bytes() if args.freeze_manifest else None
    manifest = json.loads(raw_manifest) if raw_manifest is not None else None
    raw_adjudication = args.adjudication.read_bytes() if args.adjudication else None
    adjudication = (
        LabelSet.model_validate(json.loads(raw_adjudication))
        if raw_adjudication is not None
        else None
    )
    if adjudication is not None:
        try:
            # Antes de abrir a base e de qualquer chamada aos modelos.
            verify_same_case_set(cases, adjudication)
        except FreezeError as exc:
            sys.stderr.write(f"{exc}\n")
            return EXIT_INVALID

    if args.formal:
        if manifest is None or adjudication is None:
            sys.stderr.write("formal evaluation requires --freeze-manifest and --adjudication\n")
            return EXIT_NOT_FROZEN
        # A verificação completa só é possível depois de ler da base o catálogo
        # ativo e o inventário documental: corre logo a seguir, antes de
        # qualquer caso.
    else:
        if settings.environment not in MOCK_PROVIDER_ENVIRONMENTS:
            sys.stderr.write("development trials only run in development/test environments\n")
            return EXIT_REFUSED
        if not cases.set_id.startswith("policy-v1-dev"):
            # O conjunto reservado nunca é usado para afinação.
            sys.stderr.write("development trials only accept policy-v1-dev case sets\n")
            return EXIT_REFUSED

    oracle_labels = None
    limits = Limits(settings.answering_max_context_chars, settings.answering_max_answer_chars)
    outcomes: list[CaseOutcome] = []
    packets: list[EvidencePacket] = []
    packets_by_digest: dict[str, EvidencePacket] = {}
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
        inventory = corpus_inventory_bytes(collect_corpus_inventory(db, institution.id))
        head, clean = git_state(REPOSITORY_ROOT)
        try:
            # Identidade de cada entrada da recolha, para a reanálise offline.
            inputs = {
                "cases": {
                    "file_sha256": sha256(raw_cases),
                    "frozen_sha256": sha256(corpus_bytes(json.loads(raw_cases))),
                },
                "adjudication": None
                if adjudication is None or raw_adjudication is None
                else {
                    "file_sha256": sha256(raw_adjudication),
                    "frozen_sha256": sha256(label_set_bytes(adjudication)),
                },
                "freeze_manifest": None
                if manifest is None or raw_manifest is None
                else {
                    "file_sha256": sha256(raw_manifest),
                    "frozen_sha256": sha256(canonical_bytes(manifest)),
                    "code_commit": manifest.get("code_commit"),
                },
                "corpus_inventory": {"frozen_sha256": sha256(inventory)},
                "catalog": {
                    "frozen_sha256": sha256(catalog_bytes(catalog_payload)),
                    "snapshot": catalog_payload,
                },
            }
            if args.formal:
                assert manifest is not None and adjudication is not None
                # Todos os artefactos — os gerados a partir do código, o
                # catálogo ativo e o inventário documental da base —, o commit
                # e a árvore de trabalho.
                verify_formal_freeze(
                    manifest,
                    cases_payload=json.loads(raw_cases),
                    corpus_inventory_payload=json.loads(inventory),
                    adjudication=adjudication,
                    catalog_payload=catalog_payload,
                    commit=args.commit,
                    head_commit=head or "",
                    working_tree_clean=clean,
                )
                validate_formal_annotations(cases.cases, adjudication, json.loads(inventory))
            if adjudication is not None and manifest is not None:
                oracle_labels = verified_adjudication(adjudication, manifest)
                # O P-oráculo usa a política, os casos e o catálogo, e as
                # métricas comparam as condições com uma adjudicação feita
                # sobre o corpus congelado: tudo tem de ser o congelado, também
                # fora do modo formal.
                verify_artifact(manifest, "corpus", corpus_bytes(json.loads(raw_cases)))
                verify_artifact(manifest, "catalog", catalog_bytes(catalog_payload))
                verify_artifact(manifest, "manifest", inventory)
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
                for packet in run.packets.values():
                    packets_by_digest[packet.digest] = packet
                    packets.append(packet)
        # A base não pode ter mudado durante a execução: os packets das três
        # execuções têm de vir do mesmo corpus.
        if corpus_inventory_bytes(collect_corpus_inventory(db, institution.id)) != inventory:
            sys.stderr.write("the document inventory changed during the evaluation\n")
            return EXIT_NOT_FROZEN
    if oracle_labels is not None:
        dates = {case.case_id: case.reference_date for case in cases.cases}
        for labels in oracle_labels.cases:
            outcomes.append(
                run_oracle(labels, catalog=catalog_payload, reference_date=dates[labels.case_id])
            )

    summaries = summarize_outcomes(outcomes)
    metrics: dict[str, Any] = {"status": "not_computed_without_adjudication"}
    if oracle_labels is not None:
        metrics = compute_report_metrics(
            cases.cases,
            summaries,
            {case.case_id: case for case in oracle_labels.cases},
            packets_by_digest,
            catalog_payload,
            ratings=None,
            formal=args.formal,
        )

    report = build_collection_report(
        formal=args.formal,
        cases=cases,
        collection_id=str(uuid.uuid4()),
        collected_at=datetime.now(UTC),
        code_commit=args.commit,
        git=(head, clean),
        runtime=config_payload()["runtime"],
        inputs=inputs,
        packets=packets,
        outcomes=outcomes,
        metrics=metrics,
    )
    # Criação exclusiva: um relatório que entretanto apareça não é sobrescrito.
    with args.output.open("xb") as handle:
        handle.write(report_bytes(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
