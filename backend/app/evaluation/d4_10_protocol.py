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

#: Estados do bloco de validação, com os nomes que o artefacto já usava. O
#: estado pendente é diferente conforme a intenção porque a operação que a
#: máquina fez foi diferente: localizar evidência não é o mesmo que procurar e
#: não encontrar.
MACHINE_LOCATED: Final = "MACHINE_LOCATED_PENDING_HUMAN_CONFIRMATION"
MACHINE_SEARCHED: Final = "MACHINE_SEARCHED_PENDING_HUMAN_CONFIRMATION"
VALIDATION_STATUSES: Final = (MACHINE_LOCATED, MACHINE_SEARCHED, HUMAN_CONFIRMED)

#: Que bloco de validação cada intenção usa, e qual o estado pendente próprio.
VALIDATION_BLOCK_BY_INTENT: Final = {
    ANSWERABLE: "answerable_validation",
    NO_EVIDENCE: "no_evidence_validation",
}
PENDING_VALIDATION_STATUS_BY_BLOCK: Final = {
    "answerable_validation": MACHINE_LOCATED,
    "no_evidence_validation": MACHINE_SEARCHED,
}

#: O campo que justifica a etiqueta, por bloco. Um ANSWERABLE justifica-se pelo
#: que a evidência diz; um NO_EVIDENCE justifica-se pelo que a procura devolveu.
RATIONALE_FIELD_BY_BLOCK: Final = {
    "answerable_validation": "rationale",
    "no_evidence_validation": "search_result",
}

#: O campo que sustenta materialmente a etiqueta, por bloco.
SUPPORT_FIELD_BY_BLOCK: Final = {
    "answerable_validation": "located_evidence",
    "no_evidence_validation": "terms_searched",
}

#: Revisão de independência semântica, por cenário. Sobreposição zero de
#: identificadores e de texto normalizado **não** prova independência: duas
#: formulações diferentes podem testar o mesmo facto institucional já medido.
#: Só um humano decide isso, e por isso o estado inicial é pendente.
PENDING_HUMAN_REVIEW: Final = "PENDING_HUMAN_REVIEW"
INDEPENDENT: Final = "INDEPENDENT"
RELATED_BUT_DISTINCT: Final = "RELATED_BUT_DISTINCT"
EXCLUDE: Final = "EXCLUDE"
OVERLAP_REVIEW_STATUSES: Final = (
    PENDING_HUMAN_REVIEW,
    INDEPENDENT,
    RELATED_BUT_DISTINCT,
    EXCLUDE,
)
#: Estados com que um cenário pode entrar na D4.10b. ``EXCLUDE`` não é um deles:
#: um cenário excluído tem de sair do conjunto **antes** de qualquer execução.
ADMISSIBLE_OVERLAP_STATUSES: Final = (INDEPENDENT, RELATED_BUT_DISTINCT)
OVERLAP_REVIEW_FIELD: Final = "historical_overlap_review"

#: Prefixo dos identificadores desta fase. Distinto de ``Q`` (D4.1–D4.9) e de
#: ``DA`` (D4.8.2) para que a reutilização acidental de um identificador
#: histórico seja visível à vista desarmada e detetável por teste.
QUESTION_ID_PATTERN: Final = re.compile(r"^DX\d{3}$")
SCENARIO_ID_PATTERN: Final = re.compile(r"^SC-[AN]\d{2}$")

#: A natureza temporal da D4.10a.1 não pode ser apagada por uma redação mais
#: curta no artefacto. O valor faz parte do ``protocol_digest``.
AMENDMENT_KIND: Final = "post_exposure_pre_execution_protocol_amendment"

#: Inventário mínimo conhecido comunicado para a emenda. Validá-lo aqui impede
#: que uma futura reconstrução omita silenciosamente uma exposição desfavorável.
KNOWN_PRIOR_EXPOSURES: Final = {
    "DX026": ("SC-A16", ANSWERABLE),
    "DX027": ("SC-A16", ANSWERABLE),
    "DX043": ("SC-N01", NO_EVIDENCE),
    "DX044": ("SC-N01", NO_EVIDENCE),
    "DX045": ("SC-N02", NO_EVIDENCE),
    "DX046": ("SC-N03", NO_EVIDENCE),
    "DX047": ("SC-N03", NO_EVIDENCE),
}
KNOWN_EXPOSED_SCENARIOS: Final = {
    "SC-A16": ANSWERABLE,
    "SC-N01": NO_EVIDENCE,
    "SC-N02": NO_EVIDENCE,
    "SC-N03": NO_EVIDENCE,
}
_OBSERVATION_FIELDS: Final = frozenset(
    {
        "question_id",
        "scenario_id",
        "answerability_intent",
        "exposure_surface",
        "retrieval_executed",
        "ranking_observed",
        "trace_observed",
        "returned_content_read",
        "target_chunk_content_read",
        "target_chunk_index",
        "target_corpus_item_id",
        "persisted_user_message_timestamps_utc",
        "persisted_end_to_end_execution_count",
        "persisted_answer_statuses_observed",
        "persisted_cited_source_counts_observed",
        "reconstruction_basis",
        "reconstruction_status",
        "observer_formed_belief_about_label",
        "observation_belief_rationale",
    }
)

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
    return VALIDATION_BLOCK_BY_INTENT[question["answerability_intent"]]


def _non_empty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def verify_question_confirmation(question: Mapping[str, Any]) -> None:
    """Recusa uma confirmação humana incoerente ou sem fundamento registado.

    O contrato anterior lia apenas o ``review_status`` e, quando este era
    ``HUMAN_CONFIRMED``, exigia que existisse um ``annotator``. Isso deixava
    passar uma pergunta em que o bloco de validação continuava a dizer
    ``MACHINE_LOCATED_PENDING_HUMAN_CONFIRMATION``: o resumo contava-a como
    confirmada enquanto o registo da validação dizia o contrário. Dois campos
    que descrevem o mesmo facto não podem discordar — nem na ordem inversa, com
    o bloco confirmado e a pergunta por rever.

    Uma confirmação humana afirma três coisas ao mesmo tempo: que um humano
    decidiu, quem foi, e sobre que material. As três são verificadas aqui.
    """
    qid = question.get("question_id")
    block = validation_block_name(question)
    validation = question.get(block)
    if not isinstance(validation, Mapping):
        msg = f"{qid}: {block} ausente"
        raise ProtocolError(msg)

    review_status = question.get("review_status")
    validation_status = validation.get("validation_status")
    if validation_status not in VALIDATION_STATUSES:
        msg = f"{qid}: validation_status ausente ou desconhecido"
        raise ProtocolError(msg)

    confirmed_review = review_status == HUMAN_CONFIRMED
    confirmed_validation = validation_status == HUMAN_CONFIRMED
    if confirmed_review != confirmed_validation:
        msg = (
            f"{qid}: confirmação incoerente — review_status {review_status!r} e "
            f"validation_status {validation_status!r}"
        )
        raise ProtocolError(msg)

    if not confirmed_review:
        # Pendente: o estado do bloco tem de ser o pendente próprio da intenção.
        if validation_status != PENDING_VALIDATION_STATUS_BY_BLOCK[block]:
            msg = (
                f"{qid}: validation_status {validation_status!r} não é o estado "
                f"pendente de {block}"
            )
            raise ProtocolError(msg)
        return

    if not _non_empty_string(validation.get("annotator")):
        msg = f"{qid}: HUMAN_CONFIRMED sem annotator nomeado"
        raise ProtocolError(msg)
    if not _non_empty_string(validation.get("validation_method")):
        msg = f"{qid}: HUMAN_CONFIRMED sem validation_method"
        raise ProtocolError(msg)
    rationale_field = RATIONALE_FIELD_BY_BLOCK[block]
    if not _non_empty_string(validation.get(rationale_field)):
        msg = f"{qid}: HUMAN_CONFIRMED sem {rationale_field}"
        raise ProtocolError(msg)
    support_field = SUPPORT_FIELD_BY_BLOCK[block]
    if not validation.get(support_field):
        msg = f"{qid}: HUMAN_CONFIRMED sem {support_field}"
        raise ProtocolError(msg)


def question_is_confirmed(question: Mapping[str, Any]) -> bool:
    """Se esta pergunta conta como humanamente validada.

    Passa pela **mesma** verificação que a guarda usa. Uma segunda leitura, mais
    permissiva, seria uma forma de contar confirmações que a validação recusa —
    exatamente o desencontro que esta fase corrigiu entre `review_status` e
    `validation_status`.
    """
    try:
        verify_question_confirmation(question)
    except ProtocolError:
        return False
    validation = question.get(validation_block_name(question))
    if not isinstance(validation, Mapping):
        return False
    return (
        question.get("review_status") == HUMAN_CONFIRMED
        and validation.get("validation_status") == HUMAN_CONFIRMED
    )


def known_historical_ids(payload: Mapping[str, Any]) -> frozenset[str]:
    """Identificadores históricos que o conjunto declara ter revisto."""
    declared = (payload.get("independence_manifest") or {}).get(
        "historical_question_ids"
    )
    return frozenset(declared or ())


def verify_scenario_review(
    scenario: Mapping[str, Any], known_ids: frozenset[str] = frozenset()
) -> None:
    """Recusa uma revisão de independência ausente, desconhecida ou sem assinatura."""
    sid = scenario.get("scenario_id")
    review = scenario.get(OVERLAP_REVIEW_FIELD)
    if not isinstance(review, Mapping):
        msg = f"{sid}: {OVERLAP_REVIEW_FIELD} ausente"
        raise ProtocolError(msg)
    status = review.get("status")
    if status not in OVERLAP_REVIEW_STATUSES:
        msg = f"{sid}: status de sobreposição desconhecido: {status!r}"
        raise ProtocolError(msg)
    if status == PENDING_HUMAN_REVIEW:
        return

    # Decisão final: tem sempre de ser assinada.
    if not _non_empty_string(review.get("annotator")):
        msg = f"{sid}: decisão {status} sem annotator nomeado"
        raise ProtocolError(msg)
    if status in (RELATED_BUT_DISTINCT, EXCLUDE):
        refs = review.get("historical_refs")
        if not refs:
            msg = f"{sid}: {status} sem historical_refs"
            raise ProtocolError(msg)
        for ref in refs:
            if not HISTORICAL_QUESTION_ID_PATTERN.match(str(ref)):
                msg = f"{sid}: historical_ref fora do padrão Q###/DA###: {ref!r}"
                raise ProtocolError(msg)
            # O padrão só diz que **parece** um identificador histórico. `Q999`
            # parece e não existe, e uma justificação que aponte para uma
            # pergunta inexistente não sustenta nada.
            if known_ids and str(ref) not in known_ids:
                msg = f"{sid}: historical_ref inexistente: {ref!r}"
                raise ProtocolError(msg)
        if not _non_empty_string(review.get("rationale")):
            msg = f"{sid}: {status} sem rationale"
            raise ProtocolError(msg)


def scenario_review_is_final(
    scenario: Mapping[str, Any], known_ids: frozenset[str] = frozenset()
) -> bool:
    """Se este cenário já tem decisão de independência **válida** e admissível.

    Como em :func:`question_is_confirmed`, passa pela mesma verificação que a
    guarda: contar um cenário como revisto só pelo rótulo do estado deixaria
    passar uma decisão sem anotador, sem justificação ou a apontar para uma
    pergunta que não existe.
    """
    try:
        verify_scenario_review(scenario, known_ids)
    except ProtocolError:
        return False
    review = scenario.get(OVERLAP_REVIEW_FIELD) or {}
    return review.get("status") in ADMISSIBLE_OVERLAP_STATUSES


def verify_overlap_review(payload: Mapping[str, Any]) -> None:
    """Recusa qualquer revisão de independência inválida no conjunto.

    Sobreposição zero de identificadores e de texto normalizado é o que o código
    consegue provar sozinho, e não é independência semântica: duas formulações
    sem uma palavra em comum podem testar exatamente o mesmo requisito já medido
    noutra fase. Quem decide isso é um humano, cenário a cenário — todos os 32,
    e não apenas o que a máquina achou suspeito.
    """
    known_ids = known_historical_ids(payload)
    for scenario in payload["scenarios"]:
        verify_scenario_review(scenario, known_ids)


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


def scenario_review_identity(scenario: Mapping[str, Any]) -> dict[str, Any]:
    """A projeção da revisão de independência que o digest cobre."""
    review = scenario.get(OVERLAP_REVIEW_FIELD)
    return {
        "scenario_id": scenario["scenario_id"],
        OVERLAP_REVIEW_FIELD: dict(review) if isinstance(review, Mapping) else None,
    }


def human_review_digest(payload: Mapping[str, Any]) -> str:
    """Digest do processo de revisão humana — perguntas **e** cenários.

    Sem este digest, confirmar as cinquenta validações deixaria o registo de
    quem validou o quê fora de qualquer selagem — e portanto editável depois,
    sem rasto. Com ele, trocar o anotador de uma pergunta, mudar a pergunta que
    foi validada ou reescrever a evidência registada muda o ``protocol_digest``.

    Cobre também a revisão de independência de cada cenário, pela mesma razão:
    decidir que ``SC-N04`` é independente de DA036/DA037 é um juízo humano com
    consequências sobre a validade do painel, e um juízo que não está selado é
    um juízo que se pode reescrever depois de ver os resultados.

    O ``scenario_digest`` continua a **não** cobrir esta revisão: se cobrisse,
    rever a independência invalidaria os cenários revistos — a mesma armadilha
    que o ``question_set_digest`` evita ao não cobrir o ``review_status``.
    """
    projection = {
        "questions": sorted(
            (human_review_identity(question) for question in payload["questions"]),
            key=lambda record: record["question_id"],
        ),
        "scenarios": sorted(
            (scenario_review_identity(scenario) for scenario in payload["scenarios"]),
            key=lambda record: record["scenario_id"],
        ),
    }
    return _digest(projection)


def protocol_digest(protocol: Mapping[str, Any]) -> str:
    """Digest do protocolo, sem os campos que descrevem a própria selagem."""
    excluded = {"protocol_digest", "sealed_at"}
    return _digest({k: v for k, v in protocol.items() if k not in excluded})


def verify_prior_observation_disclosure(protocol: Mapping[str, Any]) -> None:
    """Recusa uma D4.10a.1 que esconda ou interprete a exposição conhecida."""
    if protocol.get("amendment_kind") != AMENDMENT_KIND:
        msg = f"amendment_kind tem de ser {AMENDMENT_KIND!r}"
        raise ProtocolError(msg)

    disclosure = protocol.get("prior_observation_disclosure")
    if not isinstance(disclosure, Mapping):
        msg = "prior_observation_disclosure obrigatório e incorporado por valor"
        raise ProtocolError(msg)
    observations = disclosure.get("observations")
    if not isinstance(observations, Sequence) or isinstance(observations, (str, bytes)):
        msg = "prior_observation_disclosure.observations tem de ser uma lista"
        raise ProtocolError(msg)

    indexed: dict[str, Mapping[str, Any]] = {}
    for position, observation in enumerate(observations):
        if not isinstance(observation, Mapping):
            msg = f"observations[{position}] tem de ser um objeto"
            raise ProtocolError(msg)
        unknown_fields = sorted(set(observation) - _OBSERVATION_FIELDS)
        if unknown_fields:
            msg = f"observations[{position}] contém campos não observacionais: {unknown_fields}"
            raise ProtocolError(msg)
        required = {
            "question_id",
            "scenario_id",
            "answerability_intent",
            "exposure_surface",
            "observer_formed_belief_about_label",
        }
        missing = sorted(required - set(observation))
        if missing:
            msg = f"observations[{position}] campos obrigatórios em falta: {missing}"
            raise ProtocolError(msg)
        qid = observation["question_id"]
        if not isinstance(qid, str) or qid in indexed:
            msg = f"observations[{position}] question_id inválido ou duplicado"
            raise ProtocolError(msg)
        surfaces = observation["exposure_surface"]
        if (
            not isinstance(surfaces, Sequence)
            or isinstance(surfaces, (str, bytes))
            or not surfaces
            or not all(
                isinstance(surface, str) and surface.strip() for surface in surfaces
            )
        ):
            msg = f"{qid}: exposure_surface tem de ser uma lista não vazia"
            raise ProtocolError(msg)
        if "diagnostic_observation" in surfaces:
            msg = (
                f"{qid}: diagnostic_observation é demasiado ambíguo; declare o "
                "canal reconstruído ou a reconstrução parcial"
            )
            raise ProtocolError(msg)
        if "end_to_end" in surfaces:
            reconstruction_fields = {
                "persisted_user_message_timestamps_utc",
                "persisted_end_to_end_execution_count",
                "persisted_answer_statuses_observed",
                "persisted_cited_source_counts_observed",
                "reconstruction_basis",
                "reconstruction_status",
            }
            missing_reconstruction = sorted(
                reconstruction_fields - set(observation)
            )
            if missing_reconstruction:
                msg = (
                    f"{qid}: reconstrução end_to_end com campos em falta: "
                    f"{missing_reconstruction}"
                )
                raise ProtocolError(msg)
            timestamps = observation.get("persisted_user_message_timestamps_utc")
            executions = observation.get("persisted_end_to_end_execution_count")
            statuses = observation.get("persisted_answer_statuses_observed")
            source_counts = observation.get(
                "persisted_cited_source_counts_observed"
            )
            reconstruction_basis = observation.get("reconstruction_basis")
            reconstruction_status = observation.get("reconstruction_status")
            complete_reconstruction_invalid = (
                not isinstance(timestamps, Sequence)
                or isinstance(timestamps, (str, bytes))
                or not timestamps
                or not all(
                    isinstance(timestamp, str) and timestamp.strip()
                    for timestamp in timestamps
                )
                or not isinstance(executions, int)
                or isinstance(executions, bool)
                or executions != len(timestamps)
                or not isinstance(statuses, Sequence)
                or isinstance(statuses, (str, bytes))
                or not statuses
                or len(statuses) != executions
                or not all(isinstance(status, str) and status for status in statuses)
                or not isinstance(source_counts, Sequence)
                or isinstance(source_counts, (str, bytes))
                or not source_counts
                or len(source_counts) != executions
                or not all(
                    isinstance(count, int) and not isinstance(count, bool) and count >= 0
                    for count in source_counts
                )
                or not isinstance(reconstruction_basis, str)
                or not reconstruction_basis.strip()
            )
            partial_reconstruction = (
                reconstruction_status
                == "partial_end_to_end_details_not_recovered"
                and timestamps == []
                and executions is None
                and statuses == []
                and source_counts == []
                and isinstance(reconstruction_basis, str)
                and bool(reconstruction_basis.strip())
            )
            if reconstruction_status == "complete_from_persisted_messages":
                if complete_reconstruction_invalid:
                    msg = f"{qid}: reconstrução end_to_end incompleta ou incoerente"
                    raise ProtocolError(msg)
            elif not partial_reconstruction:
                msg = f"{qid}: reconstrução end_to_end incompleta ou incoerente"
                raise ProtocolError(msg)
        if "partially_reconstructed_diagnostic_observation" in surfaces:
            if (
                observation.get("reconstruction_status") != "channel_not_recovered"
                or not isinstance(observation.get("reconstruction_basis"), str)
                or not observation["reconstruction_basis"].strip()
            ):
                msg = f"{qid}: reconstrução parcial exige estado e base explícitos"
                raise ProtocolError(msg)
        target_identity_present = (
            "target_chunk_index" in observation
            or "target_corpus_item_id" in observation
        )
        if observation.get("target_chunk_content_read") is True or target_identity_present:
            chunk_index = observation.get("target_chunk_index")
            corpus_item_id = observation.get("target_corpus_item_id")
            if (
                not isinstance(chunk_index, int)
                or isinstance(chunk_index, bool)
                or chunk_index < 0
                or not isinstance(corpus_item_id, str)
                or not corpus_item_id.strip()
            ):
                msg = f"{qid}: target chunk exige corpus_item_id e chunk_index válidos"
                raise ProtocolError(msg)
        belief = observation["observer_formed_belief_about_label"]
        if not isinstance(belief, bool):
            msg = f"{qid}: observer_formed_belief_about_label tem de ser booleano"
            raise ProtocolError(msg)
        if belief is False:
            rationale = observation.get("observation_belief_rationale")
            if not isinstance(rationale, str) or not rationale.strip():
                msg = (
                    f"{qid}: observation_belief_rationale não vazio é obrigatório "
                    "quando observer_formed_belief_about_label é false"
                )
                raise ProtocolError(msg)
        indexed[qid] = observation

    missing_known = sorted(set(KNOWN_PRIOR_EXPOSURES) - set(indexed))
    if missing_known:
        msg = f"exposições conhecidas em falta: {missing_known}"
        raise ProtocolError(msg)
    for qid, (scenario_id, intent) in KNOWN_PRIOR_EXPOSURES.items():
        observation = indexed[qid]
        if (
            observation["scenario_id"] != scenario_id
            or observation["answerability_intent"] != intent
        ):
            msg = f"{qid}: cenário ou intenção divergente no disclosure"
            raise ProtocolError(msg)

    exposed_scenarios = disclosure.get("exposed_scenarios")
    if not isinstance(exposed_scenarios, Sequence) or isinstance(
        exposed_scenarios, (str, bytes)
    ):
        msg = "prior_observation_disclosure.exposed_scenarios tem de ser uma lista"
        raise ProtocolError(msg)
    declared_scenarios = {
        scenario.get("scenario_id"): scenario.get("answerability_intent")
        for scenario in exposed_scenarios
        if isinstance(scenario, Mapping)
    }
    for scenario_id, intent in KNOWN_EXPOSED_SCENARIOS.items():
        if declared_scenarios.get(scenario_id) != intent:
            msg = f"{scenario_id}: exposição de cenário ausente ou com intenção divergente"
            raise ProtocolError(msg)


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
        # Só um humano assina uma confirmação humana — e os dois campos que a
        # descrevem têm de dizer a mesma coisa.
        verify_question_confirmation(question)

    verify_overlap_review(payload)

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
    questions = payload["questions"]
    scenarios = payload["scenarios"]

    # Uma pergunta só conta como confirmada se passar pela mesma verificação
    # que a guarda aplica. Contar apenas `review_status` deixava passar uma
    # pergunta marcada como revista cujo bloco de validação ainda dizia
    # «pendente»; contar pelo rótulo do estado deixaria passar uma decisão de
    # cenário sem anotador ou sem justificação.
    known_ids = known_historical_ids(payload)

    statuses = Counter(question["review_status"] for question in questions)
    confirmed = sum(1 for question in questions if question_is_confirmed(question))
    pending_questions = len(questions) - confirmed

    overlap_statuses = Counter(
        (scenario.get(OVERLAP_REVIEW_FIELD) or {}).get("status")
        for scenario in scenarios
    )
    admissible = sum(
        1 for scenario in scenarios if scenario_review_is_final(scenario, known_ids)
    )
    pending_scenarios = len(scenarios) - admissible
    excluded = overlap_statuses[EXCLUDE]

    return {
        "by_status": dict(sorted(statuses.items())),
        "pending_human_review": pending_questions,
        "human_confirmed": confirmed,
        "total_questions": len(questions),
        "scenario_overlap_review": {
            "by_status": dict(
                sorted((str(k), v) for k, v in overlap_statuses.items())
            ),
            "total_scenarios": len(scenarios),
            "reviewed_and_admissible": admissible,
            "pending_or_inadmissible": pending_scenarios,
            "marked_exclude_still_present": excluded,
        },
        # `freeze_ready` afirma que **toda** a revisão humana está feita: as
        # perguntas e a independência dos cenários. Um cenário marcado EXCLUDE
        # que continue no conjunto bloqueia — a remoção tem de acontecer antes
        # de qualquer execução, não depois de se ver o que ele produziu.
        "freeze_ready": pending_questions == 0
        and pending_scenarios == 0
        and excluded == 0,
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
        "human_review_digest": human_review_digest(payload),
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
