"""Admissão e abstenção da condição densa: contratos, regras e métricas (D4.8.2).

Módulo **puro**: recebe estruturas já lidas e devolve estruturas. Não fala com a
base de dados, não lê ficheiros, não contacta fornecedor nenhum e — como
``dense_baseline``, ``lexical_dense_comparison``, ``repooling`` e
``ground_truth_identity`` — **não** é reexportado por
``app/evaluation/__init__.py``.

A pergunta que esta fase existe para responder
----------------------------------------------

A D4.8.1 estabeleceu que C1 (denso) recupera muito melhor do que C0 (lexical) e
que **não tem etapa capaz de recusar**: devolveu 70 de 70 resultados possíveis,
43 deles de grau 0, e cinco resultados na única pergunta sem evidência no
corpus — todos julgados irrelevantes.

Esta fase **não** procura o melhor limiar. Procura saber se uma regra de
admissão **fixada antes de ver os dados** e escolhida **apenas em DEV**
generaliza para cenários independentes. O resultado pode ser negativo, e um
resultado negativo é um resultado.

Porque é que a decisão é sobre a pergunta e não sobre o resultado
-----------------------------------------------------------------

As regras aqui decidem **admitir ou abster** a pergunta inteira, não filtrar
resultado a resultado. É a decisão que o princípio constitucional exige — que
*ausência de resultados seja uma resposta legítima* — e é a única que C1 não
sabe tomar. Filtrar resultados individualmente é outra experiência, com outras
métricas, e não é esta.

O que os sinais são, e o que não são
------------------------------------

``top1`` e ``top2`` são similaridades do cosseno entre a pergunta e o segmento.
**Não são confiança.** ``ScoreSemantics.comparable_across_queries`` é ``False``
para a condição densa, e essa declaração vale aqui inteira: a similaridade
depende de onde a *pergunta* cai no espaço de embeddings, e nenhuma calibração
foi feita. Uma regra construída sobre eles é uma heurística sobre uma quantidade
não calibrada — é exatamente por isso que tem de ser validada fora do conjunto
onde foi escolhida.
"""

import hashlib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from app.evaluation.results import canonical_json

# O limiar de relevância, os valores de k e as três métricas vêm do protocolo de
# P1 e são importados dali, nunca redeclarados: uma segunda definição do mesmo
# limiar é a forma de as duas divergirem sem que nada falhe.
from app.evaluation.retrieval_metrics import (
    BINARY_RELEVANCE_THRESHOLD,
    K_VALUES,
    mean,
    ndcg_at_k,
    recall_at_k,
    reciprocal_rank,
)

# ---------------------------------------------------------------------------
# Vocabulário
# ---------------------------------------------------------------------------

#: A pergunta tem resposta no corpus, verificada por leitura.
ANSWERABLE: Final = "ANSWERABLE"

#: A pergunta **não** tem resposta no corpus, verificado por inspeção dirigida.
#: «Nenhum retriever encontrou» não é prova de ausência e não é aceite como
#: método de validação — ver ``VALIDATION_METHOD``.
NO_EVIDENCE: Final = "NO_EVIDENCE"

LABELS: Final = (ANSWERABLE, NO_EVIDENCE)

#: Método de validação da ausência. O nome é longo de propósito: descreve o que
#: foi feito, e o que foi feito não é «o retriever não devolveu nada».
VALIDATION_METHOD: Final = "normalised_full_corpus_term_search_and_reading"

#: Decisões possíveis de uma regra de admissão.
ADMIT: Final = "ADMIT"
ABSTAIN: Final = "ABSTAIN"

#: Divisões do conjunto.
DEV: Final = "DEV"
HELD_OUT: Final = "HELD_OUT"
SPLITS: Final = (DEV, HELD_OUT)

# ---------------------------------------------------------------------------
# Regras candidatas — pré-registadas
# ---------------------------------------------------------------------------

#: Controlo: a condição densa tal como a D4.8.1 a mediu. **Admite sempre.** Não
#: é uma regra que se possa escolher; existe para que a comparação tenha um
#: ponto zero e para que «a política não piorou nada» seja verificável.
RULE_R0: Final = "R0"

#: Admite se ``top1 >= t``. O sinal mais simples possível.
RULE_R1: Final = "R1"

#: Admite se ``top1 >= t`` **e** ``top1 - top2 >= m``. A hipótese é que uma
#: pergunta sem resposta produz um topo indistinto — muitos vizinhos igualmente
#: mornos — enquanto uma pergunta com resposta destaca um segmento.
RULE_R2: Final = "R2"

CANDIDATE_RULES: Final = (RULE_R0, RULE_R1, RULE_R2)

#: Ordem de simplicidade, usada pelo desempate. R0 é o mais simples porque não
#: tem parâmetros; R2 é o menos simples porque tem dois.
RULE_COMPLEXITY: Final[Mapping[str, int]] = {RULE_R0: 0, RULE_R1: 1, RULE_R2: 2}


@dataclass(frozen=True)
class AdmissionSignals:
    """Os sinais que uma regra pode ver, e mais nenhum.

    ``top2`` é ``None`` quando a recuperação devolveu menos de dois resultados.
    Não se substitui por zero: zero é uma similaridade possível e confundi-los
    faria a margem parecer máxima justamente onde há menos informação.
    """

    top1: float | None
    top2: float | None
    returned: int

    @property
    def margin(self) -> float | None:
        if self.top1 is None or self.top2 is None:
            return None
        return self.top1 - self.top2


@dataclass(frozen=True)
class AdmissionPolicy:
    """Uma regra com os seus parâmetros. É isto que se congela."""

    rule: str
    min_top1: float | None = None
    min_margin: float | None = None

    def __post_init__(self) -> None:
        if self.rule not in CANDIDATE_RULES:
            msg = f"unknown rule {self.rule!r}"
            raise ValueError(msg)
        if self.rule == RULE_R0 and (
            self.min_top1 is not None or self.min_margin is not None
        ):
            msg = "R0 is the no-admission control and takes no parameters"
            raise ValueError(msg)
        if self.rule == RULE_R1 and (
            self.min_top1 is None or self.min_margin is not None
        ):
            msg = "R1 takes min_top1 and nothing else"
            raise ValueError(msg)
        if self.rule == RULE_R2 and (self.min_top1 is None or self.min_margin is None):
            msg = "R2 takes min_top1 and min_margin"
            raise ValueError(msg)

    @property
    def complexity(self) -> int:
        return RULE_COMPLEXITY[self.rule]

    def as_dict(self) -> dict[str, Any]:
        return {
            "rule": self.rule,
            "min_top1": self.min_top1,
            "min_margin": self.min_margin,
        }


def decide(policy: AdmissionPolicy, signals: AdmissionSignals) -> str:
    """Admitir ou abster, dada uma política e os sinais de uma pergunta.

    Uma recuperação vazia é abstenção sob **qualquer** regra, incluindo R0: não
    há nada para admitir. Não é uma decisão da política — é a ausência de
    resultado a falar por si, e conta como tal nas métricas.

    Em R2, uma margem indefinida (menos de dois resultados) **não** satisfaz o
    critério. A alternativa — tratá-la como margem infinita — admitiria com
    base em informação que não existe.
    """
    if signals.returned == 0 or signals.top1 is None:
        return ABSTAIN
    if policy.rule == RULE_R0:
        return ADMIT
    if policy.min_top1 is not None and signals.top1 < policy.min_top1:
        return ABSTAIN
    if policy.rule == RULE_R2:
        margin = signals.margin
        if margin is None or policy.min_margin is None or margin < policy.min_margin:
            return ABSTAIN
    return ADMIT


# ---------------------------------------------------------------------------
# Métricas de admissão e abstenção
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class QuestionOutcome:
    """O que aconteceu a uma pergunta sob uma política.

    ``grades`` são os graus do top ``k`` devolvido, por ordem de posição, e
    ficam vazios quando a política se absteve — a abstenção não devolve nada,
    e contar os graus que teriam sido devolvidos misturaria duas coisas.
    """

    question_id: str
    scenario_id: str
    label: str
    decision: str
    signals: AdmissionSignals
    grades: tuple[int, ...]
    judged_grades: tuple[int, ...]

    @property
    def admitted(self) -> bool:
        return self.decision == ADMIT

    @property
    def correct_abstention(self) -> bool:
        return self.label == NO_EVIDENCE and not self.admitted

    @property
    def false_abstention(self) -> bool:
        """Abstenção numa pergunta que **tem** resposta no corpus.

        É o erro que a fase se propõe limitar por orçamento: uma abstenção falsa
        recusa evidência que existia, e é indistinguível, para quem pergunta, de
        o corpus não a ter.
        """
        return self.label == ANSWERABLE and not self.admitted

    @property
    def exposed_to_noise(self) -> bool:
        """Admitida numa pergunta sem evidência: o caso que a política combate."""
        return self.label == NO_EVIDENCE and self.admitted

    @property
    def preserved_relevant(self) -> bool:
        """Admitida **e** com pelo menos um grau 2 no que foi devolvido."""
        return self.admitted and any(
            grade >= BINARY_RELEVANCE_THRESHOLD for grade in self.grades
        )


def _share(numerator: int, denominator: int) -> float | None:
    """Proporção, ou ``None`` quando o denominador é zero.

    Devolver ``None`` e não ``0.0`` é deliberado: uma taxa sobre zero casos não
    é zero, é indefinida, e escrever zero no artefacto convidaria a lê-la como
    «nunca aconteceu».
    """
    if denominator == 0:
        return None
    return round(numerator / denominator, 6)


def admission_metrics(outcomes: Sequence[QuestionOutcome]) -> dict[str, Any]:
    """Risco, cobertura e as duas taxas de abstenção.

    ``risk`` é definido sobre as perguntas **admitidas**: a fração delas que não
    tinha evidência no corpus. É o risco que a admissão assume — devolver
    resultados onde não há resposta. Não é «fração de resultados irrelevantes»,
    que é outra quantidade e está em :func:`retrieval_quality`.
    """
    answerable = [o for o in outcomes if o.label == ANSWERABLE]
    no_evidence = [o for o in outcomes if o.label == NO_EVIDENCE]
    admitted = [o for o in outcomes if o.admitted]

    return {
        "total_questions": len(outcomes),
        "answerable_questions": len(answerable),
        "no_evidence_questions": len(no_evidence),
        "admitted": len(admitted),
        "abstained": len(outcomes) - len(admitted),
        "correct_abstentions": sum(1 for o in outcomes if o.correct_abstention),
        "incorrect_abstentions": sum(1 for o in outcomes if o.false_abstention),
        "correct_abstention_rate": _share(
            sum(1 for o in no_evidence if o.correct_abstention), len(no_evidence)
        ),
        "false_abstention_rate": _share(
            sum(1 for o in answerable if o.false_abstention), len(answerable)
        ),
        "coverage": _share(len(admitted), len(outcomes)),
        "coverage_answerable": _share(
            sum(1 for o in answerable if o.admitted), len(answerable)
        ),
        "risk": _share(sum(1 for o in admitted if o.label == NO_EVIDENCE), len(admitted)),
        "answerable_with_relevant_preserved": _share(
            sum(1 for o in answerable if o.preserved_relevant), len(answerable)
        ),
    }


def retrieval_quality(outcomes: Sequence[QuestionOutcome]) -> dict[str, Any]:
    """Qualidade do que foi devolvido, sobre as perguntas **admitidas**.

    A separação face a :func:`admission_metrics` é o ponto: «a pergunta correu
    bem» e «os resultados devolvidos são bons» são afirmações diferentes, e uma
    política que se abstenha muito melhora a segunda destruindo a primeira.
    Medi-las juntas esconderia exatamente essa troca.

    Recall, MRR e nDCG são calculados **apenas sobre as perguntas ANSWERABLE
    admitidas**: numa pergunta sem evidência não há alvo, e as três métricas
    são indefinidas — é a mesma regra do ``metric_protocol`` de P1.
    """
    admitted_answerable = [
        o for o in outcomes if o.admitted and o.label == ANSWERABLE
    ]
    admitted = [o for o in outcomes if o.admitted]

    grades = [grade for o in admitted for grade in o.grades]
    histogram = {"0": 0, "1": 0, "2": 0}
    for grade in grades:
        histogram[str(grade)] += 1

    per_question_recall = {
        str(k): [
            recall_at_k(
                list(o.grades),
                sum(
                    1
                    for g in o.judged_grades
                    if g >= BINARY_RELEVANCE_THRESHOLD
                ),
                k,
            )
            for o in admitted_answerable
        ]
        for k in K_VALUES
    }

    return {
        "measured_questions": len(admitted_answerable),
        "recall": {
            str(k): round(mean(per_question_recall[str(k)]), 6) if admitted_answerable else None
            for k in K_VALUES
        },
        "mrr": (
            round(mean([reciprocal_rank(list(o.grades)) for o in admitted_answerable]), 6)
            if admitted_answerable
            else None
        ),
        "ndcg": {
            str(k): (
                round(
                    mean(
                        [
                            ndcg_at_k(list(o.grades), list(o.judged_grades), k)
                            for o in admitted_answerable
                        ]
                    ),
                    6,
                )
                if admitted_answerable
                else None
            )
            for k in K_VALUES
        },
        "returned_total": len(grades),
        "grade_histogram": histogram,
        "grade0_share": _share(histogram["0"], len(grades)),
        "grade1_share": _share(histogram["1"], len(grades)),
        "grade2_share": _share(histogram["2"], len(grades)),
        "irrelevant_returned_total": histogram["0"],
        "mean_irrelevant_per_admitted_question": (
            round(histogram["0"] / len(admitted), 6) if admitted else None
        ),
    }


def evaluate_policy(
    policy: AdmissionPolicy, outcomes_input: Sequence[Mapping[str, Any]]
) -> tuple[tuple[QuestionOutcome, ...], dict[str, Any]]:
    """Aplica a política e devolve o resultado por pergunta e os agregados.

    ``outcomes_input`` traz, por pergunta, os sinais e os graus **já
    resolvidos**: a política não vê texto, não vê o corpus e não sabe que
    documento devolveu o quê. É deliberado — uma regra que pudesse olhar para o
    conteúdo deixaria de ser a regra simples que a fase se propôs testar.
    """
    outcomes: list[QuestionOutcome] = []
    for record in outcomes_input:
        signals = AdmissionSignals(
            top1=record["top1"],
            top2=record["top2"],
            returned=record["returned"],
        )
        decision = decide(policy, signals)
        outcomes.append(
            QuestionOutcome(
                question_id=record["question_id"],
                scenario_id=record["scenario_id"],
                label=record["label"],
                decision=decision,
                signals=signals,
                grades=tuple(record["grades"]) if decision == ADMIT else (),
                judged_grades=tuple(record["judged_grades"]),
            )
        )
    frozen = tuple(outcomes)
    return frozen, {
        "admission": admission_metrics(frozen),
        "retrieval": retrieval_quality(frozen),
    }


# ---------------------------------------------------------------------------
# Split por cenário
# ---------------------------------------------------------------------------


def verify_split_by_scenario(
    questions: Sequence[Mapping[str, Any]], assignments: Mapping[str, str]
) -> tuple[str, ...]:
    """Nenhuma família semântica pode atravessar a fronteira DEV/HELD-OUT.

    É a guarda que impede a forma de *leakage* que mais facilmente passa
    despercebida: uma paráfrase em DEV e a outra em HELD-OUT tornaria o
    conjunto final parcialmente conhecido pela calibração, e o resultado
    pareceria generalização sem o ser.
    """
    problems: list[str] = []
    seen: dict[str, str] = {}
    for question in questions:
        scenario = str(question["scenario_id"])
        split = assignments.get(scenario)
        if split is None:
            problems.append(f"{question['question_id']}: scenario {scenario} has no split")
            continue
        if split not in SPLITS:
            problems.append(f"scenario {scenario}: unknown split {split!r}")
        previous = seen.setdefault(scenario, split)
        if previous != split:
            problems.append(
                f"scenario {scenario} is assigned to both {previous} and {split}"
            )
    for scenario, split in assignments.items():
        if split not in SPLITS:
            problems.append(f"scenario {scenario}: unknown split {split!r}")
    return tuple(problems)


def alternating_split_assignments(
    scenarios: Sequence[Mapping[str, Any]],
) -> dict[str, str]:
    """Reproduz o algoritmo de split declarado pelo dataset.

    Dentro de cada estrato ``(label, difficulty)``, os cenarios sao ordenados
    pelo identificador e distribuidos alternadamente, com DEV primeiro. Manter
    esta funcao pura permite provar que as atribuicoes persistidas foram
    produzidas pelo algoritmo declarado, em vez de apenas verificar que cada
    cenario aparece num dos lados.
    """
    strata: dict[tuple[str, str], list[str]] = {}
    for scenario in scenarios:
        key = (str(scenario["label"]), str(scenario["difficulty"]))
        strata.setdefault(key, []).append(str(scenario["scenario_id"]))

    assignments: dict[str, str] = {}
    for key in sorted(strata):
        for index, scenario_id in enumerate(sorted(strata[key])):
            assignments[scenario_id] = DEV if index % 2 == 0 else HELD_OUT
    return dict(sorted(assignments.items()))


def questions_of_split(
    questions: Sequence[Mapping[str, Any]],
    assignments: Mapping[str, str],
    split: str,
) -> list[Mapping[str, Any]]:
    """As perguntas de um split, na ordem canónica do ``question_id``."""
    return sorted(
        (q for q in questions if assignments.get(str(q["scenario_id"])) == split),
        key=lambda q: str(q["question_id"]),
    )


# ---------------------------------------------------------------------------
# Digests
# ---------------------------------------------------------------------------


def _digest(payload: object) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def question_dataset_digest(questions: Sequence[Mapping[str, Any]]) -> str:
    """Identidade do conjunto de perguntas: o que a medição lê, e nada mais.

    Mesma disciplina de ``GROUND_TRUTH_DIGEST_SCOPE``: entram o identificador,
    o texto, o cenário, o rótulo e os julgamentos; ficam de fora as notas de
    validação e a dificuldade, que são anotação de desenho e não entram em
    cálculo nenhum.
    """
    return _digest(
        sorted(
            (
                {
                    "question_id": q["question_id"],
                    "question": q["question"],
                    "scenario_id": q["scenario_id"],
                    "label": q["label"],
                    "judgments": sorted(
                        (
                            {
                                "corpus_item_id": j["corpus_item_id"],
                                "chunk_index": j["chunk_index"],
                                "relevance": j["relevance"],
                            }
                            for j in q["judgments"]
                        ),
                        key=lambda j: (j["corpus_item_id"], j["chunk_index"]),
                    ),
                }
                for q in questions
            ),
            key=lambda q: str(q["question_id"]),
        )
    )


def scenario_digest(scenarios: Sequence[Mapping[str, Any]]) -> str:
    return _digest(
        sorted(
            (
                {
                    "scenario_id": s["scenario_id"],
                    "label": s["label"],
                    "difficulty": s["difficulty"],
                    "topic": s["topic"],
                }
                for s in scenarios
            ),
            key=lambda s: str(s["scenario_id"]),
        )
    )


def split_digest(assignments: Mapping[str, str], split_version: str) -> str:
    return _digest(
        {"split_version": split_version, "assignments": dict(sorted(assignments.items()))}
    )


def frozen_vectors_digest(vectors: Sequence[Mapping[str, Any]]) -> str:
    """Identidade do conjunto de vetores congelados.

    Cobre a identidade completa do modelo, o SHA do texto embebido e o digest
    do vetor — as três coisas que teriam de coincidir para que duas execuções
    fossem a mesma experiência. Não cobre o vetor em bruto: o seu digest já o
    representa e repeti-lo tornaria o cálculo caro sem acrescentar garantia.
    """
    return _digest(
        sorted(
            (
                {
                    "question_id": v["question_id"],
                    "content_sha256": v["content_sha256"],
                    "provider": v["provider"],
                    "model": v["model"],
                    "dimension": v["dimension"],
                    "normalization": v["normalization"],
                    "similarity_metric": v["similarity_metric"],
                    "configuration_version": v["configuration_version"],
                    "vector_digest": v["vector_digest"],
                }
                for v in vectors
            ),
            key=lambda v: str(v["question_id"]),
        )
    )


def parameter_space_digest(space: Mapping[str, Any]) -> str:
    return _digest(space)


def selection_policy_digest(selection: Mapping[str, Any]) -> str:
    return _digest(selection)


def candidate_rules_digest(rules: Iterable[str]) -> str:
    return _digest(sorted(rules))


#: O digest do protocolo cobre tudo o que foi pré-registado e mais nada. Ficam
#: de fora o instante em que foi carimbado e o próprio digest: o primeiro muda
#: sem que o compromisso mude, e o segundo não se pode conter a si mesmo.
PROTOCOL_DIGEST_SCOPE: Final = "pre_registered_fields"

_PROTOCOL_VOLATILE_KEYS: Final = frozenset({"registered_at", "protocol_digest"})


def protocol_projection(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in payload.items() if k not in _PROTOCOL_VOLATILE_KEYS}


def protocol_digest(payload: Mapping[str, Any]) -> str:
    """Identidade do compromisso pré-registado.

    Quem consome o protocolo recalcula-o antes de o usar. É o que impede a
    alteração silenciosa do critério de seleção entre a pré-registação e a
    calibração — o caso em que tudo continua a correr e a experiência deixa de
    ser a que foi anunciada.
    """
    return _digest(protocol_projection(payload))


# ---------------------------------------------------------------------------
# Digests dos artefactos de execução
# ---------------------------------------------------------------------------

#: Âmbito do ``result_digest``: as decisões e as métricas. **Não** as
#: similaridades em bruto.
RESULT_DIGEST_SCOPE: Final = "decision_relevant_fields"

#: Âmbito do ``execution_digest``: o *payload* como foi escrito, tirando apenas
#: ``executed_at`` e o próprio campo.
EXECUTION_DIGEST_SCOPE: Final = "full_payload"

_RUN_KEYS: Final = frozenset({"executed_at", "result_digest", "execution_digest"})
_EXECUTION_DIGEST_EXCLUDED: Final = frozenset({"executed_at", "execution_digest"})

#: Campos de ``question_signals`` que transportam similaridade em bruto.
_SIGNAL_SCORE_KEYS: Final = frozenset({"top1", "top2", "margin"})


def result_projection(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Projeção de que se deriva o ``result_digest``: a decisão, sem a deriva.

    Herda a correção da D4.8.1: o digest canónico descreve **o resultado**, não
    a execução. As similaridades saem da projeção porque são o único campo que
    pode variar sem que nada de substantivo mude — e ficam inteiras no
    artefacto, cobertas pelo ``execution_digest``.

    A consequência é a que se quer: uma deriva que **não** vira nenhuma decisão
    deixa o ``result_digest`` intacto; uma que vira alguma altera-o, porque as
    decisões por pergunta estão dentro da projeção. O portão de reprodutibilidade
    passa assim a falhar exatamente quando deve.
    """
    projection = {key: value for key, value in payload.items() if key not in _RUN_KEYS}
    signals = payload.get("question_signals")
    if signals is not None:
        projection["question_signals"] = [
            {key: value for key, value in record.items() if key not in _SIGNAL_SCORE_KEYS}
            for record in signals
        ]
    return projection


def execution_projection(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Projeção de que se deriva o ``execution_digest``: tudo menos o instante."""
    return {
        key: value
        for key, value in payload.items()
        if key not in _EXECUTION_DIGEST_EXCLUDED
    }


def artefact_digests(payload: Mapping[str, Any]) -> tuple[str, str]:
    """``(result_digest, execution_digest)`` de um artefacto desta fase.

    A ordem não é arbitrária: o ``execution_digest`` cobre o *payload* **como
    fica escrito**, e o ``result_digest`` é um dos campos escritos, pelo que é
    carimbado antes. Sem esse passo a função não seria idempotente — no runner
    correria sobre um *payload* sem ``result_digest`` e na verificação sobre um
    que já o tem, e um artefacto válido pareceria adulterado.
    """
    result = hashlib.sha256(
        canonical_json(result_projection(payload)).encode("utf-8")
    ).hexdigest()
    stamped = {**payload, "result_digest": result}
    execution = hashlib.sha256(
        canonical_json(execution_projection(stamped)).encode("utf-8")
    ).hexdigest()
    return result, execution


# ---------------------------------------------------------------------------
# Seleção pré-registada
# ---------------------------------------------------------------------------


def candidate_policies(space: Mapping[str, Any]) -> list[AdmissionPolicy]:
    """As políticas candidatas, derivadas do espaço pré-registado.

    Derivadas e não enumeradas à mão: uma lista escrita à parte podia divergir
    do espaço declarado no protocolo, e a experiência passaria a avaliar um
    conjunto diferente do que anunciou.
    """
    policies = [AdmissionPolicy(rule=RULE_R0)]
    policies += [
        AdmissionPolicy(rule=RULE_R1, min_top1=float(top1))
        for top1 in space["min_top1"]
    ]
    policies += [
        AdmissionPolicy(rule=RULE_R2, min_top1=float(top1), min_margin=float(margin))
        for top1 in space["min_top1"]
        for margin in space["min_margin"]
    ]
    return policies


def selection_sort_key(entry: Mapping[str, Any]) -> tuple[Any, ...]:
    """Chave de ordenação do critério pré-registado, do melhor para o pior.

    Implementa, por esta ordem: maior ``correct_abstention_rate``, menor
    ``false_abstention_rate``, regra mais simples, menor ``min_top1``, menor
    ``min_margin``. Ausência de parâmetro conta como o menor valor possível —
    R0 e R1 não têm margem, e tratá-la como infinita poria a regra mais simples
    no fim justamente no desempate que existe para a favorecer.
    """
    policy = entry["policy"]
    admission = entry["admission"]
    correct = admission["correct_abstention_rate"] or 0.0
    false = admission["false_abstention_rate"] or 0.0
    return (
        -correct,
        false,
        RULE_COMPLEXITY[str(policy["rule"])],
        policy["min_top1"] if policy["min_top1"] is not None else float("-inf"),
        policy["min_margin"] if policy["min_margin"] is not None else float("-inf"),
    )


def select_policy(
    evaluations: Sequence[Mapping[str, Any]], max_false_abstention_rate: float
) -> dict[str, Any]:
    """Aplica o critério pré-registado e devolve o rasto completo da escolha.

    Devolve o rasto e não só o vencedor: sem as candidatas elegíveis, a sua
    ordem e o motivo de exclusão das restantes, «foi esta a escolhida» é uma
    afirmação que ninguém pode conferir.
    """
    eligible = [
        entry
        for entry in evaluations
        if (entry["admission"]["false_abstention_rate"] or 0.0)
        <= max_false_abstention_rate
    ]
    ranked = sorted(eligible, key=selection_sort_key)
    selected = ranked[0] if ranked else None
    return {
        "candidates_evaluated": len(evaluations),
        "eligible": len(eligible),
        "excluded_by_budget": len(evaluations) - len(eligible),
        "max_false_abstention_rate": max_false_abstention_rate,
        "ranking": [
            {
                "policy": entry["policy"],
                "correct_abstention_rate": entry["admission"]["correct_abstention_rate"],
                "false_abstention_rate": entry["admission"]["false_abstention_rate"],
            }
            for entry in ranked
        ],
        "selected_policy": selected["policy"] if selected else None,
    }


def heldout_manifest_digest(manifest: Mapping[str, Any]) -> str:
    """Digest do compromisso público sobre o HELD-OUT.

    O manifesto identifica as perguntas do conjunto final **sem** as revelar:
    identificadores, cenários e o digest dos rótulos. Publicá-lo antes da
    calibração é o que torna verificável, depois, que o conjunto não mudou.
    """
    return _digest(manifest)


def heldout_labels_digest(questions: Sequence[Mapping[str, Any]]) -> str:
    """Digest dos rótulos e julgamentos que ficam selados.

    Fica no manifesto **antes** da calibração e é reconferido em D4.8.2c. É o
    que torna verificável que o conjunto final não foi tocado no intervalo: o
    digest não revela um único rótulo, mas qualquer alteração muda-o.
    """
    return _digest(
        sorted(
            (
                {
                    "question_id": q["question_id"],
                    "label": q["label"],
                    "judgments": sorted(
                        (
                            {
                                "corpus_item_id": j["corpus_item_id"],
                                "chunk_index": j["chunk_index"],
                                "relevance": j["relevance"],
                            }
                            for j in q["judgments"]
                        ),
                        key=lambda j: (j["corpus_item_id"], j["chunk_index"]),
                    ),
                }
                for q in questions
            ),
            key=lambda q: str(q["question_id"]),
        )
    )


# ---------------------------------------------------------------------------
# Selagem: o que a calibração pode ver
# ---------------------------------------------------------------------------

#: Contrato do ficheiro que a calibração lê. A calibração aceita **este** e
#: recusa qualquer outro — é por aqui que a barreira deixa de ser disciplina e
#: passa a ser comportamento.
DEV_PROJECTION_CONTRACT: Final = "dense_admission_dev_projection"

#: Campos que a projeção DEV nunca leva. ``split_rule`` traz as atribuições de
#: **todos** os cenários e ``scenarios`` traz os rótulos de todos: qualquer um
#: deles diria à calibração o que há do outro lado.
_PROJECTION_FORBIDDEN_KEYS: Final = frozenset({"split_rule", "scenarios"})


class LeakageError(RuntimeError):
    """A calibração foi apontada a dados que não pode ver."""


def dev_projection_questions(
    questions: Sequence[Mapping[str, Any]], assignments: Mapping[str, str]
) -> list[Mapping[str, Any]]:
    """As perguntas de DEV, tal como vão para o ficheiro da calibração.

    Não é uma vista filtrada em memória: é o conteúdo de um ficheiro separado.
    A diferença importa — uma vista filtrada deixa os rótulos do HELD-OUT ao
    alcance de um descuido de uma linha, e a fase promete que não estão.
    """
    return questions_of_split(questions, assignments, DEV)


def heldout_manifest(
    questions: Sequence[Mapping[str, Any]],
    assignments: Mapping[str, str],
    manifest_version: str,
) -> dict[str, Any]:
    """O compromisso público sobre o conjunto final, sem revelar o conjunto.

    Leva identificadores e cenários — que dizem **quantas** e **quais**
    perguntas ficam seladas — e o digest dos rótulos, que não diz nenhum. Depois
    da calibração, comparar este manifesto com o conjunto realmente avaliado é o
    que distingue «não foi tocado» de «acredita em mim».
    """
    held = questions_of_split(questions, assignments, HELD_OUT)
    return {
        "manifest_version": manifest_version,
        "question_count": len(held),
        "question_ids": [str(q["question_id"]) for q in held],
        "scenario_ids": sorted({str(q["scenario_id"]) for q in held}),
        "labels_digest": heldout_labels_digest(held),
    }


def verify_dev_projection(
    payload: Mapping[str, Any], manifest: Mapping[str, Any]
) -> tuple[str, ...]:
    """As guardas da barreira, devolvidas como lista de problemas.

    Não basta que a projeção contenha só DEV: tem de ser **impossível** que
    contenha mais. As três verificações respondem a três maneiras diferentes de
    o conjunto final chegar à calibração — pela porta da frente (o contrato
    errado), por engano (uma pergunta selada na lista) e pela porta lateral (uma
    estrutura auxiliar que traga as atribuições ou os rótulos todos).
    """
    problems: list[str] = []

    if payload.get("contract") != DEV_PROJECTION_CONTRACT:
        problems.append(
            f"contract is {payload.get('contract')!r}, expected "
            f"{DEV_PROJECTION_CONTRACT!r}"
        )
    if payload.get("split_scope") != DEV:
        problems.append(f"split_scope is {payload.get('split_scope')!r}, expected {DEV!r}")

    for key in sorted(_PROJECTION_FORBIDDEN_KEYS & set(payload)):
        problems.append(f"the DEV projection carries {key!r}, which describes both splits")

    sealed_questions = {str(qid) for qid in manifest.get("question_ids", ())}
    sealed_scenarios = {str(sid) for sid in manifest.get("scenario_ids", ())}
    for question in payload.get("questions", ()):
        question_id = str(question.get("question_id"))
        if question_id in sealed_questions:
            problems.append(f"{question_id}: sealed question present in the DEV projection")
        scenario_id = str(question.get("scenario_id"))
        if scenario_id in sealed_scenarios:
            problems.append(
                f"{question_id}: scenario {scenario_id} belongs to the sealed set"
            )

    return tuple(problems)


def load_calibration_questions(
    payload: Mapping[str, Any], manifest: Mapping[str, Any]
) -> list[Mapping[str, Any]]:
    """Única porta de entrada dos dados na calibração.

    Levanta :class:`LeakageError` em vez de devolver menos: uma barreira que
    filtrasse em silêncio deixaria a calibração correr sobre um conjunto que
    ninguém pediu, e o resultado pareceria válido. Apontar esta função ao
    dataset completo é um erro, não uma calibração sobre tudo.
    """
    problems = verify_dev_projection(payload, manifest)
    if problems:
        raise LeakageError(
            "the calibration was pointed at data it must not see: " + "; ".join(problems)
        )
    return sorted(
        (dict(question) for question in payload["questions"]),
        key=lambda question: str(question["question_id"]),
    )
