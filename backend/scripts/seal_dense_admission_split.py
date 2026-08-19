"""Sela o split da D4.8.2a: escreve o artefacto do split e a projeção DEV.

Uso (a partir de ``backend/``):

    python -m scripts.seal_dense_admission_split \
        --dataset ../docs/evaluation/dense-admission-dataset-v1.json \
        --frozen-vectors ../docs/evaluation/dense-admission-frozen-vectors-v1.json \
        --split-output ../docs/evaluation/dense-admission-split-v1.json \
        --dev-output ../docs/evaluation/dense-admission-dev-v1.json \
        --dev-vectors-output ../docs/evaluation/dense-admission-dev-vectors-v1.json \
        [--overwrite]

Corre **antes** da calibração e mais nenhuma vez. Depois de correr, a política
da D4.8.2b escolhe-se sobre o ficheiro DEV que este comando escreve, e o
conjunto final fica identificado por um manifesto público que não revela um
único rótulo.

Porque é que a projeção DEV é um ficheiro e não um filtro
--------------------------------------------------------

A promessa da fase é que a calibração **não consegue** carregar os rótulos do
HELD-OUT. Um filtro em memória não a cumpre: os rótulos continuariam no
ficheiro que a calibração abre, a um descuido de distância, e a garantia
passaria a depender de ninguém escrever a linha errada. Separar em dois
ficheiros torna a promessa verificável por inspeção — o ficheiro que a
calibração lê não contém as perguntas seladas, e há um teste que o lê como
texto e o confirma.

O dataset completo continua a existir e continua a ser a fonte de verdade da
anotação; é dele que este comando deriva as duas peças, e é ele que a D4.8.2c
volta a abrir depois de a política estar congelada.
"""

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from app.embeddings.base import EmbeddingIdentity
from app.evaluation.dense_admission import (
    ANSWERABLE,
    DEV,
    DEV_PROJECTION_CONTRACT,
    HELD_OUT,
    NO_EVIDENCE,
    LeakageError,
    alternating_split_assignments,
    dev_projection_questions,
    frozen_vectors_digest,
    heldout_manifest,
    heldout_manifest_digest,
    load_calibration_questions,
    question_dataset_digest,
    questions_of_split,
    scenario_digest,
    split_digest,
    verify_dev_projection,
    verify_split_by_scenario,
)
from app.evaluation.dense_admission_vectors import (
    verify_frozen_vector_artefact,
)
from scripts.evaluate_retrieval_experiment import (
    EXIT_BASELINE_MISMATCH,
    EXIT_OK,
    EXIT_OUTPUT_EXISTS,
    ExperimentError,
    _load_json,
)

SEAL_VERSION: Final = "d4.8.2a-seal-1"
MANIFEST_VERSION: Final = "v1"
DEV_VECTORS_CONTRACT: Final = "dense_admission_dev_frozen_vectors"
SPLIT_RULE: Final = "stratified_alternating_over_sorted_scenario_id"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--frozen-vectors", type=Path, required=True)
    parser.add_argument("--split-output", type=Path, required=True)
    parser.add_argument("--dev-output", type=Path, required=True)
    parser.add_argument("--dev-vectors-output", type=Path, required=True)
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
    for output in (args.split_output, args.dev_output, args.dev_vectors_output):
        if output.exists() and not args.overwrite:
            raise ExperimentError(
                f"refusing to overwrite {output} without --overwrite", EXIT_OUTPUT_EXISTS
            )

    dataset = _load_json(args.dataset)
    frozen = _load_json(args.frozen_vectors)
    questions = dataset["questions"]
    scenarios = dataset["scenarios"]
    assignments = dict(dataset["split_rule"]["assignments"])

    if dataset["split_rule"]["rule"] != SPLIT_RULE:
        raise ExperimentError(
            f"unsupported split rule {dataset['split_rule']['rule']!r}",
            EXIT_BASELINE_MISMATCH,
        )
    expected_assignments = alternating_split_assignments(scenarios)
    if assignments != expected_assignments:
        raise ExperimentError(
            "the persisted assignments do not match the declared alternating rule",
            EXIT_BASELINE_MISMATCH,
        )

    problems = verify_split_by_scenario(questions, assignments)
    if problems:
        raise ExperimentError(
            "the split does not hold at scenario level: " + "; ".join(problems),
            EXIT_BASELINE_MISMATCH,
        )

    identity = EmbeddingIdentity(**frozen["embedding"])
    vector_problems = verify_frozen_vector_artefact(
        frozen,
        questions,
        identity,
    )
    if vector_problems:
        raise ExperimentError(
            "the frozen vectors do not cover the dataset: " + "; ".join(vector_problems),
            EXIT_BASELINE_MISMATCH,
        )

    _verify_judgments(questions)

    dev_questions = dev_projection_questions(questions, assignments)
    held_questions = questions_of_split(questions, assignments, HELD_OUT)
    manifest = heldout_manifest(questions, assignments, MANIFEST_VERSION)
    dev_ids = {str(question["question_id"]) for question in dev_questions}
    dev_vectors = [
        dict(vector)
        for vector in frozen["vectors"]
        if str(vector["question_id"]) in dev_ids
    ]
    dev_vectors_digest = frozen_vectors_digest(dev_vectors)

    dev_payload: dict[str, Any] = {
        "schema_version": "1",
        "contract": DEV_PROJECTION_CONTRACT,
        "split_scope": DEV,
        "seal_version": SEAL_VERSION,
        "dataset_version": dataset["dataset_version"],
        "split_version": dataset["split_rule"]["split_version"],
        "corpus_id": dataset["corpus_id"],
        "scope_note": (
            "Unico ficheiro de dados que a calibracao da D4.8.2b le. Contem "
            "exclusivamente as perguntas de DEV, com rotulos e julgamentos. Nao "
            "contem nenhuma pergunta, rotulo, julgamento nem cenario do HELD-OUT, "
            "nem as atribuicoes do split, que diriam o que ha do outro lado. "
            "Apontar a calibracao ao dataset completo levanta LeakageError."
        ),
        "relevance_scale": dataset["relevance_scale"],
        "label_definitions": dataset["label_definitions"],
        "question_count": len(dev_questions),
        "questions": [dict(question) for question in dev_questions],
    }
    dev_payload["dev_questions_digest"] = question_dataset_digest(dev_questions)

    dev_vectors_payload: dict[str, Any] = {
        "schema_version": "1",
        "contract": DEV_VECTORS_CONTRACT,
        "split_scope": DEV,
        "seal_version": SEAL_VERSION,
        "dataset_version": dataset["dataset_version"],
        "split_version": dataset["split_rule"]["split_version"],
        "scope_note": (
            "Unico ficheiro de vetores que a calibracao le. Contem apenas os "
            "embeddings DEV e compromete a origem no conjunto global selado."
        ),
        "embedding": dict(frozen["embedding"]),
        "questions_frozen": len(dev_vectors),
        "frozen_vectors_digest": frozen["frozen_vectors_digest"],
        "dev_vectors_digest": dev_vectors_digest,
        "vectors": dev_vectors,
    }
    dev_vector_problems = verify_frozen_vector_artefact(
        dev_vectors_payload,
        dev_questions,
        identity,
        digest_field="dev_vectors_digest",
        expected_digest=dev_vectors_digest,
    )
    if dev_vector_problems:
        raise ExperimentError(
            "the DEV vector projection just built is invalid: "
            + "; ".join(dev_vector_problems),
            EXIT_BASELINE_MISMATCH,
        )

    projection_problems = verify_dev_projection(dev_payload, manifest)
    if projection_problems:
        raise ExperimentError(
            "the DEV projection just built does not satisfy the barrier: "
            + "; ".join(projection_problems),
            EXIT_BASELINE_MISMATCH,
        )

    # A barreira só vale se recusar o que tem de recusar. Verificar aqui, e não
    # apenas no teste, é o que impede que um artefacto selado por engano com o
    # dataset inteiro chegue a existir.
    try:
        load_calibration_questions(dataset, manifest)
    except LeakageError:
        pass
    else:
        raise ExperimentError(
            "the barrier accepted the full dataset as a DEV projection",
            EXIT_BASELINE_MISMATCH,
        )

    split_payload: dict[str, Any] = {
        "schema_version": "1",
        "contract": "dense_admission_split",
        "seal_version": SEAL_VERSION,
        "dataset_version": dataset["dataset_version"],
        "split_version": dataset["split_rule"]["split_version"],
        "corpus_id": dataset["corpus_id"],
        "scope_note": (
            "Split por cenario, fixado antes de qualquer calibracao. A unidade e "
            "o cenario e nunca a pergunta: duas parafrases do mesmo pedido "
            "separadas pela fronteira tornariam o conjunto final parcialmente "
            "conhecido pela calibracao, e o resultado pareceria generalizacao sem "
            "o ser."
        ),
        "rule": dataset["split_rule"]["rule"],
        "seed": dataset["split_rule"]["seed"],
        "rule_note": dataset["split_rule"]["note"],
        "assignments": dict(sorted(assignments.items())),
        "counts": _counts(questions, assignments, scenarios),
        "dev": {
            "question_count": len(dev_questions),
            "question_ids": [str(q["question_id"]) for q in dev_questions],
            "scenario_ids": sorted({str(q["scenario_id"]) for q in dev_questions}),
            "questions_digest": question_dataset_digest(dev_questions),
            "vectors_digest": dev_vectors_digest,
        },
        "heldout_manifest": manifest,
        "heldout_manifest_note": (
            "Compromisso publico sobre o conjunto final: diz quantas e quais "
            "perguntas ficam seladas e nao diz nenhum rotulo. O labels_digest "
            "cobre rotulos e julgamentos do HELD-OUT e e reconferido na D4.8.2c: "
            "e o que distingue 'o conjunto nao foi tocado' de 'acredita em mim'."
        ),
        "dataset_questions_digest": question_dataset_digest(questions),
        "scenario_digest": scenario_digest(scenarios),
        "frozen_vectors_digest": frozen_vectors_digest(frozen["vectors"]),
        "embedding": dict(frozen["embedding"]),
    }
    split_payload["heldout_manifest_digest"] = heldout_manifest_digest(manifest)
    split_payload["split_digest"] = split_digest(
        assignments, str(dataset["split_rule"]["split_version"])
    )
    split_payload["sealed_at"] = datetime.now(UTC).isoformat()

    args.dev_output.write_text(
        json.dumps(dev_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    args.dev_vectors_output.write_text(
        json.dumps(dev_vectors_payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    args.split_output.write_text(
        json.dumps(split_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    print(f"cenarios DEV / HELD-OUT : {split_payload['counts']['scenarios']}")
    print(f"perguntas DEV           : {len(dev_questions)}")
    print(f"perguntas HELD-OUT      : {len(held_questions)}")
    print(f"split_digest            : {split_payload['split_digest']}")
    print(f"heldout_manifest_digest : {split_payload['heldout_manifest_digest']}")
    print(f"labels_digest (selado)  : {manifest['labels_digest']}")
    print(f"written                 : {args.split_output}")
    print(f"written                 : {args.dev_output}")
    print(f"written                 : {args.dev_vectors_output}")
    return EXIT_OK


def _verify_judgments(questions: Sequence[dict[str, Any]]) -> None:
    """Duas invariantes do dataset, verificadas antes de selar.

    Uma pergunta ANSWERABLE sem nenhum grau 2 não está anotada — está por
    anotar, e mediria falha de recuperação onde há falha de anotação. Um grau 2
    numa pergunta NO_EVIDENCE contradiz o rótulo: uma das duas coisas está
    errada, e selar sem saber qual é selar um erro.
    """
    problems: list[str] = []
    for question in questions:
        grades = [int(j["relevance"]) for j in question["judgments"]]
        label = question["label"]
        if label == ANSWERABLE and 2 not in grades:
            problems.append(f"{question['question_id']}: ANSWERABLE with no grade 2")
        if label == NO_EVIDENCE and 2 in grades:
            problems.append(f"{question['question_id']}: NO_EVIDENCE with a grade 2")
        if label == NO_EVIDENCE and "no_evidence_validation" not in question:
            problems.append(f"{question['question_id']}: NO_EVIDENCE without validation")
    if problems:
        raise ExperimentError(
            "the dataset contradicts itself: " + "; ".join(problems),
            EXIT_BASELINE_MISMATCH,
        )


def _counts(
    questions: Sequence[dict[str, Any]],
    assignments: dict[str, str],
    scenarios: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    counts: dict[str, Any] = {"scenarios": {}, "questions": {}}
    for split in (DEV, HELD_OUT):
        split_questions = questions_of_split(questions, assignments, split)
        counts["scenarios"][split] = sum(
            1 for s in scenarios if assignments.get(str(s["scenario_id"])) == split
        )
        counts["questions"][split] = {
            "total": len(split_questions),
            ANSWERABLE: sum(1 for q in split_questions if q["label"] == ANSWERABLE),
            NO_EVIDENCE: sum(1 for q in split_questions if q["label"] == NO_EVIDENCE),
        }
    return counts


if __name__ == "__main__":
    sys.exit(main())
