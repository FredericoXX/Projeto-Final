"""Baseline experimental de dense retrieval sobre P1/S1 (D4.8).

Uso (a partir de ``backend/``, com o virtual environment ativo, depois de
``python -m scripts.embed_pilot_corpus``):

    python -m scripts.evaluate_dense_baseline \
        --ground-truth ../docs/evaluation/retrieval-ground-truth-p1-repooled.json \
        --binding ../storage/pilot-corpus/S1-identifier-binding.json \
        --baseline ../docs/evaluation/retrieval-baseline-p1-s1.json \
        --variants ../docs/evaluation/ranking-variants-p1-s1.json \
        --output ../docs/evaluation/dense-baseline-p1-s1.json \
        --repooling-output ../docs/evaluation/dense-repooling-requests-p1-s1.json \
        [--overwrite]

Executa as mesmas 14 perguntas de P1/S1 em duas condições e compara-as:

- **C0 — lexical.** ``PostgresLexicalRetriever.search``, o retriever de
  produção, chamado exatamente como o chama ``app.services.retrieval_service``.
  Nada é reimplementado.
- **C1 — denso.** ``PostgresDenseRetriever.search``, sobre os vetores
  persistidos por ``scripts.embed_pilot_corpus``, reutilizando a mesma
  ``RetrievalEligibility``.

Não implementa nem simula recuperação híbrida, RRF, reranking semântico ou
qualquer combinação das duas condições. Não altera o retrieval de produção:
nenhuma rota resolve o retriever denso.

A pergunta que cada condição recebe
-----------------------------------

C0 recebe a pergunta **normalizada** (``normalize_text``), como em produção e
como no D4.2. C1 recebe a pergunta **original**, porque foi a forma original do
``content`` que foi embebida — alimentar o modelo com texto sem acentos nem
maiúsculas degradaria deliberadamente a condição que se quer medir. As duas
partem da mesma string do ground truth; o que difere é o pré-processamento que
cada pipeline define para si, e é assim que cada uma seria efetivamente
executada. Está declarado no artefacto (``query_preprocessing``).

Guardas, por ordem de execução
------------------------------

1. **Integridade dos artefactos consumidos.** O ficheiro do D4.2 e o do D4.7
   têm de coincidir com o seu próprio ``result_digest``. Reproduzir os números
   não substitui esta verificação: eles são recalculados a partir da base e
   continuariam a coincidir com um digest adulterado.
2. **Protocolo de métricas.** O ``metric_protocol`` do ground truth tem de
   declarar exatamente as constantes implementadas.
3. **Identidade do ground truth.** O digest do conjunto de perguntas tem de ser
   o do conjunto repooled do D4.6, e o mesmo que o D4.7 declara ter consumido.
4. **Snapshot.** O corpus reconstruído tem de continuar a ser S1.
5. **Identidade e cobertura do índice vetorial.** Primeiro, o índice tem de ser
   **homogéneo** para a identidade declarada — sem vetores de outra
   ``configuration_version`` e sem vetores cujo conteúdo o chunk já não tem.
   Depois, todos os segmentos admissíveis têm de ter vetor **dessa** identidade.
   As duas sobrepõem-se em parte, e a diferença está em ``verify_index_identity``:
   a homogeneidade dá o diagnóstico da configuração divergente e é a única a
   apanhar o vetor obsoleto, que satisfaz a identidade e conta como coberto.
6. **Replicação de C0.** O ranking posicional de C0 tem de reproduzir o do
   D4.2, pergunta a pergunta, e as suas métricas sob o conjunto repooled têm de
   reproduzir a célula de controlo do D4.7. Sem isto, qualquer diferença
   observada entre C0 e C1 poderia ser uma diferença entre duas execuções de C0.

Se qualquer uma falhar, **nada é escrito**.
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
from sqlalchemy.orm import Session

from app.core.text_normalization import normalize_text
from app.documents.retrievability import (
    RetrievabilityContext,
    RetrievalEligibility,
)
from app.embeddings.base import EmbeddingIdentity
from app.evaluation.dense_baseline import (
    CONDITION_DENSE,
    CONDITION_LEXICAL,
    CONDITIONS,
    REPOOLING_REQUIRED,
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
from app.evaluation.results import canonical_json
from app.evaluation.retrieval_metrics import (
    BINARY_RELEVANCE_THRESHOLD,
    K_VALUES,
    PRIMARY_K,
    UNJUDGED_GRADE,
    mean,
    ndcg_at_k,
    recall_at_k,
    reciprocal_rank,
)
from app.evaluation.snapshot_builder import build_evaluation_snapshot
from app.models.chunk_embedding import ChunkEmbedding
from app.models.document_chunk import DocumentChunk
from app.retrieval.base import RetrievalContext
from app.retrieval.dense import DENSE_PIPELINE_VERSION, PostgresDenseRetriever
from app.retrieval.lexical import PostgresLexicalRetriever
from scripts.embed_pilot_corpus import (
    DEFAULT_EMBEDDING_MODEL,
    content_digest,
    vector_digest,
)
from scripts.evaluate_retrieval_baseline import verify_metric_protocol
from scripts.evaluate_retrieval_experiment import (
    EXIT_BASELINE_MISMATCH,
    EXIT_OK,
    EXIT_OUTPUT_EXISTS,
    EXIT_SNAPSHOT_MISMATCH,
    ExperimentError,
    SessionLocalFactory,
    _corpus_item_for,
    _load_json,
    _ranking_signature,
    verify_baseline_integrity,
)

EXPERIMENT_VERSION: Final = "d4.8-dense-baseline-1"
DIGEST_ALGORITHM: Final = "sha256"

#: Índice vetorial incompleto: uma condição que não vê parte do corpus não é
#: comparável com uma que o vê inteiro.
EXIT_INDEX_INCOMPLETE: Final = 7

#: Identidade do conjunto de perguntas repooled do D4.6. É declarada aqui, e não
#: lida do ficheiro, porque uma comparação D4.8 tem de estar ligada a um conjunto
#: concreto: ler o digest do próprio ficheiro que se está a usar verificaria
#: apenas que o ficheiro é consistente consigo mesmo.
EXPECTED_GROUND_TRUTH_DIGEST: Final = (
    "ada6b38886a06910e425e4be164099a3a63320050890253404064e3fde88586e"
)

#: Célula de controlo do D4.7 que C0 tem de reproduzir: pesos de produção,
#: orçamento de produção.
D47_CONTROL_VARIANT: Final = "A0"
D47_CONTROL_POLICY: Final = "current_quota"

#: Pré-processamento declarado de cada condição — ver o docstring do módulo.
QUERY_PREPROCESSING: Final[Mapping[str, str]] = {
    CONDITION_LEXICAL: "normalize_text",
    CONDITION_DENSE: "none",
}


# ---------------------------------------------------------------------------
# Identidade do índice vetorial
# ---------------------------------------------------------------------------


def verify_index_identity(
    db: Session,
    *,
    context: RetrievabilityContext,
    identity: EmbeddingIdentity,
) -> None:
    """Recusa um índice **misto** ou **obsoleto** sobre o corpus admissível.

    Duas condições, verificadas sobre as linhas cujo ``(provider, model)``
    coincide com o declarado:

    - **configuração divergente**: alguma linha com outra
      ``configuration_version``. É a assinatura de uma reindexação a meio;
    - **conteúdo obsoleto**: alguma linha cujo ``embedded_content_sha256`` já
      não é o SHA-256 do ``content`` **atual** do chunk. O vetor descreve texto
      que já não existe.

    O que esta guarda acrescenta à cobertura
    ----------------------------------------

    A cobertura filtra pela identidade completa, pelo que uma reindexação
    interrompida a meio já lhe aparece como **cobertura parcial**. As duas
    guardas não são, por isso, redundantes da forma que se poderia supor:

    - na configuração divergente **sobrepõem-se**, e o valor desta é o
      diagnóstico. A cobertura diria «1830 de 1834 segmentos embebidos», que se
      lê como *falta indexar*; esta diz que os vetores existem e são de outra
      configuração, que é um problema diferente e com outra correção. Corre
      também **antes** de qualquer pesquisa, e não por pergunta;
    - no conteúdo obsoleto **só esta apanha**. Um vetor obsoleto satisfaz a
      identidade e conta como coberto: para a cobertura, o segmento está
      indexado.

    O SHA é **recalculado** a partir do ``content``, e não comparado com o
    ``content_sha256`` persistido. Comparar dois valores persistidos deixaria
    passar exatamente o caso que interessa: se o conteúdo mudar sem que o hash
    do chunk seja atualizado, os dois valores obsoletos coincidem entre si e a
    verificação passaria sobre um vetor que descreve texto que já não existe. É
    a mesma definição que a indexação usa quando envia o texto.

    Em qualquer dos casos nada é escrito: um artefacto produzido sobre um índice
    misto declararia uma configuração que não descreve os vetores usados.
    """
    eligible = RetrievalEligibility.select_eligible_chunk_ids(context).subquery(
        "eligible_chunks"
    )
    rows = db.execute(
        select(
            ChunkEmbedding.configuration_version,
            ChunkEmbedding.embedded_content_sha256,
            DocumentChunk.content,
        )
        .join(eligible, eligible.c.id == DocumentChunk.id)
        .join(
            ChunkEmbedding,
            (ChunkEmbedding.chunk_id == DocumentChunk.id)
            & (ChunkEmbedding.provider == identity.provider)
            & (ChunkEmbedding.model == identity.model),
        )
    ).all()

    divergent = sorted(
        {
            configuration
            for configuration, _, _ in rows
            if configuration != identity.configuration_version
        }
    )
    stale = sum(1 for _, embedded, content in rows if embedded != content_digest(content))

    problems: list[str] = []
    if divergent:
        problems.append(
            f"vectors of other configurations are present: {divergent} "
            f"(declared {identity.configuration_version!r})"
        )
    if stale:
        problems.append(
            f"{stale} vectors describe content the chunk no longer has"
        )
    if problems:
        raise ExperimentError(
            "the vector index is not homogeneous for the declared identity "
            f"{identity.provider}:{identity.model}; the artefact would be "
            "labelled with a configuration that does not describe the vectors "
            "used: " + "; ".join(problems),
            EXIT_INDEX_INCOMPLETE,
        )


def embedding_index_digest(
    db: Session,
    *,
    context: RetrievabilityContext,
    identity: EmbeddingIdentity,
    document_index: Mapping[str, str],
) -> tuple[str, int]:
    """Digest do índice vetorial e número de vetores que o compõem.

    Cobre **quatro** coisas, e é preciso que cubra as quatro: a identidade
    completa do índice, a âncora do segmento, o SHA do texto que foi embebido e
    o conteúdo binário do próprio vetor. Sem a última, reembeber o mesmo texto
    pelo mesmo modelo produziria um digest igual com vetores diferentes — e a
    deriva do fornecedor passaria despercebida exatamente onde importa. Sem a
    primeira, dois índices de fornecedores ou configurações diferentes poderiam
    partilhar digest.

    Usa a âncora do protocolo (``corpus_item_id`` + ``chunk_index``) e nunca os
    UUID locais: o digest tem de descrever o corpus, não a instalação.
    """
    eligible = RetrievalEligibility.select_eligible_chunk_ids(context).subquery(
        "eligible_chunks"
    )
    rows = db.execute(
        select(
            DocumentChunk.document_id,
            DocumentChunk.chunk_index,
            ChunkEmbedding.embedded_content_sha256,
            ChunkEmbedding.embedding,
        )
        .join(eligible, eligible.c.id == DocumentChunk.id)
        .join(
            ChunkEmbedding,
            (ChunkEmbedding.chunk_id == DocumentChunk.id)
            & ChunkEmbedding.matches_identity(identity),
        )
    ).all()

    entries: list[list[Any]] = []
    for document_id, chunk_index, content_sha256, vector in rows:
        corpus_item_id = _corpus_item_for(str(document_id), document_index)
        if corpus_item_id is None:
            raise ExperimentError(
                f"document {document_id} is embedded but is not bound to a "
                "corpus item; the binding file does not describe this snapshot",
                EXIT_SNAPSHOT_MISMATCH,
            )
        values = [float(value) for value in vector]
        entries.append(
            [corpus_item_id, chunk_index, content_sha256, vector_digest(values)]
        )

    entries.sort(key=lambda entry: (entry[0], entry[1]))
    payload = {
        "provider": identity.provider,
        "model": identity.model,
        "configuration_version": identity.configuration_version,
        "entries": entries,
    }
    digest = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    return digest, len(entries)


# ---------------------------------------------------------------------------
# Execução de uma condição
# ---------------------------------------------------------------------------


def evaluate_condition(
    db: Session,
    question: Mapping[str, Any],
    *,
    condition: str,
    retriever: Any,
    query: str,
    document_index: Mapping[str, str],
    grades: Mapping[tuple[str, int], int],
    context: RetrievalContext,
    top_k: int,
    official_only: bool,
) -> dict[str, Any]:
    """Executa uma pergunta numa condição e devolve o registo comparável.

    O mesmo formato para as duas condições, para que a comparação não dependa de
    quem produziu o registo. O que é específico de cada estratégia vive em
    ``trace``, com as chaves que essa estratégia sabe produzir.
    """
    result = retriever.search(db, query, context, top_k, official_only)
    trace = result.trace

    ranking: list[dict[str, Any]] = []
    for position, evidence in enumerate(result.evidence, start=1):
        corpus_item_id = _corpus_item_for(str(evidence.document_id), document_index)
        if corpus_item_id is None:
            raise ExperimentError(
                f"{question['question_id']}: document {evidence.document_id} is not "
                "bound to a corpus item",
                EXIT_SNAPSHOT_MISMATCH,
            )
        grade = grades.get((corpus_item_id, evidence.chunk_index))
        ranking.append(
            {
                "position": position,
                "corpus_item_id": corpus_item_id,
                "chunk_index": evidence.chunk_index,
                "score": round(float(evidence.score), 6),
                "grade": UNJUDGED_GRADE if grade is None else grade,
                "judged": grade is not None,
            }
        )

    record: dict[str, Any] = {
        "condition": condition,
        "retrieved_count": len(result.evidence),
        "candidates_evaluated": trace.candidates_evaluated,
        "result_count_before_limit": trace.result_count_before_limit,
        "score_kind": str(result.score_semantics.kind),
        "score_version": result.score_semantics.version,
        "comparable_across_queries": result.score_semantics.comparable_across_queries,
        "ranking": ranking,
    }
    if condition == CONDITION_LEXICAL:
        record["candidate_budget"] = getattr(trace, "global_candidate_limit", None)
        record["excluded_counts"] = {
            "no_content_match": getattr(trace, "excluded_no_content_match", None),
            "insufficient_coverage": getattr(trace, "excluded_insufficient_coverage", None),
            "below_threshold": getattr(trace, "excluded_below_threshold", None),
        }
    else:
        record["candidate_budget"] = getattr(trace, "candidate_limit", None)
        record["admissible_chunks"] = getattr(trace, "admissible_chunks", None)
        record["embedded_chunks"] = getattr(trace, "embedded_chunks", None)
        record["similarity_metric"] = getattr(trace, "similarity_metric", None)
    return record


def condition_metrics(
    ranking: Sequence[Mapping[str, Any]], judged_grades: Sequence[int]
) -> dict[str, Any]:
    """As métricas do protocolo, sobre um ranking já resolvido em graus."""
    retrieved_grades = [int(entry["grade"]) for entry in ranking]
    total_relevant = sum(
        1 for grade in judged_grades if grade >= BINARY_RELEVANCE_THRESHOLD
    )
    return {
        "total_relevant_judged": total_relevant,
        "recall": {
            str(k): round(recall_at_k(retrieved_grades, total_relevant, k), 6)
            for k in K_VALUES
        },
        "reciprocal_rank": round(reciprocal_rank(retrieved_grades), 6),
        "ndcg": {
            str(k): round(ndcg_at_k(retrieved_grades, judged_grades, k), 6)
            for k in K_VALUES
        },
    }


def aggregate_metrics(measured: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Macro-média: cada pergunta pesa o mesmo, como no D4.2."""
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


# ---------------------------------------------------------------------------
# Guardas
# ---------------------------------------------------------------------------


def verify_ground_truth_identity(
    ground_truth: Mapping[str, Any], variants: Mapping[str, Any]
) -> str:
    """O conjunto de perguntas tem de ser o repooled do D4.6, e o do D4.7."""
    digest = ground_truth_digest(ground_truth)
    problems: list[str] = []
    if digest != EXPECTED_GROUND_TRUTH_DIGEST:
        problems.append(
            f"ground_truth_digest {digest} != expected {EXPECTED_GROUND_TRUTH_DIGEST}"
        )
    declared = variants.get("ground_truth_digest")
    if declared != digest:
        problems.append(
            f"the D4.7 artefact declares ground_truth_digest {declared}, "
            f"not {digest}"
        )
    if problems:
        raise ExperimentError(
            "the question set is not the one D4.8 is defined against: "
            + "; ".join(problems),
            EXIT_BASELINE_MISMATCH,
        )
    return digest


def verify_index_coverage(records: Sequence[Mapping[str, Any]]) -> None:
    """Nenhum segmento admissível pode ficar de fora do índice vetorial."""
    problems: list[str] = []
    for record in records:
        dense = record["conditions"][CONDITION_DENSE]
        admissible = dense["admissible_chunks"]
        embedded = dense["embedded_chunks"]
        if admissible != embedded:
            problems.append(
                f"{record['question_id']}: {embedded} of {admissible} admissible "
                "chunks are embedded"
            )
    if problems:
        raise ExperimentError(
            "the vector index does not cover the admissible corpus; C1 would be "
            "measured against a smaller corpus than C0: " + "; ".join(problems),
            EXIT_INDEX_INCOMPLETE,
        )


def verify_c0_reproduces_d42(
    records: Sequence[Mapping[str, Any]], baseline: Mapping[str, Any]
) -> None:
    """O ranking de C0 tem de ser, posição a posição, o do D4.2.

    Compara **todas** as perguntas, incluindo as que o D4.2 arruma em
    ``observed_only`` — a pergunta sem evidência relevante e a excluída das
    métricas continuam a ser execuções do retriever e teriam de mudar se o
    retriever tivesse mudado.

    As métricas do D4.2 **não** são comparadas aqui, e isso é deliberado: foram
    medidas contra o conjunto *seed*, e este experimento mede contra o conjunto
    repooled. O que tem de ser idêntico é o que o retriever devolveu; os números
    mudam porque mudou a densidade da anotação, não o sistema.
    """
    reference = {
        result["question_id"]: result
        for result in [*baseline["question_results"], *baseline.get("observed_only", [])]
    }
    got = {record["question_id"]: record for record in records}

    problems: list[str] = []
    missing = sorted(set(reference) - set(got))
    extra = sorted(set(got) - set(reference))
    if missing:
        problems.append(f"questions missing from C0: {missing}")
    if extra:
        problems.append(f"questions absent from the D4.2 baseline: {extra}")

    for question_id in sorted(set(reference) & set(got)):
        lexical = got[question_id]["conditions"][CONDITION_LEXICAL]
        want = reference[question_id]
        if lexical["retrieved_count"] != want["retrieved_count"]:
            problems.append(
                f"{question_id} retrieved_count {lexical['retrieved_count']} "
                f"!= D4.2 {want['retrieved_count']}"
            )
        got_ranking = _ranking_signature(lexical["ranking"])
        want_ranking = _ranking_signature(want["ranking"])
        if got_ranking != want_ranking:
            problems.append(
                f"{question_id} ranking {got_ranking} != D4.2 {want_ranking}"
            )

    if problems:
        raise ExperimentError(
            "C0 does not reproduce the D4.2 lexical baseline; a difference between "
            "C0 and C1 could be a difference between two runs of C0: "
            + "; ".join(problems),
            EXIT_BASELINE_MISMATCH,
        )


def _close(got: float, want: float) -> bool:
    return abs(got - want) <= 1e-9


def verify_c0_reproduces_d47_control(
    records: Sequence[Mapping[str, Any]],
    aggregate: Mapping[str, Any],
    variants: Mapping[str, Any],
) -> None:
    """As métricas de C0 sob o conjunto repooled têm de ser as do controlo D4.7.

    O D4.7 mediu a configuração de produção contra este mesmo conjunto de
    julgamentos. Se C0 divergir dele, ou o protocolo foi aplicado de outra
    maneira aqui, ou o sistema mudou — e em qualquer dos casos a comparação com
    C1 mediria essa diferença por engano.
    """
    control = next(
        (
            cell
            for cell in variants["cells"]
            if cell["variant_id"] == D47_CONTROL_VARIANT
            and cell["budget_policy"] == D47_CONTROL_POLICY
        ),
        None,
    )
    if control is None:
        raise ExperimentError(
            f"the D4.7 artefact has no {D47_CONTROL_VARIANT}/{D47_CONTROL_POLICY} cell",
            EXIT_BASELINE_MISMATCH,
        )

    problems: list[str] = []
    # O D4.7 mantém as 14 perguntas em ``question_results`` e marca as duas não
    # medidas com ``measured: false``, sem chaves de métrica. A comparação é
    # entre os conjuntos **medidos** dos dois lados — que é também a forma de
    # detetar que uma pergunta deixou de ser medida aqui e continua a sê-lo lá.
    reference = {
        result["question_id"]: result
        for result in control["question_results"]
        if "recall" in result
    }
    measured = {
        record["question_id"]: record["conditions"][CONDITION_LEXICAL]["metrics"]
        for record in records
        if "metrics" in record["conditions"][CONDITION_LEXICAL]
    }
    if sorted(measured) != sorted(reference):
        problems.append(
            f"measured questions {sorted(measured)} != D4.7 control {sorted(reference)}"
        )
    for question_id in sorted(set(measured) & set(reference)):
        for k in K_VALUES:
            for metric in ("recall", "ndcg"):
                got = measured[question_id][metric][str(k)]
                want = reference[question_id][metric][str(k)]
                if not _close(got, want):
                    problems.append(
                        f"{question_id} {metric}@{k} {got} != D4.7 control {want}"
                    )
        got_rr = measured[question_id]["reciprocal_rank"]
        want_rr = reference[question_id]["reciprocal_rank"]
        if not _close(got_rr, want_rr):
            problems.append(
                f"{question_id} reciprocal_rank {got_rr} != D4.7 control {want_rr}"
            )

    control_aggregate = control["aggregate"]
    if aggregate["questions_measured"] != control_aggregate["questions_measured"]:
        problems.append(
            f"questions_measured {aggregate['questions_measured']} "
            f"!= D4.7 control {control_aggregate['questions_measured']}"
        )
    if not _close(aggregate["mrr"], control_aggregate["mrr"]):
        problems.append(
            f"aggregate mrr {aggregate['mrr']} != D4.7 control {control_aggregate['mrr']}"
        )
    for k in K_VALUES:
        for metric in ("recall", "ndcg"):
            got = aggregate[metric][str(k)]
            want = control_aggregate[metric][str(k)]
            if not _close(got, want):
                problems.append(
                    f"aggregate {metric}@{k} {got} != D4.7 control {want}"
                )

    if problems:
        raise ExperimentError(
            "C0 does not reproduce the D4.7 control cell under the repooled "
            "judgments: " + "; ".join(problems),
            EXIT_BASELINE_MISMATCH,
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ground-truth", type=Path, required=True)
    parser.add_argument("--binding", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--variants", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repooling-output", type=Path, required=True)
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
    for path in (args.output, args.repooling_output):
        if path.exists() and not args.overwrite:
            raise ExperimentError(
                f"refusing to overwrite {path} without --overwrite", EXIT_OUTPUT_EXISTS
            )

    ground_truth = _load_json(args.ground_truth)
    binding = _load_json(args.binding)
    baseline = _load_json(args.baseline)
    variants = _load_json(args.variants)

    # Os dois artefactos consumidos têm de ser aqueles que os seus digests
    # declaram. Ver a guarda 1 no docstring do módulo.
    verify_baseline_integrity(baseline)
    verify_baseline_integrity(variants)
    verify_metric_protocol(ground_truth)
    digest = verify_ground_truth_identity(ground_truth, variants)

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
                "the corpus no longer matches S1; the experiment would not be "
                "comparable with the D4.2 baseline",
                EXIT_SNAPSHOT_MISMATCH,
            )

        retrievability = RetrievabilityContext(
            institution_id=institution_id,
            language=language,
            reference_date=reference_date,
            official_only=official_only,
        )
        # Homogeneidade antes de cobertura: um índice misto tem a contagem
        # certa e os vetores errados.
        verify_index_identity(db, context=retrievability, identity=identity)
        index_digest, indexed_vectors = embedding_index_digest(
            db,
            context=retrievability,
            identity=identity,
            document_index=document_index,
        )

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

    measured = [
        record
        for record in records
        if "metrics" in record["conditions"][CONDITION_LEXICAL]
    ]
    aggregates = {
        condition: aggregate_metrics(
            [record["conditions"][condition]["metrics"] for record in measured]
        )
        for condition in CONDITIONS
    }
    verify_c0_reproduces_d47_control(records, aggregates[CONDITION_LEXICAL], variants)

    repooling = [
        request
        for record in records
        for request in record.pop("repooling_requests")
    ]
    unjudged_total = len(repooling)
    comparability = classify_comparability(unjudged_total)

    payload: dict[str, Any] = {
        "experiment_version": EXPERIMENT_VERSION,
        "digest_algorithm": DIGEST_ALGORITHM,
        "corpus_id": ground_truth["corpus_id"],
        "snapshot_id": ground_truth["snapshot_id"],
        "corpus_digest": ground_truth["corpus_digest"],
        "reference_date": ground_truth["reference_date"],
        "ground_truth_digest": digest,
        "ground_truth_digest_algorithm": DIGEST_ALGORITHM,
        "ground_truth_digest_scope": GROUND_TRUTH_DIGEST_SCOPE,
        "d42_baseline_result_digest": baseline["result_digest"],
        "d47_result_digest": variants["result_digest"],
        "c0_reproduces_d42_ranking": True,
        "c0_reproduces_d47_control": True,
        "retrieval": retrieval,
        "conditions": list(CONDITIONS),
        "query_preprocessing": dict(QUERY_PREPROCESSING),
        "embedding": {
            # A identidade viaja inteira, e é a mesma pela qual o índice foi
            # filtrado, verificado e resumido em digest.
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
        "dense_pipeline_version": DENSE_PIPELINE_VERSION,
        "dense_relevance_threshold": None,
        "primary_k": PRIMARY_K,
        "comparability": comparability,
        "comparability_note": (
            "As metricas de C1 sao PROVISORIAS enquanto houver resultados por "
            "julgar: sob ASSUMED_IRRELEVANT um segmento nunca julgado conta grau "
            "0, o que penaliza a condicao nova por ser nova. Nenhum vencedor "
            "pode ser declarado antes do repooling."
            if comparability == REPOOLING_REQUIRED
            else "A uniao dos dois top 5 esta inteiramente julgada."
        ),
        "unjudged_in_top_k_total": unjudged_total,
        "questions_with_unjudged": sorted(
            {request["question_id"] for request in repooling}
        ),
        "aggregate": aggregates,
        "question_results": records,
    }
    payload["result_digest"] = hashlib.sha256(
        canonical_json(payload).encode("utf-8")
    ).hexdigest()
    payload["executed_at"] = datetime.now(UTC).isoformat()

    repooling_payload: dict[str, Any] = {
        "schema_version": "1",
        "contract": "retrieval_repooling_requests",
        "source_experiment": EXPERIMENT_VERSION,
        "corpus_id": ground_truth["corpus_id"],
        "snapshot_id": ground_truth["snapshot_id"],
        "corpus_digest": ground_truth["corpus_digest"],
        "ground_truth_digest": digest,
        "scope_note": (
            "Pares pergunta/segmento que entraram no top 5 de C0 ou de C1 e nao "
            "tem julgamento no conjunto repooled do D4.6. Enquanto esta lista nao "
            "estiver vazia, a comparacao C0 x C1 nao e definitiva. A ancora e "
            "corpus_item_id + chunk_index; nenhum texto documental e versionado."
        ),
        "requests_total": len(repooling),
        "requests": repooling,
    }
    repooling_payload["result_digest"] = hashlib.sha256(
        canonical_json(repooling_payload).encode("utf-8")
    ).hexdigest()

    args.output.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    args.repooling_output.write_text(
        json.dumps(repooling_payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    for condition in CONDITIONS:
        summary = aggregates[condition]
        label = "provisorio" if condition == CONDITION_DENSE and unjudged_total else ""
        print(
            f"{condition}  R@1={summary['recall']['1']:.4f} "
            f"R@3={summary['recall']['3']:.4f} R@5={summary['recall']['5']:.4f} "
            f"MRR={summary['mrr']:.4f} nDCG@5={summary['ndcg']['5']:.4f} {label}"
        )
    print(f"comparabilidade : {comparability} ({unjudged_total} por julgar)")
    print(f"index_digest    : {index_digest}")
    print(f"result_digest   : {payload['result_digest']}")
    print(f"written         : {args.output}")
    print(f"written         : {args.repooling_output}")
    return EXIT_OK


def judged_grades_by_anchor(
    question: Mapping[str, Any],
) -> dict[tuple[str, int], int]:
    """``(corpus_item_id, chunk_index) -> grau``.

    Ancorado no identificador do corpus e não no ``document_id`` local, ao
    contrário do índice equivalente do D4.3: aqui os julgamentos são comparados
    com rankings que já foram traduzidos para a âncora do protocolo, e traduzir
    duas vezes seria uma oportunidade a mais de os dois lados divergirem.
    """
    return {
        (judgment["corpus_item_id"], judgment["chunk_index"]): judgment["relevance"]
        for judgment in question["evidence_judgments"]
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
    """Executa as duas condições e compara-as, sem decidir nada."""
    grades = judged_grades_by_anchor(question)
    judged_grades = sorted(grades.values(), reverse=True)
    measurable = not question["no_relevant_evidence"] and not question["excluded_from_metrics"]

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

    targets = [
        {
            "corpus_item_id": item.corpus_item_id,
            "chunk_index": item.chunk_index,
            "rank_c0": _rank_of(item, c0_pool),
            "rank_c1": _rank_of(item, c1_pool),
        }
        for item in sorted(
            PoolItem(corpus_item_id, chunk_index)
            for (corpus_item_id, chunk_index), grade in grades.items()
            if grade >= BINARY_RELEVANCE_THRESHOLD
        )
    ]

    return {
        "question_id": question["question_id"],
        "temporal_scope": question["temporal_scope"],
        "difficulty_types": list(question["difficulty_types"]),
        "no_relevant_evidence": question["no_relevant_evidence"],
        "excluded_from_metrics": question["excluded_from_metrics"],
        "measured": measurable,
        "judged_grades": judged_grades,
        "targets": targets,
        "union_size": len(union_pool(c0_pool, c1_pool)),
        "overlap": overlap_count(c0_pool, c1_pool),
        "exclusive_to_c0": [_anchor(item) for item in exclusive_to(c0_pool, c1_pool)],
        "exclusive_to_c1": [_anchor(item) for item in exclusive_to(c1_pool, c0_pool)],
        "unjudged_in_top_k": {
            CONDITION_LEXICAL: [
                _anchor(PoolItem(request.corpus_item_id, request.chunk_index))
                for request in requests
                if CONDITION_LEXICAL in request.retrieved_by
            ],
            CONDITION_DENSE: [
                _anchor(PoolItem(request.corpus_item_id, request.chunk_index))
                for request in requests
                if CONDITION_DENSE in request.retrieved_by
            ],
        },
        "conditions": conditions,
        "repooling_requests": [
            {
                "question_id": request.question_id,
                "corpus_item_id": request.corpus_item_id,
                "chunk_index": request.chunk_index,
                "retrieved_by": list(request.retrieved_by),
                "rank_c0": request.rank_c0,
                "rank_c1": request.rank_c1,
            }
            for request in requests
        ],
    }


def _rank_of(item: PoolItem, pool: Sequence[PoolItem]) -> int | None:
    for position, candidate in enumerate(pool, start=1):
        if candidate == item:
            return position
    return None


def _anchor(item: PoolItem) -> dict[str, Any]:
    return {"corpus_item_id": item.corpus_item_id, "chunk_index": item.chunk_index}


if __name__ == "__main__":
    sys.exit(main())
