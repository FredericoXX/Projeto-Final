"""D4.10a — valida o conjunto de perguntas e sela o protocolo pré-registado.

Este comando **não executa a experiência**. Não gera embeddings, não corre
retrieval, não constrói pool, não julga, não calcula métricas e não decide nada.
Lê o conjunto de perguntas, verifica os invariantes, calcula os digests e
escreve o protocolo que a futura D4.10b terá de citar.

A separação existe porque a D4.9 não a teve. Lá, a regra de decisão e o
resultado nasceram no mesmo commit e nada no histórico provava a ordem. Aqui o
protocolo é selado antes de existir qualquer ranking, e o runner seguinte —
noutro commit — recusa correr contra um protocolo diferente.
"""

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from app.evaluation.d4_10_protocol import (
    DIGEST_ALGORITHM,
    ProtocolError,
    distribution,
    document_distribution,
    human_review_digest,
    human_review_summary,
    protocol_digest,
    question_set_digest,
    scenario_digest,
    scenario_distribution,
    verify_declared_identity,
    verify_protocol_has_no_results,
    verify_question_set,
)

PROTOCOL_VERSION: Final = "d4.10-protocol-v1"
QUESTION_SET_VERSION: Final = "d4.10-question-set-v1"

EXIT_OK: Final = 0
EXIT_OUTPUT_EXISTS: Final = 3
EXIT_GUARD_FAILED: Final = 4

#: Identidade das três condições, copiada das fases que as mediram e **não**
#: reinventada aqui. A D4.10 mede generalização sobre perguntas novas: alterar
#: uma condição ao mesmo tempo tornaria o resultado inatribuível.
CONDITIONS: Final[dict[str, Any]] = {
    "C0": {
        "condition": "C0",
        "name": "lexical",
        "retriever": "PostgresLexicalRetriever",
        "score_kind": "lexical_relevance",
        "score_version": "lexical_composite_v1",
        "comparable_across_queries": False,
        "top_k": 5,
        "frozen_from": "D4.8.1 (lexical-dense-comparison-p1-s1.json)",
    },
    "C1": {
        "condition": "C1",
        "name": "dense",
        "retriever": "PostgresDenseRetriever",
        "provider": "openai",
        "model": "text-embedding-3-small",
        "dimension": 1536,
        "normalization": "none",
        "similarity_metric": "cosine",
        "configuration_version": "openai_embeddings_v1",
        "index_digest": (
            "451d9f2fbe07a799ca694026e8238dd9aa3296c15e03d46330bb1d36d3d9370c"
        ),
        "top_k": 5,
        "frozen_from": "D4.8 / D4.8.1",
    },
    "C2": {
        "condition": "C2",
        "name": "hybrid_rrf",
        "method": "reciprocal_rank_fusion",
        "formula": "sum over conditions of 1 / (k_rrf + rank), ranks 1-based",
        "k_rrf": 60,
        "source_depth": 5,
        "final_top_k": 5,
        "sources": ["C0", "C1"],
        "absent_condition_contributes": False,
        "uses_original_scores": False,
        "arithmetic": "exact rational (fractions.Fraction)",
        "tie_break": [
            "maior rrf_score, em aritmetica exata",
            "menor best_rank entre as condicoes que o devolveram",
            "menor corpus_item_id",
            "menor chunk_index",
        ],
        "frozen_from": "D4.9 (app/evaluation/hybrid_rrf.py)",
        "tie_break_note": (
            "Congelado tal como a D4.9 o mediu. A sensibilidade observada em Q003 "
            "- um empate exato resolvido pela identidade a favor de um distrator - "
            "e uma HIPOTESE A OBSERVAR nesta fase, nao uma autorizacao para "
            "corrigir o algoritmo dentro do mesmo teste."
        ),
    },
}

METRIC_PROTOCOL: Final[dict[str, Any]] = {
    "inherited_from": "docs/evaluation/retrieval-ground-truth-p1-seed.json#metric_protocol",
    "k_values": [1, 3, 5],
    "primary_k": 5,
    "binary_relevance_threshold": 2,
    "ndcg_gain_mapping": {"0": 0, "1": 1, "2": 3},
    "unjudged_chunk_treatment": "ASSUMED_IRRELEVANT",
    "primary_metric": "ndcg@5",
    "primary_metric_rationale": (
        "A fusao altera sobretudo a ORDEM dos candidatos. O Recall com limiar "
        "binario no grau 2 e cego a reordenacoes dentro do top 5; o nDCG@5 mede "
        "presenca, posicao e grau."
    ),
    "primary_comparison": "C2 versus C1",
    "primary_comparison_rationale": (
        "C1 ja superou C0 de forma inequivoca na D4.8.1. 'C2 > C0' seria "
        "satisfeito por qualquer fusao que preservasse a ordem densa e nao "
        "informaria nada."
    ),
    "secondary_metrics": [
        "recall@1", "recall@3", "recall@5",
        "mrr",
        "ndcg@1", "ndcg@3",
        "solved_question_rate",
        "grade_distribution",
        "per_question_delta",
        "improved_equal_worsened_counts",
        "c0_only_grade2_targets_preserved_by_c2",
        "c1_only_grade2_targets_preserved_by_c2",
    ],
    "no_evidence_metrics": {
        "excluded_from": ["recall", "mrr", "ndcg"],
        "reason": "Sem alvo relevante, as metricas nao estao definidas.",
        "reported_instead": [
            "returned_count por condicao",
            "grade0_returned",
            "grade1_returned",
            "noise_per_question",
        ],
        "note": "Nenhum threshold ou admission policy e introduzido.",
    },
    "tie_observation": {
        "note": (
            "A D4.10 observa, sem alterar a regra: quantos empates de RRF "
            "ocorreram, quantos chegaram ao desempate por identidade, quantos "
            "mudaram o grau da primeira posicao e em quantos o desempate "
            "favoreceu um resultado relevante ou irrelevante."
        )
    },
}

POOLING_PROTOCOL: Final[dict[str, Any]] = {
    "pool": "top5(C0) union top5(C1)",
    "c2_note": (
        "C2 deriva dessa uniao e nao pode introduzir elementos novos; a guarda "
        "que o verifica ja existe desde a D4.9."
    ),
    "judgment_requirement": (
        "Todo o elemento do pool tem de ser julgado antes de qualquer metrica "
        "final."
    ),
    "unjudged_policy": (
        "Se unjudged_in_top_k > 0 para uma pergunta, essa pergunta NAO entra nas "
        "metricas finais ate o julgamento estar completo. Nao se assume "
        "unjudged = 0."
    ),
    "relevance_scale": {
        "0": "irrelevante",
        "1": "parcialmente util/contextual, insuficiente para responder sozinho",
        "2": "evidencia diretamente relevante/suficiente para o alvo avaliado",
    },
    "grades_not_produced_in_d4_10a": True,
}

EMBEDDING_FREEZE_PROTOCOL: Final[dict[str, Any]] = {
    "when": "D4.10b, antes de qualquer medicao",
    "rule": (
        "Os embeddings das perguntas sao gerados UMA vez e congelados. A D4.10b "
        "nao volta a consultar o fornecedor depois do congelamento."
    ),
    "per_vector_fields": [
        "question_id", "content_sha256", "provider", "model", "dimension",
        "normalization", "similarity_metric", "configuration_version",
        "vector_digest", "vector",
    ],
    "rationale": (
        "A D4.8 mediu deriva do fornecedor na ordem de 1e-4 na similaridade "
        "para o MESMO texto. Congelar remove a unica fonte conhecida de "
        "nao determinismo do lado externo."
    ),
    "generated_in_d4_10a": False,
}

BOOTSTRAP_PROTOCOL: Final[dict[str, Any]] = {
    "unit": "scenario_id",
    "unit_rationale": (
        "Perguntas do mesmo cenario sao parafrases da mesma familia semantica e "
        "nao sao observacoes independentes. Reamostrar por pergunta duplicaria "
        "evidencia estatistica que nao existe."
    ),
    "replicates": 10000,
    "confidence_interval": 0.95,
    "seed": 20260819,
    "intervals_for": [
        "delta_ndcg_at_5_c2_minus_c1",
        "delta_mrr_c2_minus_c1",
        "delta_recall_at_5_c2_minus_c1",
        "delta_solved_question_rate_c2_minus_c1",
    ],
    "forbidden": [
        "usar o bootstrap para escolher configuracao",
        "alterar a seed depois de observar resultados",
    ],
}

DECISION_PROTOCOL: Final[dict[str, Any]] = {
    "magnitude_threshold": None,
    "magnitude_threshold_note": (
        "NAO existe limiar de 'ganho material'. A D4.9 introduziu um "
        "MATERIAL_DELTA = 0.02 contra a instrucao explicita da fase e teve de o "
        "remover. A magnitude e reportada como estimativa, intervalo, casos e "
        "cenarios."
    ),
    "A_EVIDENCE_FOR_HYBRID": (
        "delta nDCG@5 C2-C1 positivo E o intervalo de confianca de 95% agrupado "
        "por cenario NAO inclui zero E Recall@5 de C2 nao inferior ao de C1 E "
        "solved_question_rate de C2 nao inferior ao de C1. Significa evidencia "
        "no painel independente de que C2 melhora C1 - NAO significa producao."
    ),
    "B_EVIDENCE_FOR_DENSE": (
        "o intervalo de delta nDCG@5 fica integralmente abaixo de zero, OU ha "
        "degradacao consistente das metricas secundarias essenciais que torne a "
        "fusao injustificavel. A causa tem de ser documentada."
    ),
    "C_INCONCLUSIVE": (
        "o intervalo inclui zero, OU os resultados sao mistos, OU o ganho nao e "
        "robusto entre cenarios, OU a amostra continua insuficiente para "
        "distinguir C1 de C2. Um resultado inconclusivo e valido e NAO autoriza "
        "novo tuning sobre o mesmo conjunto."
    ),
}

FORBIDDEN_CHANGES: Final = [
    "alterar o conjunto de perguntas depois de observar rankings",
    "remover perguntas cujo resultado seja desfavoravel",
    "mover perguntas entre cenarios",
    "alterar k_rrf, source_depth, final_top_k ou o desempate",
    "alterar a metrica primaria ou o protocolo de metricas",
    "alterar a unidade, o numero de replicas ou a seed do bootstrap",
    "introduzir admission policy, threshold, confidence ou answerability",
    "alterar C0, C1, o corpus, o chunking, o indice ou o ground truth historico",
    "criar um limiar de ganho material",
]


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        msg = f"{path}: esperado um objeto JSON"
        raise ProtocolError(msg)
    return payload


def build_protocol(
    question_set: dict[str, Any], snapshot: dict[str, Any]
) -> dict[str, Any]:
    """Constrói o protocolo a partir do conjunto validado. Não mede nada."""
    questions = question_set["questions"]
    # A identidade do corpus tem de bater certo dos dois lados. Sem isto, o
    # painel podia ter sido desenhado contra um snapshot e medido contra outro.
    for field in ("snapshot_id", "corpus_digest"):
        if question_set[field] != snapshot[field]:
            msg = (
                f"{field} divergente: o conjunto declara {question_set[field]!r} "
                f"e o snapshot {snapshot[field]!r}"
            )
            raise ProtocolError(msg)
    protocol: dict[str, Any] = {
        "schema_version": 1,
        "contract": "d4_10_pre_registered_protocol",
        "protocol_version": PROTOCOL_VERSION,
        "phase": "D4.10a",
        "scope_note": (
            "Protocolo pre-registado da D4.10. Nao contem resultados: nenhum "
            "embedding foi gerado, nenhum retrieval executado, nenhum ranking "
            "observado e nenhuma metrica calculada nesta fase."
        ),
        "research_question": (
            "Num conjunto independente de cenarios e perguntas nao utilizado nas "
            "fases D4.2-D4.9, a fusao lexical+densa por RRF preserva ou melhora a "
            "qualidade de recuperacao face ao Dense Retrieval isolado?"
        ),
        "corpus_id": question_set["corpus_id"],
        "snapshot_id": snapshot["snapshot_id"],
        "corpus_digest": snapshot["corpus_digest"],
        "reference_date": snapshot["reference_date"],
        "usable_documents": question_set["usable_documents"],
        "independence_manifest": question_set["independence_manifest"],
        "question_set_version": QUESTION_SET_VERSION,
        "question_set_digest": question_set_digest(questions),
        "scenario_digest": scenario_digest(question_set),
        "human_review_digest": human_review_digest(questions),
        "distribution": distribution(question_set),
        "scenario_distribution": scenario_distribution(question_set),
        "document_distribution": document_distribution(question_set),
        "human_review": human_review_summary(question_set),
        "conditions": CONDITIONS,
        "metric_protocol": METRIC_PROTOCOL,
        "pooling_protocol": POOLING_PROTOCOL,
        "embedding_freeze_protocol": EMBEDDING_FREEZE_PROTOCOL,
        "bootstrap_protocol": BOOTSTRAP_PROTOCOL,
        "decision_protocol": DECISION_PROTOCOL,
        "forbidden_changes": FORBIDDEN_CHANGES,
        "d4_10b_preconditions": [
            "protocol_digest desta selagem",
            "question_set_digest identico",
            "scenario_digest identico",
            "human_review_digest identico",
            "human_review.freeze_ready verdadeiro",
            "identidade de C0, C1 e C2 identica a declarada aqui",
        ],
        "digest_scope": {
            "question_set_digest": (
                "substancia das perguntas: identificador, cenario, texto, "
                "idioma, intencao e documento alvo. NAO cobre a revisao, para "
                "que confirmar uma validacao nao invalide o conjunto validado."
            ),
            "scenario_digest": (
                "metadados de cada cenario - tipo, topico, documento alvo, "
                "intencao, contagem - e as perguntas que o compoem."
            ),
            "human_review_digest": (
                "estado de revisao e bloco de validacao inteiro de cada "
                "pergunta: anotador, metodo, estado, racional e ancoras ou "
                "termos procurados. Existe porque o question_set_digest nao "
                "cobre nada disto; sem ele, a validacao humana ficaria fora da "
                "selagem e seria editavel sem rasto."
            ),
        },
        "digest_algorithm": DIGEST_ALGORITHM,
    }
    verify_protocol_has_no_results(protocol)
    protocol["protocol_digest"] = protocol_digest(protocol)
    protocol["sealed_at"] = datetime.now(UTC).isoformat()
    return protocol


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="seal_d4_10_protocol",
        description=(
            "D4.10a - valida o conjunto de perguntas e sela o protocolo "
            "pre-registado. Nao executa a experiencia."
        ),
    )
    parser.add_argument("--question-set", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.output.exists() and not args.overwrite:
        print(f"error: {args.output} já existe; use --overwrite", file=sys.stderr)
        return EXIT_OUTPUT_EXISTS

    try:
        question_set = load_json(args.question_set)
        snapshot = load_json(args.snapshot)
        verify_question_set(question_set)
        # O conjunto tem de trazer a sua identidade carimbada e correta. Selar
        # um conjunto por carimbar produziria um protocolo cujos digests só
        # existiriam no protocolo, sem nada do lado do conjunto a confirmá-los.
        verify_declared_identity(question_set)
        protocol = build_protocol(question_set, snapshot)
    except (ProtocolError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_GUARD_FAILED

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(protocol, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")

    review = protocol["human_review"]
    dist = protocol["distribution"]
    print(f"cenarios              : {dist['scenario_count']}")
    print(f"perguntas             : {dist['question_count']}")
    print(f"  por intencao        : {dist['by_answerability_intent']}")
    print(f"question_set_digest   : {protocol['question_set_digest']}")
    print(f"scenario_digest       : {protocol['scenario_digest']}")
    print(f"human_review_digest   : {protocol['human_review_digest']}")
    print(f"protocol_digest       : {protocol['protocol_digest']}")
    print(f"revisao humana pendente: {review['pending_human_review']}")
    print(f"pronto para congelar  : {review['freeze_ready']}")
    print(f"escrito               : {args.output}")
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
