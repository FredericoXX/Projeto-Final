"""Avalia a política congelada no HELD-OUT, uma única vez (D4.8.2c).

Uso (a partir de ``backend/``):

    python -m scripts.evaluate_dense_admission_heldout \
        --protocol ../docs/evaluation/dense-admission-protocol-v1.json \
        --split ../docs/evaluation/dense-admission-split-v1.json \
        --dataset ../docs/evaluation/dense-admission-dataset-v1.json \
        --calibration ../docs/evaluation/dense-admission-calibration-v1.json \
        --frozen-vectors ../docs/evaluation/dense-admission-frozen-vectors-v1.json \
        --binding ../storage/pilot-corpus/S1-identifier-binding.json \
        --output ../docs/evaluation/dense-admission-heldout-v1.json \
        [--overwrite]

**Este comando não escolhe nada.** Não tem espaço de parâmetros, não avalia
candidatas e não tem critério de seleção: lê a política que a D4.8.2b congelou e
aplica-a. É a diferença entre medir generalização e fazer uma segunda
calibração com outro nome.

O que é verificado antes de medir
---------------------------------

- que o protocolo não foi alterado depois de pré-registado;
- que o conjunto final é **exatamente** o que o manifesto selou, comparando os
  identificadores e recalculando o ``labels_digest`` — se um rótulo tivesse
  mudado no intervalo, o digest mudava;
- que a calibração declara a política congelada e que os seus próprios digests
  fecham;
- que o índice vetorial é o pré-registado.

A comparação com R0 é obrigatória e corre sempre, seja qual for a decisão: sem
o controlo, «a política melhorou» não tem contra o quê ser medido.
"""

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from app.embeddings.base import EmbeddingIdentity
from app.evaluation.dense_admission import (
    ANSWERABLE,
    HELD_OUT,
    NO_EVIDENCE,
    RULE_R0,
    AdmissionPolicy,
    alternating_split_assignments,
    artefact_digests,
    evaluate_policy,
    frozen_vectors_digest,
    heldout_labels_digest,
    question_dataset_digest,
    questions_of_split,
    scenario_digest,
)
from app.evaluation.dense_admission_vectors import verify_frozen_vector_artefact
from scripts.calibrate_dense_admission import (
    retrieve_signals,
    verify_protocol_integrity,
    verify_split_integrity,
)
from scripts.evaluate_retrieval_experiment import (
    EXIT_BASELINE_MISMATCH,
    EXIT_OK,
    EXIT_OUTPUT_EXISTS,
    ExperimentError,
    _load_json,
)

HELDOUT_VERSION: Final = "d4.8.2c-heldout-1"

DECISION_A: Final = "A_GENERALISED"
DECISION_B: Final = "B_DID_NOT_GENERALISE"
DECISION_C: Final = "C_INSUFFICIENT_EVIDENCE"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--split", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--calibration", type=Path, required=True)
    parser.add_argument("--frozen-vectors", type=Path, required=True)
    parser.add_argument("--binding", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return _run(args)
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
    dataset = _load_json(args.dataset)
    calibration = _load_json(args.calibration)
    frozen = _load_json(args.frozen_vectors)
    binding = _load_json(args.binding)

    verify_protocol_integrity(protocol)
    verify_split_integrity(split, protocol)
    verify_calibration_integrity(calibration, protocol, split)

    verify_dataset_integrity(dataset, split, protocol)

    assignments = dict(dataset["split_rule"]["assignments"])
    questions = questions_of_split(dataset["questions"], assignments, HELD_OUT)
    manifest = split["heldout_manifest"]
    verify_sealed_set(questions, manifest)

    identity = EmbeddingIdentity(**frozen["embedding"])
    full_vector_problems = verify_frozen_vector_artefact(
        frozen,
        dataset["questions"],
        identity,
        expected_digest=str(protocol["frozen_vectors_digest"]),
    )
    if full_vector_problems:
        raise ExperimentError(
            "the global frozen-vector artefact is invalid: "
            + "; ".join(full_vector_problems),
            EXIT_BASELINE_MISMATCH,
        )
    if frozen_vectors_digest(frozen["vectors"]) != split["frozen_vectors_digest"]:
        raise ExperimentError(
            "the global frozen vectors do not match the sealed split",
            EXIT_BASELINE_MISMATCH,
        )

    held_ids = {str(question["question_id"]) for question in questions}
    held_vectors = [v for v in frozen["vectors"] if str(v["question_id"]) in held_ids]
    problems = verify_frozen_vector_artefact(
        {
            "vectors": held_vectors,
            "heldout_vectors_digest": frozen_vectors_digest(held_vectors),
        },
        questions,
        identity,
        digest_field="heldout_vectors_digest",
    )
    if problems:
        raise ExperimentError(
            "the frozen vectors do not cover the held-out set: " + "; ".join(problems),
            EXIT_BASELINE_MISMATCH,
        )

    signals, index_digest, indexed_vectors = retrieve_signals(
        questions, held_vectors, identity, binding, protocol
    )

    frozen_policy = AdmissionPolicy(
        rule=str(calibration["selected_policy"]["rule"]),
        min_top1=calibration["selected_policy"]["min_top1"],
        min_margin=calibration["selected_policy"]["min_margin"],
    )
    control = AdmissionPolicy(rule=RULE_R0)

    selected_outcomes, selected_metrics = evaluate_policy(frozen_policy, signals)
    _, control_metrics = evaluate_policy(control, signals)

    dev_admission = calibration["selected_policy_metrics"]["admission"]
    decision = decide_generalisation(
        protocol=protocol,
        dev_admission=dev_admission,
        heldout_admission=selected_metrics["admission"],
        policy=frozen_policy,
    )

    payload: dict[str, Any] = {
        "schema_version": "1",
        "contract": "dense_admission_heldout",
        "phase": "D4.8.2c",
        "heldout_version": HELDOUT_VERSION,
        "split_scope": HELD_OUT,
        "scope_note": (
            "Avaliacao unica da politica congelada sobre o conjunto final. O comando "
            "nao tem espaco de parametros nem criterio de selecao: aplica a politica "
            "que a D4.8.2b escolheu em DEV e compara-a com o controlo R0. Nao houve "
            "recalibracao, e o resultado - qualquer que fosse - e o resultado."
        ),
        "protocol_version": protocol["protocol_version"],
        "protocol_digest": protocol["protocol_digest"],
        "dataset_version": dataset["dataset_version"],
        "dataset_questions_digest": protocol["dataset_questions_digest"],
        "scenario_digest": protocol["scenario_digest"],
        "split_version": split["split_version"],
        "split_digest": split["split_digest"],
        "heldout_manifest_digest": split["heldout_manifest_digest"],
        "heldout_labels_digest": heldout_labels_digest(questions),
        "sealed_set_verified": True,
        "calibration_result_digest": calibration["result_digest"],
        "frozen_policy": frozen_policy.as_dict(),
        "questions_evaluated": len(questions),
        "questions_by_label": {
            ANSWERABLE: sum(1 for q in questions if q["label"] == ANSWERABLE),
            NO_EVIDENCE: sum(1 for q in questions if q["label"] == NO_EVIDENCE),
        },
        "retrieval": {
            "condition": calibration["retrieval"]["condition"],
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
        "decisions": {
            outcome.question_id: outcome.decision for outcome in selected_outcomes
        },
        "frozen_policy_metrics": selected_metrics,
        "control_metrics": control_metrics,
        "control_comparison": _comparison(control_metrics, selected_metrics),
        "dev_versus_heldout": {
            "dev": {
                "correct_abstention_rate": dev_admission["correct_abstention_rate"],
                "false_abstention_rate": dev_admission["false_abstention_rate"],
                "coverage": dev_admission["coverage"],
                "risk": dev_admission["risk"],
            },
            "heldout": {
                "correct_abstention_rate": selected_metrics["admission"][
                    "correct_abstention_rate"
                ],
                "false_abstention_rate": selected_metrics["admission"][
                    "false_abstention_rate"
                ],
                "coverage": selected_metrics["admission"]["coverage"],
                "risk": selected_metrics["admission"]["risk"],
            },
        },
        "decision": decision,
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

    admission = selected_metrics["admission"]
    control_admission = control_metrics["admission"]
    print(f"perguntas HELD-OUT         : {len(questions)}")
    print(f"politica congelada         : {frozen_policy.as_dict()}")
    print(f"correct_abstention_rate    : {admission['correct_abstention_rate']} "
          f"(DEV {dev_admission['correct_abstention_rate']})")
    print(f"false_abstention_rate      : {admission['false_abstention_rate']} "
          f"(DEV {dev_admission['false_abstention_rate']})")
    print(f"coverage                   : {admission['coverage']} "
          f"(R0 {control_admission['coverage']})")
    print(f"risk                       : {admission['risk']} "
          f"(R0 {control_admission['risk']})")
    print(f"decisao                    : {decision['decision']}")
    print(f"result_digest              : {result_digest}")
    print(f"execution_digest           : {execution_digest}")
    print(f"written                    : {args.output}")
    return EXIT_OK


def verify_calibration_integrity(
    calibration: Mapping[str, Any],
    protocol: Mapping[str, Any],
    split: Mapping[str, Any],
) -> None:
    """A política tem de vir de uma calibração fechada e sobre este protocolo."""
    if not calibration.get("policy_frozen"):
        raise ExperimentError(
            "the calibration artefact does not declare the policy frozen",
            EXIT_BASELINE_MISMATCH,
        )
    result_digest, execution_digest = artefact_digests(calibration)
    if result_digest != calibration.get("result_digest"):
        raise ExperimentError(
            "the calibration artefact does not match its own result_digest",
            EXIT_BASELINE_MISMATCH,
        )
    if execution_digest != calibration.get("execution_digest"):
        raise ExperimentError(
            "the calibration artefact does not match its own execution_digest",
            EXIT_BASELINE_MISMATCH,
        )
    if calibration.get("protocol_digest") != protocol.get("protocol_digest"):
        raise ExperimentError(
            "the calibration was run against a different protocol",
            EXIT_BASELINE_MISMATCH,
        )
    if calibration.get("heldout_manifest_digest") != split.get(
        "heldout_manifest_digest"
    ):
        raise ExperimentError(
            "the calibration and the split refer to different sealed sets",
            EXIT_BASELINE_MISMATCH,
        )
    bindings = {
        "dataset_version": calibration.get("dataset_version"),
        "dataset_questions_digest": calibration.get("dataset_questions_digest"),
        "scenario_digest": calibration.get("scenario_digest"),
        "split_version": calibration.get("split_version"),
        "split_digest": calibration.get("split_digest"),
        "dev_questions_digest": calibration.get("dev_questions_digest"),
        "dev_vectors_digest": calibration.get("dev_vectors_digest"),
        "frozen_vectors_digest": calibration.get("retrieval", {}).get(
            "frozen_vectors_digest"
        ),
    }
    mismatched = [
        field
        for field, value in bindings.items()
        if value != protocol.get(field)
    ]
    if mismatched:
        raise ExperimentError(
            "the calibration does not carry the complete sealed identity: "
            + ", ".join(mismatched),
            EXIT_BASELINE_MISMATCH,
        )


def verify_dataset_integrity(
    dataset: Mapping[str, Any],
    split: Mapping[str, Any],
    protocol: Mapping[str, Any],
) -> None:
    """Reconstrói no held-out a identidade e o algoritmo do dataset selado."""
    assignments = dict(dataset["split_rule"]["assignments"])
    expected_assignments = alternating_split_assignments(dataset["scenarios"])
    checks = {
        "dataset_version": dataset.get("dataset_version"),
        "dataset_questions_digest": question_dataset_digest(dataset["questions"]),
        "scenario_digest": scenario_digest(dataset["scenarios"]),
        "split_version": dataset["split_rule"].get("split_version"),
    }
    problems = [
        f"{field}: dataset {value} != split {split.get(field)}"
        for field, value in checks.items()
        if value != split.get(field) or value != protocol.get(field)
    ]
    if assignments != split.get("assignments"):
        problems.append("dataset assignments differ from the sealed split")
    if assignments != expected_assignments:
        problems.append("assignments do not match the declared alternating algorithm")
    if dataset["split_rule"].get("rule") != split.get("rule"):
        problems.append("dataset and split declare different split algorithms")
    if problems:
        raise ExperimentError(
            "the dataset is not the one that was sealed: " + "; ".join(problems),
            EXIT_BASELINE_MISMATCH,
        )


def verify_sealed_set(
    questions: Sequence[Mapping[str, Any]], manifest: Mapping[str, Any]
) -> None:
    """O conjunto final é o que foi selado — identificadores e rótulos.

    Comparar identificadores apanha uma pergunta acrescentada ou removida;
    recalcular o ``labels_digest`` apanha o caso mais difícil de ver, que é o
    rótulo ou o julgamento alterado depois de a calibração ter corrido. Sem esta
    segunda verificação, «não mexi no HELD-OUT» seria uma afirmação sobre a
    memória de quem conduziu a experiência.
    """
    sealed_ids = [str(qid) for qid in manifest["question_ids"]]
    actual_ids = [str(question["question_id"]) for question in questions]
    if sorted(sealed_ids) != sorted(actual_ids):
        raise ExperimentError(
            "the held-out set is not the one that was sealed: "
            f"sealed {len(sealed_ids)} questions, found {len(actual_ids)}",
            EXIT_BASELINE_MISMATCH,
        )
    recomputed = heldout_labels_digest(questions)
    if recomputed != manifest["labels_digest"]:
        raise ExperimentError(
            "the held-out labels changed after sealing: "
            f"{recomputed} != {manifest['labels_digest']}",
            EXIT_BASELINE_MISMATCH,
        )


def decide_generalisation(
    *,
    protocol: Mapping[str, Any],
    dev_admission: Mapping[str, Any],
    heldout_admission: Mapping[str, Any],
    policy: AdmissionPolicy,
) -> dict[str, Any]:
    """Aplica a regra de decisão pré-registada. Não interpreta.

    Devolve também o cálculo que a sustenta, porque uma decisão A/B/C sem os
    números que a produziram não é verificável por quem lê.
    """
    rule = protocol["heldout_decision_rule"]
    floor = float(rule["generalisation_retention_floor"])
    budget = float(protocol["selection"]["max_false_abstention_rate"])
    dev_correct = dev_admission["correct_abstention_rate"] or 0.0
    held_correct = heldout_admission["correct_abstention_rate"] or 0.0
    held_false = heldout_admission["false_abstention_rate"] or 0.0
    retained = held_correct / dev_correct if dev_correct else None

    if policy.rule == RULE_R0:
        decision = DECISION_C
        rationale = (
            "a calibracao selecionou R0: nao ha politica de abstencao para testar"
        )
    elif held_false > budget:
        decision = DECISION_B
        rationale = (
            f"false_abstention_rate {held_false} excede o orcamento pre-registado {budget}"
        )
    elif held_correct <= 0.0:
        decision = DECISION_B
        rationale = "a politica nao se absteve em nenhuma pergunta sem evidencia"
    elif retained is not None and retained < floor:
        decision = DECISION_B
        rationale = (
            f"reteve {round(retained, 6)} do beneficio medido em DEV, abaixo do minimo "
            f"pre-registado {floor}"
        )
    else:
        decision = DECISION_A
        rationale = (
            f"false_abstention_rate {held_false} dentro do orcamento {budget} e "
            f"correct_abstention_rate {held_correct} retem {round(retained or 0.0, 6)} "
            f"do valor medido em DEV"
        )

    return {
        "decision": decision,
        "rationale": rationale,
        "max_false_abstention_rate": budget,
        "generalisation_retention_floor": floor,
        "dev_correct_abstention_rate": dev_correct,
        "heldout_correct_abstention_rate": held_correct,
        "heldout_false_abstention_rate": held_false,
        "retained_fraction": None if retained is None else round(retained, 6),
        "decision_rule_source": "dense-admission-protocol-v1.json#heldout_decision_rule",
    }


def _comparison(
    control: Mapping[str, Any], selected: Mapping[str, Any]
) -> dict[str, Any]:
    """R0 contra a política, campo a campo, sem escolher um vencedor."""
    fields = (
        "coverage",
        "coverage_answerable",
        "risk",
        "correct_abstention_rate",
        "false_abstention_rate",
        "answerable_with_relevant_preserved",
    )
    return {
        "admission": {
            field: {
                "R0": control["admission"][field],
                "selected": selected["admission"][field],
            }
            for field in fields
        },
        "retrieval": {
            field: {
                "R0": control["retrieval"][field],
                "selected": selected["retrieval"][field],
            }
            for field in (
                "measured_questions",
                "mrr",
                "returned_total",
                "grade0_share",
                "grade2_share",
                "mean_irrelevant_per_admitted_question",
            )
        },
        "note": (
            "A leitura honesta desta tabela e uma troca, nao uma melhoria: a "
            "politica reduz o risco e a exposicao a ruido baixando a cobertura. "
            "Qual dos lados vale mais e uma decisao de produto, nao um resultado "
            "de medicao."
        ),
    }


if __name__ == "__main__":
    sys.exit(main())
