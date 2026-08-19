"""D4.9 — funde os rankings da D4.8.1 por RRF e compara C0, C1 e C2.

Esta fase **não executa retrieval**. Consome os rankings já versionados pela
D4.8.1 e limita-se a reordená-los, pelo que não precisa de base de dados, de
rede, do SDK do fornecedor nem das Settings de produção. Há teste que confirma
que importar este módulo não carrega ``sqlalchemy`` nem ``openai``.

O que a fase mede, e o que não mede
-----------------------------------

Mede **fusão de posições**. Não mede admissão nem abstenção: a política
``top1 >= 0,60`` da D4.8.2 não é aplicada aqui, e aplicá-la faria com que um
resultado diferente não pudesse ser atribuído nem à fusão nem à admissão. C2 é
uma experiência de recuperação — não sabe quando deve recusar, e nenhuma métrica
abaixo diz que sabe.

Reprodução de C0 e C1
---------------------

O runner **recalcula** as métricas de C0 e C1 a partir dos rankings guardados e
exige que coincidam, casa a casa, com as que a D4.8.1 gravou. Não é cerimónia:
é o que prova que o código de métricas desta fase é o mesmo protocolo, e não uma
segunda implementação que produz números parecidos. Se divergir, a comparação
com C2 não teria significado e a execução pára antes de escrever seja o que for.
"""

import argparse
import hashlib
import json
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from app.evaluation.dense_baseline import (
    COMPARABLE,
    CONDITION_DENSE,
    CONDITION_LEXICAL,
    PoolItem,
)
from app.evaluation.ground_truth_identity import (
    GROUND_TRUTH_DIGEST_ALGORITHM,
    GROUND_TRUTH_DIGEST_SCOPE,
    ground_truth_digest,
)
from app.evaluation.hybrid_rrf import (
    CONDITION_HYBRID,
    FINAL_TOP_K,
    K_RRF,
    SOURCE_DEPTH,
    FusedItem,
    fusion_configuration,
    reciprocal_rank_fusion,
)
from app.evaluation.lexical_dense_comparison import artefact_digests
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

EXPERIMENT_VERSION: Final = "d4.9-hybrid-rrf-1"
DIGEST_ALGORITHM: Final = "sha256"

EXIT_OK: Final = 0
EXIT_OUTPUT_EXISTS: Final = 3
EXIT_GUARD_FAILED: Final = 4

#: Identidade da fonte, declarada aqui e não lida do ficheiro: se o artefacto da
#: D4.8.1 for substituído por outro, esta fase tem de recusar em vez de medir
#: contra uma base diferente sem dar por isso.
SOURCE_RESULT_DIGEST: Final = (
    "b708a70ed922c2937903033b1a3847457dffa3d682934d8e2e6b73e525f7a003"
)

# ---------------------------------------------------------------------------
# Critério de decisão — fixado antes de qualquer medição
# ---------------------------------------------------------------------------

#: Métrica principal da comparação. nDCG@5 e não Recall@5 porque a fusão altera
#: sobretudo **posições**, e o Recall com limiar binário no grau 2 é cego a
#: reordenações dentro do top 5.
PRIMARY_METRIC: Final = "ndcg@5"

#: Diferença a partir da qual um efeito é considerado material. É arbitrário no
#: sentido em que qualquer limiar o é. Com 12 perguntas, 0,02 de nDCG@5
#: macro-médio é aproximadamente o que uma única pergunta produz ao trocar uma
#: posição no meio do top 5 — abaixo disso, a amostra não distingue efeito de
#: ruído.
#:
#: **Sobre a ordem temporal, com precisão:** este valor foi escrito antes de a
#: experiência correr, mas vive na mesma árvore de trabalho que o resultado e
#: não há commit que separe um do outro. O histórico do repositório **não prova**
#: que precedeu a medição — só o testemunho de quem o escreveu o afirma. Quem
#: auditar deve tratar o limiar como *declarado na implementação*, não como
#: pré-registo verificável, e ler a decisão com essa reserva. Uma fase futura que
#: queira a garantia forte tem de commitar o protocolo antes de medir, como a
#: D4.8.2 fez com o seu `protocol_digest`.
MATERIAL_DELTA: Final = 0.02

#: A comparação que decide é **C2 contra C1**. C1 já é muito superior a C0, pelo
#: que «C2 > C0» não é informação: seria satisfeito por qualquer fusão que
#: preservasse a ordem densa.
DECISION_BASELINE: Final = CONDITION_DENSE

DECISION_RULE: Final = {
    "primary_metric": PRIMARY_METRIC,
    "baseline": DECISION_BASELINE,
    "material_delta": MATERIAL_DELTA,
    "evaluated_in_order": [
        (
            "B_DENSE_REMAINS_PREFERRED: alguma pergunta resolvida por C1 deixa "
            "de ser resolvida por C2, OU Recall@5 desce, OU nDCG@5 desce pelo "
            "menos material_delta."
        ),
        (
            "A_HYBRID_SUPPORTED: nDCG@5 sobe pelo menos material_delta, "
            "Recall@5 nao desce, nenhuma pergunta e perdida e os alvos "
            "exclusivos de C0 preservados por C2 nao sao menos do que os que C1 "
            "preservava."
        ),
        (
            "D_HYBRID_PROMISING_BUT_NEEDS_BROADER_EVALUATION: ha beneficio "
            "concreto de complementaridade - um alvo de grau 2 que C1 nao tinha "
            "no top 5 passa a estar, ou alguma pergunta melhora - mas o ganho "
            "agregado fica abaixo de material_delta."
        ),
        (
            "C_EVIDENCE_INSUFFICIENT: sem regressao, sem beneficio concreto e "
            "com |delta| abaixo de material_delta - o efeito e demasiado "
            "pequeno para sustentar decisao arquitetural nesta amostra."
        ),
    ],
    "note": (
        "Declarado na implementacao e registado como fixado antes da execucao. "
        "Nenhum criterio foi acrescentado, removido ou reordenado depois de "
        "observar os resultados."
    ),
    "pre_registration_caveat": (
        "A ordem temporal NAO tem prova independente: a regra e o resultado "
        "vivem na mesma arvore de trabalho e nenhum commit os separa. Tratar "
        "como criterio declarado na implementacao, nao como pre-registo "
        "auditavel. Ver MATERIAL_DELTA em scripts.evaluate_hybrid_rrf."
    ),
}

DECISION_A: Final = "A_HYBRID_SUPPORTED"
DECISION_B: Final = "B_DENSE_REMAINS_PREFERRED"
DECISION_C: Final = "C_EVIDENCE_INSUFFICIENT"
DECISION_D: Final = "D_HYBRID_PROMISING_BUT_NEEDS_BROADER_EVALUATION"


class GuardError(RuntimeError):
    """Uma pré-condição da fase falhou. Nada é escrito."""


# ---------------------------------------------------------------------------
# Carregamento e guardas
# ---------------------------------------------------------------------------


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        msg = f"{path}: expected a JSON object"
        raise GuardError(msg)
    return payload


def verify_source_integrity(source: Mapping[str, Any]) -> None:
    """O artefacto da D4.8.1 tem de ser aquele que os seus digests declaram."""
    result, execution = artefact_digests(source)
    declared_result = source.get("result_digest")
    declared_execution = source.get("execution_digest")
    if declared_result != result:
        msg = (
            "D4.8.1 result_digest nao confere: o ficheiro declara "
            f"{declared_result} e o conteudo produz {result}"
        )
        raise GuardError(msg)
    if declared_execution != execution:
        msg = (
            "D4.8.1 execution_digest nao confere: o ficheiro declara "
            f"{declared_execution} e o conteudo produz {execution}"
        )
        raise GuardError(msg)
    if declared_result != SOURCE_RESULT_DIGEST:
        msg = (
            "a fonte nao e a D4.8.1 que esta fase declara medir: esperado "
            f"{SOURCE_RESULT_DIGEST}, encontrado {declared_result}"
        )
        raise GuardError(msg)


def verify_ground_truth(
    source: Mapping[str, Any], ground_truth: Mapping[str, Any]
) -> None:
    """A identidade do ground truth e o protocolo de métricas têm de coincidir."""
    recomputed = ground_truth_digest(ground_truth)
    if recomputed != source["ground_truth_digest"]:
        msg = (
            "ground_truth_digest divergente: a D4.8.1 mediu contra "
            f"{source['ground_truth_digest']} e o ficheiro produz {recomputed}"
        )
        raise GuardError(msg)
    if source["ground_truth_digest_algorithm"] != GROUND_TRUTH_DIGEST_ALGORITHM:
        msg = "algoritmo de digest do ground truth divergente"
        raise GuardError(msg)
    if source["ground_truth_digest_scope"] != GROUND_TRUTH_DIGEST_SCOPE:
        msg = "ambito de digest do ground truth divergente"
        raise GuardError(msg)

    protocol = ground_truth["metric_protocol"]
    expected = {
        "k_values": list(K_VALUES),
        "primary_k": PRIMARY_K,
        "binary_relevance_threshold": BINARY_RELEVANCE_THRESHOLD,
        "ndcg_gain_mapping": {str(k): v for k, v in NDCG_GAIN_BY_GRADE.items()},
        "unjudged_chunk_treatment": "ASSUMED_IRRELEVANT",
    }
    for key, value in expected.items():
        if protocol.get(key) != value:
            msg = (
                f"metric_protocol.{key} divergente: o ficheiro declara "
                f"{protocol.get(key)!r} e o codigo usa {value!r}"
            )
            raise GuardError(msg)
    if UNJUDGED_GRADE != 0:
        msg = "UNJUDGED_GRADE divergente do protocolo"
        raise GuardError(msg)


def verify_comparability(source: Mapping[str, Any]) -> None:
    """A união dos dois top 5 tem de estar inteiramente julgada."""
    if source["comparability"] != COMPARABLE:
        msg = f"comparabilidade {source['comparability']!r}: C2 nao e mensuravel"
        raise GuardError(msg)
    if source["unjudged_in_top_k_total"] != 0:
        msg = (
            "existem resultados por julgar no top 5 da D4.8.1: "
            f"{source['unjudged_in_top_k_total']}"
        )
        raise GuardError(msg)


def verify_snapshot(source: Mapping[str, Any], ground_truth: Mapping[str, Any]) -> None:
    for field in ("corpus_id", "snapshot_id", "corpus_digest", "reference_date"):
        if source[field] != ground_truth[field]:
            msg = (
                f"{field} divergente entre a D4.8.1 ({source[field]!r}) e o "
                f"ground truth ({ground_truth[field]!r})"
            )
            raise GuardError(msg)


# ---------------------------------------------------------------------------
# Métricas, na definição do protocolo
# ---------------------------------------------------------------------------


def condition_metrics(
    grades: Sequence[int], judged_grades: Sequence[int]
) -> dict[str, Any]:
    """As métricas do protocolo, sobre um ranking já resolvido em graus.

    Deliberadamente idêntica à da D4.8/D4.8.1 — as mesmas funções puras, as
    mesmas constantes, o mesmo arredondamento. O runner verifica-o reproduzindo
    C0 e C1 antes de medir C2.
    """
    total_relevant = sum(
        1 for grade in judged_grades if grade >= BINARY_RELEVANCE_THRESHOLD
    )
    return {
        "total_relevant_judged": total_relevant,
        "recall": {
            str(k): round(recall_at_k(grades, total_relevant, k), 6) for k in K_VALUES
        },
        "reciprocal_rank": round(reciprocal_rank(grades), 6),
        "ndcg": {
            str(k): round(ndcg_at_k(grades, judged_grades, k), 6) for k in K_VALUES
        },
    }


def aggregate_metrics(measured: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Macro-média: cada pergunta pesa o mesmo, como em toda a série D4."""
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


def metric_delta(left: Mapping[str, Any], right: Mapping[str, Any]) -> dict[str, Any]:
    """``left - right`` para o bloco agregado, casa a casa."""
    return {
        "recall": {
            str(k): round(left["recall"][str(k)] - right["recall"][str(k)], 6)
            for k in K_VALUES
        },
        "mrr": round(left["mrr"] - right["mrr"], 6),
        "ndcg": {
            str(k): round(left["ndcg"][str(k)] - right["ndcg"][str(k)], 6)
            for k in K_VALUES
        },
    }


# ---------------------------------------------------------------------------
# Fusão
# ---------------------------------------------------------------------------


def pool_items(ranking: Sequence[Mapping[str, Any]]) -> tuple[PoolItem, ...]:
    """Extrai a sequência ordenada de identidades de um ranking do artefacto.

    Só a identidade atravessa esta fronteira. O ``score`` fica para trás aqui, e
    não na função de fusão: assim o score não chega sequer a estar ao alcance do
    código que ordena.
    """
    ordered = sorted(ranking, key=lambda entry: entry["position"])
    return tuple(
        PoolItem(corpus_item_id=entry["corpus_item_id"], chunk_index=entry["chunk_index"])
        for entry in ordered
    )


def grades_by_item(question: Mapping[str, Any]) -> dict[PoolItem, int]:
    """``PoolItem -> grau`` a partir dos rankings já julgados da D4.8.1."""
    grades: dict[PoolItem, int] = {}
    for condition in (CONDITION_LEXICAL, CONDITION_DENSE):
        for entry in question["conditions"][condition]["ranking"]:
            item = PoolItem(
                corpus_item_id=entry["corpus_item_id"], chunk_index=entry["chunk_index"]
            )
            grade = int(entry["grade"])
            if grades.setdefault(item, grade) != grade:
                msg = f"grau inconsistente para {item} em {question['question_id']}"
                raise GuardError(msg)
    return grades


def fused_ranking_record(
    fused: Sequence[FusedItem], grades: Mapping[PoolItem, int]
) -> list[dict[str, Any]]:
    """O ranking de C2 na forma do artefacto — sem score original nenhum."""
    return [
        {
            "position": position,
            "corpus_item_id": entry.item.corpus_item_id,
            "chunk_index": entry.item.chunk_index,
            "rrf_score": round(float(entry.rrf_score), 8),
            "rank_c0": entry.rank_c0,
            "rank_c1": entry.rank_c1,
            "contributing_conditions": list(entry.contributing_conditions),
            "grade": grades[entry.item],
            "judged": True,
        }
        for position, entry in enumerate(fused, start=1)
    ]


# ---------------------------------------------------------------------------
# Análise por pergunta
# ---------------------------------------------------------------------------


def solved(metrics: Mapping[str, Any]) -> bool:
    """Uma pergunta está resolvida quando há um grau 2 no top 5."""
    return metrics["reciprocal_rank"] > 0.0


def compare(left: Mapping[str, Any], right: Mapping[str, Any]) -> str:
    """``improves`` / ``equal`` / ``worsens`` de ``left`` face a ``right``.

    O critério é o par (reciprocal rank, nDCG@5), por esta ordem: a posição do
    primeiro alvo domina, e o nDCG desempata reordenações que não a mudam.
    """
    left_key = (left["reciprocal_rank"], left["ndcg"][str(PRIMARY_K)])
    right_key = (right["reciprocal_rank"], right["ndcg"][str(PRIMARY_K)])
    if left_key > right_key:
        return "improves"
    if left_key < right_key:
        return "worsens"
    return "equal"


def target_ranks(
    ranking: Sequence[Mapping[str, Any]], targets: Sequence[PoolItem]
) -> dict[str, int | None]:
    """Posição de cada alvo de grau 2 no ranking, ou ``None`` se ausente."""
    positions = {
        PoolItem(entry["corpus_item_id"], entry["chunk_index"]): entry["position"]
        for entry in ranking
    }
    return {f"{item.corpus_item_id}#{item.chunk_index}": positions.get(item) for item in targets}


def evaluate_question(question: Mapping[str, Any]) -> dict[str, Any]:
    """Funde uma pergunta e compara as três condições."""
    question_id = question["question_id"]
    conditions = question["conditions"]
    grades = grades_by_item(question)
    judged_grades = list(question["judged_grades"])

    rankings = {
        CONDITION_LEXICAL: pool_items(conditions[CONDITION_LEXICAL]["ranking"]),
        CONDITION_DENSE: pool_items(conditions[CONDITION_DENSE]["ranking"]),
    }
    union = set(rankings[CONDITION_LEXICAL]) | set(rankings[CONDITION_DENSE])

    fused = reciprocal_rank_fusion(rankings)
    outside = [entry.item for entry in fused if entry.item not in union]
    if outside:
        msg = (
            f"{question_id}: C2 devolveu segmentos fora da uniao dos top 5: "
            f"{sorted((item.corpus_item_id, item.chunk_index) for item in outside)}"
        )
        raise GuardError(msg)
    unjudged = [entry.item for entry in fused if entry.item not in grades]
    if unjudged:
        msg = f"{question_id}: C2 devolveu segmentos nao julgados: {sorted(unjudged)}"
        raise GuardError(msg)

    record: dict[str, Any] = {
        "question_id": question_id,
        "temporal_scope": question["temporal_scope"],
        "no_relevant_evidence": question["no_relevant_evidence"],
        "excluded_from_metrics": question["excluded_from_metrics"],
        "measured": question["measured"],
        "judged_grades": judged_grades,
        "union_size": len(union),
        "conditions": {},
    }

    # C0 e C1 reproduzidos a partir dos rankings guardados. As métricas só
    # existem para perguntas mensuráveis: Recall, MRR e nDCG são indefinidos sem
    # alvo (Q013), e a pergunta temporalmente ambígua continua fora (Q014).
    for condition in (CONDITION_LEXICAL, CONDITION_DENSE):
        ranking = conditions[condition]["ranking"]
        reproduced = (
            condition_metrics([int(entry["grade"]) for entry in ranking], judged_grades)
            if question["measured"]
            else None
        )
        stored = conditions[condition].get("metrics")
        if question["measured"] and stored != reproduced:
            msg = (
                f"{question_id}: {condition} nao reproduz as metricas da D4.8.1.\n"
                f"  guardado:    {stored}\n  reproduzido: {reproduced}"
            )
            raise GuardError(msg)
        record["conditions"][condition] = {
            "condition": condition,
            "retrieved_count": len(ranking),
            "ranking": [
                {
                    "position": entry["position"],
                    "corpus_item_id": entry["corpus_item_id"],
                    "chunk_index": entry["chunk_index"],
                    "grade": entry["grade"],
                }
                for entry in ranking
            ],
            "metrics": reproduced,
        }

    fused_record = fused_ranking_record(fused, grades)
    hybrid_metrics = (
        condition_metrics([entry["grade"] for entry in fused_record], judged_grades)
        if question["measured"]
        else None
    )
    record["conditions"][CONDITION_HYBRID] = {
        "condition": CONDITION_HYBRID,
        "retrieved_count": len(fused_record),
        "ranking": fused_record,
        "metrics": hybrid_metrics,
    }

    targets = sorted(item for item, grade in grades.items() if grade >= BINARY_RELEVANCE_THRESHOLD)
    record["grade2_targets"] = {
        "count": len(targets),
        "ranks": {
            CONDITION_LEXICAL: target_ranks(
                record["conditions"][CONDITION_LEXICAL]["ranking"], targets
            ),
            CONDITION_DENSE: target_ranks(
                record["conditions"][CONDITION_DENSE]["ranking"], targets
            ),
            CONDITION_HYBRID: target_ranks(fused_record, targets),
        },
    }
    if hybrid_metrics is None:
        record["comparison"] = None
        return record

    lexical_metrics = record["conditions"][CONDITION_LEXICAL]["metrics"]
    dense_metrics = record["conditions"][CONDITION_DENSE]["metrics"]
    record["comparison"] = {
        "c2_versus_c0": compare(hybrid_metrics, lexical_metrics),
        "c2_versus_c1": compare(hybrid_metrics, dense_metrics),
        "solved": {
            CONDITION_LEXICAL: solved(lexical_metrics),
            CONDITION_DENSE: solved(dense_metrics),
            CONDITION_HYBRID: solved(hybrid_metrics),
        },
    }
    return record


# ---------------------------------------------------------------------------
# Complementaridade e decisão
# ---------------------------------------------------------------------------


def complementarity(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """O que a fusão fez à evidência que cada condição via sozinha."""
    c0_only_preserved = 0
    c0_only_total = 0
    c1_only_preserved = 0
    c1_only_total = 0
    promoted = 0
    demoted = 0
    recovered_for_c1: list[str] = []

    for record in records:
        if not record["measured"]:
            continue
        ranks = record["grade2_targets"]["ranks"]
        for key in ranks[CONDITION_HYBRID]:
            rank_c0 = ranks[CONDITION_LEXICAL][key]
            rank_c1 = ranks[CONDITION_DENSE][key]
            rank_c2 = ranks[CONDITION_HYBRID][key]
            if rank_c0 is not None and rank_c1 is None:
                c0_only_total += 1
                if rank_c2 is not None:
                    c0_only_preserved += 1
                    recovered_for_c1.append(f"{record['question_id']}:{key}")
            if rank_c1 is not None and rank_c0 is None:
                c1_only_total += 1
                if rank_c2 is not None:
                    c1_only_preserved += 1
            if rank_c1 is not None and rank_c2 is not None:
                if rank_c2 < rank_c1:
                    promoted += 1
                elif rank_c2 > rank_c1:
                    demoted += 1

    return {
        "grade2_targets_exclusive_to_c0": c0_only_total,
        "grade2_targets_exclusive_to_c0_preserved_by_c2": c0_only_preserved,
        "grade2_targets_exclusive_to_c1": c1_only_total,
        "grade2_targets_exclusive_to_c1_preserved_by_c2": c1_only_preserved,
        "grade2_targets_promoted_over_c1": promoted,
        "grade2_targets_demoted_versus_c1": demoted,
        "grade2_targets_c1_missed_and_c2_recovered": sorted(recovered_for_c1),
        "questions_improved_over_c1": sum(
            1
            for record in records
            if record["measured"] and record["comparison"]["c2_versus_c1"] == "improves"
        ),
        "questions_worsened_versus_c1": sum(
            1
            for record in records
            if record["measured"] and record["comparison"]["c2_versus_c1"] == "worsens"
        ),
        "questions_solved_by_c1_and_lost_by_c2": sorted(
            record["question_id"]
            for record in records
            if record["measured"]
            and record["comparison"]["solved"][CONDITION_DENSE]
            and not record["comparison"]["solved"][CONDITION_HYBRID]
        ),
        "questions_solved_by_c2_and_not_by_c1": sorted(
            record["question_id"]
            for record in records
            if record["measured"]
            and record["comparison"]["solved"][CONDITION_HYBRID]
            and not record["comparison"]["solved"][CONDITION_DENSE]
        ),
    }


def decide(
    delta: Mapping[str, Any], analysis: Mapping[str, Any]
) -> dict[str, Any]:
    """Aplica o critério declarado em :data:`DECISION_RULE`, sem interpretação.

    «Declarado», e não «pré-registado»: ver a ressalva em
    :data:`MATERIAL_DELTA` sobre o que o histórico do repositório prova e o que
    não prova quanto à ordem temporal.
    """
    delta_ndcg5 = delta["ndcg"][str(PRIMARY_K)]
    delta_recall5 = delta["recall"][str(PRIMARY_K)]
    lost = analysis["questions_solved_by_c1_and_lost_by_c2"]
    recovered = analysis["grade2_targets_c1_missed_and_c2_recovered"]
    improved = analysis["questions_improved_over_c1"]
    preserved_c0_only = (
        analysis["grade2_targets_exclusive_to_c0_preserved_by_c2"]
        == analysis["grade2_targets_exclusive_to_c0"]
    )

    if lost or delta_recall5 < 0 or delta_ndcg5 <= -MATERIAL_DELTA:
        decision = DECISION_B
        rationale = (
            f"perguntas perdidas: {lost or 'nenhuma'}; delta Recall@5 "
            f"{delta_recall5}; delta nDCG@5 {delta_ndcg5}"
        )
    elif delta_ndcg5 >= MATERIAL_DELTA and delta_recall5 >= 0 and preserved_c0_only:
        decision = DECISION_A
        rationale = (
            f"delta nDCG@5 {delta_ndcg5} >= {MATERIAL_DELTA}, Recall@5 nao desce "
            f"({delta_recall5}) e os alvos exclusivos de C0 foram preservados"
        )
    elif recovered or improved:
        decision = DECISION_D
        rationale = (
            f"beneficio concreto - alvos recuperados {recovered or 'nenhum'}, "
            f"perguntas melhoradas {improved} - mas delta nDCG@5 {delta_ndcg5} "
            f"fica abaixo de {MATERIAL_DELTA}"
        )
    else:
        decision = DECISION_C
        rationale = (
            f"sem regressao, sem beneficio concreto e delta nDCG@5 {delta_ndcg5} "
            f"abaixo de {MATERIAL_DELTA}"
        )

    return {
        "decision": decision,
        "rationale": rationale,
        "primary_metric": PRIMARY_METRIC,
        "baseline": DECISION_BASELINE,
        "material_delta": MATERIAL_DELTA,
        "delta_ndcg_at_5": delta_ndcg5,
        "delta_recall_at_5": delta_recall5,
        "decision_rule_source": "scripts.evaluate_hybrid_rrf.DECISION_RULE",
    }


# ---------------------------------------------------------------------------
# Q013 e Q014
# ---------------------------------------------------------------------------


def no_evidence_analysis(records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """O que cada condição devolve numa pergunta sem evidência no corpus.

    Contagens e graus, e nada mais. **Não** se propõe limiar nenhum: uma amostra
    de uma pergunta não fundamenta um limiar, e a admissão foi estudada — e
    fechada — na D4.8.2.
    """
    analysis = []
    for record in records:
        if not record["no_relevant_evidence"]:
            continue
        entry: dict[str, Any] = {
            "question_id": record["question_id"],
            "excluded_from_metrics": True,
            "exclusion_basis": "no_relevant_evidence",
            "note": (
                "Excluida de Recall, MRR e nDCG por indefinicao (nao ha alvo). "
                "Nenhum limiar hibrido e proposto ou implementado."
            ),
        }
        for condition in (CONDITION_LEXICAL, CONDITION_DENSE, CONDITION_HYBRID):
            ranking = record["conditions"][condition]["ranking"]
            histogram = {"0": 0, "1": 0, "2": 0}
            for result in ranking:
                histogram[str(result["grade"])] += 1
            entry[condition] = {
                "retrieved": len(ranking),
                "grade_histogram": histogram,
                "irrelevant_returned": histogram["0"],
            }
        analysis.append(entry)
    return analysis


def excluded_analysis(
    source: Mapping[str, Any], records: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """As exclusões metodológicas herdadas, preservadas tal como estavam."""
    excluded = []
    for question in source["excluded_questions"]:
        record = next(
            item for item in records if item["question_id"] == question["question_id"]
        )
        excluded.append(
            {
                "question_id": question["question_id"],
                "exclusion_reason": question["exclusion_reason"],
                "handling": (
                    "Continua excluida de todas as metricas. A D4.9 nao resolve "
                    "a ambiguidade temporal nem inventa uma convencao de "
                    "vigencia: fundir rankings nao produz informacao "
                    "institucional que o corpus nao tem."
                ),
                "c2_retrieved": record["conditions"][CONDITION_HYBRID]["retrieved_count"],
            }
        )
    return excluded


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def build_payload(
    source: Mapping[str, Any], ground_truth: Mapping[str, Any]
) -> dict[str, Any]:
    """Constrói o artefacto completo, sem o escrever."""
    records = [evaluate_question(question) for question in source["question_results"]]
    measured = [record for record in records if record["measured"]]

    aggregate = {
        condition: aggregate_metrics(
            [record["conditions"][condition]["metrics"] for record in measured]
        )
        for condition in (CONDITION_LEXICAL, CONDITION_DENSE, CONDITION_HYBRID)
    }
    for condition in (CONDITION_LEXICAL, CONDITION_DENSE):
        if aggregate[condition] != source["aggregate"][condition]:
            msg = (
                f"o agregado de {condition} nao reproduz a D4.8.1.\n"
                f"  guardado:    {source['aggregate'][condition]}\n"
                f"  reproduzido: {aggregate[condition]}"
            )
            raise GuardError(msg)

    delta_c1 = metric_delta(aggregate[CONDITION_HYBRID], aggregate[CONDITION_DENSE])
    analysis = complementarity(records)

    payload: dict[str, Any] = {
        "experiment_version": EXPERIMENT_VERSION,
        "digest_algorithm": DIGEST_ALGORITHM,
        "scope_note": (
            "Experiencia offline de fusao de rankings. Nao altera o retrieval de "
            "producao, nao liga a condicao densa a API, nao aplica politica de "
            "admissao e nao e uma medida de answerability."
        ),
        "corpus_id": source["corpus_id"],
        "snapshot_id": source["snapshot_id"],
        "corpus_digest": source["corpus_digest"],
        "reference_date": source["reference_date"],
        "ground_truth_digest": source["ground_truth_digest"],
        "ground_truth_digest_algorithm": source["ground_truth_digest_algorithm"],
        "ground_truth_digest_scope": source["ground_truth_digest_scope"],
        "source_experiment_version": source["experiment_version"],
        "source_result_digest": source["result_digest"],
        "source_execution_digest": source["execution_digest"],
        "comparability": source["comparability"],
        "unjudged_in_top_k_total": 0,
        "primary_k": PRIMARY_K,
        "retrieval": source["retrieval"],
        "embedding": source["embedding"],
        "source_conditions": {
            CONDITION_LEXICAL: source["conditions"][CONDITION_LEXICAL],
            CONDITION_DENSE: source["conditions"][CONDITION_DENSE],
        },
        "conditions_reproduced": {
            CONDITION_LEXICAL: True,
            CONDITION_DENSE: True,
            "note": (
                "As metricas de C0 e C1 foram recalculadas a partir dos rankings "
                "guardados e conferem casa a casa com as da D4.8.1, por pergunta "
                "e no agregado. E o que prova que C2 e medido pelo mesmo "
                "protocolo e nao por uma segunda implementacao."
            ),
        },
        "fusion": fusion_configuration(),
        "admission_policy_applied": False,
        "admission_policy_note": (
            "A politica R1 top1 >= 0,60 da D4.8.2 NAO e aplicada. Fundir e "
            "admitir sao dois mecanismos, e altera-los na mesma experiencia "
            "tornaria o resultado inatribuivel. A D4.8.2 permanece fechada."
        ),
        "aggregate": aggregate,
        "aggregate_delta_c2_minus_c0": metric_delta(
            aggregate[CONDITION_HYBRID], aggregate[CONDITION_LEXICAL]
        ),
        "aggregate_delta_c2_minus_c1": delta_c1,
        "complementarity": analysis,
        "decision_rule": DECISION_RULE,
        "decision": decide(delta_c1, analysis),
        "no_evidence_questions": no_evidence_analysis(records),
        "excluded_questions": excluded_analysis(source, records),
        "question_results": records,
        "limitations": [
            "Um unico corpus (P1) e um unico snapshot (S1).",
            "Doze perguntas medidas: qualquer delta agregado move-se com uma pergunta.",
            "Um unico anotador, sem medida de concordancia entre anotadores.",
            "Um unico modelo de embeddings e um unico indice vetorial.",
            "source_depth = 5: a fusao so pode reordenar o que as condicoes ja viam.",
            (
                "k_rrf herdado do artigo original e nao afinado - o resultado nao e "
                "o melhor RRF possivel neste corpus."
            ),
            "Ground truth incompleto por construcao (DIRECTED_JUDGMENT_INCOMPLETE).",
            "Nada aqui demonstra generalizacao para outro corpus ou instituicao.",
            "O hibrido nao foi avaliado com politica de admissao propria.",
            "O resultado nao autoriza promocao para producao.",
        ],
        "result_digest_scope": "full_payload_without_run_fields",
        "execution_digest_scope": "full_payload",
        "reproducibility_note": (
            "A fase consome rankings persistidos e nao contacta o fornecedor: "
            "result_digest e execution_digest sao ambos estaveis entre execucoes."
        ),
    }
    return payload


def stamp_digests(payload: dict[str, Any]) -> dict[str, Any]:
    """Carimba ``result_digest`` e ``execution_digest``.

    ``result_digest`` cobre o *payload* sem os campos de execução;
    ``execution_digest`` cobre-o já carimbado, tirando apenas o instante. Ao
    contrário da D4.8.1, aqui não há similaridade a excluir: nenhuma quantidade
    deste artefacto vem do fornecedor, pelo que os dois digests têm de ser
    estáveis e uma divergência é sinal, não deriva.
    """
    run_fields = {"executed_at", "result_digest", "execution_digest"}
    projection = {k: v for k, v in payload.items() if k not in run_fields}
    result = hashlib.sha256(canonical_json(projection).encode("utf-8")).hexdigest()
    stamped = {**payload, "result_digest": result}
    execution_projection = {
        k: v for k, v in stamped.items() if k not in {"executed_at", "execution_digest"}
    }
    execution = hashlib.sha256(
        canonical_json(execution_projection).encode("utf-8")
    ).hexdigest()
    stamped["execution_digest"] = execution
    return stamped


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="evaluate_hybrid_rrf",
        description=(
            "D4.9 - funde os rankings top-5 da D4.8.1 por Reciprocal Rank Fusion "
            "e compara C0, C1 e C2 sobre P1/S1."
        ),
    )
    parser.add_argument("--comparison", type=Path, required=True)
    parser.add_argument("--ground-truth", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.output.exists() and not args.overwrite:
        print(f"error: {args.output} already exists; use --overwrite", file=sys.stderr)
        return EXIT_OUTPUT_EXISTS

    try:
        source = load_json(args.comparison)
        ground_truth = load_json(args.ground_truth)
        verify_source_integrity(source)
        verify_ground_truth(source, ground_truth)
        verify_snapshot(source, ground_truth)
        verify_comparability(source)
        payload = build_payload(source, ground_truth)
    except GuardError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_GUARD_FAILED

    payload["executed_at"] = datetime.now(UTC).isoformat()
    payload = stamp_digests(payload)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")

    aggregate = payload["aggregate"]
    delta = payload["aggregate_delta_c2_minus_c1"]
    print(f"perguntas medidas          : {aggregate[CONDITION_HYBRID]['questions_measured']}")
    print(
        f"k_rrf                      : {K_RRF} "
        f"(source_depth {SOURCE_DEPTH}, top_k {FINAL_TOP_K})"
    )
    for condition in (CONDITION_LEXICAL, CONDITION_DENSE, CONDITION_HYBRID):
        block = aggregate[condition]
        print(
            f"{condition} Recall@5 {block['recall']['5']:.4f}  "
            f"MRR {block['mrr']:.4f}  nDCG@5 {block['ndcg']['5']:.4f}"
        )
    print(f"delta C2-C1 nDCG@5         : {delta['ndcg']['5']}")
    print(f"decisao                    : {payload['decision']['decision']}")
    print(f"result_digest              : {payload['result_digest']}")
    print(f"execution_digest           : {payload['execution_digest']}")
    print(f"written                    : {args.output}")
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
