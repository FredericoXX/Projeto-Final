"""Comparação definitiva C0 (lexical) × C1 (denso) sobre P1/S1 (D4.8.1).

Uso (a partir de ``backend/``, com o virtual environment ativo, sobre o índice
vetorial que o D4.8 persistiu — **sem** reembeber):

    python -m scripts.evaluate_lexical_dense_comparison \
        --ground-truth ../docs/evaluation/retrieval-ground-truth-p1-lexical-dense-repooled.json \
        --historical-ground-truth ../docs/evaluation/retrieval-ground-truth-p1-repooled.json \
        --repooling-requests ../docs/evaluation/dense-repooling-requests-p1-s1.json \
        --binding ../storage/pilot-corpus/S1-identifier-binding.json \
        --baseline ../docs/evaluation/retrieval-baseline-p1-s1.json \
        --dense-baseline ../docs/evaluation/dense-baseline-p1-s1.json \
        --output ../docs/evaluation/lexical-dense-comparison-p1-s1.json \
        [--overwrite]

Porque é que esta fase existe
-----------------------------

O D4.8 mediu C0 e C1 contra um conjunto de julgamentos construído por inspeção
dirigida a partir de execuções **lexicais**. Trinta e um resultados do top 5 —
**todos de C1** — nunca tinham sido vistos por um anotador, e sob
``ASSUMED_IRRELEVANT`` contavam grau 0 por isso mesmo. As métricas de C1 eram
provisórias por construção, e o próprio artefacto as marcava como tal.

Esta fase julga esses 31 pares e volta a medir as **mesmas** execuções contra o
conjunto completo. Não altera o retrieval, não implementa arquitetura híbrida,
não introduz limiar denso e não escolhe modelo nenhum.

O que muda entre o D4.8 e esta fase, e o que não pode mudar
-----------------------------------------------------------

Muda **uma** coisa: os julgamentos. Tudo o resto tem de ser o mesmo, e é isso
que as guardas impõem — se os rankings mudassem, a diferença de métricas
deixaria de ser atribuível ao repooling.

Guardas, por ordem de execução
------------------------------

1. **Integridade dos artefactos consumidos.** O D4.2, o D4.8 e a lista de
   pedidos de repooling têm de coincidir com o seu próprio ``result_digest``.
2. **Protocolo de métricas** — as constantes declaradas têm de ser as
   implementadas, no conjunto novo.
3. **Controlo do repooling.** O conjunto novo tem de estender o do D4.6 sem
   remover nem rever julgamento nenhum e sem tocar nas perguntas
   (``verify_repooling``), e tem de ter julgado **exatamente** os pedidos que o
   artefacto do D4.8 lista (``verify_requests_satisfied``). O digest do conjunto
   histórico é declarado **no código**: lê-lo do ficheiro em uso verificaria
   apenas que ele é consistente consigo mesmo.
4. **Snapshot** — o corpus reconstruído tem de continuar a ser S1.
5. **Índice vetorial** — homogéneo, completo e com o ``index_digest`` que o D4.8
   declara. É a garantia de que C1 não mudou: o digest cobre o conteúdo binário
   de cada vetor, pelo que uma reindexação, ainda que do mesmo texto pelo mesmo
   modelo, seria detetada aqui (D4.8 §8.1).
6. **Replicação dos rankings.** C0 tem de reproduzir o ranking posicional do
   D4.2 **e** o do D4.8; C1 tem de reproduzir o do D4.8. As métricas do D4.7
   **não** são comparadas: foram medidas contra o conjunto anterior, e é
   precisamente o denominador do Recall que o repooling alterou em Q006 e Q007.
7. **Comparabilidade.** A união dos dois top 5 tem de estar inteiramente
   julgada. Se sobrar um resultado por julgar, a comparação não é definitiva e
   nada é escrito.

Se qualquer uma falhar, **nada é escrito**.

Os dois digests do artefacto
----------------------------

O fornecedor de embeddings não é bit a bit determinístico (D4.8 §8.1), e C1
embebe a **pergunta** a cada execução: duas execuções produzem rankings, graus e
métricas idênticos e similaridades ligeiramente diferentes. O artefacto declara
por isso dois digests, e o canónico é o que descreve o **resultado**:

- ``result_digest`` — âmbito ``provider_independent_fields``. **Tem** de ser
  idêntico entre execuções sobre o mesmo índice e o mesmo *ground truth*;
- ``execution_digest`` — âmbito ``full_payload``. Muda com a deriva, e é isso
  que o torna útil.

Ambos vêm de ``app.evaluation.lexical_dense_comparison.artefact_digests``, que é
também a definição que a verificação de integridade tem de usar: um artefacto
com dois digests não é verificável por ``verify_baseline_integrity``, que assume
a convenção de um só.
"""

import argparse
import hashlib
import json
import sys
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Final
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.text_normalization import normalize_text
from app.documents.retrievability import RetrievabilityContext
from app.evaluation.dense_baseline import (
    COMPARABLE,
    CONDITION_DENSE,
    CONDITION_LEXICAL,
    CONDITIONS,
    PoolItem,
    build_repooling_requests,
    classify_comparability,
    exclusive_to,
    overlap_count,
    ranked_pool,
    union_pool,
)
from app.evaluation.ground_truth_identity import (
    GROUND_TRUTH_DIGEST_SCOPE,
    ground_truth_digest,
)
from app.evaluation.lexical_dense_comparison import (
    BOTH,
    C0_ONLY,
    C1_ONLY,
    EXECUTION_DIGEST_SCOPE,
    NEITHER,
    RESULT_DIGEST_SCOPE,
    SOLVED_BY_BOTH,
    SOLVED_BY_C0_ONLY,
    SOLVED_BY_C1_ONLY,
    SOLVED_BY_NEITHER,
    artefact_digests,
    classify_question,
    favoured_condition,
    grade_histogram,
    target_outcomes,
)
from app.evaluation.repooling import (
    denominator_changes,
    verify_repooling,
    verify_requests_satisfied,
)
from app.evaluation.results import canonical_json
from app.evaluation.retrieval_metrics import (
    BINARY_RELEVANCE_THRESHOLD,
    K_VALUES,
    PRIMARY_K,
)
from app.evaluation.snapshot_builder import build_evaluation_snapshot
from app.retrieval.base import RetrievalContext
from app.retrieval.dense import DENSE_PIPELINE_VERSION, PostgresDenseRetriever
from app.retrieval.lexical import PostgresLexicalRetriever
from scripts.embed_pilot_corpus import DEFAULT_EMBEDDING_MODEL
from scripts.evaluate_dense_baseline import (
    EXIT_INDEX_INCOMPLETE,
    QUERY_PREPROCESSING,
    aggregate_metrics,
    condition_metrics,
    embedding_index_digest,
    evaluate_condition,
    judged_grades_by_anchor,
    verify_c0_reproduces_d42,
    verify_index_coverage,
    verify_index_identity,
)
from scripts.evaluate_retrieval_baseline import verify_metric_protocol
from scripts.evaluate_retrieval_experiment import (
    EXIT_BASELINE_MISMATCH,
    EXIT_OK,
    EXIT_OUTPUT_EXISTS,
    EXIT_SNAPSHOT_MISMATCH,
    ExperimentError,
    SessionLocalFactory,
    _load_json,
    _ranking_signature,
    verify_baseline_integrity,
)

EXPERIMENT_VERSION: Final = "d4.8.1-lexical-dense-comparison-1"
DIGEST_ALGORITHM: Final = "sha256"

#: A união dos dois top 5 ficou por julgar. É a condição que esta fase existe
#: para eliminar, e encontrá-la aqui significa que o repooling não a eliminou.
EXIT_NOT_COMPARABLE: Final = 8

#: Identidade do conjunto de perguntas **antes** do repooling desta fase: o
#: repooled do D4.6, que o D4.8 mediu. Declarada aqui, e não lida do ficheiro,
#: pela mesma razão que no D4.8.
HISTORICAL_GROUND_TRUTH_DIGEST: Final = (
    "ada6b38886a06910e425e4be164099a3a63320050890253404064e3fde88586e"
)


# ---------------------------------------------------------------------------
# Guardas
# ---------------------------------------------------------------------------


def verify_requests_integrity(requests: Mapping[str, Any]) -> None:
    """A lista de pedidos tem de ser aquela que o seu próprio digest declara.

    Sem isto, o âmbito do repooling seria um ficheiro editável à mão, e a
    afirmação «foram julgados exatamente estes 31 pares» não teria conteúdo:
    quem acrescentasse um julgamento poderia acrescentar o pedido a seguir.
    """
    declared = requests.get("result_digest")
    if not declared:
        raise ExperimentError(
            "the repooling request artefact has no result_digest",
            EXIT_BASELINE_MISMATCH,
        )
    payload = {key: value for key, value in requests.items() if key != "result_digest"}
    recomputed = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    if recomputed != declared:
        raise ExperimentError(
            "the repooling request artefact does not match its own digest: "
            f"{recomputed} != {declared}",
            EXIT_BASELINE_MISMATCH,
        )
    if len(requests["requests"]) != requests["requests_total"]:
        raise ExperimentError(
            "the repooling request artefact declares a total it does not contain",
            EXIT_BASELINE_MISMATCH,
        )


def verify_repooling_control(
    historical: Mapping[str, Any],
    repooled: Mapping[str, Any],
    requests: Mapping[str, Any],
    dense_baseline: Mapping[str, Any],
) -> dict[str, Any]:
    """As condições do controlo do repooling, numa só guarda.

    Devolve o relatório para o artefacto, para que o número de julgamentos
    acrescentados por grau seja **medido** e não declarado em prosa.
    """
    historical_digest = ground_truth_digest(historical)
    repooled_digest = ground_truth_digest(repooled)

    problems: list[str] = []
    if historical_digest != HISTORICAL_GROUND_TRUTH_DIGEST:
        problems.append(
            f"the historical set is not the one D4.8 measured: {historical_digest} "
            f"!= {HISTORICAL_GROUND_TRUTH_DIGEST}"
        )
    for artefact, name in (
        (requests, "the repooling request list"),
        (dense_baseline, "the D4.8 artefact"),
    ):
        declared = artefact.get("ground_truth_digest")
        if declared != HISTORICAL_GROUND_TRUTH_DIGEST:
            problems.append(
                f"{name} declares ground_truth_digest {declared}, not "
                f"{HISTORICAL_GROUND_TRUTH_DIGEST}"
            )
    if repooled_digest == historical_digest:
        problems.append(
            "the repooled set shares its digest with the historical one; nothing "
            "measurable was added"
        )
    for field_name in ("snapshot_id", "corpus_digest", "corpus_id"):
        if historical.get(field_name) != repooled.get(field_name):
            problems.append(f"the repooling changed {field_name}")

    report = verify_repooling(historical, repooled)
    problems.extend(report.problems)
    problems.extend(
        verify_requests_satisfied(requests["requests"], historical, repooled)
    )

    if problems:
        raise ExperimentError(
            "the repooled ground truth is not a valid extension of the set D4.8 "
            "measured: " + "; ".join(problems),
            EXIT_BASELINE_MISMATCH,
        )

    return {
        "ground_truth_digest_before": historical_digest,
        "ground_truth_digest_after": repooled_digest,
        "requests_total": requests["requests_total"],
        "judgments_added": report.added_total,
        "judgments_added_by_grade": {
            str(grade): count for grade, count in report.added_by_grade.items()
        },
        "questions_touched": list(report.questions_touched),
        "historical_judgments_removed": 0,
        "historical_judgments_revised": 0,
        "recall_denominator_changes": denominator_changes(
            historical, repooled, BINARY_RELEVANCE_THRESHOLD
        ),
    }


def verify_index_matches_d48(
    index_digest: str, indexed_vectors: int, dense_baseline: Mapping[str, Any]
) -> None:
    """O índice vetorial tem de ser, vetor a vetor, o que o D4.8 mediu.

    O ``index_digest`` cobre o conteúdo binário de cada vetor, e o D4.8 mediu
    (§8.1) que reembeber o **mesmo** texto pelo mesmo modelo produz vetores
    diferentes na ordem de 1e-4. Sem esta guarda, uma reindexação silenciosa
    entre as duas fases apareceria como efeito do repooling.
    """
    embedding = dense_baseline["embedding"]
    problems: list[str] = []
    if index_digest != embedding["index_digest"]:
        problems.append(
            f"index_digest {index_digest} != D4.8 {embedding['index_digest']}"
        )
    if indexed_vectors != embedding["indexed_vectors"]:
        problems.append(
            f"indexed_vectors {indexed_vectors} != D4.8 {embedding['indexed_vectors']}"
        )
    if problems:
        raise ExperimentError(
            "the vector index is not the one D4.8 measured; a difference in the "
            "metrics could be a difference between two indexes: " + "; ".join(problems),
            EXIT_INDEX_INCOMPLETE,
        )


def verify_reproduces_d48_rankings(
    records: Sequence[Mapping[str, Any]], dense_baseline: Mapping[str, Any]
) -> None:
    """As duas condições têm de reproduzir os rankings do D4.8, posição a posição.

    É a guarda central desta fase. O que se quer medir é o efeito de **julgar**
    31 resultados; se algum ranking mudasse, a diferença passaria a medir também
    a mudança do sistema, e as duas causas seriam indistinguíveis no agregado.

    Compara as catorze perguntas, incluindo a sem evidência e a excluída das
    métricas: continuam a ser execuções do retriever.
    """
    reference = {
        result["question_id"]: result for result in dense_baseline["question_results"]
    }
    got = {record["question_id"]: record for record in records}

    problems: list[str] = []
    missing = sorted(set(reference) - set(got))
    extra = sorted(set(got) - set(reference))
    if missing:
        problems.append(f"questions absent from this run: {missing}")
    if extra:
        problems.append(f"questions absent from the D4.8 artefact: {extra}")

    for question_id in sorted(set(reference) & set(got)):
        for condition in CONDITIONS:
            here = got[question_id]["conditions"][condition]
            there = reference[question_id]["conditions"][condition]
            if here["retrieved_count"] != there["retrieved_count"]:
                problems.append(
                    f"{question_id}/{condition} retrieved_count "
                    f"{here['retrieved_count']} != D4.8 {there['retrieved_count']}"
                )
            if _ranking_signature(here["ranking"]) != _ranking_signature(
                there["ranking"]
            ):
                problems.append(
                    f"{question_id}/{condition} ranking differs from the D4.8 artefact"
                )

    if problems:
        raise ExperimentError(
            "the rankings do not reproduce the D4.8 experiment; the difference in "
            "metrics would not be attributable to the repooling: " + "; ".join(problems),
            EXIT_BASELINE_MISMATCH,
        )


def verify_comparable(
    comparability: str, unjudged: Sequence[Mapping[str, Any]]
) -> None:
    """A união dos dois top 5 tem de estar inteiramente julgada."""
    if comparability != COMPARABLE:
        listed = ", ".join(
            f"{request['question_id']}/{request['corpus_item_id']}/"
            f"{request['chunk_index']}"
            for request in unjudged
        )
        raise ExperimentError(
            f"{len(unjudged)} results in the union of the two top {PRIMARY_K} are "
            f"still unjudged; the comparison would not be definitive: {listed}",
            EXIT_NOT_COMPARABLE,
        )


# ---------------------------------------------------------------------------
# Análise
# ---------------------------------------------------------------------------


def analyse_question(
    record: Mapping[str, Any], question: Mapping[str, Any]
) -> dict[str, Any]:
    """Complementaridade e diferença de ranking de uma pergunta.

    As duas contagens são disjuntas por construção (ver
    ``TargetOutcome.is_ranking_difference``): um alvo é exclusivo de uma
    condição ou está nas duas, nunca as duas coisas.
    """
    c0_pool = ranked_pool(record["conditions"][CONDITION_LEXICAL]["ranking"])
    c1_pool = ranked_pool(record["conditions"][CONDITION_DENSE]["ranking"])
    targets = [
        PoolItem(judgment["corpus_item_id"], judgment["chunk_index"])
        for judgment in question["evidence_judgments"]
        if judgment["relevance"] >= BINARY_RELEVANCE_THRESHOLD
    ]
    outcomes = target_outcomes(targets, c0_pool, c1_pool)
    return {
        "targets": [
            {
                "corpus_item_id": outcome.corpus_item_id,
                "chunk_index": outcome.chunk_index,
                "rank_c0": outcome.rank_c0,
                "rank_c1": outcome.rank_c1,
                "destination": outcome.destination,
                "real_complementarity": outcome.is_real_complementarity,
                "ranking_difference": outcome.is_ranking_difference,
            }
            for outcome in outcomes
        ],
        "grade_histogram": {
            condition: grade_histogram(record["conditions"][condition]["ranking"])
            for condition in CONDITIONS
        },
    }


def summarise_complementarity(
    records: Sequence[Mapping[str, Any]], *, measured_only: bool
) -> dict[str, Any]:
    """Agregação dos destinos dos alvos e da classificação das perguntas."""
    destinations: dict[str, list[str]] = {
        BOTH: [],
        C0_ONLY: [],
        C1_ONLY: [],
        NEITHER: [],
    }
    ranking_differences: list[str] = []
    for record in records:
        if measured_only and not record["measured"]:
            continue
        for target in record["analysis"]["targets"]:
            label = (
                f"{record['question_id']}/{target['corpus_item_id']}/"
                f"{target['chunk_index']}"
            )
            destinations[target["destination"]].append(label)
            if target["ranking_difference"]:
                ranking_differences.append(label)

    classes: dict[str, list[str]] = {
        SOLVED_BY_BOTH: [],
        SOLVED_BY_C0_ONLY: [],
        SOLVED_BY_C1_ONLY: [],
        SOLVED_BY_NEITHER: [],
    }
    favoured: dict[str, list[str]] = {CONDITION_LEXICAL: [], CONDITION_DENSE: []}
    for record in records:
        if not record["measured"]:
            continue
        metrics = {
            condition: record["conditions"][condition]["metrics"]
            for condition in CONDITIONS
        }
        classes[
            classify_question(
                metrics[CONDITION_LEXICAL]["reciprocal_rank"],
                metrics[CONDITION_DENSE]["reciprocal_rank"],
            )
        ].append(record["question_id"])
        winner = favoured_condition(
            metrics[CONDITION_LEXICAL], metrics[CONDITION_DENSE], PRIMARY_K
        )
        if winner is not None:
            favoured[winner].append(record["question_id"])

    return {
        "grade2_targets_total": sum(len(items) for items in destinations.values()),
        "grade2_by_destination": {
            key: {"count": len(items), "targets": items}
            for key, items in destinations.items()
        },
        "grade2_ranking_differences": {
            "count": len(ranking_differences),
            "targets": ranking_differences,
            "note": (
                "Alvos que ENTRAM no top 5 das duas condicoes em posicoes "
                "diferentes. Nao sao complementaridade: ambas encontram a mesma "
                "evidencia e uma ordena-a melhor."
            ),
        },
        "questions_by_class": {key: list(items) for key, items in classes.items()},
        "questions_favoured": {key: list(items) for key, items in favoured.items()},
        "favoured_criterion": f"ndcg@{PRIMARY_K}",
    }


def analyse_no_evidence_question(
    record: Mapping[str, Any], all_records: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    """Comportamento das duas condições na pergunta sem evidência no corpus.

    Não decide política e não propõe limiar. Regista o que é observável: quantos
    resultados cada condição devolveu, com que graus depois do repooling, e onde
    caem as similaridades face às restantes perguntas.

    A comparação das similaridades é feita **contra as outras perguntas** porque
    ``comparable_across_queries`` é ``False``: o número só é informativo em
    relação à distribuição, e apresentá-lo isolado sugeriria uma calibração que
    não existe.
    """
    dense = record["conditions"][CONDITION_DENSE]
    lexical = record["conditions"][CONDITION_LEXICAL]
    scores = [entry["score"] for entry in dense["ranking"]]

    others_top = [
        other["conditions"][CONDITION_DENSE]["ranking"][0]["score"]
        for other in all_records
        if other["question_id"] != record["question_id"]
        and other["conditions"][CONDITION_DENSE]["ranking"]
    ]

    return {
        "question_id": record["question_id"],
        "exclusion_basis": "no_relevant_evidence",
        "retrieved_c0": lexical["retrieved_count"],
        "retrieved_c1": dense["retrieved_count"],
        "grade_histogram_c1": grade_histogram(dense["ranking"]),
        "relevant_results_found": any(
            entry["grade"] >= BINARY_RELEVANCE_THRESHOLD for entry in dense["ranking"]
        ),
        "partially_useful_results_found": any(
            entry["grade"] == 1 for entry in dense["ranking"]
        ),
        "similarity_top": scores[0] if scores else None,
        "similarity_bottom": scores[-1] if scores else None,
        "other_questions_top_similarity_min": min(others_top) if others_top else None,
        "other_questions_top_similarity_max": max(others_top) if others_top else None,
        "separated_from_other_questions": bool(
            scores and others_top and max(scores) < min(others_top)
        ),
        "threshold_note": (
            "Nenhum limiar denso e proposto ou implementado. Ha UMA pergunta nesta "
            "classe: uma amostra de um nao fundamenta um limiar, e derivar um valor "
            "destes numeros seria ajustar um parametro ao ground truth."
        ),
    }


def dense_behaviour_summary(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Quanto do que cada condição devolve é grau 0, e onde C0 se absteve."""
    empty_c0 = [
        record["question_id"]
        for record in records
        if record["conditions"][CONDITION_LEXICAL]["retrieved_count"] == 0
    ]
    per_condition: dict[str, Any] = {}
    for condition in CONDITIONS:
        returned = 0
        grades = {"0": 0, "1": 0, "2": 0}
        for record in records:
            for entry in record["conditions"][condition]["ranking"]:
                returned += 1
                grades[str(int(entry["grade"]))] += 1
        per_condition[condition] = {
            "returned_total": returned,
            "grade_histogram": grades,
            "irrelevant_share": round(grades["0"] / returned, 6) if returned else None,
        }
    where_c0_empty = {
        "questions": empty_c0,
        "c1_returned": sum(
            record["conditions"][CONDITION_DENSE]["retrieved_count"]
            for record in records
            if record["question_id"] in empty_c0
        ),
        "c1_grade_histogram": _sum_histograms(
            grade_histogram(record["conditions"][CONDITION_DENSE]["ranking"])
            for record in records
            if record["question_id"] in empty_c0
        ),
    }
    return {
        "per_condition": per_condition,
        "questions_where_c0_returned_nothing": where_c0_empty,
        "abstention_note": (
            "C0 tem uma etapa capaz de devolver vazio (elegibilidade lexical e "
            "limiar sobre o score composto); C1 nao tem nenhuma. A assimetria e de "
            "mecanismo e nao e corrigida nesta fase."
        ),
    }


def _sum_histograms(histograms: Iterable[Mapping[str, int]]) -> dict[str, int]:
    total = {"0": 0, "1": 0, "2": 0}
    for histogram in histograms:
        for grade, count in histogram.items():
            total[grade] += count
    return total


def difficulty_breakdown(records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Alvos de grau 2 recuperados por cada condição, por tipo de dificuldade.

    Descritivo, e a amostra por célula é de um dígito: descreve onde as
    diferenças caem, não estabelece causa.
    """
    buckets: dict[str, dict[str, Any]] = {}
    for record in records:
        for difficulty in record["difficulty_types"]:
            bucket = buckets.setdefault(
                difficulty,
                {
                    "difficulty_type": difficulty,
                    "questions": 0,
                    "targets": 0,
                    "recovered_c0": 0,
                    "recovered_c1": 0,
                },
            )
            bucket["questions"] += 1
            for target in record["analysis"]["targets"]:
                bucket["targets"] += 1
                if target["rank_c0"] is not None:
                    bucket["recovered_c0"] += 1
                if target["rank_c1"] is not None:
                    bucket["recovered_c1"] += 1
    return [buckets[key] for key in sorted(buckets)]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ground-truth", type=Path, required=True)
    parser.add_argument("--historical-ground-truth", type=Path, required=True)
    parser.add_argument("--repooling-requests", type=Path, required=True)
    parser.add_argument("--binding", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--dense-baseline", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--embedding-model", default=DEFAULT_EMBEDDING_MODEL)
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
            f"refusing to overwrite {args.output} without --overwrite",
            EXIT_OUTPUT_EXISTS,
        )

    ground_truth = _load_json(args.ground_truth)
    historical = _load_json(args.historical_ground_truth)
    requests = _load_json(args.repooling_requests)
    binding = _load_json(args.binding)
    baseline = _load_json(args.baseline)
    dense_baseline = _load_json(args.dense_baseline)

    verify_baseline_integrity(baseline)
    verify_baseline_integrity(dense_baseline)
    verify_requests_integrity(requests)
    verify_metric_protocol(ground_truth)
    repooling_report = verify_repooling_control(
        historical, ground_truth, requests, dense_baseline
    )

    if binding.get("snapshot_id") != ground_truth.get("snapshot_id"):
        raise ExperimentError(
            "the binding file and the ground truth refer to different snapshots",
            EXIT_SNAPSHOT_MISMATCH,
        )

    retrieval = baseline["retrieval"]
    language = retrieval["language"]
    top_k = retrieval["top_k"]
    official_only = retrieval["official_only"]
    institution_id = UUID(binding["institution_id"])
    reference_date = date.fromisoformat(ground_truth["reference_date"])

    document_index = {
        item["corpus_item_id"]: item["document_id"]
        for item in binding["items"]
        if item.get("in_corpus")
    }

    from app.embeddings.dependencies import get_embedding_model

    embedding_model = get_embedding_model(args.embedding_model)
    identity = embedding_model.identity
    lexical = PostgresLexicalRetriever()
    dense = PostgresDenseRetriever(embedding_model)

    with SessionLocalFactory() as db:
        snapshot = build_evaluation_snapshot(
            db,
            institution_id=institution_id,
            language=language,
            reference_date=reference_date,
            top_k=top_k,
            official_only=official_only,
        )
        if (
            snapshot.snapshot_id != ground_truth["snapshot_id"]
            or snapshot.corpus_digest != ground_truth["corpus_digest"]
        ):
            raise ExperimentError(
                "the corpus no longer matches S1; the comparison would not be "
                "comparable with the D4.2 baseline nor with the D4.8 experiment",
                EXIT_SNAPSHOT_MISMATCH,
            )

        retrievability = RetrievabilityContext(
            institution_id=institution_id,
            language=language,
            reference_date=reference_date,
            official_only=official_only,
        )
        verify_index_identity(db, context=retrievability, identity=identity)
        index_digest, indexed_vectors = embedding_index_digest(
            db,
            context=retrievability,
            identity=identity,
            document_index=document_index,
        )
        verify_index_matches_d48(index_digest, indexed_vectors, dense_baseline)

        context = RetrievalContext(
            institution_id=institution_id,
            language=language,
            reference_date=reference_date,
        )
        records = [
            _evaluate_question(
                db,
                question,
                lexical=lexical,
                dense=dense,
                document_index=document_index,
                context=context,
                top_k=top_k,
                official_only=official_only,
            )
            for question in ground_truth["questions"]
        ]

    verify_index_coverage(records)
    verify_c0_reproduces_d42(records, baseline)
    verify_reproduces_d48_rankings(records, dense_baseline)

    unjudged = [
        request for record in records for request in record.pop("repooling_requests")
    ]
    comparability = classify_comparability(len(unjudged))
    verify_comparable(comparability, unjudged)

    questions_by_id = {
        question["question_id"]: question for question in ground_truth["questions"]
    }
    for record in records:
        record["analysis"] = analyse_question(
            record, questions_by_id[record["question_id"]]
        )

    measured = [record for record in records if record["measured"]]
    aggregates = {
        condition: aggregate_metrics(
            [record["conditions"][condition]["metrics"] for record in measured]
        )
        for condition in CONDITIONS
    }

    payload: dict[str, Any] = {
        "experiment_version": EXPERIMENT_VERSION,
        "digest_algorithm": DIGEST_ALGORITHM,
        "corpus_id": ground_truth["corpus_id"],
        "snapshot_id": ground_truth["snapshot_id"],
        "corpus_digest": ground_truth["corpus_digest"],
        "reference_date": ground_truth["reference_date"],
        "ground_truth_digest": repooling_report["ground_truth_digest_after"],
        "ground_truth_digest_algorithm": DIGEST_ALGORITHM,
        "ground_truth_digest_scope": GROUND_TRUTH_DIGEST_SCOPE,
        "d42_baseline_result_digest": baseline["result_digest"],
        "d48_result_digest": dense_baseline["result_digest"],
        "repooling_requests_result_digest": requests["result_digest"],
        "c0_reproduces_d42_ranking": True,
        "c0_reproduces_d48_ranking": True,
        "c1_reproduces_d48_ranking": True,
        "repooling": repooling_report,
        "retrieval": retrieval,
        "conditions": _condition_identities(records),
        "embedding": {
            "provider": identity.provider,
            "model": identity.model,
            "dimension": identity.dimension,
            "normalization": identity.normalization,
            "similarity_metric": identity.similarity_metric,
            "configuration_version": identity.configuration_version,
            "embedded_text_field": "content",
            "index_digest": index_digest,
            "indexed_vectors": indexed_vectors,
            "approximate_index": False,
        },
        "primary_k": PRIMARY_K,
        "comparability": comparability,
        "comparability_note": (
            "A uniao dos dois top 5 esta inteiramente julgada. As metricas desta "
            "fase substituem as metricas PROVISORIAS de C1 no D4.8."
        ),
        "unjudged_in_top_k_total": 0,
        "aggregate": aggregates,
        "aggregate_delta_c1_minus_c0": _metric_deltas(aggregates),
        "complementarity": summarise_complementarity(records, measured_only=False),
        "complementarity_measured_only": summarise_complementarity(
            records, measured_only=True
        ),
        "dense_behaviour": dense_behaviour_summary(records),
        "difficulty_breakdown": difficulty_breakdown(records),
        "no_evidence_questions": [
            analyse_no_evidence_question(record, records)
            for record in records
            if record["no_relevant_evidence"]
        ],
        "excluded_questions": [
            {
                "question_id": record["question_id"],
                "exclusion_reason": questions_by_id[record["question_id"]][
                    "exclusion_reason"
                ],
            }
            for record in records
            if record["excluded_from_metrics"]
        ],
        "question_results": records,
    }
    payload["result_digest_scope"] = RESULT_DIGEST_SCOPE
    payload["execution_digest_scope"] = EXECUTION_DIGEST_SCOPE
    payload["reproducibility_note"] = (
        "Duas execucoes desta fase sobre o mesmo indice produzem rankings, graus e "
        "metricas identicos e similaridades de C1 ligeiramente diferentes: o "
        "fornecedor de embeddings nao e bit a bit determinista, como o D4.8 mediu na "
        "seccao 8.1. Por isso ha dois digests, e o canonico descreve o RESULTADO e "
        "nao a execucao. O result_digest cobre a projecao sem a similaridade bruta de "
        "C1 e TEM de ser identico entre execucoes sobre o mesmo indice e o mesmo "
        "ground truth; e a ele que a afirmacao de reprodutibilidade se refere e e ele "
        "que uma fase seguinte cita. O execution_digest cobre o payload como foi "
        "escrito, similaridades incluidas, e MUDA com a deriva do fornecedor - e e "
        "isso que o torna util: e o que deteta que os vetores nao sao os mesmos. A "
        "deriva fica preservada e visivel, nao arredondada para fora. Um artefacto "
        "com dois digests nao e verificavel pela guarda generica de digest unico; "
        "quem o consumir tem de usar app.evaluation.lexical_dense_comparison."
        "artefact_digests."
    )
    result_digest, execution_digest = artefact_digests(payload)
    payload["result_digest"] = result_digest
    payload["execution_digest"] = execution_digest
    payload["executed_at"] = datetime.now(UTC).isoformat()

    args.output.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    for condition in CONDITIONS:
        summary = aggregates[condition]
        print(
            f"{condition}  R@1={summary['recall']['1']:.4f} "
            f"R@3={summary['recall']['3']:.4f} R@5={summary['recall']['5']:.4f} "
            f"MRR={summary['mrr']:.4f} nDCG@5={summary['ndcg']['5']:.4f}"
        )
    destinations = payload["complementarity"]["grade2_by_destination"]
    print(
        "grau 2      : "
        + ", ".join(
            f"{key}={destinations[key]['count']}"
            for key in (BOTH, C0_ONLY, C1_ONLY, NEITHER)
        )
    )
    print(f"comparabilidade : {comparability}")
    print(f"index_digest    : {index_digest}")
    print(f"result_digest   : {result_digest}  (estavel entre execucoes)")
    print(f"execution_digest: {execution_digest}  (inclui similaridades; deriva)")
    print(f"written         : {args.output}")
    return EXIT_OK


def _condition_identities(
    records: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Identidade declarada de cada condição, lida do que ela produziu.

    ``score_kind`` e ``score_version`` vêm do resultado do retriever e não de
    uma constante escrita à mão: um artefacto que declarasse a semântica do
    score por convenção poderia descrever outra coisa que não a medida.
    """
    first = records[0]["conditions"]
    return {
        CONDITION_LEXICAL: {
            "label": "lexical",
            "retriever": "app.retrieval.lexical.PostgresLexicalRetriever",
            "query_preprocessing": QUERY_PREPROCESSING[CONDITION_LEXICAL],
            "score_kind": first[CONDITION_LEXICAL]["score_kind"],
            "score_version": first[CONDITION_LEXICAL]["score_version"],
            "relevance_threshold": "settings.retrieval_min_relevance_score",
            "can_return_empty": True,
        },
        CONDITION_DENSE: {
            "label": "dense",
            "retriever": "app.retrieval.dense.PostgresDenseRetriever",
            "query_preprocessing": QUERY_PREPROCESSING[CONDITION_DENSE],
            "score_kind": first[CONDITION_DENSE]["score_kind"],
            "score_version": first[CONDITION_DENSE]["score_version"],
            "relevance_threshold": None,
            "can_return_empty": False,
            "pipeline_version": DENSE_PIPELINE_VERSION,
        },
    }


def _metric_deltas(aggregates: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """C1 − C0, calculado e não transcrito à mão para o relatório."""
    c0 = aggregates[CONDITION_LEXICAL]
    c1 = aggregates[CONDITION_DENSE]
    return {
        "recall": {
            str(k): round(c1["recall"][str(k)] - c0["recall"][str(k)], 6)
            for k in K_VALUES
        },
        "mrr": round(c1["mrr"] - c0["mrr"], 6),
        "ndcg": {
            str(k): round(c1["ndcg"][str(k)] - c0["ndcg"][str(k)], 6) for k in K_VALUES
        },
    }


def _evaluate_question(
    db: Session,
    question: Mapping[str, Any],
    *,
    lexical: PostgresLexicalRetriever,
    dense: PostgresDenseRetriever,
    document_index: Mapping[str, str],
    context: RetrievalContext,
    top_k: int,
    official_only: bool,
) -> dict[str, Any]:
    """Executa as duas condições e compara-as, sem decidir nada.

    Mesma estrutura que o D4.8 — deliberadamente, para que a guarda de
    replicação compare como com como.
    """
    grades = judged_grades_by_anchor(question)
    judged_grades = sorted(grades.values(), reverse=True)
    measurable = (
        not question["no_relevant_evidence"] and not question["excluded_from_metrics"]
    )

    conditions: dict[str, dict[str, Any]] = {}
    queries = {
        CONDITION_LEXICAL: normalize_text(question["question"]),
        CONDITION_DENSE: question["question"],
    }
    for condition, retriever in (
        (CONDITION_LEXICAL, lexical),
        (CONDITION_DENSE, dense),
    ):
        record = evaluate_condition(
            db,
            question,
            condition=condition,
            retriever=retriever,
            query=queries[condition],
            document_index=document_index,
            grades=grades,
            context=context,
            top_k=top_k,
            official_only=official_only,
        )
        if measurable:
            record["metrics"] = condition_metrics(record["ranking"], judged_grades)
        conditions[condition] = record

    c0_pool = ranked_pool(conditions[CONDITION_LEXICAL]["ranking"])
    c1_pool = ranked_pool(conditions[CONDITION_DENSE]["ranking"])
    judged_items = [PoolItem(item, index) for item, index in grades]
    requests = build_repooling_requests(
        question_id=question["question_id"],
        c0_ranking=c0_pool,
        c1_ranking=c1_pool,
        judged=judged_items,
    )

    return {
        "question_id": question["question_id"],
        "temporal_scope": question["temporal_scope"],
        "difficulty_types": list(question["difficulty_types"]),
        "no_relevant_evidence": question["no_relevant_evidence"],
        "excluded_from_metrics": question["excluded_from_metrics"],
        "measured": measurable,
        "judged_grades": judged_grades,
        "union_size": len(union_pool(c0_pool, c1_pool)),
        "overlap": overlap_count(c0_pool, c1_pool),
        "exclusive_to_c0": [
            {"corpus_item_id": item.corpus_item_id, "chunk_index": item.chunk_index}
            for item in exclusive_to(c0_pool, c1_pool)
        ],
        "exclusive_to_c1": [
            {"corpus_item_id": item.corpus_item_id, "chunk_index": item.chunk_index}
            for item in exclusive_to(c1_pool, c0_pool)
        ],
        "conditions": conditions,
        "repooling_requests": [
            {
                "question_id": request.question_id,
                "corpus_item_id": request.corpus_item_id,
                "chunk_index": request.chunk_index,
                "retrieved_by": list(request.retrieved_by),
            }
            for request in requests
        ],
    }


if __name__ == "__main__":
    sys.exit(main())
