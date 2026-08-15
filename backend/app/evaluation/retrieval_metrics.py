"""Métricas de recuperação, na interpretação fixada pelo protocolo do D4.1.

Módulo **puro**: recebe graus de relevância já resolvidos e devolve números. Não
importa SQLAlchemy, Settings, modelos nem o retriever — a execução contra a base
vive em ``scripts.evaluate_retrieval_baseline``. Tal como
``app.evaluation.results`` e ``app.evaluation.snapshot``, **não** é reexportado
por ``app/evaluation/__init__.py``: a garantia de que importar
``app.evaluation.assets`` não carrega ``sqlalchemy`` não deve depender de
disciplina, e manter este módulo fora do ``__init__`` torna-a estrutural.

Porque é que as constantes vivem aqui
-------------------------------------

O protocolo de cálculo foi fixado em
``docs/evaluation/retrieval-ground-truth-p1-seed.json`` (campo
``metric_protocol``) precisamente para que duas implementações não produzissem
números diferentes a partir do mesmo ficheiro. As constantes abaixo são a
tradução desse protocolo em código, e o *runner* **verifica** que o ficheiro de
anotações declara os mesmos valores antes de medir seja o que for. Se divergirem,
a execução pára: um protocolo que o código contradiz não é protocolo.

O que estas métricas não são
----------------------------

Não são veredictos sobre a qualidade do sistema, e não são estimativas não
enviesadas. O conjunto de julgamentos é incompleto por construção
(``DIRECTED_JUDGMENT_INCOMPLETE``), e o sentido do enviesamento **difere por
métrica**: Precision e MRR são pessimistas por construção; Recall e nDCG têm
enviesamento indeterminado, porque julgar de menos encolhe também o denominador
(no Recall) e o IDCG (no nDCG). Ver §19.2 do relatório do D4.1.
"""

import math
from collections.abc import Mapping, Sequence
from typing import Final

#: Grau mínimo que conta como relevante em Recall e MRR. Um segmento de grau 1 é
#: contexto verdadeiro que **não responde sozinho**; contá-lo como acerto
#: inflacionaria o Recall com evidência que não demonstra que o pedido foi
#: satisfeito.
BINARY_RELEVANCE_THRESHOLD: Final = 2

#: Ganho por grau no nDCG. Deliberadamente **não linear**: com ganhos 0/1/2, dois
#: segmentos de grau 1 valeriam o mesmo que um de grau 2, o que contradiz a
#: rubrica — grau 1 é insuficiente por definição, e nenhuma quantidade de
#: contexto substitui a evidência que responde.
NDCG_GAIN_BY_GRADE: Final[Mapping[int, int]] = {0: 0, 1: 1, 2: 3}

#: Cortes reportados. O primário é 5 por ser o ``top_k`` registado no snapshot;
#: 1 e 3 existem para mostrar a sensibilidade à posição, não como alternativas.
K_VALUES: Final = (1, 3, 5)
PRIMARY_K: Final = 5

#: Grau atribuído a um segmento devolvido que não tem julgamento. Convenção
#: ``ASSUMED_IRRELEVANT`` do protocolo.
UNJUDGED_GRADE: Final = 0


def gain(grade: int) -> int:
    """Ganho de um grau, com falha explícita em vez de silenciosa.

    Um grau fora da rubrica é erro de anotação, não um caso a tratar por
    omissão: devolver 0 para um grau desconhecido esconderia o problema dentro
    de uma métrica plausível.
    """
    if grade not in NDCG_GAIN_BY_GRADE:
        msg = f"unknown relevance grade: {grade!r}"
        raise ValueError(msg)
    return NDCG_GAIN_BY_GRADE[grade]


def recall_at_k(
    retrieved_grades: Sequence[int],
    total_relevant: int,
    k: int,
) -> float:
    """Fração da evidência relevante **julgada** que aparece nos primeiros ``k``.

    ``retrieved_grades`` é a sequência de graus pela ordem do ranking, com
    ``UNJUDGED_GRADE`` nas posições sem julgamento. ``total_relevant`` é o número
    de julgamentos de grau ``>= BINARY_RELEVANCE_THRESHOLD`` **da pergunta**, e
    não o número de relevantes recuperados: é o denominador que torna a métrica
    um recall e não uma contagem.

    Levanta ``ValueError`` se não existir relevante nenhum. Não devolve 0.0 nem
    1.0 nesse caso, porque ambos seriam afirmações falsas sobre uma métrica que
    ali é **indefinida**; as perguntas sem evidência são excluídas a montante,
    pelo runner, e não silenciadas aqui.
    """
    if k <= 0:
        msg = f"k must be positive, got {k}"
        raise ValueError(msg)
    if total_relevant <= 0:
        msg = "recall is undefined when the question has no relevant evidence"
        raise ValueError(msg)
    found = sum(1 for grade in retrieved_grades[:k] if grade >= BINARY_RELEVANCE_THRESHOLD)
    return found / total_relevant


def reciprocal_rank(retrieved_grades: Sequence[int]) -> float:
    """Inverso da posição do **primeiro** segmento relevante, ou 0.0.

    Calculado sobre a lista devolvida, que o retriever já truncou em ``top_k``.
    É, portanto, um *reciprocal rank* truncado: se o primeiro relevante estivesse
    na posição 7 de uma lista de 5, o valor é 0.0 e não 1/7. Isto está declarado
    porque a alternativa — pedir mais resultados do que a configuração real
    devolve — mediria um sistema diferente daquele que está em produção.
    """
    for position, grade in enumerate(retrieved_grades, start=1):
        if grade >= BINARY_RELEVANCE_THRESHOLD:
            return 1.0 / position
    return 0.0


def dcg(grades: Sequence[int], k: int) -> float:
    """Discounted cumulative gain dos primeiros ``k``, com desconto ``log2(i+1)``."""
    if k <= 0:
        msg = f"k must be positive, got {k}"
        raise ValueError(msg)
    return sum(
        gain(grade) / math.log2(position + 1)
        for position, grade in enumerate(grades[:k], start=1)
    )


def ideal_dcg(judged_grades: Sequence[int], k: int) -> float:
    """DCG da ordenação ideal dos julgamentos **desta pergunta**.

    O ideal é construído a partir dos graus julgados, ordenados por ganho
    decrescente. Não é o ideal sobre o corpus inteiro: esse exigiria julgar todo
    o corpus, que é exatamente o que não foi feito. É esta escolha que torna o
    enviesamento do nDCG **indeterminado** sob julgamentos incompletos — os
    segmentos por julgar encolhem o DCG e o IDCG ao mesmo tempo.
    """
    return dcg(sorted(judged_grades, key=gain, reverse=True), k)


def ndcg_at_k(
    retrieved_grades: Sequence[int],
    judged_grades: Sequence[int],
    k: int,
) -> float:
    """nDCG@k normalizado pelo ideal dos julgamentos da própria pergunta.

    Levanta ``ValueError`` quando o IDCG é zero — o que só acontece se a pergunta
    não tiver qualquer julgamento de ganho positivo. Nesse caso a métrica é
    indefinida, e devolver 0.0 diria "o sistema falhou" quando o que se passa é
    "não há nada contra que medir".
    """
    ideal = ideal_dcg(judged_grades, k)
    if ideal == 0.0:
        msg = "nDCG is undefined when the question has no positive-gain judgments"
        raise ValueError(msg)
    return dcg(retrieved_grades, k) / ideal


def mean(values: Sequence[float]) -> float:
    """Média aritmética, com falha explícita sobre sequência vazia.

    A agregação das métricas é **macro**: cada pergunta pesa o mesmo,
    independentemente de quantos segmentos relevantes tenha. Com uma amostra
    pequena e desequilibrada, a micro-média deixaria as perguntas com mais
    julgamentos dominar o número reportado.
    """
    if not values:
        msg = "cannot average an empty sequence"
        raise ValueError(msg)
    return sum(values) / len(values)
