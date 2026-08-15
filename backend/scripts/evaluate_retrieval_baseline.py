"""Baseline lexical real sobre um Pilot Corpus e o seu Evaluation Snapshot.

Uso (a partir de ``backend/``, com o virtual environment ativo):

    python -m scripts.evaluate_retrieval_baseline \
        --ground-truth ../docs/evaluation/retrieval-ground-truth-p1-seed.json \
        --binding ../storage/pilot-corpus/S1-identifier-binding.json \
        --output ../docs/evaluation/retrieval-baseline-p1-s1.json \
        [--overwrite]

Mede o sistema **como ele é**. Não altera ranking, pesos, limiares, planeamento
de consulta, segmentação, extração, OCR, ``top_k`` nem estratégia: chama
``PostgresLexicalRetriever.search`` exatamente como o faz
``app.services.retrieval_service``, incluindo a normalização da pergunta.

O snapshot é condição de execução, não um campo do relatório
-------------------------------------------------------------

Antes de medir, o snapshot é **reconstruído** com o builder real e comparado com
o ``snapshot_id`` e o ``corpus_digest`` que o ficheiro de anotações declara. Se
divergirem, nada é escrito e o comando termina com erro: um resultado medido
contra outro corpus não é comparável com a baseline que diz continuar, e criar
um S2 em silêncio seria a pior forma de o descobrir.

O protocolo de métricas também é verificado, e não presumido: os valores
declarados em ``metric_protocol`` têm de coincidir com as constantes de
``app.evaluation.retrieval_metrics``.
"""

import argparse
import json
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Final
from uuid import UUID

from sqlalchemy import select

from app.core.text_normalization import normalize_text
from app.database.session import SessionLocal
from app.evaluation.results import canonical_json
from app.evaluation.retrieval_metrics import (
    BINARY_RELEVANCE_THRESHOLD,
    K_VALUES,
    NDCG_GAIN_BY_GRADE,
    PRIMARY_K,
    UNJUDGED_GRADE,
    mean,
    ndcg_at_k,
    recall_at_k,
    reciprocal_rank,
)
from app.evaluation.snapshot_builder import build_evaluation_snapshot
from app.models.document_chunk import DocumentChunk
from app.retrieval.base import RetrievalContext
from app.retrieval.eligibility import decide_eligibility
from app.retrieval.lexical import PostgresLexicalRetriever
from app.retrieval.query_planning import LexicalQueryStrategy
from app.retrieval.reranking import LexicalCandidate, compute_content_match

BASELINE_SCHEMA_VERSION: Final = "2"

#: Única convenção implementada para segmentos devolvidos e não julgados.
UNJUDGED_CHUNK_TREATMENT: Final = "ASSUMED_IRRELEVANT"
DIGEST_ALGORITHM: Final = "sha256"

EXIT_OK: Final = 0
EXIT_USAGE: Final = 2
EXIT_SNAPSHOT_MISMATCH: Final = 3
EXIT_PROTOCOL_MISMATCH: Final = 4
EXIT_OUTPUT_EXISTS: Final = 5
EXIT_BINDING_INCOMPLETE: Final = 6


class BaselineError(RuntimeError):
    """Falha que impede a produção de uma baseline defensável."""

    def __init__(self, message: str, exit_code: int) -> None:
        super().__init__(message)
        self.exit_code = exit_code


def _load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise BaselineError(f"file not found: {path}", EXIT_USAGE) from error
    except json.JSONDecodeError as error:
        raise BaselineError(f"invalid JSON in {path}: {error}", EXIT_USAGE) from error


def verify_metric_protocol(ground_truth: dict[str, Any]) -> None:
    """Recusa medir se o ficheiro declarar um protocolo diferente do implementado."""
    protocol = ground_truth.get("metric_protocol")
    if not isinstance(protocol, dict):
        raise BaselineError("ground truth has no metric_protocol", EXIT_PROTOCOL_MISMATCH)

    declared_gains = {int(key): value for key, value in protocol["ndcg_gain_mapping"].items()}
    mismatches: list[str] = []
    if tuple(protocol["k_values"]) != K_VALUES:
        mismatches.append(f"k_values {protocol['k_values']} != {list(K_VALUES)}")
    if protocol["primary_k"] != PRIMARY_K:
        mismatches.append(f"primary_k {protocol['primary_k']} != {PRIMARY_K}")
    if protocol["binary_relevance_threshold"] != BINARY_RELEVANCE_THRESHOLD:
        mismatches.append(
            f"binary_relevance_threshold {protocol['binary_relevance_threshold']} "
            f"!= {BINARY_RELEVANCE_THRESHOLD}"
        )
    if declared_gains != dict(NDCG_GAIN_BY_GRADE):
        mismatches.append(f"ndcg_gain_mapping {declared_gains} != {dict(NDCG_GAIN_BY_GRADE)}")
    # O runner aplica ASSUMED_IRRELEVANT sem alternativa implementada. Aceitar um
    # ficheiro que declare outra convenção produziria números cuja interpretação
    # documentada não corresponde ao que foi calculado.
    if protocol.get("unjudged_chunk_treatment") != UNJUDGED_CHUNK_TREATMENT:
        mismatches.append(
            f"unjudged_chunk_treatment {protocol.get('unjudged_chunk_treatment')!r} "
            f"!= {UNJUDGED_CHUNK_TREATMENT!r} (the only treatment implemented)"
        )
    if mismatches:
        raise BaselineError(
            "metric protocol in the ground truth does not match the implementation: "
            + "; ".join(mismatches),
            EXIT_PROTOCOL_MISMATCH,
        )


def verify_snapshot(
    db: object,
    *,
    ground_truth: dict[str, Any],
    binding: dict[str, Any],
    retrieval: dict[str, Any],
) -> None:
    """Reconstrói o snapshot e exige coincidência com o declarado."""
    snapshot = build_evaluation_snapshot(
        db,  # type: ignore[arg-type]
        institution_id=UUID(binding["institution_id"]),
        language=retrieval["language"],
        reference_date=date.fromisoformat(ground_truth["reference_date"]),
        top_k=retrieval["top_k"],
        official_only=retrieval["official_only"],
    )
    problems: list[str] = []
    if snapshot.snapshot_id != ground_truth["snapshot_id"]:
        problems.append(
            f"snapshot_id rebuilt {snapshot.snapshot_id} "
            f"!= declared {ground_truth['snapshot_id']}"
        )
    if snapshot.corpus_digest != ground_truth["corpus_digest"]:
        problems.append(
            f"corpus_digest rebuilt {snapshot.corpus_digest} "
            f"!= declared {ground_truth['corpus_digest']}"
        )
    if problems:
        raise BaselineError(
            "the corpus no longer matches the snapshot these judgments were made "
            "against; a new snapshot is required before measuring: " + "; ".join(problems),
            EXIT_SNAPSHOT_MISMATCH,
        )


def build_document_index(binding: dict[str, Any]) -> dict[str, str]:
    """``corpus_item_id`` -> ``document_id``, apenas para itens no corpus."""
    return {
        item["corpus_item_id"]: item["document_id"]
        for item in binding["items"]
        if item.get("in_corpus")
    }


def judgment_key(document_id: str, chunk_index: int) -> tuple[str, int]:
    return (document_id, chunk_index)


#: Destinos possíveis de um segmento de grau 2. São **observações**, não
#: diagnósticos: distinguem "o retriever nunca viu este segmento" de "viu-o e
#: rejeitou-o", que a métrica sozinha confunde num único zero. A interpretação
#: causal pertence ao relatório, onde pode ser argumentada e contestada.
FATE_RETURNED: Final = "RETURNED"
FATE_CANDIDATE_EXCLUDED: Final = "CANDIDATE_EXCLUDED"
FATE_NEVER_A_CANDIDATE: Final = "NEVER_A_CANDIDATE"
#: Não devolvido, não excluído, **e** o ``top_k`` truncou sobreviventes. Nesse
#: caso não é possível afirmar que o segmento nunca foi candidato: podia ter
#: sobrevivido e ficado abaixo do corte. Distinguir isto evita uma conclusão
#: causal errada quando o corte estiver ativo.
FATE_NOT_RETURNED_INDETERMINATE: Final = "NOT_RETURNED_INDETERMINATE"


def counterfactual_eligibility(
    db: object,
    *,
    document_id: str,
    chunk_index: int,
    query_terms: tuple[str, ...],
) -> dict[str, Any]:
    """Teria este segmento passado a elegibilidade lexical, se avaliado?

    Usa **as funções reais** ``compute_content_match`` e ``decide_eligibility``,
    e não uma aproximação. A distinção importa e já produziu uma conclusão
    errada: a geração de candidatos usa Full-Text Search, que faz *stemming*,
    enquanto a cobertura da elegibilidade compara **formas canónicas exatas**
    (``term in content_set``). Aproximar a segunda pela primeira sobrestima a
    correspondência — ``residencia`` casaria ``residencias``, que na
    elegibilidade real **não** casa.
    """
    row = db.execute(  # type: ignore[attr-defined]
        select(
            DocumentChunk.id,
            DocumentChunk.document_version_id,
            DocumentChunk.content,
            DocumentChunk.normalized_content,
            DocumentChunk.language,
            DocumentChunk.page_number,
            DocumentChunk.section_title,
            DocumentChunk.structure_type,
            DocumentChunk.chunking_strategy,
        ).where(
            DocumentChunk.document_id == UUID(document_id),
            DocumentChunk.chunk_index == chunk_index,
        )
    ).one()
    candidate = LexicalCandidate(
        chunk_id=row[0],
        document_id=UUID(document_id),
        document_version_id=row[1],
        document_title="",
        chunk_index=chunk_index,
        content=row[2],
        normalized_content=row[3],
        language=row[4],
        official_source=True,
        source_url=None,
        valid_from=None,
        valid_until=None,
        page_number=row[5],
        section_title=row[6],
        structure_type=row[7],
        chunking_strategy=row[8],
        raw_score=0.0,
        strategy=LexicalQueryStrategy.REDUCED_OR,
    )
    match = compute_content_match(query_terms, candidate)
    decision = decide_eligibility(query_terms, match, LexicalQueryStrategy.REDUCED_OR)
    return {
        "coverage": round(match.coverage, 6),
        "matched_terms": sorted(match.matched_terms),
        "would_be_eligible": decision.eligible,
        "exclusion_reason": None if decision.eligible else str(decision.reason),
    }


def describe_target_fate(
    db: object,
    question: dict[str, Any],
    *,
    document_index: dict[str, str],
    returned_keys: set[tuple[str, int]],
    trace: object,
    retrieved_count: int,
    query_terms: tuple[str, ...],
) -> list[dict[str, Any]]:
    """Onde acabou cada segmento de grau 2, e porquê.

    Um Recall de 0.0 tem causas muito diferentes: o segmento nunca entrou no
    conjunto de candidatos, entrou e foi rejeitado pela elegibilidade, ou
    sobreviveu e ficou abaixo do corte. Sem esta distinção a análise de falhas
    seria especulação sobre um número.

    Para os que não foram avaliados acrescenta-se o **contrafactual**: teriam
    passado a elegibilidade? Sem ele, "nunca foi candidato" seria lido como
    privação do conjunto de candidatos, quando pode ser um segmento que seria
    rejeitado de qualquer forma. As duas leituras apontam para trabalhos
    corretivos diferentes.
    """
    excluded_by_key = {
        (entry.document_id, entry.chunk_index): entry
        for entry in getattr(trace, "excluded", ())
    }
    truncated = trace.result_count_before_limit > retrieved_count  # type: ignore[attr-defined]
    fates: list[dict[str, Any]] = []
    for judgment in question["evidence_judgments"]:
        if judgment["relevance"] < BINARY_RELEVANCE_THRESHOLD:
            continue
        document_id = document_index[judgment["corpus_item_id"]]
        key = judgment_key(document_id, judgment["chunk_index"])
        record: dict[str, Any] = {
            "corpus_item_id": judgment["corpus_item_id"],
            "chunk_index": judgment["chunk_index"],
        }
        if key in returned_keys:
            record["fate"] = FATE_RETURNED
        elif key in excluded_by_key:
            entry = excluded_by_key[key]
            record["fate"] = FATE_CANDIDATE_EXCLUDED
            record["exclusion_reason"] = entry.reason
            record["coverage"] = round(entry.coverage, 6)
            record["matched_terms"] = sorted(entry.matched_terms)
        else:
            record["fate"] = (
                FATE_NOT_RETURNED_INDETERMINATE if truncated else FATE_NEVER_A_CANDIDATE
            )
            record["counterfactual"] = counterfactual_eligibility(
                db,
                document_id=document_id,
                chunk_index=judgment["chunk_index"],
                query_terms=query_terms,
            )
        fates.append(record)
    return fates


def evaluate_question(
    db: object,
    question: dict[str, Any],
    *,
    document_index: dict[str, str],
    context: RetrievalContext,
    retriever: PostgresLexicalRetriever,
    top_k: int,
    official_only: bool,
) -> dict[str, Any]:
    """Executa uma pergunta e resolve os graus observados, sem calcular métricas."""
    normalized_query = normalize_text(question["question"])
    result = retriever.search(db, normalized_query, context, top_k, official_only)  # type: ignore[arg-type]

    grades_by_key: dict[tuple[str, int], int] = {}
    for judgment in question["evidence_judgments"]:
        item = judgment["corpus_item_id"]
        if item not in document_index:
            raise BaselineError(
                f"{question['question_id']}: corpus_item_id {item!r} is not bound to a "
                "document in the corpus; the binding file does not describe this snapshot",
                EXIT_BINDING_INCOMPLETE,
            )
        grades_by_key[judgment_key(document_index[item], judgment["chunk_index"])] = judgment[
            "relevance"
        ]

    item_by_document = {value: key for key, value in document_index.items()}
    ranking: list[dict[str, Any]] = []
    returned_keys: set[tuple[str, int]] = set()
    for position, evidence in enumerate(result.evidence, start=1):
        key = judgment_key(str(evidence.document_id), evidence.chunk_index)
        returned_keys.add(key)
        grade = grades_by_key.get(key)
        ranking.append(
            {
                "position": position,
                "corpus_item_id": item_by_document.get(str(evidence.document_id)),
                "chunk_index": evidence.chunk_index,
                "score": round(evidence.score, 6),
                "relevance": UNJUDGED_GRADE if grade is None else grade,
                "judged": grade is not None,
            }
        )

    trace = result.trace
    query_terms = tuple(getattr(trace, "informative_terms", ()))
    return {
        "question_id": question["question_id"],
        "temporal_scope": question["temporal_scope"],
        "difficulty_types": question["difficulty_types"],
        "no_relevant_evidence": question["no_relevant_evidence"],
        "excluded_from_metrics": question["excluded_from_metrics"],
        "exclusion_reason": question["exclusion_reason"],
        "retrieved_count": len(result.evidence),
        "candidates_evaluated": trace.candidates_evaluated,
        "result_count_before_limit": trace.result_count_before_limit,
        # Planeamento e orçamento: sem isto, afirmações sobre variantes que não
        # produzem candidatos ou sobre utilização do orçamento não podem ser
        # reconstruídas a partir do artefacto versionado.
        "query_terms": list(query_terms),
        "candidate_budget": getattr(trace, "global_candidate_limit", None),
        "variants": [
            {
                "strategy": str(variant.strategy),
                "quota": variant.quota,
                "returned_count": variant.returned_count,
            }
            for variant in getattr(trace, "variants", ())
        ],
        "excluded_counts": {
            "no_content_match": getattr(trace, "excluded_no_content_match", None),
            "insufficient_coverage": getattr(trace, "excluded_insufficient_coverage", None),
            "below_threshold": getattr(trace, "excluded_below_threshold", None),
        },
        "ranking": ranking,
        "judged_grades": sorted(grades_by_key.values(), reverse=True),
        "target_fate": describe_target_fate(
            db,
            question,
            document_index=document_index,
            returned_keys=returned_keys,
            trace=trace,
            retrieved_count=len(result.evidence),
            query_terms=query_terms,
        ),
    }


def add_metrics(record: dict[str, Any]) -> dict[str, Any]:
    """Acrescenta métricas a uma pergunta medível. Não decide quem é medível."""
    retrieved_grades = [entry["relevance"] for entry in record["ranking"]]
    judged_grades = record["judged_grades"]
    total_relevant = sum(1 for g in judged_grades if g >= BINARY_RELEVANCE_THRESHOLD)

    record["total_relevant_judged"] = total_relevant
    record["recall"] = {
        str(k): round(recall_at_k(retrieved_grades, total_relevant, k), 6) for k in K_VALUES
    }
    record["reciprocal_rank"] = round(reciprocal_rank(retrieved_grades), 6)
    record["ndcg"] = {
        str(k): round(ndcg_at_k(retrieved_grades, judged_grades, k), 6) for k in K_VALUES
    }
    return record


def aggregate(measured: list[dict[str, Any]]) -> dict[str, Any]:
    """Macro-média sobre as perguntas medidas: cada pergunta pesa o mesmo."""
    return {
        "questions_measured": len(measured),
        "recall": {
            str(k): round(mean([record["recall"][str(k)] for record in measured]), 6)
            for k in K_VALUES
        },
        "mrr": round(mean([record["reciprocal_rank"] for record in measured]), 6),
        "ndcg": {
            str(k): round(mean([record["ndcg"][str(k)] for record in measured]), 6)
            for k in K_VALUES
        },
    }


def run(
    *,
    ground_truth_path: Path,
    binding_path: Path,
) -> dict[str, Any]:
    ground_truth = _load_json(ground_truth_path)
    binding = _load_json(binding_path)

    verify_metric_protocol(ground_truth)

    if binding.get("snapshot_id") != ground_truth.get("snapshot_id"):
        raise BaselineError(
            "the binding file and the ground truth refer to different snapshots",
            EXIT_SNAPSHOT_MISMATCH,
        )

    institution_id = UUID(binding["institution_id"])
    reference_date = date.fromisoformat(ground_truth["reference_date"])
    # Configuração da experiência: a de S1, lida do snapshot reconstruído, para
    # que a baseline não possa medir com parâmetros diferentes dos registados.
    retriever = PostgresLexicalRetriever()

    with SessionLocal() as db:
        probe = build_evaluation_snapshot(
            db,
            institution_id=institution_id,
            language="pt",
            reference_date=reference_date,
            top_k=PRIMARY_K,
            official_only=True,
        )
        retrieval = probe.retrieval.canonical()
        verify_snapshot(
            db, ground_truth=ground_truth, binding=binding, retrieval=retrieval
        )

        document_index = build_document_index(binding)
        context = RetrievalContext(
            institution_id=institution_id,
            language=retrieval["language"],
            reference_date=reference_date,
        )

        records = [
            evaluate_question(
                db,
                question,
                document_index=document_index,
                context=context,
                retriever=retriever,
                top_k=retrieval["top_k"],
                official_only=retrieval["official_only"],
            )
            for question in ground_truth["questions"]
        ]

    measured: list[dict[str, Any]] = []
    observed_only: list[dict[str, Any]] = []
    for record in records:
        if record["no_relevant_evidence"] or record["excluded_from_metrics"]:
            observed_only.append(record)
            continue
        measured.append(add_metrics(record))

    payload: dict[str, Any] = {
        "schema_version": BASELINE_SCHEMA_VERSION,
        "digest_algorithm": DIGEST_ALGORITHM,
        "corpus_id": ground_truth["corpus_id"],
        "snapshot_id": ground_truth["snapshot_id"],
        "corpus_digest": ground_truth["corpus_digest"],
        "reference_date": ground_truth["reference_date"],
        "snapshot_verified_before_execution": True,
        "retrieval": retrieval,
        "metric_protocol": {
            "k_values": list(K_VALUES),
            "primary_k": PRIMARY_K,
            "binary_relevance_threshold": BINARY_RELEVANCE_THRESHOLD,
            "ndcg_gain_mapping": {str(k): v for k, v in NDCG_GAIN_BY_GRADE.items()},
            "unjudged_chunk_treatment": UNJUDGED_CHUNK_TREATMENT,
            "aggregation": "macro_average_over_measured_questions",
        },
        "questions_total": len(records),
        "aggregate": aggregate(measured),
        "question_results": sorted(measured, key=lambda record: record["question_id"]),
        "observed_only": sorted(observed_only, key=lambda record: record["question_id"]),
    }
    return payload


def result_digest(payload: dict[str, Any]) -> str:
    """Digest do conteúdo experimental, **sem** o carimbo temporal.

    ``executed_at`` muda a cada execução por construção; incluí-lo tornaria duas
    execuções idênticas indistinguíveis de duas execuções divergentes.
    """
    import hashlib

    without_timestamp = {key: value for key, value in payload.items() if key != "executed_at"}
    return hashlib.sha256(canonical_json(without_timestamp).encode("utf-8")).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ground-truth", required=True, type=Path)
    parser.add_argument("--binding", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)

    try:
        payload = run(ground_truth_path=args.ground_truth, binding_path=args.binding)
    except BaselineError as error:
        print(f"error: {error}", file=sys.stderr)
        return error.exit_code

    payload["result_digest"] = result_digest(payload)
    payload["executed_at"] = datetime.now(UTC).isoformat()

    output: Path = args.output
    if output.exists() and not args.overwrite:
        print(f"error: {output} already exists (use --overwrite)", file=sys.stderr)
        return EXIT_OUTPUT_EXISTS
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    aggregate_metrics = payload["aggregate"]
    print(f"snapshot verified : {payload['snapshot_id']}")
    print(f"questions total   : {payload['questions_total']}")
    print(f"questions measured: {aggregate_metrics['questions_measured']}")
    for k in K_VALUES:
        print(f"Recall@{k}          : {aggregate_metrics['recall'][str(k)]:.4f}")
    print(f"MRR               : {aggregate_metrics['mrr']:.4f}")
    for k in K_VALUES:
        print(f"nDCG@{k}            : {aggregate_metrics['ndcg'][str(k)]:.4f}")
    print(f"result_digest     : {payload['result_digest']}")
    print(f"written           : {output}")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
