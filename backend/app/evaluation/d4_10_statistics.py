"""Estimador, bootstrap e regra de decisão da D4.10, pré-registados na D4.10a.

Módulo **puro**: aritmética e aleatoriedade semeada, sem entrada/saída, sem
rede, sem base de dados e sem qualquer artefacto de resultados. Como
``d4_10_protocol``, **não** é reexportado por ``app/evaluation/__init__.py``.

Porque é que isto existe antes de haver dados
---------------------------------------------

O protocolo da D4.10a fixava ``unit=scenario_id``, 10000 réplicas, IC de 95% e
uma seed — e isso não chega para determinar um resultado. Faltava dizer se o
intervalo é *percentile*, *basic* ou BCa; se o estimador dá o mesmo peso a cada
pergunta ou a cada cenário; como entra um cenário sorteado duas vezes; e que
perguntas participam. Duas implementações razoáveis dariam intervalos
diferentes, e a decisão A/B/C depende do intervalo. Deixar isso em aberto seria
guardar para depois da medição uma escolha que a muda.

Escrever o cálculo agora, com testes sobre dados sintéticos, é o que torna a
escolha verificável: a D4.10b não implementa estatística nenhuma, chama isto.

As decisões congeladas
----------------------

**Peso por cenário, não por pergunta.** O delta de cada pergunta é agregado
dentro do cenário e só depois entre cenários. Um cenário com duas paráfrases
pesa tanto como um cenário com uma: as paráfrases são a mesma família semântica
e não são observações independentes — a mesma razão pela qual a unidade de
reamostragem é o cenário.

**Intervalo *percentile*.** O mais simples de descrever e de reproduzir. Não é
o de melhor cobertura em amostras pequenas; é o que fica inequívoco por
escrito, e a alternativa — escolher BCa depois de ver os intervalos — é
exatamente o que esta fase existe para impedir.

**Quantil linear (Hyndman-Fan tipo 7).** O mesmo que ``numpy.quantile`` usa por
omissão, implementado aqui para não depender da versão de uma biblioteca.
"""

import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from app.evaluation.d4_10_protocol import ANSWERABLE

#: Valores pré-registados. A seed é a data em que o protocolo foi desenhado.
DEFAULT_REPLICATES: Final = 10000
DEFAULT_SEED: Final = 20260819
DEFAULT_CONFIDENCE: Final = 0.95

#: Método do intervalo, congelado. Ver o cabeçalho para a justificação.
CI_METHOD: Final = "PERCENTILE"
QUANTILE_METHOD: Final = "linear_hyndman_fan_type_7"
PRNG: Final = "random.Random(seed).choices"

#: Ramos da decisão científica. Não há um quarto.
A_EVIDENCE_FOR_HYBRID: Final = "A_EVIDENCE_FOR_HYBRID"
B_EVIDENCE_FOR_DENSE: Final = "B_EVIDENCE_FOR_DENSE"
C_INCONCLUSIVE: Final = "C_INCONCLUSIVE"
DECISIONS: Final = (A_EVIDENCE_FOR_HYBRID, B_EVIDENCE_FOR_DENSE, C_INCONCLUSIVE)


class StatisticsError(ValueError):
    """Entrada inválida para o estimador. Nada é calculado."""


@dataclass(frozen=True, slots=True)
class ConfidenceInterval:
    """Intervalo *percentile* e a estimativa pontual que o acompanha."""

    point_estimate: float
    lower: float
    upper: float
    method: str
    confidence: float
    replicates: int
    seed: int
    units: int


@dataclass(frozen=True, slots=True)
class DecisionInputs:
    """Tudo o que a regra A/B/C lê, e nada mais.

    Os campos são macro-médias por cenário, calculadas como
    :func:`scenario_macro_mean`. A regra não vê métricas secundárias: elas são
    reportadas e discutidas, mas não podem reclassificar o resultado.
    """

    interval: ConfidenceInterval
    recall_at_5_c1: float
    recall_at_5_c2: float
    solved_question_rate_c1: float
    solved_question_rate_c2: float


def quantile(values: Sequence[float], q: float) -> float:
    """Quantil linear (Hyndman-Fan tipo 7) de uma amostra não ordenada.

    Implementado aqui, e não importado, para que o resultado não dependa da
    versão de uma biblioteca instalada no momento da execução.
    """
    if not values:
        msg = "quantil de amostra vazia"
        raise StatisticsError(msg)
    if not 0.0 <= q <= 1.0:
        msg = f"quantil fora de [0, 1]: {q}"
        raise StatisticsError(msg)
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    position = (len(ordered) - 1) * q
    lower_index = int(position)
    fraction = position - lower_index
    if lower_index + 1 == len(ordered):
        return float(ordered[lower_index])
    low = float(ordered[lower_index])
    high = float(ordered[lower_index + 1])
    return low + fraction * (high - low)


def eligible_scenario_deltas(
    question_set: Mapping[str, Any], deltas_by_question: Mapping[str, float]
) -> dict[str, list[float]]:
    """Agrupa deltas por cenário, aceitando **apenas** perguntas ANSWERABLE.

    A elegibilidade estava declarada no protocolo e não era executável: o
    bootstrap recebia um mapa já agrupado e não tinha como saber a intenção das
    perguntas que lhe deram origem. Uma NO_EVIDENCE que entrasse por engano
    ficaria invisível — e nDCG, Recall e MRR não estão sequer definidos sem alvo
    relevante, pelo que o número resultante não significaria nada.

    Por isso recusa, em vez de ignorar: uma NO_EVIDENCE com delta é um erro de
    quem chama, não um caso a tratar em silêncio.
    """
    intents = {
        question["question_id"]: question["answerability_intent"]
        for question in question_set["questions"]
    }
    scenarios = {
        question["question_id"]: question["scenario_id"]
        for question in question_set["questions"]
    }

    unknown = sorted(set(deltas_by_question) - set(intents))
    if unknown:
        msg = f"perguntas fora do conjunto: {unknown}"
        raise StatisticsError(msg)
    ineligible = sorted(
        qid for qid in deltas_by_question if intents[qid] != ANSWERABLE
    )
    if ineligible:
        msg = (
            f"perguntas NO_EVIDENCE não entram no bootstrap de retrieval: "
            f"{ineligible}"
        )
        raise StatisticsError(msg)

    grouped: dict[str, list[float]] = {}
    for qid in sorted(deltas_by_question):
        grouped.setdefault(scenarios[qid], []).append(float(deltas_by_question[qid]))
    return grouped


def scenario_mean(values: Sequence[float]) -> float:
    """Média aritmética dos deltas das perguntas de um cenário."""
    if not values:
        msg = "cenário sem perguntas elegíveis"
        raise StatisticsError(msg)
    return sum(float(value) for value in values) / len(values)


def scenario_macro_mean(deltas_by_scenario: Mapping[str, Sequence[float]]) -> float:
    """Estimador primário: média entre cenários das médias dentro de cada cenário.

    Cada cenário pesa um, tenha ele uma pergunta ou três.
    """
    if not deltas_by_scenario:
        msg = "nenhum cenário elegível"
        raise StatisticsError(msg)
    per_scenario = [
        scenario_mean(deltas_by_scenario[scenario])
        for scenario in sorted(deltas_by_scenario)
    ]
    return sum(per_scenario) / len(per_scenario)


def bootstrap_replicates(
    deltas_by_scenario: Mapping[str, Sequence[float]],
    *,
    replicates: int = DEFAULT_REPLICATES,
    seed: int = DEFAULT_SEED,
) -> tuple[float, ...]:
    """Reamostra **cenários** com reposição e devolve a estatística de cada réplica.

    Cada ocorrência de um cenário sorteado transporta todas as suas perguntas
    elegíveis, através da média já calculada dentro do cenário; um cenário
    sorteado duas vezes contribui duas vezes com esse mesmo valor. As perguntas
    nunca são reamostradas individualmente — seria tratar paráfrases da mesma
    família como observações independentes.
    """
    if replicates < 1:
        msg = f"réplicas tem de ser positivo: {replicates}"
        raise StatisticsError(msg)
    if not deltas_by_scenario:
        msg = "nenhum cenário elegível"
        raise StatisticsError(msg)

    # Ordem lexicográfica antes de amostrar: sem uma ordem fixa, a mesma seed
    # produziria sequências diferentes conforme a ordem de iteração do mapa.
    order = sorted(deltas_by_scenario)
    per_scenario = {
        scenario: scenario_mean(deltas_by_scenario[scenario]) for scenario in order
    }
    values = [per_scenario[scenario] for scenario in order]
    size = len(order)
    rng = random.Random(seed)  # noqa: S311 - reamostragem estatística, não segurança
    return tuple(
        sum(drawn) / size for drawn in (rng.choices(values, k=size) for _ in range(replicates))
    )


def bootstrap_interval(
    deltas_by_scenario: Mapping[str, Sequence[float]],
    *,
    replicates: int = DEFAULT_REPLICATES,
    seed: int = DEFAULT_SEED,
    confidence: float = DEFAULT_CONFIDENCE,
) -> ConfidenceInterval:
    """Intervalo *percentile* do estimador macro por cenário."""
    if not 0.0 < confidence < 1.0:
        msg = f"confiança fora de (0, 1): {confidence}"
        raise StatisticsError(msg)
    drawn = bootstrap_replicates(
        deltas_by_scenario, replicates=replicates, seed=seed
    )
    tail = (1.0 - confidence) / 2.0
    return ConfidenceInterval(
        point_estimate=scenario_macro_mean(deltas_by_scenario),
        lower=quantile(drawn, tail),
        upper=quantile(drawn, 1.0 - tail),
        method=CI_METHOD,
        confidence=confidence,
        replicates=replicates,
        seed=seed,
        units=len(deltas_by_scenario),
    )


def decide(inputs: DecisionInputs) -> str:
    """A regra A/B/C, total e determinística.

    Lê apenas os limites do intervalo e duas comparações de não-inferioridade.
    Não existe limiar de magnitude: a D4.9 introduziu um ``MATERIAL_DELTA``
    contra a instrução explícita da fase e teve de o remover. Aqui a pergunta é
    sobre sinal e incerteza — multiplicar todos os deltas por qualquer fator
    positivo não muda a decisão.

    Também não existe espaço interpretativo: «degradação consistente» e
    «resultados mistos» são discussão, não classificação. Tudo o que não é A
    nem B é C.
    """
    interval = inputs.interval
    if (
        interval.lower > 0
        and inputs.recall_at_5_c2 >= inputs.recall_at_5_c1
        and inputs.solved_question_rate_c2 >= inputs.solved_question_rate_c1
    ):
        return A_EVIDENCE_FOR_HYBRID
    if interval.upper < 0:
        return B_EVIDENCE_FOR_DENSE
    return C_INCONCLUSIVE


def protocol_block() -> dict[str, Any]:
    """O bloco pré-registado que o protocolo transporta.

    Vive aqui, junto do código que o implementa, para que a descrição e o
    cálculo não possam divergir sem que um teste o note.
    """
    return {
        "unit": "scenario_id",
        "unit_rationale": (
            "Perguntas do mesmo cenario sao parafrases da mesma familia "
            "semantica e nao sao observacoes independentes. Reamostrar por "
            "pergunta duplicaria evidencia estatistica que nao existe."
        ),
        "eligible_questions": "apenas ANSWERABLE",
        "eligibility_is_enforced_by": (
            "app/evaluation/d4_10_statistics.py::eligible_scenario_deltas, que "
            "recusa qualquer pergunta NO_EVIDENCE em vez de a ignorar."
        ),
        "eligible_questions_rationale": (
            "Sem alvo relevante, nDCG, Recall e MRR nao estao definidos. As "
            "NO_EVIDENCE sao analisadas a parte, por contagem de ruido, e nao "
            "entram em nenhum bootstrap de retrieval."
        ),
        "estimator": "scenario_macro_mean",
        "estimator_definition": (
            "Para cada pergunta ANSWERABLE, delta = metrica(C2) - metrica(C1). "
            "Para cada cenario, media aritmetica dos deltas das suas perguntas. "
            "Estimador = media aritmetica dos valores por cenario. Cada cenario "
            "pesa um."
        ),
        "replicates": DEFAULT_REPLICATES,
        "seed": DEFAULT_SEED,
        "prng": PRNG,
        "sampling": (
            "Ordenar os scenario_id elegiveis lexicograficamente. Por replica, "
            "sortear N identificadores COM REPOSICAO, sendo N o numero de "
            "cenarios elegiveis; cada ocorrencia contribui com a media do seu "
            "cenario; a estatistica da replica e a media aritmetica dos N "
            "valores. As perguntas nunca sao reamostradas individualmente."
        ),
        "confidence_interval": DEFAULT_CONFIDENCE,
        "ci_method": CI_METHOD,
        "quantiles": [0.025, 0.975],
        "quantile_method": QUANTILE_METHOD,
        "implementation": "app/evaluation/d4_10_statistics.py",
        "intervals_for": [
            "delta_ndcg_at_5_c2_minus_c1",
            "delta_mrr_c2_minus_c1",
            "delta_recall_at_5_c2_minus_c1",
            "delta_solved_question_rate_c2_minus_c1",
        ],
        "solved_question_definition": (
            "Por pergunta: 1 se existir pelo menos um resultado de grau 2 no "
            "top-5, 0 caso contrario. Agregado por cenario e depois entre "
            "cenarios, como as restantes metricas."
        ),
        "descriptive_only": (
            "A macro-media convencional por pergunta pode ser reportada para "
            "comparacao com as fases anteriores, mas a inferencia primaria e a "
            "macro-media por cenario definida aqui."
        ),
        "forbidden": [
            "usar o bootstrap para escolher configuracao",
            "alterar a seed depois de observar resultados",
            "trocar o metodo do intervalo depois de observar resultados",
            "reamostrar perguntas em vez de cenarios",
        ],
    }


def decision_block() -> dict[str, Any]:
    """A regra de decisão pré-registada, na forma que o protocolo transporta."""
    return {
        "magnitude_threshold": None,
        "magnitude_threshold_note": (
            "NAO existe limiar de 'ganho material'. A D4.9 introduziu um "
            "MATERIAL_DELTA = 0.02 contra a instrucao explicita da fase e teve "
            "de o remover. A magnitude e reportada como estimativa, intervalo, "
            "casos e cenarios."
        ),
        "implementation": "app/evaluation/d4_10_statistics.py::decide",
        "inputs": [
            "IC95 do delta nDCG@5, macro por cenario",
            "Recall@5 macro por cenario, C1 e C2",
            "solved_question_rate macro por cenario, C1 e C2",
        ],
        A_EVIDENCE_FOR_HYBRID: (
            "CI95_lower(delta_ndcg_at_5) > 0 E Recall@5(C2) >= Recall@5(C1) E "
            "solved_question_rate(C2) >= solved_question_rate(C1). Significa "
            "evidencia no painel independente de que C2 melhora C1 - NAO "
            "significa producao."
        ),
        B_EVIDENCE_FOR_DENSE: "CI95_upper(delta_ndcg_at_5) < 0.",
        C_INCONCLUSIVE: (
            "Todos os restantes casos, incluindo o intervalo que inclui zero e "
            "o que toca exatamente zero. Um resultado inconclusivo e valido e "
            "NAO autoriza novo tuning sobre o mesmo conjunto."
        ),
        "totality": (
            "A regra e total: A, B ou C, sem quarta interpretacao e sem escolha "
            "humana do ramo depois de ver os resultados."
        ),
        "secondary_metrics_cannot_reclassify": (
            "MRR, Recall@1/@3, nDCG@1/@3, distribuicao de graus e regressoes "
            "por pergunta sao reportadas e discutidas, e nao alteram o ramo."
        ),
    }
