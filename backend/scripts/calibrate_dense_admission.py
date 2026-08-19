"""Calibra a política de admissão densa **exclusivamente em DEV** (D4.8.2b).

Uso (a partir de ``backend/``):

    python -m scripts.calibrate_dense_admission \
        --protocol ../docs/evaluation/dense-admission-protocol-v1.json \
        --split ../docs/evaluation/dense-admission-split-v1.json \
        --dev ../docs/evaluation/dense-admission-dev-v1.json \
        --dev-vectors ../docs/evaluation/dense-admission-dev-vectors-v1.json \
        --binding ../storage/pilot-corpus/S1-identifier-binding.json \
        --output ../docs/evaluation/dense-admission-calibration-v1.json \
        [--overwrite]

**Não existe um argumento ``--dataset``.** Não é uma omissão: é a barreira. Este
comando não sabe abrir o dataset completo, e se lhe apontarem o dataset no lugar
da projeção DEV, :func:`load_calibration_questions` levanta ``LeakageError`` em
vez de calibrar sobre tudo. A promessa da fase — «a calibração não consegue
carregar os rótulos do HELD-OUT» — tem de ser uma propriedade do programa e não
uma intenção de quem o corre.

O que este comando decide, e o que não decide
---------------------------------------------

Avalia as 21 políticas candidatas derivadas do espaço pré-registado, aplica o
critério de seleção pré-registado e **congela** o resultado. Não escolhe o
critério, que já estava fixado; não vê o HELD-OUT; e não volta atrás se o
vencedor for R0 — que é um desfecho previsto e significa que nada foi calibrado.

Porque é que a recuperação corre aqui
-------------------------------------

Os sinais (``top1``, ``top2``) são similaridades produzidas pelo retriever sobre
o índice real. Lê-los de um ficheiro intermédio pouparia uma ligação à base de
dados e introduziria a possibilidade de calibrar sobre números que já não
correspondem ao índice. O modelo de embeddings é
:class:`FrozenQuestionEmbeddings` restrito às perguntas de DEV: pedir o
embedding de uma pergunta selada levanta erro em vez de o produzir.
"""

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Final
from uuid import UUID

from sqlalchemy.orm import Session

from app.documents.retrievability import RetrievabilityContext
from app.embeddings.base import EmbeddingIdentity
from app.evaluation.dense_admission import (
    ANSWERABLE,
    DEV,
    NO_EVIDENCE,
    AdmissionPolicy,
    LeakageError,
    artefact_digests,
    candidate_policies,
    candidate_rules_digest,
    evaluate_policy,
    heldout_manifest_digest,
    load_calibration_questions,
    parameter_space_digest,
    protocol_digest,
    question_dataset_digest,
    select_policy,
    selection_policy_digest,
    split_digest,
)
from app.evaluation.dense_admission_vectors import (
    FrozenQuestionEmbeddings,
    verify_frozen_vector_artefact,
)
from app.evaluation.dense_baseline import CONDITION_DENSE
from app.retrieval.base import RetrievalContext
from app.retrieval.dense import PostgresDenseRetriever
from scripts.evaluate_dense_baseline import (
    embedding_index_digest,
    evaluate_condition,
    verify_index_identity,
)
from scripts.evaluate_retrieval_experiment import (
    EXIT_BASELINE_MISMATCH,
    EXIT_OK,
    EXIT_OUTPUT_EXISTS,
    EXIT_SNAPSHOT_MISMATCH,
    ExperimentError,
    SessionLocalFactory,
    _load_json,
)
from scripts.seal_dense_admission_split import DEV_VECTORS_CONTRACT

CALIBRATION_VERSION: Final = "d4.8.2b-calibration-1"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--split", type=Path, required=True)
    parser.add_argument("--dev", type=Path, required=True)
    parser.add_argument("--dev-vectors", type=Path, required=True)
    parser.add_argument("--binding", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return _run(args)
    except LeakageError as error:
        print(f"error: {error}", file=sys.stderr)
        return EXIT_BASELINE_MISMATCH
    except ExperimentError as error:
        print(f"error: {error}", file=sys.stderr)
        return error.exit_code


def _run(args: argparse.Namespace) -> int:
    if args.output.exists() and not args.overwrite:
        raise ExperimentError(
            f"refusing to overwrite {args.output} without --overwrite", EXIT_OUTPUT_EXISTS
        )

    protocol = _load_json(args.protocol)
    split = _load_json(args.split)
    dev_payload = _load_json(args.dev)
    frozen = _load_json(args.dev_vectors)
    binding = _load_json(args.binding)

    verify_protocol_integrity(protocol)
    verify_split_integrity(split, protocol)

    manifest = split["heldout_manifest"]
    questions = load_calibration_questions(dev_payload, manifest)
    if question_dataset_digest(questions) != dev_payload["dev_questions_digest"]:
        raise ExperimentError(
            "the DEV projection does not match its own dev_questions_digest",
            EXIT_BASELINE_MISMATCH,
        )
    if dev_payload["dev_questions_digest"] != split["dev"]["questions_digest"]:
        raise ExperimentError(
            "the DEV projection and the sealed split disagree on the DEV questions",
            EXIT_BASELINE_MISMATCH,
        )

    if frozen.get("contract") != DEV_VECTORS_CONTRACT or frozen.get("split_scope") != DEV:
        raise LeakageError("calibration accepts only the sealed DEV vector projection")
    if frozen.get("frozen_vectors_digest") != split.get("frozen_vectors_digest"):
        raise ExperimentError(
            "the DEV vector projection and split refer to different global vectors",
            EXIT_BASELINE_MISMATCH,
        )
    if frozen.get("frozen_vectors_digest") != protocol.get("frozen_vectors_digest"):
        raise ExperimentError(
            "the DEV vector projection and protocol refer to different global vectors",
            EXIT_BASELINE_MISMATCH,
        )

    identity = EmbeddingIdentity(**frozen["embedding"])
    dev_vectors = frozen["vectors"]
    problems = verify_frozen_vector_artefact(
        frozen,
        questions,
        identity,
        digest_field="dev_vectors_digest",
        expected_digest=str(protocol["dev_vectors_digest"]),
    )
    if problems:
        raise ExperimentError(
            "the DEV frozen-vector projection is invalid: " + "; ".join(problems),
            EXIT_BASELINE_MISMATCH,
        )

    signals, index_digest, indexed_vectors = retrieve_signals(
        questions, dev_vectors, identity, binding, protocol
    )

    space = protocol["parameter_space"]
    policies = candidate_policies(space)
    if len(policies) != protocol["candidate_policies"]["total"]:
        raise ExperimentError(
            f"the protocol announces {protocol['candidate_policies']['total']} candidate "
            f"policies and the parameter space yields {len(policies)}",
            EXIT_BASELINE_MISMATCH,
        )

    evaluations = [_evaluate(policy, signals) for policy in policies]
    selection = select_policy(
        evaluations, float(protocol["selection"]["max_false_abstention_rate"])
    )
    if selection["selected_policy"] is None:
        raise ExperimentError(
            "no candidate policy satisfied the pre-registered budget, not even R0; "
            "the budget or the control is wrong",
            EXIT_BASELINE_MISMATCH,
        )

    selected = AdmissionPolicy(
        rule=str(selection["selected_policy"]["rule"]),
        min_top1=selection["selected_policy"]["min_top1"],
        min_margin=selection["selected_policy"]["min_margin"],
    )
    selected_entry = next(
        entry for entry in evaluations if entry["policy"] == selected.as_dict()
    )

    payload: dict[str, Any] = {
        "schema_version": "1",
        "contract": "dense_admission_calibration",
        "phase": "D4.8.2b",
        "calibration_version": CALIBRATION_VERSION,
        "split_scope": DEV,
        "scope_note": (
            "Calibracao feita exclusivamente sobre DEV. O comando nao tem argumento "
            "para o dataset completo e a sua unica porta de entrada de dados recusa "
            "qualquer payload que nao seja a projecao DEV. Nenhuma metrica deste "
            "artefacto foi calculada sobre o HELD-OUT."
        ),
        "protocol_version": protocol["protocol_version"],
        "protocol_digest": protocol["protocol_digest"],
        "dataset_version": dev_payload["dataset_version"],
        "dataset_questions_digest": protocol["dataset_questions_digest"],
        "scenario_digest": protocol["scenario_digest"],
        "split_version": dev_payload["split_version"],
        "split_digest": split["split_digest"],
        "dev_vectors_digest": frozen["dev_vectors_digest"],
        "heldout_manifest_digest": split["heldout_manifest_digest"],
        "heldout_labels_digest": manifest["labels_digest"],
        "heldout_untouched_note": (
            "Os dois digests do HELD-OUT ficam registados aqui sem que um unico "
            "rotulo selado tenha sido lido: sao copiados do split e servem para a "
            "D4.8.2c provar que o conjunto final nao mudou no intervalo."
        ),
        "dev_questions_digest": dev_payload["dev_questions_digest"],
        "questions_evaluated": len(questions),
        "questions_by_label": {
            ANSWERABLE: sum(1 for q in questions if q["label"] == ANSWERABLE),
            NO_EVIDENCE: sum(1 for q in questions if q["label"] == NO_EVIDENCE),
        },
        "retrieval": {
            "condition": CONDITION_DENSE,
            "language": protocol["retrieval"]["language"],
            "top_k": protocol["retrieval"]["top_k"],
            "official_only": protocol["retrieval"]["official_only"],
            "reference_date": protocol["retrieval"]["reference_date"],
            "snapshot_id": protocol["retrieval"]["snapshot_id"],
            "index_digest": index_digest,
            "indexed_vectors": indexed_vectors,
            "frozen_vectors_digest": protocol["retrieval"]["frozen_vectors_digest"],
            "embedding": dict(frozen["embedding"]),
        },
        "question_signals": signals,
        "policies": evaluations,
        "selection": selection,
        "selected_policy": selected.as_dict(),
        "selected_policy_metrics": {
            "admission": selected_entry["admission"],
            "retrieval": selected_entry["retrieval"],
        },
        "policy_frozen": True,
        "policy_frozen_note": (
            "A politica esta congelada. A D4.8.2c aplica-a tal e qual ao HELD-OUT e "
            "nao recalibra: qualquer reajuste depois de ver o conjunto final "
            "transformaria a avaliacao final noutra calibracao, e a fase deixaria de "
            "medir generalizacao."
        ),
        "digest_algorithm": "sha256",
        "result_digest_scope": "decision_relevant_fields",
        "execution_digest_scope": "full_payload",
    }

    result_digest, execution_digest = artefact_digests(payload)
    payload["result_digest"] = result_digest
    payload["execution_digest"] = execution_digest
    payload["executed_at"] = datetime.now(UTC).isoformat()

    args.output.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    admission = selected_entry["admission"]
    print(f"perguntas DEV              : {len(questions)}")
    print(f"politicas avaliadas        : {len(evaluations)}")
    print(f"elegiveis (orcamento)      : {selection['eligible']}")
    print(f"politica selecionada       : {selected.as_dict()}")
    print(f"correct_abstention_rate    : {admission['correct_abstention_rate']}")
    print(f"false_abstention_rate      : {admission['false_abstention_rate']}")
    print(f"coverage                   : {admission['coverage']}")
    print(f"risk                       : {admission['risk']}")
    print(f"result_digest              : {result_digest}")
    print(f"execution_digest           : {execution_digest}")
    print(f"written                    : {args.output}")
    return EXIT_OK


def verify_protocol_integrity(protocol: Mapping[str, Any]) -> None:
    """Os digests do protocolo, recalculados antes de o usar.

    Um protocolo que se possa editar depois de pré-registado não é um
    compromisso. Recalcular aqui é o que torna a pré-registação verificável em
    vez de declarativa.
    """
    rules = [str(rule["rule"]) for rule in protocol["candidate_rules"]]
    expected = {
        "candidate_rules_digest": candidate_rules_digest(rules),
        "parameter_space_digest": parameter_space_digest(protocol["parameter_space"]),
        "selection_policy_digest": selection_policy_digest(protocol["selection"]),
        "protocol_digest": protocol_digest(protocol),
    }
    mismatched = [
        f"{field}: artefact {protocol.get(field)} != recomputed {value}"
        for field, value in expected.items()
        if protocol.get(field) != value
    ]
    if mismatched:
        raise ExperimentError(
            "the protocol was modified after pre-registration: " + "; ".join(mismatched),
            EXIT_BASELINE_MISMATCH,
        )


def verify_split_integrity(
    split: Mapping[str, Any], protocol: Mapping[str, Any]
) -> None:
    """O manifesto selado e o protocolo têm de descrever a mesma experiência."""
    manifest = split["heldout_manifest"]
    if heldout_manifest_digest(manifest) != split["heldout_manifest_digest"]:
        raise ExperimentError(
            "the sealed held-out manifest does not match its digest",
            EXIT_BASELINE_MISMATCH,
        )
    recomputed_split_digest = split_digest(
        split["assignments"], str(split["split_version"])
    )
    if recomputed_split_digest != split.get("split_digest"):
        raise ExperimentError(
            "the split assignments do not match split_digest",
            EXIT_BASELINE_MISMATCH,
        )

    bindings = {
        "dataset_version": split.get("dataset_version"),
        "dataset_questions_digest": split.get("dataset_questions_digest"),
        "scenario_digest": split.get("scenario_digest"),
        "split_version": split.get("split_version"),
        "split_digest": split.get("split_digest"),
        "dev_questions_digest": split.get("dev", {}).get("questions_digest"),
        "dev_vectors_digest": split.get("dev", {}).get("vectors_digest"),
        "heldout_manifest_digest": split.get("heldout_manifest_digest"),
        "frozen_vectors_digest": split.get("frozen_vectors_digest"),
    }
    mismatched = [
        f"{field}: split {value} != protocol {protocol.get(field)}"
        for field, value in bindings.items()
        if value != protocol.get(field)
    ]
    if mismatched:
        raise ExperimentError(
            "the split and protocol do not bind the same sealed identity: "
            + "; ".join(mismatched),
            EXIT_BASELINE_MISMATCH,
        )


def retrieve_signals(
    questions: Sequence[Mapping[str, Any]],
    vectors: Sequence[Mapping[str, Any]],
    identity: EmbeddingIdentity,
    binding: Mapping[str, Any],
    protocol: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], str, int]:
    """Corre a condição densa e devolve os sinais por pergunta.

    O índice é verificado antes de qualquer medição e o seu digest é comparado
    com o do protocolo: calibrar sobre um índice diferente do pré-registado
    produziria números válidos para outra experiência.
    """
    document_index = {
        item["corpus_item_id"]: item["document_id"]
        for item in binding["items"]
        if item.get("in_corpus")
    }
    model = FrozenQuestionEmbeddings(vectors, identity)
    retriever = PostgresDenseRetriever(model)
    retrieval = protocol["retrieval"]

    signals: list[dict[str, Any]] = []
    with SessionLocalFactory() as db:
        retrievability = RetrievabilityContext(
            institution_id=UUID(binding["institution_id"]),
            language=str(retrieval["language"]),
            reference_date=date.fromisoformat(retrieval["reference_date"]),
            official_only=bool(retrieval["official_only"]),
        )
        verify_index_identity(db, context=retrievability, identity=identity)
        index_digest, indexed_vectors = embedding_index_digest(
            db,
            context=retrievability,
            identity=identity,
            document_index=document_index,
        )
        if index_digest != retrieval["embedding"]["index_digest"]:
            raise ExperimentError(
                "the vector index is not the one the protocol pre-registered: "
                f"{index_digest} != {retrieval['embedding']['index_digest']}",
                EXIT_SNAPSHOT_MISMATCH,
            )

        context = RetrievalContext(
            institution_id=UUID(binding["institution_id"]),
            language=retrieval["language"],
            reference_date=date.fromisoformat(retrieval["reference_date"]),
        )
        for question in questions:
            signals.append(
                _question_signals(
                    db,
                    question,
                    retriever=retriever,
                    document_index=document_index,
                    context=context,
                    top_k=int(retrieval["top_k"]),
                    official_only=bool(retrieval["official_only"]),
                )
            )
    return signals, index_digest, indexed_vectors


def _question_signals(
    db: Session,
    question: Mapping[str, Any],
    *,
    retriever: PostgresDenseRetriever,
    document_index: Mapping[str, str],
    context: RetrievalContext,
    top_k: int,
    official_only: bool,
) -> dict[str, Any]:
    """Sinais e graus de uma pergunta, com o pool de julgamento reconferido.

    Um segmento recuperado sem julgamento é erro e não grau 0: o conjunto foi
    anotado a partir **desta** recuperação, e um resultado por julgar significa
    que o índice ou os vetores já não são os de então. Tratá-lo como
    irrelevante enterraria essa divergência no meio das métricas.
    """
    grades = {
        (str(j["corpus_item_id"]), int(j["chunk_index"])): int(j["relevance"])
        for j in question["judgments"]
    }
    record = evaluate_condition(
        db,
        question,
        condition=CONDITION_DENSE,
        retriever=retriever,
        query=str(question["question"]),
        document_index=document_index,
        grades=grades,
        context=context,
        top_k=top_k,
        official_only=official_only,
    )
    unjudged = [entry for entry in record["ranking"] if not entry["judged"]]
    if unjudged:
        anchors = ", ".join(
            f"{entry['corpus_item_id']}/{entry['chunk_index']}" for entry in unjudged
        )
        raise ExperimentError(
            f"{question['question_id']}: retrieved segments outside the judged pool "
            f"({anchors}); the index no longer matches the annotated set",
            EXIT_BASELINE_MISMATCH,
        )

    scores = [float(entry["score"]) for entry in record["ranking"]]
    top1 = scores[0] if scores else None
    top2 = scores[1] if len(scores) > 1 else None
    return {
        "question_id": str(question["question_id"]),
        "scenario_id": str(question["scenario_id"]),
        "label": str(question["label"]),
        "returned": len(record["ranking"]),
        "top1": top1,
        "top2": top2,
        "margin": None if top1 is None or top2 is None else round(top1 - top2, 6),
        "grades": [int(entry["grade"]) for entry in record["ranking"]],
        "judged_grades": sorted(grades.values(), reverse=True),
        "ranking": [
            {
                "position": entry["position"],
                "corpus_item_id": entry["corpus_item_id"],
                "chunk_index": entry["chunk_index"],
                "grade": entry["grade"],
            }
            for entry in record["ranking"]
        ],
    }


def _evaluate(
    policy: AdmissionPolicy, signals: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    outcomes, metrics = evaluate_policy(policy, signals)
    return {
        "policy": policy.as_dict(),
        "admission": metrics["admission"],
        "retrieval": metrics["retrieval"],
        "decisions": {outcome.question_id: outcome.decision for outcome in outcomes},
    }


if __name__ == "__main__":
    sys.exit(main())
