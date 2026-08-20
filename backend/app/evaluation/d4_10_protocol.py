"""Identidade e guardas do protocolo pré-registado da D4.10 (fase D4.10a).

Módulo **puro**: calcula digests e valida invariantes de um conjunto de
perguntas e de um protocolo. Não importa SQLAlchemy, Settings, FastAPI nem SDK
de fornecedor, não executa retrieval e não mede coisa nenhuma. Como
``retrieval_metrics``, ``dense_baseline`` e ``hybrid_rrf``, **não** é
reexportado por ``app/evaluation/__init__.py``.

Porque é que esta fase existe separada da execução
---------------------------------------------------

A D4.9 decidiu com um limiar que vivia na mesma árvore de trabalho que o
resultado: não havia como provar que precedeu a medição, e o próprio enunciado
da fase proibia esse instrumento. A correção não é escrever melhores ressalvas —
é **separar o desenho da execução no histórico do projeto**.

Daí a divisão: a D4.10a fixa perguntas, condições, métricas, pooling, bootstrap
e regra de decisão, e produz digests. A D4.10b, noutro commit, recebe esses
digests e recusa correr se algum divergir. O que na D4.9 era testemunho passa
aqui a ser verificável por quem não estava presente.

O que os digests cobrem, e porquê
---------------------------------

``question_set_digest`` cobre a **substância** de cada pergunta — identificador,
cenário, texto, idioma, intenção de answerability e documento-alvo — e não os
campos de revisão. É deliberado: quando um humano confirmar uma validação, o
`review_status` muda e o conjunto de perguntas **não** deve passar por
alterado, porque nenhuma pergunta mudou. Editar o texto de uma pergunta, trocar
o cenário, mudar a intenção ou acrescentar/remover uma pergunta muda o digest.

``scenario_digest`` cobre a composição **e os metadados** dos cenários: que
perguntas pertencem a qual família semântica, e com que tipo, tópico, documento
alvo e intenção essa família foi declarada. É o digest que a análise por cenário
cita. Cobre a paráfrase movida de um cenário para outro sem mudar nenhum texto,
e também a redefinição silenciosa de um cenário que preserve identificadores e
contagens — reetiquetar ``exact_institutional_terms`` como ``paraphrase_natural``
mudaria a leitura dos resultados sem mudar uma única pergunta.

``human_review_digest`` cobre o **processo de validação**: por pergunta, o
estado de revisão e o bloco de validação inteiro — anotador, método, estado,
racional e âncoras ou termos procurados. Existe porque o
``question_set_digest`` deliberadamente **não** cobre nada disto, e sem um
segundo digest a validação humana ficaria por fora de toda a selagem: depois
das confirmações seria possível trocar quem validou, qual pergunta foi validada
ou que evidência foi registada sem que nenhum digest mudasse. Estes dois
digests respondem a perguntas diferentes — «as perguntas são as mesmas?» e «a
validação é a mesma?» — e por isso são separados.

Os três entram no ``protocol_digest`` e os três são precondição da D4.10b.
Confirmar a revisão muda o ``human_review_digest`` e, por consequência, o
``protocol_digest``: a selagem que a D4.10b terá de citar é a que existir
**depois** da revisão humana.
"""

import hashlib
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any, Final

from app.evaluation.results import canonical_json

#: Rótulos de intenção. **Não** são julgamentos de relevância: a D4.10a não
#: produz graus 0/1/2, que só existem depois de haver rankings para julgar.
ANSWERABLE: Final = "ANSWERABLE"
NO_EVIDENCE: Final = "NO_EVIDENCE"
ANSWERABILITY_INTENTS: Final = (ANSWERABLE, NO_EVIDENCE)

#: Estados de revisão, do mais fraco ao mais forte. Só ``HUMAN_CONFIRMED``
#: satisfaz os §13/§14 do enunciado: uma máquina pode localizar evidência e
#: registar onde a localizou, não pode assinar por um humano.
MACHINE_PROPOSED: Final = "MACHINE_PROPOSED_PENDING_HUMAN_REVIEW"
HUMAN_REVIEW_REQUIRED: Final = "HUMAN_REVIEW_REQUIRED"
HUMAN_CONFIRMED: Final = "HUMAN_CONFIRMED"
REVIEW_STATUSES: Final = (MACHINE_PROPOSED, HUMAN_REVIEW_REQUIRED, HUMAN_CONFIRMED)

#: Prefixo dos identificadores desta fase. Distinto de ``Q`` (D4.1–D4.9) e de
#: ``DA`` (D4.8.2) para que a reutilização acidental de um identificador
#: histórico seja visível à vista desarmada e detetável por teste.
QUESTION_ID_PATTERN: Final = re.compile(r"^DX\d{3}$")
SCENARIO_ID_PATTERN: Final = re.compile(r"^SC-[AN]\d{2}$")

#: Identificadores que esta fase **não** pode reutilizar.
HISTORICAL_QUESTION_ID_PATTERN: Final = re.compile(r"^(Q\d{3}|DA\d{3})$")

#: Campos que definem a substância de uma pergunta. O que fica de fora — os
#: blocos de validação e o `review_status` — é processo de revisão, não conteúdo.
QUESTION_IDENTITY_FIELDS: Final = (
    "question_id",
    "scenario_id",
    "question",
    "language",
    "answerability_intent",
    "target_document",
)

#: Metadados de um cenário que o ``scenario_digest`` cobre, além da lista de
#: perguntas que lhe pertencem.
SCENARIO_IDENTITY_FIELDS: Final = (
    "scenario_id",
    "scenario_type",
    "topic",
    "target_document",
    "answerability_intent",
    "question_count",
)

#: Metadados que uma pergunta herda do seu cenário e tem de repetir sem
#: divergir. São redundantes por conveniência de leitura; a redundância só é
#: segura se for verificada.
SCENARIO_INHERITED_FIELDS: Final = (
    "scenario_type",
    "topic",
    "target_document",
    "answerability_intent",
)

#: Campos de identidade que o artefacto declara sobre si próprio e que a
#: selagem recomputa antes de aceitar o conjunto.
DECLARED_IDENTITY_FIELDS: Final = (
    "question_set_digest",
    "scenario_digest",
    "human_review_digest",
    "scenario_distribution",
    "document_distribution",
)

#: Chave usada na distribuição por documento para as perguntas sem documento
#: alvo — as NO_EVIDENCE, que por definição não têm um. Explícita, para que a
#: distribuição some ao total e não esconda oito perguntas.
NO_TARGET_DOCUMENT: Final = "NO_TARGET_DOCUMENT"

DIGEST_ALGORITHM: Final = "sha256"


class ProtocolError(ValueError):
    """Um invariante do protocolo falhou. Nada é selado."""


def _digest(payload: object) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def question_identity(question: Mapping[str, Any]) -> dict[str, Any]:
    """A projeção de uma pergunta que o ``question_set_digest`` cobre."""
    missing = [field for field in QUESTION_IDENTITY_FIELDS if field not in question]
    if missing:
        msg = f"{question.get('question_id')!r}: campos em falta: {missing}"
        raise ProtocolError(msg)
    return {field: question[field] for field in QUESTION_IDENTITY_FIELDS}


def question_set_digest(questions: Sequence[Mapping[str, Any]]) -> str:
    """Digest da substância do conjunto, ordenado por ``question_id``."""
    projection = sorted(
        (question_identity(question) for question in questions),
        key=lambda record: record["question_id"],
    )
    return _digest(projection)


def validation_block_name(question: Mapping[str, Any]) -> str:
    """Nome do bloco de validação que a intenção da pergunta exige."""
    if question["answerability_intent"] == ANSWERABLE:
        return "answerable_validation"
    return "no_evidence_validation"


def scenario_identity(
    scenario: Mapping[str, Any], question_ids: Sequence[str]
) -> dict[str, Any]:
    """A projeção de um cenário que o ``scenario_digest`` cobre."""
    missing = [field for field in SCENARIO_IDENTITY_FIELDS if field not in scenario]
    if missing:
        msg = f"{scenario.get('scenario_id')!r}: campos em falta: {missing}"
        raise ProtocolError(msg)
    projection: dict[str, Any] = {
        field: scenario[field] for field in SCENARIO_IDENTITY_FIELDS
    }
    projection["question_ids"] = sorted(question_ids)
    return projection


def scenario_digest(payload: Mapping[str, Any]) -> str:
    """Digest dos cenários: metadados declarados e perguntas que os compõem.

    Recebe o conjunto inteiro, e não apenas as perguntas, porque os metadados
    que dão significado a um cenário — tipo, tópico, documento alvo, intenção —
    vivem no cenário. Um digest que só visse os agrupamentos deixaria passar a
    redefinição de um cenário sem tocar em nenhuma pergunta.
    """
    grouped: dict[str, list[str]] = {}
    for question in payload["questions"]:
        grouped.setdefault(question["scenario_id"], []).append(question["question_id"])
    projection = [
        scenario_identity(scenario, grouped.get(scenario["scenario_id"], ()))
        for scenario in sorted(
            payload["scenarios"], key=lambda record: record["scenario_id"]
        )
    ]
    return _digest(projection)


def human_review_identity(question: Mapping[str, Any]) -> dict[str, Any]:
    """A projeção de uma pergunta que o ``human_review_digest`` cobre.

    Cobre o bloco de validação **inteiro**, e não uma lista escolhida de campos:
    um campo acrescentado ao bloco é uma mudança no registo da validação e deve
    mudar o digest. O que fica de fora é o conteúdo da pergunta, que já tem o
    seu próprio digest.
    """
    block = validation_block_name(question)
    validation = question.get(block)
    return {
        "question_id": question["question_id"],
        "review_status": question["review_status"],
        "validation_block": block,
        "validation": dict(validation) if isinstance(validation, Mapping) else None,
    }


def human_review_digest(questions: Sequence[Mapping[str, Any]]) -> str:
    """Digest do processo de validação, ordenado por ``question_id``.

    Sem este digest, confirmar as cinquenta validações deixaria o registo de
    quem validou o quê fora de qualquer selagem — e portanto editável depois,
    sem rasto. Com ele, trocar o anotador de uma pergunta, mudar a pergunta que
    foi validada ou reescrever a evidência registada muda o ``protocol_digest``.
    """
    projection = sorted(
        (human_review_identity(question) for question in questions),
        key=lambda record: record["question_id"],
    )
    return _digest(projection)


def protocol_digest(protocol: Mapping[str, Any]) -> str:
    """Digest do protocolo, sem os campos que descrevem a própria selagem."""
    excluded = {"protocol_digest", "sealed_at"}
    return _digest({k: v for k, v in protocol.items() if k not in excluded})


def verify_question_set(payload: Mapping[str, Any]) -> None:
    """Recusa um conjunto de perguntas que viole qualquer invariante da fase.

    Cada verificação existe por uma razão que a D4.9 tornou concreta: um
    conjunto que se possa ajustar depois de ver resultados não é independente, e
    a única forma de o impedir é recusar aqui o que mais tarde seria conveniente.
    """
    questions = payload["questions"]
    scenarios = payload["scenarios"]
    if not questions:
        msg = "conjunto vazio"
        raise ProtocolError(msg)

    seen: set[str] = set()
    for question in questions:
        qid = question["question_id"]
        if HISTORICAL_QUESTION_ID_PATTERN.match(qid):
            msg = f"{qid}: identificador histórico reutilizado (Q### ou DA###)"
            raise ProtocolError(msg)
        if not QUESTION_ID_PATTERN.match(qid):
            msg = f"{qid}: identificador fora do padrão DX###"
            raise ProtocolError(msg)
        if qid in seen:
            msg = f"{qid}: identificador duplicado"
            raise ProtocolError(msg)
        seen.add(qid)

        if not SCENARIO_ID_PATTERN.match(question["scenario_id"]):
            msg = f"{qid}: scenario_id fora do padrão SC-A## / SC-N##"
            raise ProtocolError(msg)
        if question["answerability_intent"] not in ANSWERABILITY_INTENTS:
            msg = f"{qid}: answerability_intent desconhecida"
            raise ProtocolError(msg)
        if question.get("review_status") not in REVIEW_STATUSES:
            msg = f"{qid}: review_status ausente ou desconhecido"
            raise ProtocolError(msg)

        # A validação tem de existir e tem de nomear um método. Ausência de
        # bloco de validação seria uma etiqueta sem fundamento nenhum.
        block = validation_block_name(question)
        validation = question.get(block)
        if not isinstance(validation, dict) or not validation.get("validation_method"):
            msg = f"{qid}: {block} ausente ou sem validation_method"
            raise ProtocolError(msg)
        if question["answerability_intent"] == ANSWERABLE and not validation.get(
            "located_evidence"
        ):
            msg = f"{qid}: ANSWERABLE sem evidência localizada"
            raise ProtocolError(msg)
        if question["answerability_intent"] == NO_EVIDENCE and not validation.get(
            "terms_searched"
        ):
            msg = f"{qid}: NO_EVIDENCE sem termos procurados"
            raise ProtocolError(msg)
        # Só um humano assina uma confirmação humana.
        if question["review_status"] == HUMAN_CONFIRMED and not validation.get(
            "annotator"
        ):
            msg = f"{qid}: HUMAN_CONFIRMED sem annotator"
            raise ProtocolError(msg)

    declared = {scenario["scenario_id"] for scenario in scenarios}
    used = {question["scenario_id"] for question in questions}
    if declared != used:
        msg = f"cenários declarados e usados divergem: {declared ^ used}"
        raise ProtocolError(msg)

    by_scenario = {scenario["scenario_id"]: scenario for scenario in scenarios}
    if len(by_scenario) != len(scenarios):
        msg = "cenário duplicado"
        raise ProtocolError(msg)

    counts = Counter(question["scenario_id"] for question in questions)
    for scenario in scenarios:
        if counts[scenario["scenario_id"]] != scenario["question_count"]:
            msg = (
                f"{scenario['scenario_id']}: question_count declarado "
                f"{scenario['question_count']}, encontrado "
                f"{counts[scenario['scenario_id']]}"
            )
            raise ProtocolError(msg)
        # Um cenário mistura formulações da mesma intenção; misturar intenções
        # tornaria a análise por cenário incoerente.
        intents = {
            question["answerability_intent"]
            for question in questions
            if question["scenario_id"] == scenario["scenario_id"]
        }
        if len(intents) != 1:
            msg = f"{scenario['scenario_id']}: intenções mistas {sorted(intents)}"
            raise ProtocolError(msg)

    # Cada pergunta repete os metadados do seu cenário por conveniência de
    # leitura. Repetição não verificada é repetição que diverge: uma pergunta
    # podia declarar-se de outro documento alvo ou de outro tipo semântico e
    # nada a contradiria, deixando a análise por cenário a medir uma coisa e a
    # leitura por documento a medir outra. Vem depois das verificações de
    # cenário para que um cenário com intenções mistas seja diagnosticado como
    # tal, e não como divergência de uma das perguntas.
    for question in questions:
        scenario = by_scenario[question["scenario_id"]]
        for field in SCENARIO_INHERITED_FIELDS:
            if question.get(field) != scenario.get(field):
                msg = (
                    f"{question['question_id']}: {field} diverge do cenário "
                    f"{scenario['scenario_id']}: pergunta {question.get(field)!r}, "
                    f"cenário {scenario.get(field)!r}"
                )
                raise ProtocolError(msg)


def human_review_summary(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Quanto do conjunto já tem assinatura humana, e quanto não tem.

    O protocolo só pode ser declarado **congelado** quando isto chegar a zero
    pendentes: até lá, o que existe é uma proposta auditável, não um pré-registo.
    """
    statuses = Counter(question["review_status"] for question in payload["questions"])
    pending = statuses[MACHINE_PROPOSED] + statuses[HUMAN_REVIEW_REQUIRED]
    return {
        "by_status": dict(sorted(statuses.items())),
        "pending_human_review": pending,
        "human_confirmed": statuses[HUMAN_CONFIRMED],
        "freeze_ready": pending == 0,
    }


def distribution(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Distribuições declaradas no artefacto e recomputáveis a partir dele."""
    questions = payload["questions"]
    scenarios = payload["scenarios"]
    return {
        "scenario_count": len(scenarios),
        "question_count": len(questions),
        "by_answerability_intent": dict(
            sorted(Counter(q["answerability_intent"] for q in questions).items())
        ),
        "by_scenario_type": dict(
            sorted(Counter(s["scenario_type"] for s in scenarios).items())
        ),
        "questions_per_scenario": {
            "min": min(s["question_count"] for s in scenarios),
            "max": max(s["question_count"] for s in scenarios),
        },
    }


def scenario_distribution(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Composição declarada de cada cenário, indexada pelo identificador."""
    grouped: dict[str, list[str]] = {}
    for question in payload["questions"]:
        grouped.setdefault(question["scenario_id"], []).append(question["question_id"])
    return {
        scenario["scenario_id"]: {
            "scenario_type": scenario["scenario_type"],
            "topic": scenario["topic"],
            "target_document": scenario["target_document"],
            "answerability_intent": scenario["answerability_intent"],
            "question_count": scenario["question_count"],
            "question_ids": sorted(grouped.get(scenario["scenario_id"], ())),
        }
        for scenario in sorted(
            payload["scenarios"], key=lambda record: record["scenario_id"]
        )
    }


def document_distribution(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Cobertura por documento: quantas perguntas **e** de que tipos semânticos.

    As duas coisas juntas, porque separadas não respondem à pergunta que
    interessa. Cinco perguntas sobre um documento que sejam todas do mesmo tipo
    não testam a mesma coisa que cinco perguntas repartidas por termos exatos,
    paráfrase e formulação indireta, e uma contagem sozinha não distingue os
    dois casos.
    """
    questions = payload["questions"]
    keys = {question["target_document"] or NO_TARGET_DOCUMENT for question in questions}
    result: dict[str, Any] = {}
    for key in sorted(keys):
        selected = [
            question
            for question in questions
            if (question["target_document"] or NO_TARGET_DOCUMENT) == key
        ]
        result[key] = {
            "question_count": len(selected),
            "scenario_count": len({q["scenario_id"] for q in selected}),
            "scenario_ids": sorted({q["scenario_id"] for q in selected}),
            "by_scenario_type": dict(
                sorted(Counter(q["scenario_type"] for q in selected).items())
            ),
            "by_answerability_intent": dict(
                sorted(Counter(q["answerability_intent"] for q in selected).items())
            ),
            "topics": sorted({q["topic"] for q in selected}),
        }
    return result


def declared_identity(payload: Mapping[str, Any]) -> dict[str, Any]:
    """A identidade que o conjunto de perguntas declara sobre si próprio."""
    return {
        "question_set_digest": question_set_digest(payload["questions"]),
        "scenario_digest": scenario_digest(payload),
        "human_review_digest": human_review_digest(payload["questions"]),
        "scenario_distribution": scenario_distribution(payload),
        "document_distribution": document_distribution(payload),
    }


def verify_declared_identity(payload: Mapping[str, Any]) -> None:
    """Recusa um conjunto cuja identidade declarada não corresponda ao conteúdo.

    O artefacto carrega os seus próprios digests e distribuições para que quem
    o leia não precise de os recalcular à mão. Carregá-los sem os verificar
    seria pior do que não os ter: uma edição podia mudar o conteúdo e deixar
    intacta a linha que descreve o conteúdo. Esta guarda é separada de
    ``verify_question_set`` de propósito — uma verifica o que o conjunto é, a
    outra verifica o que o conjunto diz ser.
    """
    expected = declared_identity(payload)
    missing = [field for field in DECLARED_IDENTITY_FIELDS if field not in payload]
    if missing:
        msg = f"identidade declarada em falta: {missing}"
        raise ProtocolError(msg)
    for field in DECLARED_IDENTITY_FIELDS:
        if payload[field] != expected[field]:
            msg = (
                f"{field} declarado não corresponde ao conteúdo do conjunto "
                f"(recalcule com stamp_d4_10_question_set)"
            )
            raise ProtocolError(msg)


#: Campos cuja presença num protocolo significaria que a fase já observou
#: resultados. A separação D4.10a/D4.10b não é uma convenção documental: é isto.
FORBIDDEN_PROTOCOL_FIELDS: Final = (
    "aggregate",
    "metrics",
    "results",
    "question_results",
    "rankings",
    "ranking",
    "decision",
    "result_digest",
    "recall",
    "ndcg",
    "mrr",
    "grades",
    "judgments",
    "bootstrap_result",
)


def verify_protocol_has_no_results(protocol: Mapping[str, Any]) -> None:
    """Um protocolo que contenha resultados já não é um pré-registo."""

    def walk(node: object, path: str = "") -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key in FORBIDDEN_PROTOCOL_FIELDS:
                    msg = f"protocolo contém campo de resultado: {path}{key}"
                    raise ProtocolError(msg)
                walk(value, f"{path}{key}.")
        elif isinstance(node, list):
            for item in node:
                walk(item, path)

    walk(protocol)
