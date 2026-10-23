"""Configuração versionada da avaliação da política v1.

Os limiares são **propostas configuráveis** da v1.7 cuja justificação está
pendente; não são critérios de sucesso estabelecidos. A configuração é um dos
artefactos congelados (``config``) e o seu digest entra no manifesto.
"""

from typing import Any, Final

EVALUATION_CONFIG_VERSION: Final = "policy_v1_evaluation_config_2"

#: Correspondência entre os identificadores M1–M9 da v1.7 e as métricas.
#:
#: - M1 e M2 estão definidas expressamente no prompt.
#: - M3 (matriz de confusão das quatro ações, com ação preferida, acordo estrito
#:   e acordo aceitável) e o identificador M6 (citações inadmissíveis) vêm da
#:   revisão de 2026-10-23 sobre a ``main`` ``8d3164b``. **Não provêm do prompt
#:   v1.7 disponível**: são opções metodológicas provisórias, aceites como tal.
#: - Entre M3 e M6 ficam dois identificadores para os dois temas que o prompt
#:   enumera a seguir: o encaminhamento excessivo e insuficiente (M4, uma
#:   métrica com duas componentes) e o destino correto (M5, condicional e
#:   total). Depois de M6, a qualidade da mensagem (M7) e os erros de estimação
#:   (M8). M4, M5, M7 e M8 são **deduções provisórias** até confirmação contra
#:   o documento da v1.7.
#: - M9 continua **sem atribuição**: não é dedutível e não se inventa.
#:
#: Nenhuma destas atribuições é conteúdo normativo demonstrado da v1.7, e o
#: mapa não serve para declarar conformidade integral. A versão 1 deste mapa
#: (M3 = encaminhamento excessivo, M4 = insuficiente) seguia só a ordem do
#: prompt e foi substituída. Alterar o mapa muda a versão e o digest do
#: artefacto ``config``.
METRIC_IDS: Final[dict[str, Any]] = {
    "version": "policy_v1_metric_ids_provisional_2",
    "status": (
        "M1–M2 do prompt; M3 e M6 da revisão de 2026-10-23; M4, M5, M7 e M8 "
        "provisórias; M9 por atribuir"
    ),
    "normative": False,
    "conformance": "não serve para declarar conformidade integral com a v1.7",
    "origins": {
        "M1": "prompt v1.7 disponível",
        "M2": "prompt v1.7 disponível",
        "M3": (
            "revisão de 2026-10-23; não provém do prompt v1.7 disponível; "
            "opção metodológica provisória"
        ),
        "M4": "dedução provisória: tema do prompt, entre M3 e M6",
        "M5": "dedução provisória: tema do prompt, entre M3 e M6",
        "M6": (
            "identificador da revisão de 2026-10-23, não do prompt v1.7 disponível; "
            "o tema (citações inadmissíveis) está no prompt"
        ),
        "M7": "dedução provisória: tema do prompt, a seguir a M6",
        "M8": "dedução provisória: tema do prompt, a seguir a M7",
        "M9": "por atribuir",
    },
    "ids": {
        "M1": "answer_when_not_acceptable",
        "M2": "non_answer_outside_acceptable",
        "M3": "action_confusion_matrix",
        "M4": "escalation_errors",
        "M5": "destination_correct",
        "M6": "inadmissible_citations",
        "M7": "message_quality",
        "M8": "estimation_errors",
        "M9": None,
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
    "version": "policy_v1_paired_comparisons_1",
    "status": "derivadas da definição das condições; proposta configurável",
    "unit": (
        "caso, na execução principal (a primeira numerada); as três execuções não "
        "multiplicam a amostra"
    ),
    "interval": "diferença p(first) − p(second), IC de Newcombe (método 10) a 95 %",
    "measures": {
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
            "measures": ["acceptable_action", "strict_action"],
        },
        {
            "first": "P-e2e",
            "second": "B1-plena",
            "isolates": (
                "regras determinísticas contra um modelo que estima as dimensões e "
                "escolhe a ação, com o mesmo packet e as mesmas definições e regras"
            ),
            "measures": ["acceptable_action", "strict_action"],
        },
        {
            "first": "P-e2e",
            "second": "B1-composição",
            "isolates": (
                "composição da ação pelas regras contra composição pelo modelo, com as "
                "mesmas estimativas D1–D5 e o mesmo D6"
            ),
            "measures": ["acceptable_action", "strict_action"],
        },
        {
            "first": "P-oráculo",
            "second": "P-e2e",
            "isolates": (
                "os erros de estimação: a mesma política com dimensões adjudicadas "
                "contra dimensões estimadas"
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
            "measures": ["message_acceptable"],
        },
    ],
}

EVALUATION_CONFIG: Final[dict[str, Any]] = {
    "version": EVALUATION_CONFIG_VERSION,
    "runs": {"model_conditions": 3, "oracle": 1, "primary_run": 1, "tie_break": "first_run"},
    "attempts": {"estimator_max_attempts": 1, "generator_max_attempts": 1},
    "timeouts_seconds": {"estimator": 30, "generator": 30},
    "confidence_level": 0.95,
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
