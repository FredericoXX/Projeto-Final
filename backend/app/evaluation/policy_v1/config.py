"""Configuração versionada da avaliação da política v1.

Os limiares são **propostas configuráveis** da v1.7 cuja justificação está
pendente; não são critérios de sucesso estabelecidos. A configuração é um dos
artefactos congelados (``config``) e o seu digest entra no manifesto.
"""

from typing import Any, Final

EVALUATION_CONFIG_VERSION: Final = "policy_v1_evaluation_config_3"

#: Correspondence checked against the supplied working document v1.7,
#: section 9.1, page 14. It does not claim scientific approval or evaluation.
METRIC_IDS: Final[dict[str, Any]] = {
    "version": "policy_v1_metric_ids_3",
    "status": "aligned with working specification v1.7, section 9.1, page 14",
    "normative": False,
    "conformance": "working specification; calibration and scientific approval are separate",
    "origins": dict.fromkeys(
        (f"M{i}" for i in range(1, 10)),
        "Politica_decisao_v1.7_e_protocolo_de_rotulagem.docx, section 9.1, page 14",
    ),
    "ids": {
        "M1": "answer_when_not_acceptable",
        "M2": "non_answer_outside_acceptable",
        "M3": "action_confusion_matrix",
        "M4": "under_escalation",
        "M5": "destination_correct",
        "M6": "inadmissible_citations",
        "M7": "message_quality",
        "M8": "estimation_errors",
        "M9": "error_attribution",
    },
}

#: Comparações emparelhadas. Cada par declara o efeito que isola — o que a
#: definição das duas condições faz variar —, e é comparado nas medidas em que
#: esse efeito se observa. Cada medida declara o desfecho por caso e o
#: denominador; a unidade estatística e o intervalo são comuns.
#:
#: A lista é uma proposta configurável derivada das condições, não um resultado.
#: Faz parte do artefacto congelado ``config``: tem de estar congelada antes da
#: avaliação, e qualquer alteração muda o seu digest.
PAIRED_COMPARISONS: Final[dict[str, Any]] = {
    "version": "policy_v1_paired_comparisons_2",
    "status": "derivadas da definição das condições; proposta configurável",
    "unit": (
        "caso, na execução principal (a primeira numerada); as três execuções não "
        "multiplicam a amostra"
    ),
    "interval": "diferença p(first) − p(second), IC de Newcombe (método 10) a 95 %",
    "measures": {
        "over_answer": {
            "outcome": "ANSWER when ANSWER is not acceptable (M1)",
            "denominator": "paired nonfailed cases where ANSWER is not acceptable",
        },
        "undue_refusal": {
            "outcome": "non-ANSWER outside the acceptable set when ANSWER is acceptable (M2)",
            "denominator": "paired nonfailed cases where ANSWER is acceptable",
        },
        "outdated_notice": {
            "outcome": "the deterministic composer included the temporal notice (H5b)",
            "denominator": "paired nonfailed F02 cases with a recorded notice flag",
        },
        "acceptable_action": {
            "outcome": "a ação pertence às ações aceitáveis adjudicadas",
            "denominator": "casos sem falha técnica nas duas condições",
        },
        "strict_action": {
            "outcome": "a ação é a ação preferida adjudicada",
            "denominator": "casos sem falha técnica nas duas condições",
        },
        "inadmissible_citation": {
            "outcome": (
                "pelo menos uma citação inadmissível no packet da própria condição; "
                "um caso sem citações conta como sem citação inadmissível"
            ),
            "denominator": "casos sem falha técnica nas duas condições",
        },
        "message_acceptable": {
            "outcome": "a mensagem foi julgada aceitável por um avaliador humano identificado",
            "denominator": (
                "casos sem falha técnica nas duas condições e com juízo humano nas duas"
            ),
        },
    },
    "pairs": [
        {
            "first": "P-e2e",
            "second": "B0",
            "isolates": (
                "a política v1.7 completa (estimadores, R01–R12, recuperação por leitura, "
                "mensagens) contra o fluxo B0 (answered→ANSWER, "
                "insufficient_evidence→ABSTAIN)"
            ),
            "measures": ["over_answer", "undue_refusal", "acceptable_action", "strict_action"],
        },
        {
            "first": "P-e2e",
            "second": "B1-plena",
            "isolates": (
                "regras determinísticas contra um modelo que estima as dimensões e "
                "escolhe a ação, com o mesmo packet e as mesmas definições e regras"
            ),
            "measures": ["over_answer", "undue_refusal", "acceptable_action", "strict_action"],
        },
        {
            "first": "P-e2e",
            "second": "B1-composição",
            "isolates": (
                "composição da ação pelas regras contra composição pelo modelo, com as "
                "mesmas estimativas D1–D5 e o mesmo D6"
            ),
            "measures": ["over_answer", "undue_refusal", "acceptable_action", "strict_action"],
        },
        {
            "first": "P-oráculo",
            "second": "P-e2e",
            "isolates": (
                "diagnostic contrast with adjudicated dimensions; it does not causally "
                "isolate retrieval, estimation and rule errors"
            ),
            "measures": ["acceptable_action", "strict_action"],
        },
        {
            "first": "B0",
            "second": "A-sem-filtro",
            "isolates": "o filtro de validade C9/C10 no B0, e nada mais",
            "measures": ["inadmissible_citation"],
        },
        {
            "first": "P-e2e",
            "second": "A-sem-diagnóstico",
            "isolates": (
                "o diagnóstico temporal e o seu efeito na mensagem, com o mesmo filtro "
                "e as mesmas passagens"
            ),
            "measures": ["outdated_notice", "message_acceptable"],
        },
    ],
}

EVALUATION_CONFIG: Final[dict[str, Any]] = {
    "version": EVALUATION_CONFIG_VERSION,
    "runs": {"model_conditions": 3, "oracle": 1, "primary_run": 1, "tie_break": "first_run"},
    "attempts": {"estimator_max_attempts": 1, "generator_max_attempts": 1},
    "timeouts_seconds": {"estimator": 30, "generator": 30},
    "confidence_level": 0.95,
    "analysis": {
        "h1_test": "exact McNemar, two-sided; Holm across the three M1 contrasts",
        "alpha": 0.05,
        "non_inferiority_margin_justified": False,
    },
    "metric_ids": METRIC_IDS,
    "paired_comparisons": PAIRED_COMPARISONS,
    "thresholds": {
        "kappa_minimum": 0.60,
        "difference_margin_percentage_points": 5,
        "divergence_fraction": 0.20,
        "status": "proposta configurável; justificação pendente",
    },
    "sets": {
        "proposed_dev_cases": 28,
        "proposed_test_cases": 136,
        "f14_separate": True,
        "status": "proposta sujeita a calibração e dimensionamento",
    },
}
