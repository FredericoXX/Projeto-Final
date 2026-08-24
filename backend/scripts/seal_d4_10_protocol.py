"""D4.10a.1 — valida e escreve o protocolo emendado antes da execução formal.

Este comando **não executa a experiência**. Não gera embeddings, não corre
retrieval, não constrói pool, não julga, não calcula métricas e não decide nada.
Lê o conjunto de perguntas, verifica os invariantes, calcula os digests e
escreve o protocolo que a futura D4.10b terá de citar.

A separação existe porque a D4.9 não a teve. Lá, a regra de decisão e o
resultado nasceram no mesmo commit e nada no histórico provava a ordem. Aqui o
A D4.10a é selada antes da execução formal da D4.10b. Observações diagnósticas
anteriores podem existir apenas quando explicitamente declaradas no
``prior_observation_disclosure``; o runner seguinte — noutro commit — terá de
recusar correr contra um protocolo diferente.
"""

import argparse
import copy
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from app.evaluation.d4_10_protocol import (
    AMENDMENT_KIND,
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
    verify_prior_observation_disclosure,
    verify_protocol_has_no_results,
    verify_question_set,
)
from app.evaluation.d4_10_statistics import decision_block as statistics_decision_block
from app.evaluation.d4_10_statistics import protocol_block as statistics_protocol_block
from app.evaluation.d4_10_statistics import (
    sensitivity_protocol_block as statistics_sensitivity_protocol_block,
)

PROTOCOL_VERSION: Final = "d4.10-protocol-v1"
QUESTION_SET_VERSION: Final = "d4.10-question-set-v1"

EXIT_OK: Final = 0
EXIT_OUTPUT_EXISTS: Final = 3
EXIT_GUARD_FAILED: Final = 4
#: Selagem final pedida com revisão humana por concluir. Código próprio para
#: que a diferença entre «o conjunto está mal» e «o conjunto está por rever»
#: seja legível por um script de CI sem ler a mensagem.
EXIT_HUMAN_REVIEW_REQUIRED: Final = 5

#: Um protocolo produzido antes da revisão humana é uma proposta; só um
#: protocolo com toda a revisão feita desbloqueia a D4.10b.
PROTOCOL_DRAFT: Final = "DRAFT"
PROTOCOL_SEALED: Final = "SEALED"

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

#: O bootstrap e a regra de decisão vivem em ``app/evaluation/d4_10_statistics``,
#: junto do código que os implementa: uma descrição que não pode divergir do
#: cálculo é melhor pré-registo do que uma descrição bem escrita ao lado dele.
BOOTSTRAP_PROTOCOL: Final[dict[str, Any]] = statistics_protocol_block()

DECISION_PROTOCOL: Final[dict[str, Any]] = statistics_decision_block()

SENSITIVITY_ANALYSIS_PROTOCOL: Final[dict[str, Any]] = (
    statistics_sensitivity_protocol_block()
)

#: Divulgação factual incorporada por valor no protocolo. Não contém juízos de
#: correção do ground truth nem datas inventadas; a precisão temporal disponível
#: é declarada explicitamente.
PRIOR_OBSERVATION_DISCLOSURE: Final[dict[str, Any]] = {
    "disclosure_status": "known_partial_diagnostic_exposure_disclosed",
    "temporal_position": (
        "after_partial_c0_diagnostic_exposure_and_before_formal_d4_10b_execution"
    ),
    "observation_time_precision": (
        "exact_dates_and_timestamps_not_recoverable_from_the_available_record"
    ),
    "formal_d4_10b_execution_occurred": False,
    "exposed_condition": "C0_LEXICAL",
    "exposed_scenarios": [
        {"scenario_id": "SC-A16", "answerability_intent": "ANSWERABLE"},
        {"scenario_id": "SC-N01", "answerability_intent": "NO_EVIDENCE"},
        {"scenario_id": "SC-N02", "answerability_intent": "NO_EVIDENCE"},
        {"scenario_id": "SC-N03", "answerability_intent": "NO_EVIDENCE"},
    ],
    "observations": [
        {
            "question_id": "DX026",
            "scenario_id": "SC-A16",
            "answerability_intent": "ANSWERABLE",
            "exposure_surface": [
                "c0_retrieval",
                "comparative_scenario_diagnostic",
            ],
            "retrieval_executed": "C0_LEXICAL",
            "observer_formed_belief_about_label": True,
        },
        {
            "question_id": "DX027",
            "scenario_id": "SC-A16",
            "answerability_intent": "ANSWERABLE",
            "exposure_surface": [
                "end_to_end",
                "c0_retrieval",
                "c0_lexical_trace",
                "manual_database_diagnostic",
            ],
            "retrieval_executed": "C0_LEXICAL",
            "ranking_observed": True,
            "trace_observed": True,
            "returned_content_read": True,
            "target_chunk_content_read": True,
            "target_chunk_id": 284,
            "observer_formed_belief_about_label": True,
        },
        {
            "question_id": "DX043",
            "scenario_id": "SC-N01",
            "answerability_intent": "NO_EVIDENCE",
            "exposure_surface": ["diagnostic_observation"],
            "observer_formed_belief_about_label": True,
        },
        {
            "question_id": "DX044",
            "scenario_id": "SC-N01",
            "answerability_intent": "NO_EVIDENCE",
            "exposure_surface": ["diagnostic_observation"],
            "observer_formed_belief_about_label": True,
        },
        {
            "question_id": "DX045",
            "scenario_id": "SC-N02",
            "answerability_intent": "NO_EVIDENCE",
            "exposure_surface": ["diagnostic_observation"],
            "observer_formed_belief_about_label": True,
        },
        {
            "question_id": "DX046",
            "scenario_id": "SC-N03",
            "answerability_intent": "NO_EVIDENCE",
            "exposure_surface": ["diagnostic_observation"],
            "observer_formed_belief_about_label": True,
        },
        {
            "question_id": "DX047",
            "scenario_id": "SC-N03",
            "answerability_intent": "NO_EVIDENCE",
            "exposure_surface": ["diagnostic_observation"],
            "observer_formed_belief_about_label": True,
        },
    ],
    "ground_truth_guard": (
        "A exposição NO_EVIDENCE não é confirmação nem refutação do ground truth."
    ),
    "amendment_does_not_authorize_changes_to": [
        "questions",
        "scenarios",
        "intent",
        "target",
        "C0",
        "C1",
        "C2",
        "metrics",
    ],
    "no_evidence_limitation_follow_up": {
        "exposed_scenarios": 3,
        "total_scenarios": 5,
        "exposed_scenarios_percent": 60.0,
        "exposed_questions": 5,
        "total_questions": 8,
        "exposed_questions_percent": 62.5,
        "future_recovery": (
            "Se for decidida, usar painel independente posterior; não acrescentar "
            "perguntas às 50 atuais."
        ),
    },
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
    """Constrói o protocolo a partir do conjunto validado. Não mede nada.

    O ``protocol_status`` sai daqui derivado do estado real da revisão, e não de
    uma opção da linha de comandos: quem sela não escolhe se o que produz é
    definitivo.

    A validação é refeita aqui, e não assumida do chamador. O CLI já a faz, mas
    a garantia não pode depender de por onde se entra: quem chame esta função
    diretamente não pode obter um protocolo ``SEALED`` a partir de um conjunto
    que ``verify_question_set`` recusaria.
    """
    verify_question_set(question_set)
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
    review = human_review_summary(question_set)
    status = PROTOCOL_SEALED if review["freeze_ready"] else PROTOCOL_DRAFT
    protocol: dict[str, Any] = {
        "schema_version": 1,
        "contract": "d4_10_pre_registered_protocol",
        "protocol_version": PROTOCOL_VERSION,
        "phase": "D4.10a.1",
        "amendment_kind": AMENDMENT_KIND,
        "amendment_note": (
            "Emenda posterior à exposição diagnóstica parcial a C0 e anterior à "
            "execução formal C1 versus C2 da D4.10b. Não restaura independência "
            "perfeita: preserva a análise primária original e introduz a análise "
            "de sensibilidade antes da execução formal."
        ),
        "protocol_status": status,
        "protocol_status_note": (
            "DRAFT: proposta auditavel, produzida antes de a revisao humana "
            "estar completa. NAO satisfaz as precondicoes da D4.10b. SEALED: "
            "toda a revisao humana concluida - perguntas e independencia dos "
            "cenarios - e so este estado desbloqueia a D4.10b."
        ),
        "scope_note": (
            "Emenda pós-exposição e pré-execução da D4.10. Não contém resultados "
            "formais D4.10b: não houve geração de embeddings congelados, rankings "
            "formais C1/C2 nem métricas formais D4.10b. As observações diagnósticas "
            "anteriores a C0 estão declaradas no prior_observation_disclosure."
        ),
        "prior_observation_disclosure": copy.deepcopy(PRIOR_OBSERVATION_DISCLOSURE),
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
        "human_review_digest": human_review_digest(question_set),
        "distribution": distribution(question_set),
        "scenario_distribution": scenario_distribution(question_set),
        "document_distribution": document_distribution(question_set),
        "human_review": review,
        "conditions": CONDITIONS,
        "metric_protocol": METRIC_PROTOCOL,
        "pooling_protocol": POOLING_PROTOCOL,
        "embedding_freeze_protocol": EMBEDDING_FREEZE_PROTOCOL,
        "bootstrap_protocol": BOOTSTRAP_PROTOCOL,
        "sensitivity_analysis_protocol": SENSITIVITY_ANALYSIS_PROTOCOL,
        "decision_protocol": DECISION_PROTOCOL,
        "forbidden_changes": FORBIDDEN_CHANGES,
        "d4_10b_preconditions": [
            "protocol_status igual a SEALED",
            "protocol_digest desta selagem",
            "question_set_digest identico",
            "scenario_digest identico",
            "human_review_digest identico",
            "human_review.freeze_ready verdadeiro",
            "nenhum cenario marcado EXCLUDE presente no conjunto",
            "identidade de C0, C1 e C2 identica a declarada aqui",
        ],
        "d4_10b_preconditions_note": (
            "Um protocolo DRAFT nao satisfaz estas precondicoes, por mais "
            "correto que seja o resto do artefacto. A selagem que autoriza a "
            "execucao e a que existir depois da revisao humana, e tem de estar "
            "num commit anterior à primeira geração de embeddings congelados e "
            "aos primeiros rankings produzidos pela execução formal da D4.10b. "
            "As observações diagnósticas anteriores declaradas no "
            "prior_observation_disclosure não violam esta guarda."
        ),
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
                "toda a revisao humana. Por pergunta: estado de revisao e bloco "
                "de validacao inteiro - anotador, metodo, estado, racional e "
                "ancoras ou termos procurados. Por cenario: a revisao de "
                "independencia semantica face as fases historicas - estado, "
                "referencias, justificacao e anotador. Existe porque nem o "
                "question_set_digest nem o scenario_digest cobrem isto; sem "
                "ele, a revisao humana ficaria fora da selagem e seria "
                "editavel sem rasto."
            ),
        },
        "digest_algorithm": DIGEST_ALGORITHM,
    }
    verify_prior_observation_disclosure(protocol)
    verify_protocol_has_no_results(protocol)
    protocol["protocol_digest"] = protocol_digest(protocol)
    protocol["sealed_at"] = datetime.now(UTC).isoformat()
    return protocol


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="seal_d4_10_protocol",
        description=(
            "D4.10a.1 - valida o conjunto de perguntas e escreve a emenda "
            "pos-exposicao e pre-execucao. Nao executa a experiencia."
        ),
    )
    parser.add_argument("--question-set", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument(
        "--draft",
        action="store_true",
        help=(
            "produz um protocolo DRAFT com a revisao humana por concluir; "
            "sem esta opcao, a selagem recusa"
        ),
    )
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

    # Um comando chamado «seal» que aceite selar o que ainda não está revisto
    # não sela nada: produz um ficheiro com ar de definitivo. Quem quiser o
    # artefacto provisório tem de o pedir pelo nome.
    review = protocol["human_review"]
    if protocol["protocol_status"] != PROTOCOL_SEALED and not args.draft:
        overlap = review["scenario_overlap_review"]
        print(
            "error: revisão humana incompleta; a selagem final foi recusada.\n"
            f"  perguntas por confirmar : {review['pending_human_review']}"
            f" de {review['total_questions']}\n"
            f"  cenários por rever      : {overlap['pending_or_inadmissible']}"
            f" de {overlap['total_scenarios']}\n"
            f"  cenários marcados EXCLUDE ainda presentes: "
            f"{overlap['marked_exclude_still_present']}\n"
            "  use --draft para produzir explicitamente um protocolo DRAFT.",
            file=sys.stderr,
        )
        return EXIT_HUMAN_REVIEW_REQUIRED

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(protocol, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")

    dist = protocol["distribution"]
    overlap = review["scenario_overlap_review"]
    print(f"protocol_status       : {protocol['protocol_status']}")
    print(f"cenarios              : {dist['scenario_count']}")
    print(f"perguntas             : {dist['question_count']}")
    print(f"  por intencao        : {dist['by_answerability_intent']}")
    print(f"question_set_digest   : {protocol['question_set_digest']}")
    print(f"scenario_digest       : {protocol['scenario_digest']}")
    print(f"human_review_digest   : {protocol['human_review_digest']}")
    print(f"protocol_digest       : {protocol['protocol_digest']}")
    print(f"perguntas confirmadas : {review['human_confirmed']}"
          f" de {review['total_questions']}")
    print(f"cenarios por rever    : {overlap['pending_or_inadmissible']}"
          f" de {overlap['total_scenarios']}")
    print(f"pronto para congelar  : {review['freeze_ready']}")
    print(f"escrito               : {args.output}")
    if protocol["protocol_status"] != PROTOCOL_SEALED:
        print("aviso                 : DRAFT nao desbloqueia a D4.10b")
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
