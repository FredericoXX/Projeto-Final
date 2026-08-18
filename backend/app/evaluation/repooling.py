"""Controlo do *repooling* dirigido do *ground truth* (D4.6).

Módulo **puro**: recebe dicionários já lidos de JSON e devolve problemas. Não
fala com a base de dados nem lê ficheiros, e — como
``app.evaluation.ground_truth_identity`` e ``app.evaluation.candidate_budget`` —
**não** é reexportado por ``app/evaluation/__init__.py``.

O que um *repooling* pode e não pode fazer
------------------------------------------

O D4.5 mediu o ranking contra um conjunto de julgamentos em que **26 dos 33
resultados** da condição ampliada não estavam anotados. Otimizar contra isso
mediria sobretudo a incompletude. O remédio é anotar mais — mas anotar mais tem
uma regra que não é negociável:

    **acrescentar julgamentos é legítimo; rever os existentes não é**, não sem o
    declarar.

Uma revisão silenciosa de um grau antigo tornaria a série D4.2–D4.5
incomparável sem que nada o assinalasse, e a comparação "antes e depois do
repooling" deixaria de medir a incompletude para passar a medir também a mudança
de opinião do anotador. :func:`verify_repooling` recusa esse caso.

O que **não** é verificável por código é a qualidade da anotação. O módulo prova
que o conjunto novo contém o antigo e que as perguntas não mudaram; não prova que
os graus novos estejam certos. Isso é juízo do anotador, e dizer o contrário
seria vender uma garantia que o código não dá.

Porque é que os identificadores se mantêm
-----------------------------------------

Ao contrário do conjunto pareado do D4.4 — onde as **perguntas** eram outras e os
identificadores tinham de o refletir —, aqui as perguntas são as mesmas, letra a
letra. O que muda é a densidade dos julgamentos. Manter ``Q001`` é, por isso,
correto, e é o ``ground_truth_digest`` que distingue as duas versões: é
exatamente para isto que ele existe.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final

from app.evaluation.ground_truth_identity import (
    PROTOCOL_FIELDS,
    QUESTION_FIELDS,
    GroundTruthIdentityError,
)

#: Campos por pergunta cuja igualdade o repooling exige. As perguntas não podem
#: mudar: se mudassem, isto deixaria de ser um repooling e passaria a ser um
#: conjunto novo, como o do D4.4.
INVARIANT_QUESTION_FIELDS: Final = (
    *QUESTION_FIELDS,
    "temporal_scope",
    "question_origin",
    "exclusion_reason",
)

#: Campos de cada julgamento comparados por identidade.
JUDGMENT_KEY_FIELDS: Final = ("corpus_item_id", "chunk_index")


@dataclass(frozen=True)
class RepoolingReport:
    """Resumo do que o repooling acrescentou, e a lista de problemas."""

    added_by_grade: dict[int, int] = field(default_factory=dict)
    added: tuple[tuple[str, str, int, int], ...] = ()
    problems: tuple[str, ...] = ()

    @property
    def valid(self) -> bool:
        return not self.problems

    @property
    def added_total(self) -> int:
        return len(self.added)

    @property
    def questions_touched(self) -> tuple[str, ...]:
        return tuple(sorted({entry[0] for entry in self.added}))


def _judgment_index(
    question: Mapping[str, Any], context: str
) -> dict[tuple[str, int], int]:
    index: dict[tuple[str, int], int] = {}
    for judgment in question["evidence_judgments"]:
        try:
            key = (judgment["corpus_item_id"], judgment["chunk_index"])
        except KeyError as error:
            msg = f"{context}: judgment missing {error}"
            raise GroundTruthIdentityError(msg) from error
        if key in index:
            msg = f"{context}: duplicate judgment for {key}"
            raise GroundTruthIdentityError(msg)
        index[key] = judgment["relevance"]
    return index


def verify_repooling(
    historical: Mapping[str, Any], repooled: Mapping[str, Any]
) -> RepoolingReport:
    """Prova que ``repooled`` **estende** ``historical`` sem o rever.

    Devolve os julgamentos acrescentados por grau, para que o relatório possa
    declarar a diferença entre os dois digests em vez de a afirmar.
    """
    problems: list[str] = []

    for field_name in ("schema_version", "corpus_id", "snapshot_id", "corpus_digest"):
        if historical.get(field_name) != repooled.get(field_name):
            problems.append(f"ground truths disagree on {field_name}")
    historical_protocol = historical.get("metric_protocol") or {}
    repooled_protocol = repooled.get("metric_protocol") or {}
    for field_name in PROTOCOL_FIELDS:
        if historical_protocol.get(field_name) != repooled_protocol.get(field_name):
            problems.append(f"ground truths disagree on metric_protocol.{field_name}")

    historical_questions = {
        str(question["question_id"]): question for question in historical["questions"]
    }
    repooled_questions = {
        str(question["question_id"]): question for question in repooled["questions"]
    }
    missing = sorted(set(historical_questions) - set(repooled_questions))
    extra = sorted(set(repooled_questions) - set(historical_questions))
    if missing:
        problems.append(f"questions dropped by the repooling: {missing}")
    if extra:
        problems.append(f"questions invented by the repooling: {extra}")

    added: list[tuple[str, str, int, int]] = []
    added_by_grade: dict[int, int] = {}
    for question_id in sorted(set(historical_questions) & set(repooled_questions)):
        before = historical_questions[question_id]
        after = repooled_questions[question_id]
        for field_name in INVARIANT_QUESTION_FIELDS:
            if field_name == "question_id":
                continue
            if before.get(field_name) != after.get(field_name):
                problems.append(f"{question_id}: {field_name} changed; this is not a repooling")

        before_index = _judgment_index(before, question_id)
        after_index = _judgment_index(after, question_id)

        for key, grade in before_index.items():
            if key not in after_index:
                problems.append(
                    f"{question_id}: judgment {key[0]}/{key[1]} was removed"
                )
            elif after_index[key] != grade:
                problems.append(
                    f"{question_id}: judgment {key[0]}/{key[1]} was revised "
                    f"{grade} -> {after_index[key]}; a repooling may add, not revise"
                )
        for key, grade in sorted(after_index.items()):
            if key in before_index:
                continue
            added.append((question_id, key[0], key[1], grade))
            added_by_grade[grade] = added_by_grade.get(grade, 0) + 1

    if not added and not problems:
        problems.append("the repooling added no judgment at all")

    return RepoolingReport(
        added_by_grade=dict(sorted(added_by_grade.items())),
        added=tuple(added),
        problems=tuple(problems),
    )


def verify_requests_satisfied(
    requests: Sequence[Mapping[str, Any]],
    historical: Mapping[str, Any],
    repooled: Mapping[str, Any],
) -> tuple[str, ...]:
    """Prova que o repooling tratou **exatamente** os pedidos, e mais nenhum.

    :func:`verify_repooling` prova que o conjunto novo estende o antigo sem o
    rever. Não prova que estenda pela razão declarada: um repooling que
    acrescentasse julgamentos escolhidos por outro critério passaria lá e
    produziria uma comparação diferente da que o artefacto de pedidos descreve.

    Três condições, e as três são necessárias:

    - **completude** — todo o pedido tem julgamento no conjunto novo. Um pedido
      por tratar deixa um resultado do top 5 a contar grau 0 por omissão, que é
      exatamente o enviesamento que o repooling existe para remover;
    - **fidelidade** — nenhum julgamento acrescentado está fora da lista de
      pedidos. Anotar mais do que o pedido não é ilegítimo em si, mas deixa de
      ser reproduzível a partir do artefacto que declara o âmbito;
    - **necessidade** — nenhum pedido já estava julgado no conjunto histórico.
      Se estivesse, a lista de pedidos descreveria um estado que não existia, e
      o número «31 por julgar» seria falso.
    """
    problems: list[str] = []

    historical_questions = {
        str(question["question_id"]): question for question in historical["questions"]
    }
    repooled_questions = {
        str(question["question_id"]): question for question in repooled["questions"]
    }

    requested: set[tuple[str, str, int]] = set()
    for request in requests:
        key = (
            str(request["question_id"]),
            str(request["corpus_item_id"]),
            int(request["chunk_index"]),
        )
        if key in requested:
            problems.append(f"duplicate repooling request {key}")
        requested.add(key)

    added: set[tuple[str, str, int]] = set()
    for question_id, question in sorted(repooled_questions.items()):
        before = historical_questions.get(question_id)
        if before is None:
            continue
        before_index = _judgment_index(before, question_id)
        after_index = _judgment_index(question, question_id)
        for item, index in after_index:
            if (item, index) not in before_index:
                added.add((question_id, item, index))

    for key in sorted(requested - added):
        question_id, item, index = key
        question = repooled_questions.get(question_id)
        judged = question is not None and (item, index) in _judgment_index(
            question, question_id
        )
        if not judged:
            problems.append(
                f"{question_id}: {item}/{index} was requested and is still unjudged"
            )
        else:
            problems.append(
                f"{question_id}: {item}/{index} was requested but was already judged "
                "in the historical set; the request list describes a state that did "
                "not exist"
            )

    for question_id, item, index in sorted(added - requested):
        problems.append(
            f"{question_id}: {item}/{index} was judged but was not requested; the "
            "repooling is not reproducible from the declared scope"
        )

    return tuple(problems)


def relevant_target_count(
    question: Mapping[str, Any], threshold: int
) -> int:
    """Nº de julgamentos de grau ``>= threshold`` — o denominador do Recall.

    Existe aqui, e não só no runner, porque é **este** número que o repooling
    pode alterar: acrescentar um grau 2 muda o denominador da pergunta e, com
    ele, o Recall medido em todas as condições. É a razão pela qual os
    resultados históricos continuam ligados ao digest antigo.
    """
    return sum(
        1
        for judgment in question["evidence_judgments"]
        if judgment["relevance"] >= threshold
    )


def denominator_changes(
    historical: Mapping[str, Any], repooled: Mapping[str, Any], threshold: int
) -> list[dict[str, Any]]:
    """Perguntas cujo denominador do Recall mudou com o repooling.

    Sem esta lista, uma variação de Recall entre as duas versões seria
    indistinguível de uma variação de comportamento do sistema.
    """
    historical_questions = {
        str(question["question_id"]): question for question in historical["questions"]
    }
    changes: list[dict[str, Any]] = []
    for question in repooled["questions"]:
        question_id = str(question["question_id"])
        before = historical_questions.get(question_id)
        if before is None:
            continue
        was = relevant_target_count(before, threshold)
        now = relevant_target_count(question, threshold)
        if was != now:
            changes.append(
                {"question_id": question_id, "before": was, "after": now}
            )
    return changes


def judgment_coverage(
    question: Mapping[str, Any], returned: Sequence[tuple[str, int]]
) -> dict[str, int]:
    """Quantos dos resultados devolvidos têm julgamento, e quantos não têm.

    É a métrica que justifica a fase: o D4.5 mediu o ranking com 26 de 33
    resultados por julgar, e é preciso poder mostrar que isso mudou.
    """
    judged = {
        (judgment["corpus_item_id"], judgment["chunk_index"])
        for judgment in question["evidence_judgments"]
    }
    covered = sum(1 for key in returned if key in judged)
    return {
        "returned": len(returned),
        "judged": covered,
        "unjudged": len(returned) - covered,
    }
