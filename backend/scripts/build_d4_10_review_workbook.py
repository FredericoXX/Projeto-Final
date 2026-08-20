"""D4.10a — prepara a folha de trabalho da revisão humana.

Gera um documento de leitura para quem vai validar as perguntas e decidir a
independência semântica dos cenários. Junta num sítio só o que hoje está
espalhado por dois ficheiros JSON: o texto de cada pergunta, a âncora ou os
termos que a máquina registou, e — para cada cenário — as perguntas históricas
que mais se parecem com as suas, para que a comparação não dependa de memória.

**Gerar isto não é ter feito a revisão.** O comando não escreve no conjunto de
perguntas, não muda nenhum estado, não preenche anotadores e não decide nada. As
semelhanças que apresenta são um auxílio de leitura calculado por sobreposição
de palavras, não um juízo: duas formulações sem uma palavra em comum podem
testar exatamente o mesmo facto, e é por isso que a decisão é humana.

Não executa a experiência: sem embeddings, sem retrieval, sem rankings.
"""

import argparse
import json
import re
import sys
import unicodedata
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any, Final

from app.evaluation.d4_10_protocol import (
    ANSWERABLE,
    OVERLAP_REVIEW_FIELD,
    ProtocolError,
    validation_block_name,
    verify_question_set,
)

EXIT_OK: Final = 0
EXIT_GUARD_FAILED: Final = 4

#: Quantas perguntas históricas semelhantes mostrar por cenário, por ordenação
#: automática. A ordenação sozinha não chega — ver ``PINNED_REFERENCE_PATTERN``.
CANDIDATES_PER_SCENARIO: Final = 5

#: Identificadores históricos citados nas notas do próprio conjunto. São
#: mostrados sempre, à frente da ordenação automática: em SC-N04, as duas
#: históricas que a nota já identifica como a preocupação real (DA036, DA037)
#: ficam em sexto lugar e abaixo por sobreposição de palavras, atrás de cinco
#: perguntas menos aparentadas. Uma ferramenta que deixasse cair aquilo que o
#: registo já assinalou seria pior do que não existir.
PINNED_REFERENCE_PATTERN: Final = re.compile(r"\b(Q\d{3}|DA\d{3})\b")

#: Palavras demasiado comuns para indicarem parentesco entre duas perguntas.
STOPWORDS: Final = frozenset(
    """
    a ao aos as às até com como da das de do dos e em entre há na nas no nos o os
    ou para pela pelas pelo pelos por qual quais quando quanto quantos que quem se
    sem ser sobre um uma umas uns é são está estão pode posso preciso qualquer
    """.split()
)

TOKEN_PATTERN: Final = re.compile(r"[a-z0-9]+")


def normalise(text: str) -> str:
    """Sem acentos, sem caixa, sem pontuação — vários documentos vieram de OCR."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def tokens(text: str) -> set[str]:
    return {
        token
        for token in TOKEN_PATTERN.findall(normalise(text))
        if token not in STOPWORDS and len(token) > 2
    }


def similarity(left: str, right: str) -> float:
    """Jaccard sobre palavras de conteúdo. Um auxílio de leitura, não uma medida."""
    first, second = tokens(left), tokens(right)
    if not first or not second:
        return 0.0
    return len(first & second) / len(first | second)


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        msg = f"{path}: esperado um objeto JSON"
        raise ProtocolError(msg)
    return payload


def historical_questions(paths: Iterable[Path]) -> list[dict[str, str]]:
    """Texto das perguntas de Q001–Q014 e DA001–DA049, para comparação."""
    collected: list[dict[str, str]] = []
    for path in paths:
        payload = load_json(path)
        for question in payload["questions"]:
            collected.append(
                {
                    "question_id": question["question_id"],
                    "question": question["question"],
                    "source": path.name,
                }
            )
    return collected


def pinned_references(scenario_questions: Sequence[dict[str, Any]]) -> set[str]:
    """Históricas já citadas nas notas das perguntas do cenário."""
    found: set[str] = set()
    for question in scenario_questions:
        note = question.get("overlap_review_note")
        if note:
            found.update(PINNED_REFERENCE_PATTERN.findall(note))
    return found


def candidates_for(
    scenario_questions: Sequence[dict[str, Any]],
    historical: Sequence[dict[str, str]],
) -> list[tuple[float, str, str, bool]]:
    """As perguntas históricas a mostrar: as já citadas, mais as mais parecidas.

    A ordenação por palavras comuns é um auxílio fraco e sabe-se onde falha, por
    isso o que o registo já assinalou entra sempre — mesmo quando a ordenação o
    põe em sexto lugar, como acontece em SC-N04.
    """
    best: dict[str, tuple[float, str, str]] = {}
    for question in scenario_questions:
        for candidate in historical:
            score = similarity(question["question"], candidate["question"])
            current = best.get(candidate["question_id"])
            if current is None or score > current[0]:
                best[candidate["question_id"]] = (
                    score,
                    candidate["question_id"],
                    candidate["question"],
                )

    pinned = pinned_references(scenario_questions)
    ranked = sorted(
        (item for item in best.values() if item[0] > 0),
        key=lambda item: (-item[0], item[1]),
    )
    chosen = [item for item in ranked if item[1] not in pinned][
        :CANDIDATES_PER_SCENARIO
    ]
    chosen += [best[ref] for ref in sorted(pinned) if ref in best]
    return sorted(
        ((score, qid, text, qid in pinned) for score, qid, text in chosen),
        key=lambda item: (not item[3], -item[0], item[1]),
    )


def render(question_set: dict[str, Any], historical: Sequence[dict[str, str]]) -> str:
    """O documento inteiro, em markdown."""
    scenarios = sorted(question_set["scenarios"], key=lambda s: s["scenario_id"])
    questions = question_set["questions"]
    by_scenario: dict[str, list[dict[str, Any]]] = {}
    for question in questions:
        by_scenario.setdefault(question["scenario_id"], []).append(question)

    lines: list[str] = [
        "# D4.10a — folha de revisão humana",
        "",
        "**Este documento não é prova de revisão.** É o material para a fazer.",
        "Enquanto as decisões abaixo não forem tomadas por uma pessoa e escritas",
        "no conjunto de perguntas, o protocolo permanece `DRAFT` e a D4.10b está",
        "bloqueada.",
        "",
        "Nada aqui foi decidido por máquina. O que a máquina fez foi localizar",
        "evidência, registar onde a localizou e — para a independência — listar as",
        "perguntas históricas com mais palavras em comum. Semelhança de palavras",
        "não é semelhança de intenção: duas formulações sem uma palavra comum",
        "podem testar o mesmo requisito, e duas quase iguais podem testar factos",
        "diferentes. Por isso a lista é um ponto de partida, não uma resposta.",
        "",
        "Há prova concreta disso neste mesmo documento. Em `SC-N04`, as duas",
        "perguntas históricas que a nota do conjunto já identifica como a",
        "preocupação real — `DA036` e `DA037` — ficam em **sexto lugar e abaixo**",
        "por palavras em comum, atrás de cinco perguntas menos aparentadas. O",
        "parentesco que interessa (perguntar por datas de aulas de um ano que o",
        "corpus não cobre) não está nas palavras. Por isso o que o registo já",
        "assinalou aparece sempre, marcado com ⚑, à margem da ordenação.",
        "",
        "## Como preencher",
        "",
        "**Por cenário** — decidir o estado de independência face a Q001–Q014 e",
        "DA001–DA049:",
        "",
        "| Estado | Quando |",
        "| --- | --- |",
        "| `INDEPENDENT` | não testa o mesmo facto/intenção já medido |",
        "| `RELATED_BUT_DISTINCT` | há relação temática, mas o facto testado é "
        "distinto — exige `historical_refs` e `rationale` |",
        "| `EXCLUDE` | reutiliza material histórico de forma que compromete a "
        "independência — exige `historical_refs` e `rationale` |",
        "",
        "Qualquer decisão final exige `annotator` com nome real. Um cenário",
        "`EXCLUDE` tem de sair do conjunto — ele e todas as suas perguntas —",
        "**antes** de qualquer embedding ou ranking.",
        "",
        "**Por pergunta** — `CONFIRM`, `EDIT` ou `EXCLUDE`. Confirmar significa",
        "pôr `review_status` e `validation_status` em `HUMAN_CONFIRMED` e assinar",
        "com o nome real; os dois campos têm de concordar, e há guarda que recusa",
        "se não concordarem.",
        "",
        f"Cenários a rever: **{len(scenarios)}**. Perguntas a rever: "
        f"**{len(questions)}**.",
        "",
    ]

    for scenario in scenarios:
        sid = scenario["scenario_id"]
        scenario_questions = sorted(
            by_scenario.get(sid, ()), key=lambda q: q["question_id"]
        )
        review = scenario.get(OVERLAP_REVIEW_FIELD) or {}
        lines += [
            f"## {sid} — {scenario['topic']}",
            "",
            f"- tipo: `{scenario['scenario_type']}`",
            f"- intenção: `{scenario['answerability_intent']}`",
            f"- documento alvo: `{scenario['target_document'] or '—'}`",
            f"- estado da revisão de independência: `{review.get('status')}`",
            "",
            "### Semelhanças históricas a considerar",
            "",
        ]
        found = candidates_for(scenario_questions, historical)
        if found:
            lines += [
                "| Semelhança | Histórica | Texto |",
                "| ---: | --- | --- |",
            ]
            lines += [
                f"| {score:.2f} | `{qid}`{' ⚑' if pin else ''} | {text} |"
                for score, qid, text, pin in found
            ]
            if any(pin for *_, pin in found):
                lines += [
                    "",
                    "⚑ já citada na nota do conjunto; mostrada independentemente "
                    "da ordenação.",
                ]
        else:
            lines.append(
                "_Nenhuma pergunta histórica com palavras de conteúdo em comum. "
                "Isto **não** é prova de independência._"
            )
        lines += [
            "",
            "```",
            "status:          INDEPENDENT | RELATED_BUT_DISTINCT | EXCLUDE",
            "historical_refs: []",
            "rationale:",
            "annotator:",
            "```",
            "",
            "### Perguntas",
            "",
        ]
        for question in scenario_questions:
            block = validation_block_name(question)
            validation = question[block]
            lines += [
                f"#### {question['question_id']} — `{question['review_status']}`",
                "",
                f"> {question['question']}",
                "",
            ]
            if question["answerability_intent"] == ANSWERABLE:
                anchors = ", ".join(
                    f"`{item['corpus_item_id']}#{item['chunk_index']}`"
                    for item in validation["located_evidence"]
                )
                lines += [
                    "- proposta: **ANSWERABLE**",
                    f"- evidência localizada: {anchors}",
                    f"- justificação registada: {validation['rationale']}",
                ]
            else:
                terms = ", ".join(f"`{term}`" for term in validation["terms_searched"])
                lines += [
                    "- proposta: **NO_EVIDENCE**",
                    f"- termos procurados: {terms}",
                    f"- resultado da procura: {validation['search_result']}",
                ]
            if question.get("overlap_review_note"):
                lines.append(f"- nota de sobreposição: {question['overlap_review_note']}")
            lines += [
                "",
                "```",
                "decisão:   CONFIRM | EDIT | EXCLUDE",
                "annotator:",
                "notas:",
                "```",
                "",
            ]

    lines += [
        "## Depois de preencher",
        "",
        "1. aplicar as decisões ao conjunto de perguntas (`EDIT` e `EXCLUDE`",
        "   **antes** de qualquer execução);",
        "2. `python -m scripts.stamp_d4_10_question_set --question-set ...`;",
        "3. `python -m scripts.seal_d4_10_protocol ...` — sem `--draft`, que só",
        "   passa quando `freeze_ready` for verdadeiro;",
        "4. versionar essa selagem num commit anterior a qualquer execução da",
        "   D4.10b.",
    ]
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="build_d4_10_review_workbook",
        description=(
            "D4.10a - prepara a folha de revisao humana. Nao executa a "
            "experiencia e nao decide nada."
        ),
    )
    parser.add_argument("--question-set", type=Path, required=True)
    parser.add_argument("--historical", type=Path, nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        question_set = load_json(args.question_set)
        verify_question_set(question_set)
        historical = historical_questions(args.historical)
    except (ProtocolError, KeyError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_GUARD_FAILED

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render(question_set, historical), encoding="utf-8")

    print(f"cenarios a rever  : {len(question_set['scenarios'])}")
    print(f"perguntas a rever : {len(question_set['questions'])}")
    print(f"historicas lidas  : {len(historical)}")
    print(f"escrito           : {args.output}")
    print("aviso             : gerar esta folha NAO e ter feito a revisao")
    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
