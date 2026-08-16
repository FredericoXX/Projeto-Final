"""Experimento controlado do orçamento de candidatos e do ranking (D4.5).

Uso (a partir de ``backend/``, com o virtual environment ativo):

    python -m scripts.evaluate_candidate_budget_experiment \
        --ground-truth ../docs/evaluation/retrieval-ground-truth-p1-seed.json \
        --binding ../storage/pilot-corpus/S1-identifier-binding.json \
        --baseline ../docs/evaluation/retrieval-baseline-p1-s1.json \
        --output ../docs/evaluation/retrieval-experiment-candidate-budget-p1-s1.json \
        [--overwrite]

Varia **uma** coisa: quantas linhas cada variante de consulta pode devolver e
quando o teto é aplicado. Plano de consulta, elegibilidade, pesos do ranking,
limiar, ``top_k`` e *ground truth* são os de produção, chamados sem alteração.

Porque é que a fase separa candidate recall de ranking
------------------------------------------------------

O D4.2 mediu ``Recall@5 = 0`` em seis perguntas e o D4.3 mostrou que a quota
impede uma política alternativa de alcançar alguns alvos. Mas "não recuperado"
esconde três situações com remédios diferentes: o alvo **nunca foi candidato**,
foi candidato e a elegibilidade **rejeitou-o**, ou sobreviveu e o **ranking
empurrou-o** para fora do top 5. Só a terceira é um problema de ranking, e só a
primeira é um problema de orçamento.

O D4.2 não conseguia separar as duas primeiras da terceira — via apenas o trace
e classificava o caso ambíguo como ``NOT_RETURNED_INDETERMINATE``. Aqui o
conjunto de candidatos é conhecido por inteiro e a lista ordenada é guardada
antes do corte, pelo que o destino de cada alvo é uma **observação** e não uma
inferência.

Duas dimensões, e a segunda é secundária
----------------------------------------

O painel que decide é ``exact_canonical`` — a correspondência de produção — sob
as três políticas de orçamento. ``stem_normalized`` corre as mesmas três
políticas e serve **apenas** para responder à pergunta que o D4.3 deixou aberta:
se a quota estava a impedir uma política de correspondência alternativa de
alcançar um alvo, chega redistribuir o orçamento para a desbloquear? É
diagnóstico, não proposta: nenhuma conclusão sobre a quota de produção se apoia
nesse painel.

Validação embutida
------------------

A célula ``current_quota`` × ``exact_canonical`` **tem** de reproduzir o
artefacto do D4.2 por inteiro, e o artefacto do D4.2 tem de coincidir com o seu
próprio ``result_digest``. Se falhar, nada é escrito: comparar políticas contra
uma baseline mal replicada produziria deltas que medem a replicação.
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
    BUDGET_GLOBAL_LIMITED_POOL,
    BUDGET_POLICIES,
    BUDGET_REDISTRIBUTE_UNUSED,
    FATE_NEVER_A_CANDIDATE,
    FATE_RANKED_OUTSIDE_TOP_K,
    FATE_RETURNED,
    TARGET_FATES,
    adaptive_quota,
    candidate_recall,
    classify_target_fate,
    merge_candidate,
    quota_plan,
    summarise_target_position,
    truncate_pool,
)
from app.evaluation.ground_truth_identity import (
    GROUND_TRUTH_DIGEST_ALGORITHM,
    GROUND_TRUTH_DIGEST_SCOPE,
    ground_truth_digest,
)
from app.evaluation.lexical_variants import (
    MATCHING_EXACT_CANONICAL,
    MATCHING_STEM_NORMALIZED,
    variant_content_match,
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
from app.retrieval.eligibility import ExclusionReason, decide_eligibility
from app.retrieval.fts_config import resolve_fts_config
from app.retrieval.lexical import distribute_quotas, global_candidate_limit
from app.retrieval.lexical_normalization import build_lexical_representation
from app.retrieval.query_planning import plan_lexical_query, uses_advanced_syntax
from app.retrieval.reranking import (
    LexicalCandidate,
    build_features,
    compute_content_match,
    compute_score,
    informative_query_terms,
)
from scripts.evaluate_retrieval_baseline import BaselineError, verify_metric_protocol
from scripts.evaluate_retrieval_experiment import (
    ExperimentError,
    SessionLocalFactory,
    _candidate_statement,
    _corpus_item_for,
    _row_to_candidate,
    judged_grade_index,
    projection_for,
    stem_words_batch,
    verify_baseline_integrity,
    verify_baseline_replication,
    verify_snapshot,
)

EXPERIMENT_SCHEMA_VERSION: Final = "1"
DIGEST_ALGORITHM: Final = "sha256"

#: O painel que decide é o primeiro; o segundo é diagnóstico da interação que o
#: D4.3 deixou por medir.
MATCHING_PANELS: Final = (MATCHING_EXACT_CANONICAL, MATCHING_STEM_NORMALIZED)
PRIMARY_MATCHING: Final = MATCHING_EXACT_CANONICAL

EXIT_OK: Final = 0
EXIT_USAGE: Final = 2
#: Levantado pelo ``verify_snapshot`` importado, não aqui.
EXIT_SNAPSHOT_MISMATCH: Final = 3
EXIT_BASELINE_MISMATCH: Final = 4
EXIT_OUTPUT_EXISTS: Final = 5


def _load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ExperimentError(f"file not found: {path}", EXIT_USAGE) from error
    except json.JSONDecodeError as error:
        raise ExperimentError(f"invalid JSON in {path}: {error}", EXIT_USAGE) from error


# ---------------------------------------------------------------------------
# Recolha de candidatos sob uma política de orçamento
# ---------------------------------------------------------------------------


def collect_candidates(
    db: Any,
    *,
    normalized_query: str,
    context: RetrievabilityContext,
    language: str,
    top_k: int,
    policy: str,
) -> tuple[list[LexicalCandidate], dict[str, Any]]:
    """Conjunto de candidatos e o traço do orçamento, para uma política.

    O SQL, a admissibilidade documental e a conversão de linha em candidato vêm
    de ``scripts.evaluate_retrieval_experiment``, que não é tocado. O que este
    módulo acrescenta é **só** a decisão de quantas linhas pedir a cada variante.
    """
    fts_config = resolve_fts_config(language)
    plan = plan_lexical_query(normalized_query, language)
    budget = global_candidate_limit(top_k)
    variant_count = len(plan.variants)

    candidates: dict[Any, LexicalCandidate] = {}
    variant_trace: list[dict[str, Any]] = []
    rows_fetched = 0

    if policy == BUDGET_CURRENT_QUOTA:
        quotas: list[int | None] = list(distribute_quotas(budget, variant_count))
    elif policy == BUDGET_REDISTRIBUTE_UNUSED:
        quotas = [None] * variant_count  # decididas em cascata, abaixo
    elif policy == BUDGET_GLOBAL_LIMITED_POOL:
        quotas = [None] * variant_count
    else:
        raise ExperimentError(f"unknown budget policy: {policy!r}", EXIT_USAGE)

    remaining_budget = budget
    for index, variant in enumerate(plan.variants):
        if policy == BUDGET_REDISTRIBUTE_UNUSED:
            quota: int | None = adaptive_quota(remaining_budget, variant_count - index)
        else:
            quota = quotas[index]

        if quota == 0:
            variant_trace.append(
                {"strategy": variant.strategy.value, "quota": 0, "returned_count": 0}
            )
            continue

        ts_query = _ts_query(fts_config.value, variant.websearch_input)
        rows = db.execute(_candidate_statement(ts_query, context, quota)).all()
        rows_fetched += len(rows)
        variant_trace.append(
            {
                "strategy": variant.strategy.value,
                "quota": quota,
                "returned_count": len(rows),
            }
        )
        if policy == BUDGET_REDISTRIBUTE_UNUSED:
            # O orçamento é consumido pelas linhas **devolvidas**, não pela quota
            # concedida: é isso que faz de B "o mesmo teto sem desperdício" e não
            # "mais orçamento". A soma das linhas nunca excede ``budget``.
            remaining_budget -= len(rows)
        for row in rows:
            merge_candidate(candidates, _row_to_candidate(row, variant.strategy))

    unique_before = len(candidates)
    pool = list(candidates.values())
    if policy == BUDGET_GLOBAL_LIMITED_POOL:
        pool = truncate_pool(pool, budget)

    trace = {
        "budget": budget,
        "declared_quota_plan": [
            entry for entry in quota_plan(policy, budget, variant_count)
        ],
        "variants": variant_trace,
        "rows_fetched": rows_fetched,
        "unique_before_truncation": unique_before,
        "candidates_evaluated": len(pool),
        "truncated_by_global_limit": unique_before - len(pool),
    }
    return pool, trace


def _ts_query(fts_config_name: str, websearch_input: str) -> Any:
    from sqlalchemy import func

    return func.websearch_to_tsquery(fts_config_name, websearch_input)


# ---------------------------------------------------------------------------
# Onde estão os alvos na ordenação FTS
# ---------------------------------------------------------------------------


def target_candidate_positions(
    db: Any,
    *,
    questions: Sequence[Mapping[str, Any]],
    document_index: Mapping[str, str],
    context: RetrievabilityContext,
    language: str,
    top_k: int,
) -> list[dict[str, Any]]:
    """Posição de cada segmento de grau 2 na ordenação FTS **sem teto**.

    É a evidência causal da fase: diz a que distância do corte cada alvo está, e
    portanto se a quota o exclui por uma posição ou por noventa.

    Fica num bloco de topo, e não dentro de uma célula, porque **não depende da
    política de orçamento**: é uma propriedade do corpus, da consulta e da
    ordenação por ``ts_rank_cd``. Guardá-la numa célula sugeriria uma dependência
    que não existe.

    Cobre **todos** os alvos, incluindo os das perguntas excluídas das métricas:
    uma tabela que omitisse alguns não permitiria recontar a afirmação que dela
    se extrai.
    """
    fts_config = resolve_fts_config(language)
    budget = global_candidate_limit(top_k)
    records: list[dict[str, Any]] = []

    for question in questions:
        targets = [
            judgment
            for judgment in question["evidence_judgments"]
            if judgment["relevance"] >= BINARY_RELEVANCE_THRESHOLD
        ]
        if not targets:
            continue
        plan = plan_lexical_query(normalize_text(question["question"]), language)
        quotas = distribute_quotas(budget, len(plan.variants))
        quota_by_strategy = {
            variant.strategy.value: quota
            for variant, quota in zip(plan.variants, quotas, strict=True)
        }
        rows_by_strategy = {}
        for variant in plan.variants:
            ts_query = _ts_query(fts_config.value, variant.websearch_input)
            rows_by_strategy[variant.strategy.value] = db.execute(
                _candidate_statement(ts_query, context, None)
            ).all()

        for judgment in targets:
            document_id = document_index[judgment["corpus_item_id"]]
            matches: list[dict[str, Any]] = []
            for strategy, rows in rows_by_strategy.items():
                for position, row in enumerate(rows, start=1):
                    if (
                        str(row.document_id) == document_id
                        and row.chunk_index == judgment["chunk_index"]
                    ):
                        matches.append(
                            {
                                "strategy": strategy,
                                "position": position,
                                "total": len(rows),
                                "quota_under_current_policy": quota_by_strategy[strategy],
                            }
                        )
                        break
            records.append(
                {
                    "question_id": question["question_id"],
                    "corpus_item_id": judgment["corpus_item_id"],
                    "chunk_index": judgment["chunk_index"],
                    "measured_question": not question["excluded_from_metrics"],
                    "plan_variants": [v.strategy.value for v in plan.variants],
                    "quota_by_strategy": quota_by_strategy,
                    **summarise_target_position(matches, quota_by_strategy),
                }
            )
    return records


def verify_positions_explain_fates(
    positions: Sequence[Mapping[str, Any]], control_cells: Sequence[Mapping[str, Any]]
) -> list[str]:
    """A posição prevista tem de coincidir com o destino observado.

    Um alvo está no conjunto de candidatos de ``current_quota`` **se e só se**
    alguma variante o traz dentro da sua quota. Se a previsão e a observação
    divergirem, uma das duas está errada e a tabela do relatório deixaria de ser
    evidência — passaria a ser uma segunda medição não verificada, ao lado da
    primeira.
    """
    predicted_unreachable = {
        (record["question_id"], record["corpus_item_id"], record["chunk_index"])
        for record in positions
        if not record["reachable_under_current_quota"]
    }
    problems: list[str] = []
    for cell in control_cells:
        observed = {
            (result["question_id"], target["corpus_item_id"], target["chunk_index"])
            for result in cell["question_results"]
            for target in result["targets"]
            if target["fate"] == FATE_NEVER_A_CANDIDATE
        }
        if observed != predicted_unreachable:
            problems.append(
                f"{cell['matching_variant']}: targets predicted unreachable "
                f"{sorted(predicted_unreachable)} but observed NEVER_A_CANDIDATE "
                f"{sorted(observed)}"
            )
    return problems


# ---------------------------------------------------------------------------
# Ranking com diagnóstico
# ---------------------------------------------------------------------------


def rank_with_diagnostics(
    *,
    question_text: str,
    normalized_query: str,
    candidates: Sequence[LexicalCandidate],
    language: str,
    variant: str,
    stems: Mapping[str, str],
) -> tuple[list[LexicalCandidate], dict[Any, dict[str, Any]], dict[str, int]]:
    """Lista ordenada **completa** — sem corte — mais o destino de cada excluído.

    Espelha ``rank_with_variant`` de ``scripts.evaluate_retrieval_experiment``,
    e chama exatamente as mesmas funções de produção: ``decide_eligibility``,
    ``build_features``, ``compute_score`` e a mesma chave de ordenação. A única
    diferença é o que devolve: aqui a lista **não** é truncada em ``top_k``, e os
    candidatos excluídos vêm com motivo e cobertura.

    Devolver a lista inteira é o que permite distinguir "o ranking empurrou o
    alvo para fora do top 5" de "o alvo nunca sobreviveu à elegibilidade" — a
    distinção que dá nome a esta fase. Um teste fixa que o prefixo desta lista
    coincide com o resultado de ``rank_with_variant``, para que as duas não
    possam divergir em silêncio.
    """
    query_terms = informative_query_terms(normalized_query, language)
    explicit_syntax = uses_advanced_syntax(normalized_query)
    excluded_counts = {reason.value: 0 for reason in ExclusionReason}
    excluded_detail: dict[Any, dict[str, Any]] = {}

    scored: list[tuple[tuple[Any, ...], LexicalCandidate]] = []
    for candidate in candidates:
        base = compute_content_match(query_terms, candidate)
        representation = build_lexical_representation(
            candidate.normalized_content, candidate.language
        )
        projection = projection_for(
            variant,
            stems=stems,
            query_text=question_text,
            content_text=candidate.content,
        )
        match = variant_content_match(
            base=base,
            query_terms=query_terms,
            representation=representation,
            projection=projection,
        )
        decision = decide_eligibility(
            query_terms, match, candidate.strategy, explicit_syntax=explicit_syntax
        )
        if not decision.eligible:
            reason = decision.reason or ExclusionReason.NO_CONTENT_MATCH
            excluded_counts[reason.value] += 1
            excluded_detail[candidate.chunk_id] = {
                "reason": reason.value,
                "coverage": round(match.coverage, 6),
                "matched_terms": sorted(match.matched_terms),
            }
            continue
        features = build_features(query_terms, candidate, match)
        score = compute_score(features)
        if score < settings.retrieval_min_relevance_score:
            excluded_counts[ExclusionReason.BELOW_THRESHOLD.value] += 1
            excluded_detail[candidate.chunk_id] = {
                "reason": ExclusionReason.BELOW_THRESHOLD.value,
                "coverage": round(match.coverage, 6),
                "matched_terms": sorted(match.matched_terms),
            }
            continue
        key = (
            -score,
            -features.coverage,
            -features.strategy_quality,
            -candidate.raw_score,
            str(candidate.document_id),
            candidate.chunk_index,
            str(candidate.chunk_id),
        )
        scored.append((key, candidate))

    scored.sort(key=lambda item: item[0])
    return [candidate for _, candidate in scored], excluded_detail, excluded_counts


# ---------------------------------------------------------------------------
# Avaliação
# ---------------------------------------------------------------------------


def _target_records(
    question: Mapping[str, Any],
    *,
    document_index: Mapping[str, str],
    pool_keys: Mapping[tuple[str, int], Any],
    rank_by_key: Mapping[tuple[str, int], int],
    excluded_detail: Mapping[Any, Mapping[str, Any]],
    top_k: int,
) -> list[dict[str, Any]]:
    """Destino de cada segmento de grau 2, um a um."""
    records: list[dict[str, Any]] = []
    for judgment in question["evidence_judgments"]:
        if judgment["relevance"] < BINARY_RELEVANCE_THRESHOLD:
            continue
        key = (document_index[judgment["corpus_item_id"]], judgment["chunk_index"])
        chunk_id = pool_keys.get(key)
        rank = rank_by_key.get(key)
        detail = excluded_detail.get(chunk_id) if chunk_id is not None else None
        record: dict[str, Any] = {
            "corpus_item_id": judgment["corpus_item_id"],
            "chunk_index": judgment["chunk_index"],
            "in_candidate_pool": chunk_id is not None,
            "rank": rank,
            "fate": classify_target_fate(
                in_pool=chunk_id is not None,
                excluded_reason=detail["reason"] if detail else None,
                rank=rank,
                top_k=top_k,
            ),
        }
        if detail is not None:
            record["exclusion_reason"] = detail["reason"]
            record["coverage"] = detail["coverage"]
            record["matched_terms"] = detail["matched_terms"]
        records.append(record)
    return records


def evaluate_cell(
    db: Any,
    *,
    questions: Sequence[Mapping[str, Any]],
    document_index: Mapping[str, str],
    context: RetrievabilityContext,
    language: str,
    top_k: int,
    policy: str,
    variant: str,
    stems: Mapping[str, str],
) -> dict[str, Any]:
    """Uma célula: uma política de orçamento × uma política de correspondência."""
    per_question: list[dict[str, Any]] = []
    recalls: dict[int, list[float]] = {k: [] for k in K_VALUES}
    ndcgs: dict[int, list[float]] = {k: [] for k in K_VALUES}
    reciprocal_ranks: list[float] = []
    candidate_recalls: list[float] = []

    for question in questions:
        normalized_query = normalize_text(question["question"])
        pool, budget_trace = collect_candidates(
            db,
            normalized_query=normalized_query,
            context=context,
            language=language,
            top_k=top_k,
            policy=policy,
        )
        ranked, excluded_detail, excluded_counts = rank_with_diagnostics(
            question_text=question["question"],
            normalized_query=normalized_query,
            candidates=pool,
            language=language,
            variant=variant,
            stems=stems,
        )
        returned = ranked[:top_k]

        pool_keys = {
            (str(candidate.document_id), candidate.chunk_index): candidate.chunk_id
            for candidate in pool
        }
        rank_by_key = {
            (str(candidate.document_id), candidate.chunk_index): position
            for position, candidate in enumerate(ranked, start=1)
        }
        grades = judged_grade_index(question, document_index)
        retrieved_grades = [
            grades.get((str(candidate.document_id), candidate.chunk_index), UNJUDGED_GRADE)
            for candidate in returned
        ]
        judged_grades = [
            judgment["relevance"] for judgment in question["evidence_judgments"]
        ]
        total_relevant = sum(
            1 for grade in judged_grades if grade >= BINARY_RELEVANCE_THRESHOLD
        )
        targets = _target_records(
            question,
            document_index=document_index,
            pool_keys=pool_keys,
            rank_by_key=rank_by_key,
            excluded_detail=excluded_detail,
            top_k=top_k,
        )
        question_candidate_recall = candidate_recall([t["fate"] for t in targets])

        record: dict[str, Any] = {
            "question_id": question["question_id"],
            "candidates_evaluated": budget_trace["candidates_evaluated"],
            "budget_trace": budget_trace,
            "variants": budget_trace["variants"],
            "excluded_counts": excluded_counts,
            "ranked_survivors": len(ranked),
            "retrieved_count": len(returned),
            "retrieved_grades": retrieved_grades,
            "judged_distractors_returned": sum(
                1
                for candidate in returned
                if grades.get((str(candidate.document_id), candidate.chunk_index)) == 0
            ),
            "unjudged_returned": sum(
                1
                for candidate in returned
                if (str(candidate.document_id), candidate.chunk_index) not in grades
            ),
            "targets": targets,
            "candidate_recall": (
                None
                if question_candidate_recall is None
                else round(question_candidate_recall, 6)
            ),
            "ranking": [
                {
                    "position": position,
                    "corpus_item_id": _corpus_item_for(
                        str(candidate.document_id), document_index
                    ),
                    "chunk_index": candidate.chunk_index,
                    "grade": grades.get(
                        (str(candidate.document_id), candidate.chunk_index),
                        UNJUDGED_GRADE,
                    ),
                    "judged": (str(candidate.document_id), candidate.chunk_index)
                    in grades,
                }
                for position, candidate in enumerate(returned, start=1)
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
            if question_candidate_recall is not None:
                candidate_recalls.append(question_candidate_recall)
        else:
            record["measured"] = False
        per_question.append(record)

    fate_totals = {fate: 0 for fate in TARGET_FATES}
    for record in per_question:
        for target in record["targets"]:
            fate_totals[target["fate"]] += 1

    return {
        "budget_policy": policy,
        "matching_variant": variant,
        "aggregate": {
            "questions_measured": len(reciprocal_ranks),
            "recall": {str(k): round(mean(recalls[k]), 6) for k in K_VALUES},
            "mrr": round(mean(reciprocal_ranks), 6),
            "ndcg": {str(k): round(mean(ndcgs[k]), 6) for k in K_VALUES},
            "candidate_recall": round(mean(candidate_recalls), 6),
        },
        "target_fates": fate_totals,
        "totals": {
            "rows_fetched": sum(r["budget_trace"]["rows_fetched"] for r in per_question),
            "candidates_evaluated": sum(r["candidates_evaluated"] for r in per_question),
            "retrieved": sum(r["retrieved_count"] for r in per_question),
            "unjudged_returned": sum(r["unjudged_returned"] for r in per_question),
            "judged_distractors_returned": sum(
                r["judged_distractors_returned"] for r in per_question
            ),
        },
        "question_results": per_question,
    }


# ---------------------------------------------------------------------------
# Comparação entre políticas
# ---------------------------------------------------------------------------


def _ranking_signature(entries: Sequence[Mapping[str, Any]]) -> list[list[Any]]:
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


def compare_policies(
    control: Mapping[str, Any], candidate: Mapping[str, Any]
) -> dict[str, Any]:
    """Delta entre a política de produção e uma alternativa, na mesma correspondência."""
    control_by_id = {r["question_id"]: r for r in control["question_results"]}
    candidate_by_id = {r["question_id"]: r for r in candidate["question_results"]}

    changed: list[dict[str, Any]] = []
    unchanged: list[str] = []
    for question_id in sorted(control_by_id):
        before = control_by_id[question_id]
        after = candidate_by_id[question_id]
        measured = "recall" in before and "recall" in after
        metrics_changed = measured and (
            before["recall"] != after["recall"]
            or before["ndcg"] != after["ndcg"]
            or before["reciprocal_rank"] != after["reciprocal_rank"]
        )
        ranking_changed = _ranking_signature(before["ranking"]) != _ranking_signature(
            after["ranking"]
        )
        fates_changed = [t["fate"] for t in before["targets"]] != [
            t["fate"] for t in after["targets"]
        ]
        if not (metrics_changed or ranking_changed or fates_changed):
            unchanged.append(question_id)
            continue
        record: dict[str, Any] = {
            "question_id": question_id,
            "measured": measured,
            "direction": _direction(before, after) if measured else "observed_only",
            "candidates_evaluated": [
                before["candidates_evaluated"],
                after["candidates_evaluated"],
            ],
            "retrieved_count": [before["retrieved_count"], after["retrieved_count"]],
            "judged_distractors_returned": [
                before["judged_distractors_returned"],
                after["judged_distractors_returned"],
            ],
            "unjudged_returned": [
                before["unjudged_returned"],
                after["unjudged_returned"],
            ],
            "target_fates": [
                [t["fate"] for t in before["targets"]],
                [t["fate"] for t in after["targets"]],
            ],
            "ranking_before": _ranking_signature(before["ranking"]),
            "ranking_after": _ranking_signature(after["ranking"]),
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

    before_aggregate = control["aggregate"]
    after_aggregate = candidate["aggregate"]
    return {
        "matching_variant": control["matching_variant"],
        "from_policy": control["budget_policy"],
        "to_policy": candidate["budget_policy"],
        "policies_identical": not changed,
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
            "candidate_recall": round(
                after_aggregate["candidate_recall"]
                - before_aggregate["candidate_recall"],
                6,
            ),
        },
        "improved": [r["question_id"] for r in changed if r["direction"] == "improved"],
        "regressed": [r["question_id"] for r in changed if r["direction"] == "regressed"],
        "mixed": [r["question_id"] for r in changed if r["direction"] == "mixed"],
        "unchanged_count": len(unchanged),
        "questions_changed": changed,
    }


# ---------------------------------------------------------------------------
# Execução
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ground-truth", type=Path, required=True)
    parser.add_argument("--binding", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
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
    baseline = _load_json(args.baseline)

    try:
        verify_metric_protocol(dict(ground_truth))
    except BaselineError as error:
        raise ExperimentError(str(error), EXIT_USAGE) from error
    verify_baseline_integrity(baseline)

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
            institution_id=institution_id,
            language=language,
            reference_date=date.fromisoformat(ground_truth["reference_date"]),
            official_only=official_only,
        )
        stems = _stem_vocabulary(db, institution_id, questions)
        positions = target_candidate_positions(
            db,
            questions=questions,
            document_index=document_index,
            context=context,
            language=language,
            top_k=top_k,
        )

        cells = [
            evaluate_cell(
                db,
                questions=questions,
                document_index=document_index,
                context=context,
                language=language,
                top_k=top_k,
                policy=policy,
                variant=variant,
                stems=stems,
            )
            for variant in MATCHING_PANELS
            for policy in BUDGET_POLICIES
        ]

    by_key = {(cell["matching_variant"], cell["budget_policy"]): cell for cell in cells}

    control = by_key[(PRIMARY_MATCHING, BUDGET_CURRENT_QUOTA)]
    problems = verify_baseline_replication(control, baseline)
    if problems:
        raise ExperimentError(
            "the control cell does not reproduce the D4.2 baseline: " + "; ".join(problems),
            EXIT_BASELINE_MISMATCH,
        )

    position_problems = verify_positions_explain_fates(
        positions, [by_key[(variant, BUDGET_CURRENT_QUOTA)] for variant in MATCHING_PANELS]
    )
    if position_problems:
        raise ExperimentError(
            "the recorded FTS positions do not explain the observed target fates: "
            + "; ".join(position_problems),
            EXIT_BASELINE_MISMATCH,
        )

    comparisons = [
        compare_policies(by_key[(variant, BUDGET_CURRENT_QUOTA)], by_key[(variant, policy)])
        for variant in MATCHING_PANELS
        for policy in (BUDGET_REDISTRIBUTE_UNUSED, BUDGET_GLOBAL_LIMITED_POOL)
    ]

    payload: dict[str, Any] = {
        "schema_version": EXPERIMENT_SCHEMA_VERSION,
        "digest_algorithm": DIGEST_ALGORITHM,
        "corpus_id": ground_truth["corpus_id"],
        "snapshot_id": ground_truth["snapshot_id"],
        "corpus_digest": ground_truth["corpus_digest"],
        "reference_date": ground_truth["reference_date"],
        "ground_truth_digest": ground_truth_digest(ground_truth),
        "ground_truth_digest_algorithm": GROUND_TRUTH_DIGEST_ALGORITHM,
        "ground_truth_digest_scope": GROUND_TRUTH_DIGEST_SCOPE,
        "baseline_result_digest": baseline["result_digest"],
        "control_reproduces_baseline": True,
        "retrieval": retrieval,
        "global_candidate_budget": global_candidate_limit(top_k),
        "budget_policies": list(BUDGET_POLICIES),
        "matching_variants": list(MATCHING_PANELS),
        "primary_matching_variant": PRIMARY_MATCHING,
        "secondary_panel_note": (
            "The stem_normalized panel is diagnostic only: it answers whether "
            "redistributing the budget would unblock an alternative matching policy. "
            "No conclusion about the production quota rests on it."
        ),
        "target_fate_vocabulary": list(TARGET_FATES),
        "primary_k": PRIMARY_K,
        "target_candidate_positions": positions,
        "target_position_summary": _position_summary(positions),
        "positions_explain_observed_fates": True,
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
    _print_summary(cells, comparisons, payload)
    return EXIT_OK


def _position_summary(positions: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Resumo recontável a partir de ``target_candidate_positions``.

    Existe para que a afirmação do relatório sobre a proximidade dos alvos ao
    corte não seja uma contagem à mão. ``best_positions`` é a lista ordenada, de
    onde qualquer leitor reconstrói o número que quiser sem ter de confiar numa
    frase.
    """
    best = sorted(
        record["best_position"]
        for record in positions
        if record["best_position"] is not None
    )
    return {
        "targets_total": len(positions),
        "matched_by_any_variant": sum(
            1 for record in positions if record["matched_by_any_variant"]
        ),
        "reachable_under_current_quota": sum(
            1 for record in positions if record["reachable_under_current_quota"]
        ),
        "unreachable_under_current_quota": [
            f"{record['question_id']}:{record['corpus_item_id']}/{record['chunk_index']}"
            for record in positions
            if not record["reachable_under_current_quota"]
        ],
        "best_positions_sorted": best,
    }


def _stem_vocabulary(
    db: Any, institution_id: UUID, questions: Sequence[Mapping[str, Any]]
) -> dict[str, str]:
    """Mapa ``palavra -> radical`` partilhado por todas as células.

    Só o painel ``stem_normalized`` o usa, e apenas sobre formas sem acentos —
    as que o sistema já persiste. Um mapa único elimina a hipótese de duas
    células diferirem por terem visto vocabulários diferentes.
    """
    from sqlalchemy import select

    from app.models.document import Document
    from app.models.document_chunk import DocumentChunk
    from scripts.evaluate_retrieval_experiment import _WORD_RE

    vocabulary: set[str] = set()
    rows = db.execute(
        select(DocumentChunk.normalized_content)
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(Document.institution_id == institution_id)
    ).all()
    for (normalized,) in rows:
        vocabulary.update(_WORD_RE.findall(normalized))
    for question in questions:
        vocabulary.update(_WORD_RE.findall(normalize_text(question["question"])))
    return stem_words_batch(db, vocabulary)


def _print_summary(
    cells: Sequence[Mapping[str, Any]],
    comparisons: Sequence[Mapping[str, Any]],
    payload: Mapping[str, Any],
) -> None:
    for cell in cells:
        aggregate = cell["aggregate"]
        fates = cell["target_fates"]
        print(
            f"{cell['matching_variant']:16s} {cell['budget_policy']:21s} "
            f"R@5={aggregate['recall']['5']:.4f} MRR={aggregate['mrr']:.4f} "
            f"nDCG@5={aggregate['ndcg']['5']:.4f} "
            f"candR={aggregate['candidate_recall']:.4f} "
            f"ret={fates[FATE_RETURNED]} out={fates[FATE_RANKED_OUTSIDE_TOP_K]} "
            f"never={fates[FATE_NEVER_A_CANDIDATE]} "
            f"rows={cell['totals']['rows_fetched']}"
        )
    for comparison in comparisons:
        print(
            f"delta {comparison['matching_variant']:16s} "
            f"{comparison['from_policy']} -> {comparison['to_policy']:21s} "
            f"identical={comparison['policies_identical']!s:5s} "
            f"improved={comparison['improved']} regressed={comparison['regressed']} "
            f"mixed={comparison['mixed']}"
        )
    summary = payload["target_position_summary"]
    print(
        f"alvos: {summary['targets_total']} | alcancaveis com a quota atual: "
        f"{summary['reachable_under_current_quota']} | posicoes: "
        f"{summary['best_positions_sorted']}"
    )
    print(f"inalcancaveis       : {summary['unreachable_under_current_quota']}")
    print(f"ground_truth_digest : {payload['ground_truth_digest']}")
    print(f"result_digest       : {payload['result_digest']}")


if __name__ == "__main__":
    sys.exit(main())
