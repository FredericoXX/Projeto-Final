"""Ablação e reponderação controlada do ranking lexical (D4.7).

Uso (a partir de ``backend/``, com o virtual environment ativo):

    python -m scripts.evaluate_ranking_variants \
        --ground-truth ../docs/evaluation/retrieval-ground-truth-p1-repooled.json \
        --binding ../storage/pilot-corpus/S1-identifier-binding.json \
        --diagnostics ../docs/evaluation/ranking-diagnostics-p1-s1.json \
        --output ../docs/evaluation/ranking-variants-p1-s1.json \
        [--overwrite]

**Não altera nada.** O ranking de produção, os pesos, o limiar, a elegibilidade,
o orçamento de candidatos, o *query planning* e o corpus ficam como estão. O que
o comando faz é reordenar **o mesmo conjunto de candidatos elegíveis** sob
vetores de pesos alternativos e medir o resultado.

O que fica constante, e porquê importa
--------------------------------------

O conjunto de candidatos é recolhido **uma vez** por pergunta e por política de
orçamento, e reutilizado por todas as variantes. Não é otimização: é a condição
que torna a comparação válida. Se cada variante recolhesse o seu conjunto, uma
diferença de resultado poderia vir da base de dados e não dos pesos.

A elegibilidade decide antes de qualquer peso existir, pelo que o conjunto
elegível é **idêntico** em todas as variantes. A única fronteira que os pesos
podem mover é o limiar mínimo, e por isso o artefacto regista, por variante,
quantos candidatos ficam abaixo dele.

Resultados por julgar
---------------------

Uma variante que promova ao top 5 um segmento sem julgamento **não** recebe
comparação conclusiva. O protocolo trata não julgado como grau 0, o que aqui
seria uma armadilha: a variante seria penalizada por descobrir algo que ninguém
avaliou. Essas variantes são marcadas ``REPOOLING_REQUIRED`` e o *ground truth*
**não** é alterado nesta fase.

Guardas
-------

Nada é escrito se alguma falhar:

1. o artefacto do D4.6 tem de coincidir com o seu próprio ``result_digest``.
   Reproduzir as células não substitui esta verificação: elas são recalculadas a
   partir da base e continuariam a coincidir mesmo com o digest adulterado, e o
   D4.7 acabaria a declarar uma ligação a um digest que não descreve o conteúdo
   que consumiu;
2. o *ground truth* tem de ser o repooled da D4.6, pelo seu digest, e o
   diagnóstico tem de ter sido produzido contra esse mesmo conjunto;
3. o corpus e o snapshot têm de coincidir com S1;
4. a célula de controlo — pesos de produção — tem de reproduzir as células
   correspondentes do D4.6 por inteiro.
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

from app.core.config import settings
from app.core.text_normalization import normalize_text
from app.documents.retrievability import RetrievabilityContext
from app.evaluation.candidate_budget import (
    BUDGET_CURRENT_QUOTA,
    BUDGET_REDISTRIBUTE_UNUSED,
)
from app.evaluation.ground_truth_identity import (
    GROUND_TRUTH_DIGEST_ALGORITHM,
    GROUND_TRUTH_DIGEST_SCOPE,
    ground_truth_digest,
)
from app.evaluation.ranking_variants import (
    PRODUCTION_WEIGHTS,
    SIGNAL_NAMES,
    RankingVariant,
    score_with,
    with_weight,
)
from app.evaluation.repooling import judgment_coverage
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
from app.retrieval.eligibility import decide_eligibility
from app.retrieval.query_planning import uses_advanced_syntax
from app.retrieval.reranking import (
    LexicalCandidate,
    LexicalFeatures,
    build_features,
    compute_content_match,
    informative_query_terms,
)
from scripts.evaluate_candidate_budget_experiment import collect_candidates
from scripts.evaluate_retrieval_baseline import BaselineError, verify_metric_protocol
from scripts.evaluate_retrieval_experiment import (
    ExperimentError,
    SessionLocalFactory,
    _corpus_item_for,
    judged_grade_index,
    verify_baseline_integrity,
    verify_baseline_replication,
    verify_snapshot,
)

EXPERIMENT_SCHEMA_VERSION: Final = "1"
DIGEST_ALGORITHM: Final = "sha256"

#: O *ground truth* desta fase, pelo seu digest. É uma pré-condição declarada no
#: enunciado e verificada antes de medir: correr sobre outro conjunto produziria
#: números incomparáveis com a D4.6 sem que nada o assinalasse.
EXPECTED_GROUND_TRUTH_DIGEST: Final = (
    "ada6b38886a06910e425e4be164099a3a63320050890253404064e3fde88586e"
)

#: Painel primário: o orçamento de produção. O secundário existe porque o D4.5
#: concluiu que é o ranking que torna inseguro ampliar o orçamento — saber se uma
#: reponderação muda isso é a pergunta que aquela fase deixou aberta.
PRIMARY_POLICY: Final = BUDGET_CURRENT_QUOTA
POLICIES: Final = (BUDGET_CURRENT_QUOTA, BUDGET_REDISTRIBUTE_UNUSED)

REPOOLING_REQUIRED: Final = "REPOOLING_REQUIRED"
COMPARABLE: Final = "COMPARABLE"

EXIT_OK: Final = 0
EXIT_USAGE: Final = 2
EXIT_SNAPSHOT_MISMATCH: Final = 3
EXIT_BASELINE_MISMATCH: Final = 4
EXIT_OUTPUT_EXISTS: Final = 5
EXIT_GROUND_TRUTH_MISMATCH: Final = 6


# ---------------------------------------------------------------------------
# As variantes
# ---------------------------------------------------------------------------

#: Cada vetor é escrito à mão a partir de uma hipótese nomeada e derivada do
#: diagnóstico da D4.6. Não há pesquisa em grelha nem otimização: com doze
#: perguntas medidas, procurar pesos produziria sobreajustamento, não
#: conhecimento.
VARIANTS: Final[tuple[RankingVariant, ...]] = (
    RankingVariant(
        variant_id="A0",
        label="producao (controlo)",
        hypothesis=(
            "Configuracao atual. Tem de reproduzir a D4.6 por inteiro; se nao "
            "reproduzir, nenhum delta e interpretavel."
        ),
        weights=dict(PRODUCTION_WEIGHTS),
    ),
    RankingVariant(
        variant_id="A1",
        label="sem structure_table_row",
        hypothesis=(
            "O bonus estrutural esta disponivel a UM dos seis documentos do "
            "corpus (D4.6 §5.2), pelo que mede qualidade de extracao e nao "
            "pertinencia. Removido, a falha entre documentos de Q011 deve "
            "desaparecer."
        ),
        weights=with_weight(PRODUCTION_WEIGHTS, structure_table_row=0.0),
    ),
    RankingVariant(
        variant_id="A2",
        label="structure_table_row reduzido a um sexto",
        hypothesis=(
            "Se o sinal tiver algum valor legitimo em documentos bem extraidos, "
            "reduzi-lo em vez de o remover preserva esse valor e deixa de "
            "decidir comparacoes entre documentos."
        ),
        weights=with_weight(PRODUCTION_WEIGHTS, structure_table_row=0.01),
    ),
    RankingVariant(
        variant_id="A3",
        label="sem section_overlap",
        hypothesis=(
            "O overlap de seccao premeia seccoes que contem o ano por acidente "
            "de titulacao (D4.6 §5.3). Removido, deixa de creditar um segmento "
            "pelo cabecalho da seccao onde por acaso caiu."
        ),
        weights=with_weight(PRODUCTION_WEIGHTS, section_overlap=0.0),
    ),
    RankingVariant(
        variant_id="B1",
        label="title_overlap reforcado",
        hypothesis=(
            "title_overlap e o unico sinal ao nivel do DOCUMENTO, e a D4.6 "
            "mostrou que sozinho inverteria a falha entre documentos de Q011. "
            "Reforca-lo deve ajudar exatamente esse modo de falha."
        ),
        weights=with_weight(PRODUCTION_WEIGHTS, title_overlap=0.14),
    ),
    RankingVariant(
        variant_id="B2",
        label="proximity reduzido a metade",
        hypothesis=(
            "A proximidade recompensa densidade lexical, e um cabecalho e "
            "maximamente denso sem responder a nada (D4.6 §5.1). Reduzi-la deve "
            "atenuar a falha dentro do mesmo documento em Q001."
        ),
        weights=with_weight(PRODUCTION_WEIGHTS, proximity=0.07),
    ),
    RankingVariant(
        variant_id="B3",
        label="A1 + B1 (sem estrutura, com titulo reforcado)",
        hypothesis=(
            "As duas alteracoes com maior justificacao atacam modos de falha "
            "diferentes. A questao e se compoem ou se interferem."
        ),
        weights=with_weight(
            PRODUCTION_WEIGHTS, structure_table_row=0.0, title_overlap=0.14
        ),
    ),
)


def _load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ExperimentError(f"file not found: {path}", EXIT_USAGE) from error
    except json.JSONDecodeError as error:
        raise ExperimentError(f"invalid JSON in {path}: {error}", EXIT_USAGE) from error


# ---------------------------------------------------------------------------
# Ranking sob um vetor de pesos
# ---------------------------------------------------------------------------


def eligible_features(
    *,
    normalized_query: str,
    candidates: Sequence[LexicalCandidate],
    language: str,
) -> list[tuple[LexicalCandidate, LexicalFeatures]]:
    """Candidatos elegíveis e os seus sinais, calculados **uma vez**.

    A elegibilidade não vê pesos: decide a partir dos sinais de conteúdo e da
    estratégia, exatamente como em produção. Por isso o conjunto elegível é o
    mesmo em todas as variantes, e calculá-lo uma vez é também o que garante que
    nenhuma variante o possa alterar por acidente.
    """
    query_terms = informative_query_terms(normalized_query, language)
    explicit_syntax = uses_advanced_syntax(normalized_query)
    survivors: list[tuple[LexicalCandidate, LexicalFeatures]] = []
    for candidate in candidates:
        match = compute_content_match(query_terms, candidate)
        decision = decide_eligibility(
            query_terms, match, candidate.strategy, explicit_syntax=explicit_syntax
        )
        if not decision.eligible:
            continue
        survivors.append((candidate, build_features(query_terms, candidate, match)))
    return survivors


def rank_under_weights(
    survivors: Sequence[tuple[LexicalCandidate, LexicalFeatures]],
    weights: Mapping[str, float],
) -> tuple[list[LexicalCandidate], int]:
    """Ordena sob ``weights`` e aplica o limiar de produção.

    A chave de ordenação replica ``_ranking_key`` de ``app.retrieval.reranking``,
    com o score da variante no lugar do score de produção. Os desempates —
    cobertura, qualidade da estratégia, score FTS bruto e identificadores — são
    os mesmos, para que duas variantes com scores empatados não difiram por
    ordem de chegada das linhas.
    """
    scored: list[tuple[tuple[Any, ...], LexicalCandidate]] = []
    below_threshold = 0
    for candidate, features in survivors:
        score = score_with(features, weights)
        if score < settings.retrieval_min_relevance_score:
            below_threshold += 1
            continue
        scored.append(
            (
                (
                    -score,
                    -features.coverage,
                    -features.strategy_quality,
                    -candidate.raw_score,
                    str(candidate.document_id),
                    candidate.chunk_index,
                    str(candidate.chunk_id),
                ),
                candidate,
            )
        )
    scored.sort(key=lambda item: item[0])
    return [candidate for _, candidate in scored], below_threshold


# ---------------------------------------------------------------------------
# Avaliação
# ---------------------------------------------------------------------------


def evaluate_variant(
    *,
    variant: RankingVariant,
    policy: str,
    questions: Sequence[Mapping[str, Any]],
    survivors_by_question: Mapping[str, Sequence[tuple[LexicalCandidate, LexicalFeatures]]],
    document_index: Mapping[str, str],
    top_k: int,
) -> dict[str, Any]:
    """Uma célula: uma variante de pesos × uma política de orçamento."""
    weights = variant.normalised
    per_question: list[dict[str, Any]] = []
    recalls: dict[int, list[float]] = {k: [] for k in K_VALUES}
    ndcgs: dict[int, list[float]] = {k: [] for k in K_VALUES}
    reciprocal_ranks: list[float] = []
    unjudged_by_question: dict[str, list[dict[str, Any]]] = {}

    for question in questions:
        question_id = question["question_id"]
        ranked, below_threshold = rank_under_weights(
            survivors_by_question[question_id], weights
        )
        returned = ranked[:top_k]
        grades = judged_grade_index(question, document_index)
        retrieved_grades = [
            grades.get((str(c.document_id), c.chunk_index), UNJUDGED_GRADE)
            for c in returned
        ]
        judged_grades = [j["relevance"] for j in question["evidence_judgments"]]
        total_relevant = sum(
            1 for grade in judged_grades if grade >= BINARY_RELEVANCE_THRESHOLD
        )
        returned_keys = [
            (_corpus_item_for(str(c.document_id), document_index) or "?", c.chunk_index)
            for c in returned
        ]
        unjudged = [
            {"corpus_item_id": item, "chunk_index": index, "position": position}
            for position, (item, index) in enumerate(returned_keys, start=1)
            if (str(returned[position - 1].document_id), index) not in grades
        ]
        if unjudged:
            unjudged_by_question[question_id] = unjudged

        rank_by_key = {
            (str(c.document_id), c.chunk_index): position
            for position, c in enumerate(ranked, start=1)
        }
        record: dict[str, Any] = {
            "question_id": question_id,
            "eligible_candidates": len(survivors_by_question[question_id]),
            "below_threshold": below_threshold,
            "ranked_survivors": len(ranked),
            "retrieved_count": len(returned),
            "judgment_coverage": judgment_coverage(question, returned_keys),
            "unjudged_in_top_k": unjudged,
            "target_ranks": [
                {
                    "corpus_item_id": judgment["corpus_item_id"],
                    "chunk_index": judgment["chunk_index"],
                    "rank": rank_by_key.get(
                        (
                            document_index[judgment["corpus_item_id"]],
                            judgment["chunk_index"],
                        )
                    ),
                }
                for judgment in question["evidence_judgments"]
                if judgment["relevance"] >= BINARY_RELEVANCE_THRESHOLD
            ],
            "ranking": [
                {
                    "position": position,
                    "corpus_item_id": _corpus_item_for(
                        str(c.document_id), document_index
                    ),
                    "chunk_index": c.chunk_index,
                    "grade": grades.get(
                        (str(c.document_id), c.chunk_index), UNJUDGED_GRADE
                    ),
                    "judged": (str(c.document_id), c.chunk_index) in grades,
                }
                for position, c in enumerate(returned, start=1)
            ],
        }
        measurable = (
            not question["no_relevant_evidence"]
            and not question["excluded_from_metrics"]
            and total_relevant > 0
        )
        if measurable:
            record["recall"] = {
                str(k): round(recall_at_k(retrieved_grades, total_relevant, k), 6)
                for k in K_VALUES
            }
            record["reciprocal_rank"] = round(reciprocal_rank(retrieved_grades), 6)
            record["ndcg"] = {
                str(k): round(ndcg_at_k(retrieved_grades, judged_grades, k), 6)
                for k in K_VALUES
            }
            for k in K_VALUES:
                recalls[k].append(recall_at_k(retrieved_grades, total_relevant, k))
                ndcgs[k].append(ndcg_at_k(retrieved_grades, judged_grades, k))
            reciprocal_ranks.append(reciprocal_rank(retrieved_grades))
        else:
            record["measured"] = False
        per_question.append(record)

    unjudged_total = sum(len(entries) for entries in unjudged_by_question.values())
    return {
        "variant_id": variant.variant_id,
        "budget_policy": policy,
        "weights": {name: round(weights[name], 6) for name in SIGNAL_NAMES},
        "weight_deltas_from_production": variant.deltas_from_production(),
        "comparability": REPOOLING_REQUIRED if unjudged_total else COMPARABLE,
        "unjudged_in_top_k_total": unjudged_total,
        "unjudged_questions": sorted(unjudged_by_question),
        "aggregate": {
            "questions_measured": len(reciprocal_ranks),
            "recall": {str(k): round(mean(recalls[k]), 6) for k in K_VALUES},
            "mrr": round(mean(reciprocal_ranks), 6),
            "ndcg": {str(k): round(mean(ndcgs[k]), 6) for k in K_VALUES},
        },
        "question_results": per_question,
    }


def compare_to_baseline(
    baseline: Mapping[str, Any], variant: Mapping[str, Any]
) -> dict[str, Any]:
    """Deltas por pergunta e agregados, face a A0 na mesma política."""
    baseline_by_id = {r["question_id"]: r for r in baseline["question_results"]}
    variant_by_id = {r["question_id"]: r for r in variant["question_results"]}

    changed: list[dict[str, Any]] = []
    for question_id in sorted(baseline_by_id):
        before = baseline_by_id[question_id]
        after = variant_by_id[question_id]
        measured = "recall" in before and "recall" in after
        metrics_changed = measured and (
            before["recall"] != after["recall"]
            or before["ndcg"] != after["ndcg"]
            or before["reciprocal_rank"] != after["reciprocal_rank"]
        )
        ranks_changed = before["target_ranks"] != after["target_ranks"]
        ranking_changed = [
            (e["position"], e["corpus_item_id"], e["chunk_index"])
            for e in before["ranking"]
        ] != [
            (e["position"], e["corpus_item_id"], e["chunk_index"])
            for e in after["ranking"]
        ]
        if not (metrics_changed or ranks_changed or ranking_changed):
            continue
        record: dict[str, Any] = {
            "question_id": question_id,
            "measured": measured,
            "direction": _direction(before, after) if measured else "observed_only",
            "target_ranks": [before["target_ranks"], after["target_ranks"]],
            "unjudged_in_top_k": [
                before["unjudged_in_top_k"],
                after["unjudged_in_top_k"],
            ],
            "ranking_before": [
                (e["position"], e["corpus_item_id"], e["chunk_index"], e["grade"])
                for e in before["ranking"]
            ],
            "ranking_after": [
                (e["position"], e["corpus_item_id"], e["chunk_index"], e["grade"])
                for e in after["ranking"]
            ],
        }
        if measured:
            record["metrics"] = {
                "recall": {
                    str(k): [before["recall"][str(k)], after["recall"][str(k)]]
                    for k in K_VALUES
                },
                "reciprocal_rank": [
                    before["reciprocal_rank"],
                    after["reciprocal_rank"],
                ],
                "ndcg": {
                    str(k): [before["ndcg"][str(k)], after["ndcg"][str(k)]]
                    for k in K_VALUES
                },
            }
        changed.append(record)

    before_aggregate = baseline["aggregate"]
    after_aggregate = variant["aggregate"]
    return {
        "variant_id": variant["variant_id"],
        "budget_policy": variant["budget_policy"],
        "comparability": variant["comparability"],
        "identical_to_baseline": not changed,
        "aggregate_delta": {
            "recall": {
                str(k): round(
                    after_aggregate["recall"][str(k)] - before_aggregate["recall"][str(k)],
                    6,
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
        "questions_changed": changed,
    }


def _direction(before: Mapping[str, Any], after: Mapping[str, Any]) -> str:
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


# ---------------------------------------------------------------------------
# Execução
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ground-truth", type=Path, required=True)
    parser.add_argument("--binding", type=Path, required=True)
    parser.add_argument("--diagnostics", type=Path, required=True)
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

    ground_truth = _load_json(args.ground_truth)
    binding = _load_json(args.binding)
    diagnostics = _load_json(args.diagnostics)

    try:
        verify_metric_protocol(dict(ground_truth))
    except BaselineError as error:
        raise ExperimentError(str(error), EXIT_USAGE) from error

    # O artefacto do D4.6 tem de ser aquele que o seu próprio digest declara.
    # Reproduzir as células não chega: elas voltam a ser calculadas a partir da
    # base, pelo que continuariam a coincidir mesmo com o digest adulterado — e
    # o D4.7 passaria a declarar uma ligação a um digest que não representa o
    # conteúdo consumido.
    verify_baseline_integrity(diagnostics)

    digest = ground_truth_digest(ground_truth)
    if digest != EXPECTED_GROUND_TRUTH_DIGEST:
        raise ExperimentError(
            "this experiment is defined over the D4.6 repooled ground truth "
            f"({EXPECTED_GROUND_TRUTH_DIGEST}); got {digest}",
            EXIT_GROUND_TRUTH_MISMATCH,
        )
    if diagnostics.get("ground_truth_digest_after") != digest:
        raise ExperimentError(
            "the diagnostics artefact was produced against a different ground truth",
            EXIT_GROUND_TRUTH_MISMATCH,
        )

    retrieval = diagnostics["retrieval"]
    language = retrieval["language"]
    top_k = retrieval["top_k"]
    official_only = retrieval["official_only"]
    document_index = {
        item["corpus_item_id"]: item["document_id"]
        for item in binding["items"]
        if item.get("in_corpus")
    }
    questions = ground_truth["questions"]

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
            institution_id=UUID(binding["institution_id"]),
            language=language,
            reference_date=date.fromisoformat(ground_truth["reference_date"]),
            official_only=official_only,
        )

        # Um conjunto de candidatos por pergunta e por política, partilhado por
        # todas as variantes: é isto que garante que um delta mede os pesos.
        survivors: dict[str, dict[str, list[tuple[LexicalCandidate, LexicalFeatures]]]] = {}
        for policy in POLICIES:
            per_question: dict[str, list[tuple[LexicalCandidate, LexicalFeatures]]] = {}
            for question in questions:
                normalized_query = normalize_text(question["question"])
                pool, _trace = collect_candidates(
                    db,
                    normalized_query=normalized_query,
                    context=context,
                    language=language,
                    top_k=top_k,
                    policy=policy,
                )
                per_question[question["question_id"]] = eligible_features(
                    normalized_query=normalized_query,
                    candidates=pool,
                    language=language,
                )
            survivors[policy] = per_question

    cells = [
        evaluate_variant(
            variant=variant,
            policy=policy,
            questions=questions,
            survivors_by_question=survivors[policy],
            document_index=document_index,
            top_k=top_k,
        )
        for policy in POLICIES
        for variant in VARIANTS
    ]
    by_key = {(cell["budget_policy"], cell["variant_id"]): cell for cell in cells}

    diagnostics_by_policy = {
        cell["budget_policy"]: cell
        for cell in diagnostics["cells"]
        if cell["ground_truth"] == "repooled"
    }
    for policy in POLICIES:
        problems = verify_baseline_replication(
            by_key[(policy, "A0")], diagnostics_by_policy[policy]
        )
        if problems:
            raise ExperimentError(
                f"the control variant for {policy} does not reproduce the D4.6 "
                "repooled cell: " + "; ".join(problems),
                EXIT_BASELINE_MISMATCH,
            )

    comparisons = [
        compare_to_baseline(by_key[(policy, "A0")], by_key[(policy, variant.variant_id)])
        for policy in POLICIES
        for variant in VARIANTS
        if variant.variant_id != "A0"
    ]

    payload: dict[str, Any] = {
        "schema_version": EXPERIMENT_SCHEMA_VERSION,
        "digest_algorithm": DIGEST_ALGORITHM,
        "corpus_id": ground_truth["corpus_id"],
        "snapshot_id": ground_truth["snapshot_id"],
        "corpus_digest": ground_truth["corpus_digest"],
        "reference_date": ground_truth["reference_date"],
        "ground_truth_digest": digest,
        "ground_truth_digest_algorithm": GROUND_TRUTH_DIGEST_ALGORITHM,
        "ground_truth_digest_scope": GROUND_TRUTH_DIGEST_SCOPE,
        "d46_result_digest": diagnostics["result_digest"],
        "control_reproduces_d46": True,
        "retrieval": retrieval,
        "baseline_configuration": {
            "scoring_version": "lexical_composite_v1",
            "weights": dict(PRODUCTION_WEIGHTS),
            "min_relevance_score": settings.retrieval_min_relevance_score,
            "note": (
                "Imported from app.retrieval.reranking, never copied. Variants "
                "are renormalised to sum 1.0 because reranking requires it and "
                "because an absolute relevance threshold would otherwise turn a "
                "reweighting into a change of what is returned."
            ),
        },
        "variants": [
            {
                "variant_id": variant.variant_id,
                "label": variant.label,
                "hypothesis": variant.hypothesis,
                "weights_declared": dict(variant.weights),
                "weights_normalised": {
                    name: round(value, 6)
                    for name, value in variant.normalised.items()
                },
                "weight_deltas_from_production": variant.deltas_from_production(),
            }
            for variant in VARIANTS
        ],
        "budget_policies": list(POLICIES),
        "primary_budget_policy": PRIMARY_POLICY,
        "primary_k": PRIMARY_K,
        "comparability_note": (
            "A variant that promotes an unjudged segment into the top 5 is marked "
            "REPOOLING_REQUIRED. The protocol scores unjudged as grade 0, which "
            "here would penalise a variant for surfacing something nobody has "
            "assessed. The ground truth was NOT modified in this phase."
        ),
        "cells": cells,
        "comparisons": comparisons,
    }
    payload["result_digest"] = hashlib.sha256(
        canonical_json(payload).encode("utf-8")
    ).hexdigest()
    payload["executed_at"] = datetime.now(UTC).isoformat()

    args.output.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    _print_summary(payload)
    return EXIT_OK


def _print_summary(payload: Mapping[str, Any]) -> None:
    for cell in payload["cells"]:
        aggregate = cell["aggregate"]
        flag = "!" if cell["comparability"] == REPOOLING_REQUIRED else " "
        print(
            f"{cell['budget_policy']:21s} {cell['variant_id']:3s}{flag} "
            f"R@5={aggregate['recall']['5']:.4f} MRR={aggregate['mrr']:.4f} "
            f"nDCG@5={aggregate['ndcg']['5']:.4f} "
            f"nao_julgados={cell['unjudged_in_top_k_total']}"
        )
    for comparison in payload["comparisons"]:
        print(
            f"delta {comparison['budget_policy']:21s} {comparison['variant_id']:3s} "
            f"identico={comparison['identical_to_baseline']!s:5s} "
            f"melhora={comparison['improved']} piora={comparison['regressed']} "
            f"misto={comparison['mixed']} [{comparison['comparability']}]"
        )
    print(f"ground_truth_digest: {payload['ground_truth_digest']}")
    print(f"result_digest      : {payload['result_digest']}")


if __name__ == "__main__":
    sys.exit(main())
