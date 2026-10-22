"""Configuração versionada da avaliação da política v1.

Os limiares são **propostas configuráveis** da v1.7 cuja justificação está
pendente; não são critérios de sucesso estabelecidos. A configuração é um dos
artefactos congelados (``config``) e o seu digest entra no manifesto.
"""

from typing import Any, Final

EVALUATION_CONFIG_VERSION: Final = "policy_v1_evaluation_config_1"

#: Correspondência entre os identificadores M1–M9 da v1.7 e as métricas.
#: M1 e M2 estão definidas expressamente no prompt. M3–M8 seguem a **ordem em
#: que o prompt enumera** as restantes métricas — encaminhamento excessivo,
#: insuficiente, destino correto (condicional e total), citações inadmissíveis,
#: qualidade da mensagem, erros de estimação — e são **provisórias** até
#: confirmação contra o documento da v1.7. M9 não é dedutível do prompt e fica
#: **sem atribuição**: não se inventa. Alterar este mapa muda a versão e o
#: digest do artefacto ``config``.
METRIC_IDS: Final[dict[str, Any]] = {
    "version": "policy_v1_metric_ids_provisional_1",
    "status": "M1–M2 do prompt; M3–M8 provisórias pela ordem do prompt; M9 por atribuir",
    "ids": {
        "M1": "answer_when_not_acceptable",
        "M2": "non_answer_outside_acceptable",
        "M3": "over_escalation",
        "M4": "under_escalation",
        "M5": "destination_correct",
        "M6": "inadmissible_citations",
        "M7": "message_quality",
        "M8": "estimation_errors",
        "M9": None,
    },
}

EVALUATION_CONFIG: Final[dict[str, Any]] = {
    "version": EVALUATION_CONFIG_VERSION,
    "runs": {"model_conditions": 3, "oracle": 1, "primary_run": 1, "tie_break": "first_run"},
    "attempts": {"estimator_max_attempts": 1, "generator_max_attempts": 1},
    "timeouts_seconds": {"estimator": 30, "generator": 30},
    "confidence_level": 0.95,
    "metric_ids": METRIC_IDS,
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
