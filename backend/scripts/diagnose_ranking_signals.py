"""Repooling dirigido e diagnóstico dos sinais de ranking (D4.6).

Uso (a partir de ``backend/``, com o virtual environment ativo):

    python -m scripts.diagnose_ranking_signals \
        --ground-truth ../docs/evaluation/retrieval-ground-truth-p1-seed.json \
        --repooled-ground-truth ../docs/evaluation/retrieval-ground-truth-p1-repooled.json \
        --binding ../storage/pilot-corpus/S1-identifier-binding.json \
        --experiment ../docs/evaluation/retrieval-experiment-candidate-budget-p1-s1.json \
        --output ../docs/evaluation/ranking-diagnostics-p1-s1.json \
        [--overwrite]

**Não altera nada.** Não toca em pesos, limiares, fórmulas, orçamento,
elegibilidade nem no retrieval de produção. Recalcula duas condições do D4.5 com
os julgamentos reforçados e decompõe os sinais que decidem cada comparação.

Porque é que o repooling vem primeiro
-------------------------------------

O D4.5 mediu o ranking com **26 dos 33** resultados da condição ampliada por
julgar. Otimizar contra isso mediria sobretudo a incompletude da anotação. Por
isso a fase anota primeiro e diagnostica depois — e a primeira coisa que o
diagnóstico faz é mostrar o que o repooling **muda**, para que nenhuma diferença
posterior seja confundida com comportamento do sistema.

O critério de classificação, e o seu alcance
--------------------------------------------

Para cada par (alvo de grau 2, candidato acima dele) a decisão é aritmética, não
impressionista. O score é ``Σ wᵢ · sᵢ`` com todos os ``wᵢ ≥ 0``. Logo:

- se **todos** os sinais do alvo forem ``≤`` aos do concorrente, nenhuma
  reponderação com pesos não negativos pode inverter o par — os sinais atuais
  **não** contêm informação suficiente (**B**);
- se **algum** sinal favorecer o alvo, existe pelo menos uma reponderação que o
  inverteria — os sinais distinguem, e o problema pode ser de ponderação (**A**);
- se o alvo não chegou ao ranking, o par não é observável (**C**).

O alcance disto tem de ser dito: a dominância é sobre a **base linear existente**.
Alterar como um sinal é *calculado* — dar consciência de ano ao ``table_row``,
por exemplo — não é uma reponderação, é um sinal novo, e sai deliberadamente
fora desta classificação.

Guardas
-------

Nada é escrito se alguma falhar: o repooling tem de **estender** o conjunto
histórico sem rever nenhum julgamento; os dois digests têm de diferir; e as duas
condições, calculadas com o *ground truth* **histórico**, têm de reproduzir as
células correspondentes do D4.5 por inteiro.
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
from app.evaluation.lexical_variants import MATCHING_EXACT_CANONICAL
from app.evaluation.repooling import (
    denominator_changes,
    judgment_coverage,
    verify_repooling,
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
from app.retrieval.reranking import (
    W_COVERAGE,
    W_EXACT_PHRASE,
    W_FTS,
    W_ORDER,
    W_PROXIMITY,
    W_SECTION,
    W_STRATEGY,
    W_STRUCTURE,
    W_TITLE,
    LexicalCandidate,
    LexicalFeatures,
    build_features,
    compute_content_match,
    compute_score,
    informative_query_terms,
)
from scripts.evaluate_candidate_budget_experiment import (
    collect_candidates,
    rank_with_diagnostics,
)
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

DIAGNOSTICS_SCHEMA_VERSION: Final = "1"
DIGEST_ALGORITHM: Final = "sha256"

#: As duas condições de orçamento que a fase estuda. A correspondência é a de
#: produção: misturar a variante por radical traria um segundo fator.
POLICIES: Final = (BUDGET_CURRENT_QUOTA, BUDGET_REDISTRIBUTE_UNUSED)
MATCHING: Final = MATCHING_EXACT_CANONICAL

#: Base linear **real** de ``compute_score``, sinal a sinal. ``compactness`` e
#: ``length_factor`` não aparecem: não são termos do somatório — a primeira só
#: condiciona ``table_row_bonus`` e a segunda multiplica ``fts_norm``. Listá-las
#: aqui inventaria sinais que o código não tem.
SCORE_TERMS: Final[tuple[tuple[str, float], ...]] = (
    ("coverage", W_COVERAGE),
    ("exact_phrase", W_EXACT_PHRASE),
    ("proximity", W_PROXIMITY),
    ("ordered", W_ORDER),
    ("title_overlap", W_TITLE),
    ("structure_table_row", W_STRUCTURE),
    ("section_overlap", W_SECTION),
    ("fts_component", W_FTS),
    ("strategy_quality", W_STRATEGY),
)

DIAGNOSIS_REWEIGHTABLE: Final = "A_SIGNALS_DISCRIMINATE_WEIGHTING_MAY_BE_WRONG"
DIAGNOSIS_INSUFFICIENT: Final = "B_SIGNALS_INSUFFICIENT"
DIAGNOSIS_INDETERMINATE: Final = "C_INDETERMINATE"

EXIT_OK: Final = 0
EXIT_USAGE: Final = 2
EXIT_SNAPSHOT_MISMATCH: Final = 3
EXIT_BASELINE_MISMATCH: Final = 4
EXIT_OUTPUT_EXISTS: Final = 5
EXIT_REPOOLING_INVALID: Final = 6


def _load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ExperimentError(f"file not found: {path}", EXIT_USAGE) from error
    except json.JSONDecodeError as error:
        raise ExperimentError(f"invalid JSON in {path}: {error}", EXIT_USAGE) from error


# ---------------------------------------------------------------------------
# Decomposição dos sinais
# ---------------------------------------------------------------------------


def score_terms(features: LexicalFeatures) -> dict[str, float]:
    """Valor de cada termo do somatório, na forma em que ele entra no score."""
    return {
        "coverage": features.coverage,
        "exact_phrase": features.exact_phrase,
        "proximity": features.proximity,
        "ordered": features.ordered,
        "title_overlap": features.title_overlap,
        "structure_table_row": features.table_row_bonus,
        "section_overlap": features.section_overlap,
        # O comprimento não é um termo próprio: amortece o FTS dentro deste.
        "fts_component": features.fts_norm * features.length_factor,
        "strategy_quality": features.strategy_quality,
    }


def decompose(
    features: LexicalFeatures, *, structure_type: str | None = None
) -> dict[str, Any]:
    """Sinais, contribuições ponderadas e score, para uma linha do artefacto.

    ``structure_type`` viaja junto porque o bónus estrutural vale 0,06 e é
    concedido ou negado **por causa dele**. Sem o registar, a linha diria que o
    sinal decidiu a comparação sem dizer o que o produziu, e a explicação teria
    de viver fora do artefacto.
    """
    terms = score_terms(features)
    return {
        "score": round(compute_score(features), 6),
        "structure_type": structure_type,
        "signals": {name: round(value, 6) for name, value in terms.items()},
        "contributions": {
            name: round(weight * terms[name], 6) for name, weight in SCORE_TERMS
        },
        "auxiliary": {
            "compactness": round(features.compactness, 6),
            "length_factor": round(features.length_factor, 6),
            "fts_norm": round(features.fts_norm, 6),
            "matched_terms": sorted(features.matched_terms),
        },
    }


#: Chave usada quando um segmento não declara ``structure_type``. As chaves de um
#: objeto JSON têm de ser texto, e ``null`` perder-se-ia na serialização.
UNSPECIFIED_STRUCTURE: Final = "unspecified"


def document_structure_counts(db: Any, document_index: Mapping[str, str]) -> dict[str, Any]:
    """Contagem de segmentos por ``structure_type``, por documento do corpus.

    É a evidência do achado central do diagnóstico entre documentos: o bónus
    estrutural vale 0,06 e um documento sem segmentos ``table_row`` **nunca** o
    pode receber, por muito relevante que seja. Uma contagem que só existisse no
    relatório ficaria fora do ``result_digest`` e não seria reproduzível.

    São contagens, não conteúdo: nenhum texto documental atravessa a fronteira.
    """
    from sqlalchemy import func, select

    from app.models.document import Document
    from app.models.document_chunk import DocumentChunk

    by_document_id = {value: key for key, value in document_index.items()}
    rows = db.execute(
        select(Document.id, DocumentChunk.structure_type, func.count())
        .join(DocumentChunk, DocumentChunk.document_id == Document.id)
        .where(Document.id.in_([UUID(value) for value in document_index.values()]))
        .group_by(Document.id, DocumentChunk.structure_type)
    ).all()

    counts: dict[str, dict[str, int]] = {item: {} for item in document_index}
    for document_id, structure_type, total in rows:
        item = by_document_id[str(document_id)]
        counts[item][structure_type or UNSPECIFIED_STRUCTURE] = total
    return {
        item: dict(sorted(entry.items())) for item, entry in sorted(counts.items())
    }


def structure_bonus_availability(
    counts: Mapping[str, Mapping[str, int]],
) -> dict[str, Any]:
    """Que documentos podem, em princípio, receber o bónus estrutural.

    ``table_row_bonus`` exige ``structure_type == "table_row"``. Um documento com
    zero segmentos desse tipo tem o sinal **estruturalmente indisponível** — o
    ranking penaliza-o por uma propriedade da extração, não da pertinência.
    """
    eligible = sorted(item for item, entry in counts.items() if entry.get("table_row"))
    return {
        "signal": "structure_table_row",
        "weight": dict(SCORE_TERMS)["structure_table_row"],
        "requires_structure_type": "table_row",
        "documents_with_table_rows": eligible,
        "documents_without_table_rows": sorted(set(counts) - set(eligible)),
        "note": (
            "A document with no table_row chunk can never earn this bonus. Where "
            "such a document holds the correct evidence, the signal measures "
            "extraction quality rather than relevance."
        ),
    }


def compare_signals(
    target: LexicalFeatures, competitor: LexicalFeatures
) -> dict[str, Any]:
    """Quem cada sinal favorece, e se alguma reponderação inverteria o par.

    ``dominated`` é a afirmação forte: todos os sinais do alvo são ``≤`` aos do
    concorrente. Como todos os pesos são não negativos, nesse caso **nenhuma**
    reponderação da base atual coloca o alvo à frente.
    """
    target_terms = score_terms(target)
    competitor_terms = score_terms(competitor)
    per_signal: dict[str, Any] = {}
    favours_target = []
    favours_competitor = []
    for name, weight in SCORE_TERMS:
        difference = target_terms[name] - competitor_terms[name]
        if difference > 1e-9:
            favours = "target"
            favours_target.append(name)
        elif difference < -1e-9:
            favours = "competitor"
            favours_competitor.append(name)
        else:
            favours = "tie"
        per_signal[name] = {
            "target": round(target_terms[name], 6),
            "competitor": round(competitor_terms[name], 6),
            "favours": favours,
            "weighted_delta": round(weight * difference, 6),
        }
    return {
        "per_signal": per_signal,
        "favours_target": favours_target,
        "favours_competitor": favours_competitor,
        "dominated": not favours_target,
        "score_gap": round(compute_score(competitor) - compute_score(target), 6),
    }


def diagnose_pair(comparison: Mapping[str, Any]) -> str:
    if comparison["dominated"]:
        return DIAGNOSIS_INSUFFICIENT
    return DIAGNOSIS_REWEIGHTABLE


def common_signals_favouring_target(
    competitors: Sequence[Mapping[str, Any]],
) -> list[str]:
    """Sinais que favorecem o alvo contra **todos** os concorrentes de uma vez.

    A não dominância par a par diz que cada par é invertível **isoladamente**;
    não diz que exista uma ponderação única que inverta o conjunto. Um sinal que
    bata todos ao mesmo tempo é uma prova **suficiente** de que existe: basta
    concentrar o peso nele.

    A recíproca não vale, e é preciso dizê-lo: uma lista vazia não prova que
    nenhuma ponderação sirva — só que nenhuma **de um único sinal** serve. A
    resposta completa é um problema de viabilidade linear que esta fase não
    resolve, porque resolvê-lo já seria procurar pesos.
    """
    if not competitors:
        return []
    common: set[str] | None = None
    for competitor in competitors:
        favours = set(competitor["comparison"]["favours_target"])
        common = favours if common is None else common & favours
    return sorted(common or ())


# ---------------------------------------------------------------------------
# Avaliação de uma condição contra um ground truth
# ---------------------------------------------------------------------------


def _features_for(
    candidate: LexicalCandidate, query_terms: tuple[str, ...]
) -> LexicalFeatures:
    match = compute_content_match(query_terms, candidate)
    return build_features(query_terms, candidate, match)


def evaluate_condition(
    db: Any,
    *,
    questions: Sequence[Mapping[str, Any]],
    grading: Mapping[str, Mapping[str, Any]],
    document_index: Mapping[str, str],
    context: RetrievabilityContext,
    language: str,
    top_k: int,
    policy: str,
) -> tuple[dict[str, Any], dict[str, list[LexicalCandidate]], dict[str, tuple[str, ...]]]:
    """Métricas de uma condição, contra o *ground truth* passado em ``grading``.

    Devolve também as listas ordenadas e os termos de consulta, para que a
    decomposição dos sinais não tenha de repetir a execução — repeti-la abriria
    a porta a diagnosticar uma corrida diferente da que produziu as métricas.
    """
    per_question: list[dict[str, Any]] = []
    recalls: dict[int, list[float]] = {k: [] for k in K_VALUES}
    ndcgs: dict[int, list[float]] = {k: [] for k in K_VALUES}
    reciprocal_ranks: list[float] = []
    rankings: dict[str, list[LexicalCandidate]] = {}
    query_terms_by_question: dict[str, tuple[str, ...]] = {}

    for question in questions:
        question_id = question["question_id"]
        judged_question = grading[question_id]
        normalized_query = normalize_text(question["question"])
        pool, _budget_trace = collect_candidates(
            db,
            normalized_query=normalized_query,
            context=context,
            language=language,
            top_k=top_k,
            policy=policy,
        )
        ranked, _excluded_detail, _counts = rank_with_diagnostics(
            question_text=question["question"],
            normalized_query=normalized_query,
            candidates=pool,
            language=language,
            variant=MATCHING,
            stems={},
        )
        returned = ranked[:top_k]
        rankings[question_id] = ranked
        query_terms_by_question[question_id] = informative_query_terms(
            normalized_query, language
        )

        grades = judged_grade_index(judged_question, document_index)
        retrieved_grades = [
            grades.get((str(c.document_id), c.chunk_index), UNJUDGED_GRADE)
            for c in returned
        ]
        judged_grades = [
            judgment["relevance"] for judgment in judged_question["evidence_judgments"]
        ]
        total_relevant = sum(
            1 for grade in judged_grades if grade >= BINARY_RELEVANCE_THRESHOLD
        )
        returned_keys = [
            (
                _corpus_item_for(str(c.document_id), document_index) or "?",
                c.chunk_index,
            )
            for c in returned
        ]

        record: dict[str, Any] = {
            "question_id": question_id,
            "retrieved_count": len(returned),
            "total_relevant_judged": total_relevant,
            "judgment_coverage": judgment_coverage(judged_question, returned_keys),
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

    cell = {
        "budget_policy": policy,
        "matching_variant": MATCHING,
        "aggregate": {
            "questions_measured": len(reciprocal_ranks),
            "recall": {str(k): round(mean(recalls[k]), 6) for k in K_VALUES},
            "mrr": round(mean(reciprocal_ranks), 6),
            "ndcg": {str(k): round(mean(ndcgs[k]), 6) for k in K_VALUES},
        },
        "question_results": per_question,
    }
    return cell, rankings, query_terms_by_question


# ---------------------------------------------------------------------------
# Casos de ranking
# ---------------------------------------------------------------------------


def ranking_cases(
    *,
    policy: str,
    questions: Sequence[Mapping[str, Any]],
    grading: Mapping[str, Mapping[str, Any]],
    document_index: Mapping[str, str],
    rankings: Mapping[str, Sequence[LexicalCandidate]],
    query_terms_by_question: Mapping[str, tuple[str, ...]],
    top_k: int,
) -> list[dict[str, Any]]:
    """Todo o alvo de grau 2 ultrapassado por um candidato de grau inferior.

    Enumerado, não escolhido a dedo: qualquer alvo que apareça na lista ordenada
    com alguém menos relevante acima entra aqui, e os alvos que nunca chegam ao
    ranking entram como indeterminados.
    """
    cases: list[dict[str, Any]] = []
    for question in questions:
        question_id = question["question_id"]
        judged_question = grading[question_id]
        grades = judged_grade_index(judged_question, document_index)
        ranked = rankings[question_id]
        query_terms = query_terms_by_question[question_id]
        rank_by_key = {
            (str(c.document_id), c.chunk_index): position
            for position, c in enumerate(ranked, start=1)
        }
        features_cache: dict[Any, LexicalFeatures] = {
            c.chunk_id: _features_for(c, query_terms) for c in ranked
        }

        for judgment in judged_question["evidence_judgments"]:
            if judgment["relevance"] < BINARY_RELEVANCE_THRESHOLD:
                continue
            key = (document_index[judgment["corpus_item_id"]], judgment["chunk_index"])
            position = rank_by_key.get(key)
            if position is None:
                cases.append(
                    {
                        "budget_policy": policy,
                        "question_id": question_id,
                        "target": {
                            "corpus_item_id": judgment["corpus_item_id"],
                            "chunk_index": judgment["chunk_index"],
                        },
                        "target_rank": None,
                        "within_top_k": False,
                        "diagnosis": DIAGNOSIS_INDETERMINATE,
                        "diagnosis_note": (
                            "the target never reached the ranking; no signal "
                            "comparison is observable"
                        ),
                        "competitors": [],
                    }
                )
                continue

            target = ranked[position - 1]
            target_features = features_cache[target.chunk_id]
            competitors: list[dict[str, Any]] = []
            for above in ranked[: position - 1]:
                above_key = (str(above.document_id), above.chunk_index)
                grade = grades.get(above_key, UNJUDGED_GRADE)
                if grade >= BINARY_RELEVANCE_THRESHOLD:
                    continue
                comparison = compare_signals(target_features, features_cache[above.chunk_id])
                competitors.append(
                    {
                        "corpus_item_id": _corpus_item_for(
                            str(above.document_id), document_index
                        ),
                        "chunk_index": above.chunk_index,
                        "rank": rank_by_key[above_key],
                        "grade": grade,
                        "judged": above_key in grades,
                        "same_document_as_target": str(above.document_id) == key[0],
                        "structure_type": above.structure_type,
                        "decomposition": decompose(
                            features_cache[above.chunk_id],
                            structure_type=above.structure_type,
                        ),
                        "comparison": comparison,
                        "diagnosis": diagnose_pair(comparison),
                    }
                )
            if not competitors:
                continue
            diagnoses = {c["diagnosis"] for c in competitors}
            common = common_signals_favouring_target(competitors)
            insufficient = DIAGNOSIS_INSUFFICIENT in diagnoses
            cases.append(
                {
                    "budget_policy": policy,
                    "question_id": question_id,
                    "target": {
                        "corpus_item_id": judgment["corpus_item_id"],
                        "chunk_index": judgment["chunk_index"],
                    },
                    "target_rank": position,
                    "within_top_k": position <= top_k,
                    "target_structure_type": target.structure_type,
                    "target_decomposition": decompose(
                        target_features, structure_type=target.structure_type
                    ),
                    "unjudged_competitors": sum(
                        1 for c in competitors if not c["judged"]
                    ),
                    "cross_document_competitors": sum(
                        1 for c in competitors if not c["same_document_as_target"]
                    ),
                    "common_signals_favouring_target": common,
                    "single_signal_inversion_possible": bool(common),
                    "diagnosis": (
                        DIAGNOSIS_INSUFFICIENT if insufficient else DIAGNOSIS_REWEIGHTABLE
                    ),
                    "diagnosis_note": (
                        "at least one competitor dominates the target on every "
                        "signal; no non-negative reweighting inverts that pair"
                        if insufficient
                        else (
                            "every competitor is beaten by the target on some signal, "
                            "and at least one signal beats them all at once, so a "
                            "single reweighting demonstrably inverts the whole set"
                            if common
                            else "every competitor is beaten by the target on some "
                            "signal, but no single signal beats them all; pairwise "
                            "invertibility does not establish that one weighting "
                            "inverts the set"
                        )
                    ),
                    "competitors": competitors,
                }
            )
    return cases


# ---------------------------------------------------------------------------
# Execução
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ground-truth", type=Path, required=True)
    parser.add_argument("--repooled-ground-truth", type=Path, required=True)
    parser.add_argument("--binding", type=Path, required=True)
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


def _by_id(ground_truth: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {question["question_id"]: question for question in ground_truth["questions"]}


def _run(args: argparse.Namespace) -> int:
    if args.output.exists() and not args.overwrite:
        raise ExperimentError(
            f"refusing to overwrite {args.output} without --overwrite", EXIT_OUTPUT_EXISTS
        )

    historical = _load_json(args.ground_truth)
    repooled = _load_json(args.repooled_ground_truth)
    binding = _load_json(args.binding)
    experiment = _load_json(args.experiment)

    for ground_truth in (historical, repooled):
        try:
            verify_metric_protocol(dict(ground_truth))
        except BaselineError as error:
            raise ExperimentError(str(error), EXIT_USAGE) from error
    verify_baseline_integrity(experiment)

    report = verify_repooling(historical, repooled)
    if not report.valid:
        raise ExperimentError(
            "the repooled ground truth is not a valid extension of the historical "
            "one: " + "; ".join(report.problems),
            EXIT_REPOOLING_INVALID,
        )
    historical_digest = ground_truth_digest(historical)
    repooled_digest = ground_truth_digest(repooled)
    if historical_digest == repooled_digest:
        raise ExperimentError(
            "the repooled ground truth shares its digest with the historical one",
            EXIT_REPOOLING_INVALID,
        )

    retrieval = experiment["retrieval"]
    language = retrieval["language"]
    top_k = retrieval["top_k"]
    official_only = retrieval["official_only"]
    document_index = {
        item["corpus_item_id"]: item["document_id"]
        for item in binding["items"]
        if item.get("in_corpus")
    }
    questions = historical["questions"]
    historical_by_id = _by_id(historical)
    repooled_by_id = _by_id(repooled)

    with SessionLocalFactory() as db:
        verify_snapshot(
            db,
            ground_truth=historical,
            binding=binding,
            language=language,
            top_k=top_k,
            official_only=official_only,
        )
        context = RetrievabilityContext(
            institution_id=UUID(binding["institution_id"]),
            language=language,
            reference_date=date.fromisoformat(historical["reference_date"]),
            official_only=official_only,
        )

        structure_counts = document_structure_counts(db, document_index)
        cells: list[dict[str, Any]] = []
        cases: list[dict[str, Any]] = []
        for policy in POLICIES:
            for label, grading in (
                ("historical", historical_by_id),
                ("repooled", repooled_by_id),
            ):
                cell, rankings, query_terms = evaluate_condition(
                    db,
                    questions=questions,
                    grading=grading,
                    document_index=document_index,
                    context=context,
                    language=language,
                    top_k=top_k,
                    policy=policy,
                )
                cell["ground_truth"] = label
                cells.append(cell)
                if label == "repooled":
                    cases.extend(
                        ranking_cases(
                            policy=policy,
                            questions=questions,
                            grading=grading,
                            document_index=document_index,
                            rankings=rankings,
                            query_terms_by_question=query_terms,
                            top_k=top_k,
                        )
                    )

    by_key = {(cell["ground_truth"], cell["budget_policy"]): cell for cell in cells}
    d45_by_policy = {
        cell["budget_policy"]: cell
        for cell in experiment["cells"]
        if cell["matching_variant"] == MATCHING
    }
    for policy in POLICIES:
        problems = verify_baseline_replication(
            by_key[("historical", policy)], d45_by_policy[policy]
        )
        if problems:
            raise ExperimentError(
                f"the historical-ground-truth cell for {policy} does not reproduce "
                "the D4.5 cell: " + "; ".join(problems),
                EXIT_BASELINE_MISMATCH,
            )

    payload: dict[str, Any] = {
        "schema_version": DIAGNOSTICS_SCHEMA_VERSION,
        "digest_algorithm": DIGEST_ALGORITHM,
        "corpus_id": historical["corpus_id"],
        "snapshot_id": historical["snapshot_id"],
        "corpus_digest": historical["corpus_digest"],
        "reference_date": historical["reference_date"],
        "ground_truth_digest_algorithm": GROUND_TRUTH_DIGEST_ALGORITHM,
        "ground_truth_digest_scope": GROUND_TRUTH_DIGEST_SCOPE,
        "ground_truth_digest_before": historical_digest,
        "ground_truth_digest_after": repooled_digest,
        "repooling": {
            "artefact": args.repooled_ground_truth.name,
            "extends": args.ground_truth.name,
            "judgments_added": report.added_total,
            "judgments_added_by_grade": {
                str(grade): count for grade, count in report.added_by_grade.items()
            },
            "questions_touched": list(report.questions_touched),
            "added": [
                {
                    "question_id": question_id,
                    "corpus_item_id": item,
                    "chunk_index": index,
                    "relevance": grade,
                }
                for question_id, item, index, grade in report.added
            ],
            "recall_denominator_changes": denominator_changes(
                historical, repooled, BINARY_RELEVANCE_THRESHOLD
            ),
            "revisions": [],
            "revisions_note": (
                "A repooling may add judgments; revising an existing grade would "
                "make the D4.2-D4.5 series incomparable without saying so. The "
                "guard rejects any revision, so this list is empty by construction."
            ),
        },
        "d45_result_digest": experiment["result_digest"],
        "reproduces_d45_cells": True,
        "retrieval": retrieval,
        "matching_variant": MATCHING,
        "budget_policies": list(POLICIES),
        "primary_k": PRIMARY_K,
        "score_terms": [
            {"signal": name, "weight": weight} for name, weight in SCORE_TERMS
        ],
        "score_terms_note": (
            "The real linear basis of compute_score. compactness and length_factor "
            "are absent because they are not summands: the first only gates "
            "table_row_bonus, the second multiplies fts_norm inside fts_component."
        ),
        "document_structure_counts": structure_counts,
        "structure_bonus_availability": structure_bonus_availability(structure_counts),
        "cells": cells,
        "ranking_cases": cases,
        "diagnosis_summary": _diagnosis_summary(cases),
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


def _diagnosis_summary(cases: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for policy in POLICIES:
        policy_cases = [case for case in cases if case["budget_policy"] == policy]
        summary[policy] = {
            "cases": len(policy_cases),
            "by_diagnosis": {
                diagnosis: sum(
                    1 for case in policy_cases if case["diagnosis"] == diagnosis
                )
                for diagnosis in (
                    DIAGNOSIS_REWEIGHTABLE,
                    DIAGNOSIS_INSUFFICIENT,
                    DIAGNOSIS_INDETERMINATE,
                )
            },
            "questions": sorted({case["question_id"] for case in policy_cases}),
        }
    return summary


def _print_summary(payload: Mapping[str, Any]) -> None:
    repooling = payload["repooling"]
    print(
        f"repooling: +{repooling['judgments_added']} julgamentos "
        f"por grau {repooling['judgments_added_by_grade']} "
        f"em {len(repooling['questions_touched'])} perguntas"
    )
    print(f"denominador alterado: {repooling['recall_denominator_changes']}")
    print(f"digest antes : {payload['ground_truth_digest_before']}")
    print(f"digest depois: {payload['ground_truth_digest_after']}")
    for cell in payload["cells"]:
        aggregate = cell["aggregate"]
        print(
            f"{cell['budget_policy']:21s} {cell['ground_truth']:11s} "
            f"R@5={aggregate['recall']['5']:.4f} MRR={aggregate['mrr']:.4f} "
            f"nDCG@5={aggregate['ndcg']['5']:.4f}"
        )
    for policy, entry in payload["diagnosis_summary"].items():
        print(f"{policy:21s} casos={entry['cases']} {entry['by_diagnosis']}")
    availability = payload["structure_bonus_availability"]
    print(
        f"bonus estrutural (peso {availability['weight']}): "
        f"disponivel em {availability['documents_with_table_rows']} | "
        f"indisponivel em {availability['documents_without_table_rows']}"
    )
    print(f"result_digest: {payload['result_digest']}")


if __name__ == "__main__":
    sys.exit(main())
