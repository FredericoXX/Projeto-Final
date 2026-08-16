"""Condição pareada com diacríticos sobre P1/S1 (D4.4).

Uso (a partir de ``backend/``, com o virtual environment ativo):

    python -m scripts.evaluate_diacritics_experiment \
        --ground-truth ../docs/evaluation/retrieval-ground-truth-p1-seed.json \
        --paired-ground-truth ../docs/evaluation/retrieval-ground-truth-p1-diacritics.json \
        --binding ../storage/pilot-corpus/S1-identifier-binding.json \
        --baseline ../docs/evaluation/retrieval-baseline-p1-s1.json \
        --experiment ../docs/evaluation/retrieval-experiment-p1-s1.json \
        --output ../docs/evaluation/retrieval-experiment-diacritics-p1-s1.json \
        [--overwrite]

Isola **uma** variável: os diacríticos da pergunta. Não altera o retrieval de
produção, o corpus, o *ground truth* histórico nem os artefactos do D4.2/D4.3.

Porque é que o fator fica isolado
---------------------------------

A consulta enviada ao PostgreSQL é construída a partir de ``normalize_text``, que
**remove** diacríticos. As duas condições produzem, por isso, a mesma
``tsquery``, o mesmo conjunto de candidatos e os mesmos ``query_terms`` — o que
muda é só o texto de que a variante ``stem_accented`` lê a acentuação do lado da
pergunta. Nada mais no caminho difere, o que torna a atribuição de causa direta
em vez de inferida.

Daí decorre uma previsão verificável antes de medir: ``exact_canonical`` e
``stem_normalized`` **não leem** o texto acentuado da pergunta, pelo que as suas
duas células têm de sair idênticas. O artefacto regista se saíram.

Reutilização, não cópia
-----------------------

A execução por célula, a recolha de candidatos, a ordenação e as guardas vêm por
importação de ``scripts.evaluate_retrieval_experiment``, que não é tocado. Copiar
esse código faria as duas experiências divergirem em silêncio, e o D4.4 deixaria
de estar a medir o mesmo sistema que o D4.3 mediu.

Guardas
-------

Nada é escrito se alguma falhar:

1. o pareamento tem de ser válido — cada pergunta pareada difere da original
   **apenas** em marcas combinantes, com julgamentos, âmbito temporal e exclusões
   idênticos;
2. os dois conjuntos têm de ter ``ground_truth_digest`` **diferentes**, sob pena
   de o par não ser par nenhum;
3. a célula ``exact_canonical`` × conjunto original tem de reproduzir o
   artefacto do D4.2 por inteiro;
4. as três células do conjunto original têm de reproduzir as três células
   ``production_quota`` do D4.3, o que verifica mecanicamente que o D4.4 não
   deslocou o D4.3;
5. as perguntas **sem** diacríticos a restituir têm de medir exatamente o mesmo
   nas duas condições. São controlos nulos: um texto byte a byte igual que
   produzisse resultados diferentes denunciaria não determinismo, e qualquer
   delta observado noutro sítio deixaria de ser atribuível ao diacrítico.
"""

import argparse
import hashlib
import json
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Final
from uuid import UUID

from sqlalchemy import select

from app.core.text_normalization import normalize_text
from app.documents.retrievability import RetrievabilityContext
from app.evaluation.ground_truth_identity import (
    GROUND_TRUTH_DIGEST_ALGORITHM,
    GROUND_TRUTH_DIGEST_SCOPE,
    PairingReport,
    ground_truth_digest,
    verify_pairing,
)
from app.evaluation.lexical_variants import (
    MATCHING_EXACT_CANONICAL,
    MATCHING_VARIANTS,
    POOL_PRODUCTION_QUOTA,
)
from app.evaluation.results import canonical_json
from app.evaluation.retrieval_metrics import K_VALUES, PRIMARY_K
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from scripts.evaluate_retrieval_baseline import BaselineError, verify_metric_protocol
from scripts.evaluate_retrieval_experiment import (
    _WORD_RE,
    ExperimentError,
    SessionLocalFactory,
    corpus_accented_vocabulary,
    evaluate_cell,
    stem_words_batch,
    verify_baseline_integrity,
    verify_baseline_replication,
    verify_snapshot,
)

EXPERIMENT_SCHEMA_VERSION: Final = "1"
DIGEST_ALGORITHM: Final = "sha256"

#: Nome das duas condições. O fator experimental é a diferença entre elas e mais
#: nada: mesmo corpus, mesmo snapshot, mesmas quotas, mesmos julgamentos.
CONDITION_ORIGINAL: Final = "original"
CONDITION_DIACRITICS: Final = "diacritics"
CONDITIONS: Final = (CONDITION_ORIGINAL, CONDITION_DIACRITICS)

EXIT_OK: Final = 0
EXIT_USAGE: Final = 2
#: Levantado pelo ``verify_snapshot`` importado, não aqui; declarado para que a
#: tabela de códigos de saída deste script esteja completa.
EXIT_SNAPSHOT_MISMATCH: Final = 3
EXIT_BASELINE_MISMATCH: Final = 4
EXIT_OUTPUT_EXISTS: Final = 5
EXIT_PAIRING_INVALID: Final = 6
EXIT_NULL_CONTROL: Final = 7


def _load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ExperimentError(f"file not found: {path}", EXIT_USAGE) from error
    except json.JSONDecodeError as error:
        raise ExperimentError(f"invalid JSON in {path}: {error}", EXIT_USAGE) from error


# ---------------------------------------------------------------------------
# Comparação entre condições
# ---------------------------------------------------------------------------


def _ranking_signature(entries: Sequence[Mapping[str, Any]]) -> list[list[Any]]:
    """Identidade posicional de um resultado, com ``judged`` incluído.

    O grau sozinho não bastaria: um segmento **não julgado** e um distractor
    julgado de grau 0 partilham o valor 0, e sem a bandeira o artefacto faria
    passar ruído por distractor — ou o contrário.
    """
    return [
        [
            entry["position"],
            entry["corpus_item_id"],
            entry["chunk_index"],
            entry["grade"],
            entry["judged"],
        ]
        for entry in entries
    ]


def _metric_pairs(
    before: Mapping[str, Any], after: Mapping[str, Any]
) -> dict[str, Any]:
    """Métricas das duas condições lado a lado, sem as achatar num só número."""
    return {
        "recall": {
            str(k): [before["recall"][str(k)], after["recall"][str(k)]] for k in K_VALUES
        },
        "reciprocal_rank": [before["reciprocal_rank"], after["reciprocal_rank"]],
        "ndcg": {
            str(k): [before["ndcg"][str(k)], after["ndcg"][str(k)]] for k in K_VALUES
        },
    }


def _direction(before: Mapping[str, Any], after: Mapping[str, Any]) -> str:
    """Sentido da mudança segundo Recall@5, MRR e nDCG@5 **em conjunto**.

    Deliberadamente não reduzido ao Recall: uma alteração que suba o Recall e
    desça a posição do primeiro relevante não é uma melhoria, e chamar-lhe isso
    esconderia a perda.
    """
    deltas = [
        after["recall"][str(PRIMARY_K)] - before["recall"][str(PRIMARY_K)],
        after["reciprocal_rank"] - before["reciprocal_rank"],
        after["ndcg"][str(PRIMARY_K)] - before["ndcg"][str(PRIMARY_K)],
    ]
    up = any(delta > 1e-9 for delta in deltas)
    down = any(delta < -1e-9 for delta in deltas)
    if up and down:
        return "mixed"
    if up:
        return "improved"
    if down:
        return "regressed"
    return "reordered_without_metric_change"


def compare_conditions(
    original_cell: Mapping[str, Any],
    paired_cell: Mapping[str, Any],
    pair_index: Mapping[str, str],
) -> dict[str, Any]:
    """Delta de uma variante entre as duas condições.

    Só as perguntas que **mudaram** ganham registo completo; das restantes fica a
    contagem e a lista de identificadores. Com 14 perguntas × 3 variantes, emitir
    tudo afogaria o achado no artefacto.
    """
    original_by_id = {
        result["question_id"]: result for result in original_cell["question_results"]
    }
    paired_by_id = {
        result["question_id"]: result for result in paired_cell["question_results"]
    }

    changed: list[dict[str, Any]] = []
    unchanged: list[str] = []
    for original_id, paired_id in sorted(pair_index.items()):
        before = original_by_id[original_id]
        after = paired_by_id[paired_id]
        ranking_changed = _ranking_signature(before["ranking"]) != _ranking_signature(
            after["ranking"]
        )
        measured = "recall" in before and "recall" in after
        metrics_changed = measured and (
            before["recall"] != after["recall"]
            or before["ndcg"] != after["ndcg"]
            or before["reciprocal_rank"] != after["reciprocal_rank"]
        )
        if not ranking_changed and not metrics_changed:
            unchanged.append(original_id)
            continue

        record: dict[str, Any] = {
            "question_id": original_id,
            "paired_question_id": paired_id,
            "measured": measured,
            "direction": _direction(before, after) if measured else "observed_only",
            "retrieved_count": [before["retrieved_count"], after["retrieved_count"]],
            "judged_distractors_returned": [
                before["judged_distractors_returned"],
                after["judged_distractors_returned"],
            ],
            "unjudged_returned": [before["unjudged_returned"], after["unjudged_returned"]],
            "ranking_before": _ranking_signature(before["ranking"]),
            "ranking_after": _ranking_signature(after["ranking"]),
        }
        if measured:
            record["metrics"] = _metric_pairs(before, after)
        changed.append(record)

    before_aggregate = original_cell["aggregate"]
    after_aggregate = paired_cell["aggregate"]
    return {
        "matching_variant": original_cell["matching_variant"],
        "conditions_identical": not changed,
        "aggregate_delta": {
            "recall": {
                str(k): round(
                    after_aggregate["recall"][str(k)] - before_aggregate["recall"][str(k)], 6
                )
                for k in K_VALUES
            },
            "mrr": round(after_aggregate["mrr"] - before_aggregate["mrr"], 6),
            "ndcg": {
                str(k): round(
                    after_aggregate["ndcg"][str(k)] - before_aggregate["ndcg"][str(k)], 6
                )
                for k in K_VALUES
            },
        },
        "improved": [r["question_id"] for r in changed if r["direction"] == "improved"],
        "regressed": [r["question_id"] for r in changed if r["direction"] == "regressed"],
        "mixed": [r["question_id"] for r in changed if r["direction"] == "mixed"],
        "unchanged_count": len(unchanged),
        "unchanged": unchanged,
        "questions_changed": changed,
    }


def verify_null_controls(
    original_cell: Mapping[str, Any],
    paired_cell: Mapping[str, Any],
    pair_index: Mapping[str, str],
    identical_pairs: Sequence[str],
) -> list[str]:
    """As perguntas sem diacríticos a restituir têm de medir exatamente o mesmo.

    O texto é byte a byte igual nas duas condições; qualquer diferença aqui é não
    determinismo ou defeito da montagem, e invalidaria a atribuição de **todos**
    os outros deltas ao diacrítico.
    """
    original_by_id = {
        result["question_id"]: result for result in original_cell["question_results"]
    }
    paired_by_id = {
        result["question_id"]: result for result in paired_cell["question_results"]
    }
    problems: list[str] = []
    for question_id in identical_pairs:
        before = original_by_id[question_id]
        after = paired_by_id[pair_index[question_id]]
        for field in ("retrieved_count", "judged_distractors_returned", "unjudged_returned"):
            if before[field] != after[field]:
                problems.append(
                    f"null control {question_id}: {field} {before[field]} -> {after[field]}"
                )
        if _ranking_signature(before["ranking"]) != _ranking_signature(after["ranking"]):
            problems.append(f"null control {question_id}: ranking changed")
        if ("recall" in before) != ("recall" in after):
            problems.append(f"null control {question_id}: measurability changed")
        elif "recall" in before:
            if before["recall"] != after["recall"] or before["ndcg"] != after["ndcg"]:
                problems.append(f"null control {question_id}: metrics changed")
            if before["reciprocal_rank"] != after["reciprocal_rank"]:
                problems.append(f"null control {question_id}: reciprocal_rank changed")
    return problems


def _pairing_summary(report: PairingReport) -> dict[str, Any]:
    return {
        "pairs_total": len(report.pairs),
        "diacritics_restored": list(report.restored_pairs),
        "identity_pairs": list(report.identical_pairs),
        "identity_pairs_note": (
            "questions whose correct spelling carries no diacritic; they are the "
            "experiment's internal null controls"
        ),
        "reformulation_required": [],
        "restorations": {
            pair.original_id: [list(item) for item in pair.restored]
            for pair in report.pairs
            if pair.restored
        },
    }


# ---------------------------------------------------------------------------
# Execução
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ground-truth", type=Path, required=True)
    parser.add_argument("--paired-ground-truth", type=Path, required=True)
    parser.add_argument("--binding", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--experiment", type=Path, required=True)
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


def _verify_protocols(*ground_truths: Mapping[str, Any]) -> None:
    for ground_truth in ground_truths:
        try:
            verify_metric_protocol(dict(ground_truth))
        except BaselineError as error:
            raise ExperimentError(str(error), EXIT_USAGE) from error


def _run(args: argparse.Namespace) -> int:
    if args.output.exists() and not args.overwrite:
        raise ExperimentError(
            f"refusing to overwrite {args.output} without --overwrite", EXIT_OUTPUT_EXISTS
        )

    ground_truth = _load_json(args.ground_truth)
    paired_ground_truth = _load_json(args.paired_ground_truth)
    binding = _load_json(args.binding)
    baseline = _load_json(args.baseline)
    d43_experiment = _load_json(args.experiment)

    _verify_protocols(ground_truth, paired_ground_truth)
    verify_baseline_integrity(baseline)
    verify_baseline_integrity(d43_experiment)

    report = verify_pairing(ground_truth, paired_ground_truth)
    if not report.valid:
        raise ExperimentError(
            "the paired question set is not a valid pairing of the original: "
            + "; ".join(report.problems),
            EXIT_PAIRING_INVALID,
        )
    original_digest = ground_truth_digest(ground_truth)
    paired_digest = ground_truth_digest(paired_ground_truth)
    if original_digest == paired_digest:
        raise ExperimentError(
            "the two question sets share a ground_truth_digest; there is no "
            "paired condition to measure",
            EXIT_PAIRING_INVALID,
        )
    pair_index = {pair.original_id: pair.paired_id for pair in report.pairs}

    retrieval = baseline["retrieval"]
    language = retrieval["language"]
    top_k = retrieval["top_k"]
    official_only = retrieval["official_only"]
    institution_id = UUID(binding["institution_id"])

    document_index = {
        item["corpus_item_id"]: item["document_id"]
        for item in binding["items"]
        if item.get("in_corpus")
    }
    question_sets = {
        CONDITION_ORIGINAL: ground_truth["questions"],
        CONDITION_DIACRITICS: paired_ground_truth["questions"],
    }

    with SessionLocalFactory() as db:
        verify_snapshot(
            db,
            ground_truth=ground_truth,
            binding=binding,
            language=language,
            top_k=top_k,
            official_only=official_only,
        )
        context = RetrievabilityContext(
            institution_id=institution_id,
            language=language,
            reference_date=date.fromisoformat(ground_truth["reference_date"]),
            official_only=official_only,
        )

        # Um único mapa ``palavra -> radical``, partilhado pelas seis células. O
        # radical de uma palavra é função apenas dela, pelo que reuni-las em lote
        # não faz nenhum lado herdar informação do outro — e um mapa comum
        # elimina a hipótese de as células diferirem por terem visto vocabulários
        # diferentes.
        vocabulary: set[str] = corpus_accented_vocabulary(db, institution_id)
        rows = db.execute(
            select(DocumentChunk.normalized_content)
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(Document.institution_id == institution_id)
        ).all()
        for (normalized,) in rows:
            vocabulary.update(_WORD_RE.findall(normalized))
        for questions in question_sets.values():
            for question in questions:
                vocabulary.update(_WORD_RE.findall(question["question"].casefold()))
                vocabulary.update(_WORD_RE.findall(normalize_text(question["question"])))

        stems = stem_words_batch(db, vocabulary)

        cells: list[dict[str, Any]] = []
        for condition in CONDITIONS:
            for variant in MATCHING_VARIANTS:
                cell = evaluate_cell(
                    db,
                    questions=question_sets[condition],
                    document_index=document_index,
                    context=context,
                    language=language,
                    top_k=top_k,
                    variant=variant,
                    stems=stems,
                    pool=POOL_PRODUCTION_QUOTA,
                )
                cell["question_set"] = condition
                cells.append(cell)

    by_key = {(cell["question_set"], cell["matching_variant"]): cell for cell in cells}

    control = by_key[(CONDITION_ORIGINAL, MATCHING_EXACT_CANONICAL)]
    problems = verify_baseline_replication(control, baseline)
    if problems:
        raise ExperimentError(
            "the control cell does not reproduce the D4.2 baseline: " + "; ".join(problems),
            EXIT_BASELINE_MISMATCH,
        )

    d43_by_variant = {
        cell["matching_variant"]: cell
        for cell in d43_experiment["cells"]
        if cell["pool_condition"] == POOL_PRODUCTION_QUOTA
    }
    for variant in MATCHING_VARIANTS:
        problems = verify_baseline_replication(
            by_key[(CONDITION_ORIGINAL, variant)], d43_by_variant[variant]
        )
        if problems:
            raise ExperimentError(
                f"the original-condition cell for {variant} does not reproduce the "
                "D4.3 production_quota cell: " + "; ".join(problems),
                EXIT_BASELINE_MISMATCH,
            )

    null_control_problems: list[str] = []
    for variant in MATCHING_VARIANTS:
        null_control_problems.extend(
            verify_null_controls(
                by_key[(CONDITION_ORIGINAL, variant)],
                by_key[(CONDITION_DIACRITICS, variant)],
                pair_index,
                report.identical_pairs,
            )
        )
    if null_control_problems:
        raise ExperimentError(
            "questions with no diacritics to restore did not measure identically "
            "across conditions: " + "; ".join(null_control_problems),
            EXIT_NULL_CONTROL,
        )

    deltas = [
        compare_conditions(
            by_key[(CONDITION_ORIGINAL, variant)],
            by_key[(CONDITION_DIACRITICS, variant)],
            pair_index,
        )
        for variant in MATCHING_VARIANTS
    ]

    payload: dict[str, Any] = {
        "schema_version": EXPERIMENT_SCHEMA_VERSION,
        "digest_algorithm": DIGEST_ALGORITHM,
        "corpus_id": ground_truth["corpus_id"],
        "snapshot_id": ground_truth["snapshot_id"],
        "corpus_digest": ground_truth["corpus_digest"],
        "reference_date": ground_truth["reference_date"],
        "ground_truth_digest_algorithm": GROUND_TRUTH_DIGEST_ALGORITHM,
        "ground_truth_digest_scope": GROUND_TRUTH_DIGEST_SCOPE,
        "ground_truth_digest_scope_note": (
            "The digest covers exactly the fields the measurement reads: schema, "
            "contract, corpus id, the operative metric protocol, and each question's "
            "id, text, language, exclusion flags and relevance judgments. It is not a "
            "file hash: prose, difficulty tags, temporal_scope and provenance are "
            "excluded because none of them enters any metric."
        ),
        "question_sets": {
            CONDITION_ORIGINAL: {
                "artefact": args.ground_truth.name,
                "ground_truth_digest": original_digest,
            },
            CONDITION_DIACRITICS: {
                "artefact": args.paired_ground_truth.name,
                "ground_truth_digest": paired_digest,
            },
        },
        "pairing": _pairing_summary(report),
        "baseline_result_digest": baseline["result_digest"],
        "control_reproduces_baseline": True,
        "d43_result_digest": d43_experiment["result_digest"],
        "reproduces_d43_production_cells": True,
        "null_controls_hold": True,
        "retrieval": retrieval,
        "matching_variants": list(MATCHING_VARIANTS),
        "question_set_conditions": list(CONDITIONS),
        "pool_condition": POOL_PRODUCTION_QUOTA,
        "primary_k": PRIMARY_K,
        "cells": cells,
        "deltas": deltas,
    }
    payload["result_digest"] = hashlib.sha256(
        canonical_json(payload).encode("utf-8")
    ).hexdigest()
    payload["executed_at"] = datetime.now(UTC).isoformat()

    args.output.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    print(f"original_digest : {original_digest}")
    print(f"paired_digest   : {paired_digest}")
    print(f"pairs           : {len(report.pairs)} "
          f"({len(report.restored_pairs)} restored, {len(report.identical_pairs)} identity)")
    for cell in cells:
        aggregate = cell["aggregate"]
        print(
            f"{cell['matching_variant']:18s} {cell['question_set']:11s} "
            f"R@5={aggregate['recall']['5']:.4f} MRR={aggregate['mrr']:.4f} "
            f"nDCG@5={aggregate['ndcg']['5']:.4f}"
        )
    for delta in deltas:
        print(
            f"delta {delta['matching_variant']:18s} identical={delta['conditions_identical']!s:5s} "
            f"improved={delta['improved']} regressed={delta['regressed']} mixed={delta['mixed']}"
        )
    print(f"result_digest   : {payload['result_digest']}")
    print(f"written         : {args.output}")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
