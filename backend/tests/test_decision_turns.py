"""Modo experimental da política v1.7 através da API real.

PostgreSQL real, recuperação lexical real, persistência real; estimador e
gerador são doubles determinísticos (``tests/decision_support.py``). Os
documentos, pedidos e catálogos são fixtures **técnicas e sintéticas** — não
são anotação científica nem casos de avaliação.
"""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.decision.contracts import RequestConstraint, ScopeClass
from app.decision.dimensions import Specificity, policy_input_from_dict
from app.decision.estimators.base import EstimationError, ItemDraft, ReadingDraft
from app.decision.policy import decide as decide_policy
from app.models.decision_record import DecisionRecord
from app.models.message import Message
from app.models.message_source import MessageSource
from tests.decision_support import (
    RecordingGenerator,
    ScriptedEstimator,
    analysis,
    decide,
    make_world,
    support_by_title,
)
from tests.role_support import create_account_and_login

ENROLMENT = "O prazo de matrícula termina a 30 de setembro. A matrícula faz-se no portal académico."
FEES = "As propinas de matrícula pagam-se em dez prestações mensais."


def _records(factory: sessionmaker[Session]) -> list[DecisionRecord]:
    with factory() as db:
        return list(db.scalars(select(DecisionRecord).order_by(DecisionRecord.created_at)).all())


def _count(factory: sessionmaker[Session], model: type) -> int:
    with factory() as db:
        return db.scalar(select(func.count()).select_from(model)) or 0


# --- Modo desativado e configuração ----------------------------------------------------


def test_policy_mode_is_disabled_by_default(client: TestClient, install) -> None:
    world = make_world(client)
    install(ScriptedEstimator(result=analysis()))
    conversation = world.conversation(client)

    response = decide(client, conversation, world.student)
    status = client.get("/api/v1/decision/status", headers=world.student).json()

    assert response.status_code == 503
    assert status["enabled"] is False
    assert status["catalog_configured"] is True


def test_b0_ask_is_unchanged_when_the_policy_is_enabled(
    client: TestClient,
    policy_enabled,
    install,
) -> None:
    """O contrato legado continua a declarar answered/insufficient_evidence."""
    world = make_world(client)
    world.document(client, "Regulamento de matrículas", ENROLMENT)
    install(ScriptedEstimator(result=analysis()))
    conversation = world.conversation(client)

    response = client.post(
        f"/api/v1/conversations/{conversation}/ask",
        json={"query": "prazo de matrícula"},
        headers=world.student,
    )

    assert response.status_code == 201
    assert response.json()["status"] == "answered"
    assert "action" not in response.json()
    assert response.json()["assistant_message"]["extra_metadata"] == {"answer_status": "answered"}


def test_institution_without_catalog_is_not_configured(
    client: TestClient,
    policy_enabled,
    install,
) -> None:
    world = make_world(client, catalog=None)
    install(ScriptedEstimator(result=analysis()))

    response = decide(client, world.conversation(client), world.student)

    assert response.status_code == 503


# --- As quatro ações pela API -------------------------------------------------------------


def test_r01_out_of_scope_abstains_without_retrieval_or_generation(
    client: TestClient,
    policy_enabled,
    install,
    test_session_factory,
) -> None:
    world = make_world(client)
    world.document(client, "Regulamento de matrículas", ENROLMENT)
    estimator = ScriptedEstimator(
        result=analysis(scope=ScopeClass.OUT_OF_SCOPE, items=(), topic=None)
    )
    generator = RecordingGenerator()
    install(estimator, generator)

    response = decide(
        client, world.conversation(client), world.student, query="Qual é a capital de França?"
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["action"], body["rule"]) == ("abstain", "R01")
    assert estimator.assessment_calls == []
    assert generator.calls == []
    assert body["assistant_message"]["sources"] == []
    record = _records(test_session_factory)[-1]
    assert record.record["retrieval"]["queries"] == 0


def test_r09_answers_with_the_generator_and_persists_citations(
    client: TestClient,
    policy_enabled,
    install,
    test_session_factory,
) -> None:
    world = make_world(client)
    world.document(client, "Regulamento de matrículas", ENROLMENT)
    generator = RecordingGenerator()
    install(
        ScriptedEstimator(result=analysis(), assess_with=support_by_title({"I1": "matrículas"})),
        generator,
    )

    response = decide(client, world.conversation(client), world.student)

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["action"], body["rule"]) == ("answer", "R09")
    assert len(generator.calls) == 1
    assert [source["document_title"] for source in body["assistant_message"]["sources"]] == [
        "Regulamento de matrículas"
    ]
    metadata = body["assistant_message"]["extra_metadata"]
    assert metadata["turn_type"] == "policy_decision"
    assert metadata["decision_trigger"] == "automatic"
    assert metadata["policy_version"] == body["policy_version"]
    assert _count(test_session_factory, MessageSource) == 1


def test_r10_answers_the_supported_part_and_declares_the_gap(
    client: TestClient,
    policy_enabled,
    install,
) -> None:
    world = make_world(client)
    world.document(client, "Regulamento de matrículas", ENROLMENT)
    items = (ItemDraft("I1", "prazo de matrícula"), ItemDraft("I2", "valor da taxa de matrícula"))
    install(
        ScriptedEstimator(
            result=analysis(items=items),
            assess_with=support_by_title({"I1": "matrículas"}, partial_misleading=False),
        )
    )

    body = decide(client, world.conversation(client), world.student).json()

    assert (body["action"], body["rule"]) == ("answer", "R10")
    assert body["gap_items"] == ["valor da taxa de matrícula"]
    assert "valor da taxa de matrícula" in body["assistant_message"]["content"]


def test_answer_without_a_citation_for_an_item_is_a_technical_failure_not_an_abstention(
    client: TestClient,
    policy_enabled,
    install,
    test_session_factory,
) -> None:
    world = make_world(client)
    world.document(client, "Regulamento de matrículas", ENROLMENT)
    world.document(client, "Tabela de propinas", FEES)
    items = (ItemDraft("I1", "prazo"), ItemDraft("I2", "propinas"))
    install(
        ScriptedEstimator(
            result=analysis(items=items),
            assess_with=support_by_title({"I1": "matrículas", "I2": "propinas"}),
        ),
        # Cita só a primeira evidência: o item I2 fica sem citação.
        RecordingGenerator(cite=lambda context: (context.evidence[0].evidence_id,)),
    )

    response = decide(
        client, world.conversation(client), world.student, query="prazo de matrícula e propinas"
    )

    assert response.status_code == 502
    assert _count(test_session_factory, Message) == 0
    record = _records(test_session_factory)[-1]
    assert (record.status, record.action, record.rule) == ("technical_failure", None, None)
    assert record.failure_code == "missing_item_citation"


def test_r06_clarifies_and_the_continuation_starts_a_new_revalidated_decision(
    client: TestClient,
    policy_enabled,
    install,
    test_session_factory,
) -> None:
    world = make_world(client)
    world.document(client, "Regulamento de matrículas", ENROLMENT)
    world.document(client, "Tabela de propinas", FEES)
    readings = (
        ReadingDraft("L1", "Prazo da matrícula", "prazo de matrícula"),
        ReadingDraft("L2", "Prazo das propinas de matrícula", "propinas de matrícula"),
    )
    estimator = ScriptedEstimator(
        result=analysis(
            specificity=Specificity.UNDERSPECIFIED,
            ambiguity_material=True,
            user_can_distinguish=True,
            readings=readings,
        ),
        assess_with=support_by_title(
            {"I1": "matrículas"}, coverage={"L1": "matrículas", "L2": "propinas"}
        ),
    )
    generator = RecordingGenerator()
    install(estimator, generator)
    conversation = world.conversation(client)

    clarify = decide(
        client, conversation, world.student, query="Qual é o prazo da matrícula?"
    ).json()

    assert (clarify["action"], clarify["rule"]) == ("clarify", "R06")
    assert [option["reading_id"] for option in clarify["clarification_options"]] == ["L1", "L2"]
    assert generator.calls == []
    # Recuperação por leitura: uma consulta por leitura, mais o diagnóstico.
    assert _records(test_session_factory)[-1].record["retrieval"]["per_reading"] is True

    estimator.result = analysis()
    continued = decide(
        client,
        conversation,
        world.student,
        query=None,
        clarification={"message_id": clarify["assistant_message"]["id"], "reading_id": "L1"},
    )

    assert continued.status_code == 200, continued.text
    body = continued.json()
    assert body["action"] == "answer"
    assert body["user_message"]["content"] == "Prazo da matrícula"
    assert (
        body["user_message"]["extra_metadata"]["clarification_of"]
        == clarify["assistant_message"]["id"]
    )
    # A nova decisão parte do pedido original e da leitura escolhida.
    assert estimator.analysis_calls[-1].selected_reading == "Prazo da matrícula"
    assert estimator.analysis_calls[-1].query == "Qual é o prazo da matrícula?"


def test_unknown_clarification_option_is_not_found(
    client: TestClient,
    policy_enabled,
    install,
) -> None:
    world = make_world(client)
    install(ScriptedEstimator(result=analysis()))
    conversation = world.conversation(client)
    decide(client, conversation, world.student)
    message = client.get(f"/api/v1/conversations/{conversation}/messages", headers=world.student)
    assistant = message.json()["items"][-1]

    response = decide(
        client,
        conversation,
        world.student,
        query=None,
        clarification={"message_id": assistant["id"], "reading_id": "L9"},
    )

    assert response.status_code == 404


@pytest.mark.parametrize(
    ("constraint", "topic", "rule", "action"),
    [
        (RequestConstraint.ADMINISTRATIVE_ACTION_REQUIRED, "enrolment", "R02", "escalate"),
        (RequestConstraint.ADMINISTRATIVE_ACTION_REQUIRED, "fees", "R03", "abstain"),
        (RequestConstraint.PERSONAL_DATA_REQUIRED, "grades", "R04", "escalate"),
        (RequestConstraint.PERSONAL_DATA_REQUIRED, "fees", "R05", "abstain"),
        (RequestConstraint.PERSONAL_DATA_REQUIRED, None, "R05", "abstain"),
    ],
)
def test_constraints_escalate_only_to_a_catalog_service_competent_for_the_topic(
    client: TestClient,
    policy_enabled,
    install,
    constraint: RequestConstraint,
    topic: str | None,
    rule: str,
    action: str,
) -> None:
    """O destino genérico E1 da instituição não prova competência: só o catálogo."""
    world = make_world(client)
    generator = RecordingGenerator()
    install(
        ScriptedEstimator(result=analysis(constraints=frozenset({constraint}), topic=topic)),
        generator,
    )

    body = decide(
        client, world.conversation(client), world.student, query="Qual é a minha nota?"
    ).json()

    assert (body["action"], body["rule"]) == (action, rule)
    assert generator.calls == []
    content = body["assistant_message"]["content"]
    if action == "escalate":
        assert body["destination"]["service_id"] == "academic-office"
        assert body["assistant_message"]["extra_metadata"]["handoff_trigger"] == "policy_decision"
        assert "não foi enviado" in content
    else:
        assert body["destination"] is None
        assert "academicos@example.org" not in content


def test_procedure_in_an_escalation_is_a_cited_excerpt_of_admissible_evidence(
    client: TestClient,
    policy_enabled,
    install,
) -> None:
    world = make_world(client)
    world.document(client, "Regulamento de matrículas", ENROLMENT)
    generator = RecordingGenerator()
    install(
        ScriptedEstimator(
            result=analysis(
                constraints=frozenset({RequestConstraint.ADMINISTRATIVE_ACTION_REQUIRED}),
                procedure_item=ItemDraft("P1", "como fazer a matrícula"),
            ),
            assess_with=support_by_title({"P1": "matrículas"}),
        ),
        generator,
    )

    body = decide(
        client, world.conversation(client), world.student, query="Matricule-me no curso"
    ).json()

    assert body["rule"] == "R02"
    assert generator.calls == []
    assert "portal académico" in body["assistant_message"]["content"]
    assert [source["document_title"] for source in body["assistant_message"]["sources"]] == [
        "Regulamento de matrículas"
    ]


@pytest.mark.parametrize(
    ("topic", "rule", "action"), [("enrolment", "R07", "escalate"), ("fees", "R08", "abstain")]
)
def test_unresolvable_conflict_cites_both_orientations(
    client: TestClient,
    policy_enabled,
    install,
    topic: str,
    rule: str,
    action: str,
) -> None:
    world = make_world(client)
    world.document(client, "Regulamento de matrículas A", ENROLMENT)
    world.document(
        client,
        "Regulamento de matrículas B",
        "O prazo de matrícula termina a 15 de outubro. A matrícula faz-se presencialmente.",
    )
    install(
        ScriptedEstimator(
            result=analysis(topic=topic),
            assess_with=support_by_title(
                {"I1": "matrículas"},
                conflicts=(("I1", ("matrículas A", "matrículas B"), False),),
            ),
        )
    )

    body = decide(client, world.conversation(client), world.student).json()

    assert (body["action"], body["rule"]) == (action, rule)
    titles = {source["document_title"] for source in body["assistant_message"]["sources"]}
    assert titles == {"Regulamento de matrículas A", "Regulamento de matrículas B"}


@pytest.mark.parametrize(
    ("topic", "rule", "action"), [("enrolment", "R11", "escalate"), ("fees", "R12", "abstain")]
)
def test_no_support_escalates_or_abstains_and_says_what_was_not_found(
    client: TestClient,
    policy_enabled,
    install,
    topic: str,
    rule: str,
    action: str,
) -> None:
    world = make_world(client)
    world.document(client, "Regulamento de matrículas", ENROLMENT)
    install(ScriptedEstimator(result=analysis(topic=topic), assess_with=support_by_title({})))

    body = decide(client, world.conversation(client), world.student).json()

    assert (body["action"], body["rule"]) == (action, rule)
    # "Não encontrei", relativo ao que foi consultado — nunca "não existe".
    assert "documentos consultados" in body["assistant_message"]["content"]


# --- Diagnóstico temporal e data de referência ----------------------------------------------


def test_expired_relevant_evidence_changes_the_message_but_not_the_action(
    client: TestClient,
    policy_enabled,
    install,
) -> None:
    world = make_world(client)
    today = datetime.now(UTC).date()
    world.document(
        client,
        "Calendário antigo",
        ENROLMENT,
        valid_from=today - timedelta(days=400),
        valid_until=today - timedelta(days=1),
    )
    estimator = ScriptedEstimator(result=analysis(topic="fees"))
    install(estimator)

    body = decide(client, world.conversation(client), world.student).json()

    assert (body["action"], body["rule"]) == ("abstain", "R12")
    assert body["temporal_notice"] is True
    content = body["assistant_message"]["content"]
    assert "Calendário antigo" in content and "não está em vigor" in content
    # O conteúdo caducado nunca é usado como fundamento nem chega ao estimador.
    assert "30 de setembro" not in content
    assert body["assistant_message"]["sources"] == []


def test_no_temporal_notice_when_current_evidence_was_also_found(
    client: TestClient,
    policy_enabled,
    install,
) -> None:
    """Auditoria de 2026-10-22, achado 6: o aviso só se aplica quando apenas
    foi encontrada informação fora de vigor. Com evidência vigente que suporta
    parte do pedido, o documento caducado não gera aviso."""
    world = make_world(client)
    today = datetime.now(UTC).date()
    world.document(client, "Regulamento de matrículas", ENROLMENT)
    world.document(
        client,
        "Calendário antigo",
        "O prazo de matrícula antigo terminava a 1 de setembro.",
        valid_from=today - timedelta(days=400),
        valid_until=today - timedelta(days=1),
    )
    items = (ItemDraft("I1", "prazo de matrícula"), ItemDraft("I2", "taxa"))
    install(
        ScriptedEstimator(
            result=analysis(items=items),
            assess_with=support_by_title({"I1": "Regulamento"}, partial_misleading=True),
        )
    )

    body = decide(client, world.conversation(client), world.student).json()

    assert (body["action"], body["rule"]) == ("escalate", "R11")
    assert body["temporal_notice"] is False
    assert "Calendário antigo" not in body["assistant_message"]["content"]


def test_temporal_notice_documents_must_still_be_authorized_at_persistence(
    client: TestClient,
    policy_enabled,
    install,
    test_session_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Auditoria, achado 5: o título de um documento caducado entra na
    mensagem; se esse documento deixar de estar autorizado ao papel durante a
    decisão, o turno não é gravado."""
    from app.services import decision_service

    world = make_world(client)
    today = datetime.now(UTC).date()
    expired, _ = world.document(
        client,
        "Calendário antigo",
        ENROLMENT,
        valid_from=today - timedelta(days=400),
        valid_until=today - timedelta(days=1),
    )
    install(ScriptedEstimator(result=analysis(topic="fees")))
    original_gather = decision_service.gather_evidence

    def gather_then_restrict(*args, **kwargs):  # type: ignore[no-untyped-def]
        gathered = original_gather(*args, **kwargs)
        with test_session_factory() as db:
            db.execute(
                text("UPDATE documents SET access_roles = ARRAY['staff'] WHERE id = :id"),
                {"id": expired["id"]},
            )
            db.commit()
        return gathered

    monkeypatch.setattr(decision_service, "gather_evidence", gather_then_restrict)

    response = decide(client, world.conversation(client), world.student)

    assert response.status_code == 409
    assert "Calendário antigo" not in response.text
    assert _count(test_session_factory, Message) == 0


def test_uncited_admissible_evidence_must_still_be_authorized_at_persistence(
    client: TestClient,
    policy_enabled,
    install,
    test_session_factory,
) -> None:
    """Auditoria, achado 5: a decisão (aqui, a falta de suporte) assenta em
    evidência admissível não citada; se um desses documentos for vedado ao
    papel durante a decisão, o turno não é gravado."""
    world = make_world(client)
    document, _ = world.document(client, "Regulamento de matrículas", ENROLMENT)

    def restrict_then_assess(request):  # type: ignore[no-untyped-def]
        with test_session_factory() as db:
            db.execute(
                text("UPDATE documents SET access_roles = ARRAY['staff'] WHERE id = :id"),
                {"id": document["id"]},
            )
            db.commit()
        return support_by_title({})(request)

    install(ScriptedEstimator(result=analysis(), assess_with=restrict_then_assess))

    response = decide(client, world.conversation(client), world.student)

    assert response.status_code == 409
    assert _count(test_session_factory, Message) == 0
    assert _records(test_session_factory)[-1].status == "technical_failure"


def test_no_results_never_invent_an_outdated_notice(
    client: TestClient,
    policy_enabled,
    install,
) -> None:
    world = make_world(client)
    install(ScriptedEstimator(result=analysis(topic="fees")))

    body = decide(client, world.conversation(client), world.student).json()

    assert body["temporal_notice"] is False
    assert "em vigor" not in body["assistant_message"]["content"]


@pytest.mark.parametrize(
    ("valid_from_offset", "valid_until_offset", "admissible"),
    [(0, None, True), (None, 0, True), (1, None, False), (None, -1, False)],
    ids=["starts-today", "ends-today", "starts-tomorrow", "ended-yesterday"],
)
def test_validity_limits_are_inclusive_at_the_reference_date(
    client: TestClient,
    policy_enabled,
    install,
    valid_from_offset: int | None,
    valid_until_offset: int | None,
    admissible: bool,
) -> None:
    world = make_world(client)
    today = datetime.now(UTC).date()
    world.document(
        client,
        "Calendário com limites",
        ENROLMENT,
        valid_from=None if valid_from_offset is None else today + timedelta(days=valid_from_offset),
        valid_until=None
        if valid_until_offset is None
        else today + timedelta(days=valid_until_offset),
    )
    estimator = ScriptedEstimator(
        result=analysis(), assess_with=support_by_title({"I1": "limites"})
    )
    install(estimator)

    body = decide(client, world.conversation(client), world.student).json()

    seen = [p.document_title for call in estimator.assessment_calls for p in call.passages]
    assert ("Calendário com limites" in seen) is admissible
    assert (body["action"] == "answer") is admissible


def test_one_reference_date_is_used_across_the_turn(
    client: TestClient,
    policy_enabled,
    install,
    test_session_factory,
) -> None:
    world = make_world(client)
    world.document(client, "Regulamento de matrículas", ENROLMENT)
    estimator = ScriptedEstimator(
        result=analysis(), assess_with=support_by_title({"I1": "matrículas"})
    )
    install(estimator)

    body = decide(client, world.conversation(client), world.student).json()

    record = _records(test_session_factory)[-1]
    reference = record.reference_date.isoformat()
    assert body["assistant_message"]["extra_metadata"]["reference_date"] == reference
    assert record.record["policy_input"]["reference_date"] == reference
    assert record.record["policy_input"]["admissibility"]["reference_date"] == reference
    assert estimator.analysis_calls[0].reference_date == record.reference_date


# --- Autorização documental por papel e isolamento -------------------------------------------


def test_role_restricted_documents_never_reach_the_estimator_or_the_message(
    client: TestClient,
    policy_enabled,
    install,
) -> None:
    world = make_world(client)
    world.document(client, "Regulamento de matrículas", ENROLMENT)
    world.document(
        client,
        "Procedimento interno de matrículas",
        "O prazo de matrícula interno para docentes termina a 1 de setembro.",
        access_roles=["staff"],
    )
    staff, _ = create_account_and_login(client, world.admin, role="staff")
    estimator = ScriptedEstimator(
        result=analysis(), assess_with=support_by_title({"I1": "matrículas"})
    )
    install(estimator)

    student_body = decide(client, world.conversation(client), world.student).json()
    student_titles = {p.document_title for p in estimator.assessment_calls[-1].passages}
    decide(client, world.conversation(client, staff), staff)
    staff_titles = {p.document_title for p in estimator.assessment_calls[-1].passages}

    assert "Procedimento interno de matrículas" not in student_titles
    assert "Procedimento interno de matrículas" in staff_titles
    assert "interno" not in str(student_body)


def test_sources_of_documents_later_restricted_are_withheld_on_read(
    client: TestClient,
    policy_enabled,
    install,
    test_session_factory,
) -> None:
    world = make_world(client)
    document, _ = world.document(client, "Regulamento de matrículas", ENROLMENT)
    install(
        ScriptedEstimator(result=analysis(), assess_with=support_by_title({"I1": "matrículas"}))
    )
    conversation = world.conversation(client)
    decide(client, conversation, world.student)

    restricted = client.patch(
        f"/api/v1/documents/{document['id']}",
        json={"access_roles": ["staff"]},
        headers=world.manager,
    )
    listed = client.get(f"/api/v1/conversations/{conversation}/messages", headers=world.student)

    assert restricted.status_code == 200
    assert all(item["sources"] == [] for item in listed.json()["items"])
    assert "Regulamento" not in listed.text
    # O registo histórico não é alterado.
    assert _count(test_session_factory, MessageSource) == 1


def test_documents_of_another_institution_never_become_evidence(
    client: TestClient,
    policy_enabled,
    install,
) -> None:
    world = make_world(client)
    other = make_world(client)
    other.document(client, "Regulamento de matrículas de outra instituição", ENROLMENT)
    estimator = ScriptedEstimator(
        result=analysis(), assess_with=support_by_title({"I1": "matrículas"})
    )
    install(estimator)

    body = decide(client, world.conversation(client), world.student).json()

    assert estimator.assessment_calls == []  # nenhuma passagem admissível
    assert body["rule"] == "R11"


# --- Falhas técnicas, registo e replay ---------------------------------------------------------


@pytest.mark.parametrize("failure", ["timeout", "invalid_output"])
def test_estimator_failure_is_technical_and_never_an_abstention(
    client: TestClient,
    policy_enabled,
    install,
    test_session_factory,
    failure: str,
) -> None:
    world = make_world(client)
    install(ScriptedEstimator(result=analysis(), fail_with=EstimationError(failure)))

    response = decide(client, world.conversation(client), world.student)

    assert response.status_code == 502
    assert "abstain" not in response.text
    assert _count(test_session_factory, Message) == 0
    record = _records(test_session_factory)[-1]
    assert (record.status, record.failure_code, record.action) == (
        "technical_failure",
        failure,
        None,
    )


def test_invalid_estimator_reference_to_inadmissible_evidence_is_rejected(
    client: TestClient,
    policy_enabled,
    install,
    test_session_factory,
) -> None:
    world = make_world(client)
    world.document(client, "Regulamento de matrículas", ENROLMENT)

    def invent(request):  # type: ignore[no-untyped-def]
        assessment = support_by_title({"I1": "matrículas"})(request)
        from dataclasses import replace

        from app.decision.estimators.base import ItemSupportDraft

        return replace(
            assessment,
            item_support=(ItemSupportDraft("I1", True, frozenset({"E99"})),),
        )

    install(ScriptedEstimator(result=analysis(), assess_with=invent))

    response = decide(client, world.conversation(client), world.student)

    assert response.status_code == 502
    assert _records(test_session_factory)[-1].failure_code == "invalid_assessment"


def test_decision_record_is_protected_and_replays_to_the_same_decision(
    client: TestClient,
    policy_enabled,
    install,
    test_session_factory,
) -> None:
    world = make_world(client)
    world.document(client, "Regulamento de matrículas", ENROLMENT)
    install(
        ScriptedEstimator(result=analysis(), assess_with=support_by_title({"I1": "matrículas"}))
    )

    body = decide(client, world.conversation(client), world.student).json()

    record = _records(test_session_factory)[-1]
    replayed = decide_policy(policy_input_from_dict(record.record["policy_input"]))
    assert replayed.as_dict() == record.record["decision"]
    assert record.record["policy_input"]["support"]["origin"] == "test_double"
    # Nada do registo detalhado chega ao cliente.
    assert "policy_input" not in str(body)
    assert "admissible_evidence" not in str(body)
    assert record.record["versions"]["catalog_version"] == 1
    # Utilização registada por componente; o custo monetário não é inventado.
    assert record.record["usage"]["generator"]["attempts"] == 1
    assert record.record["usage"]["generator"]["cost"] is None
    assert record.record["usage"]["estimator"]["attempts"] >= 1
    # O registo não guarda conteúdo documental.
    assert "30 de setembro" not in str(record.record)


def test_catalog_is_versioned_and_managed_only_by_the_institutional_admin(
    client: TestClient,
) -> None:
    world = make_world(client)
    second = client.put(
        "/api/v1/decision/catalog",
        json={
            "scope_description": "Atendimento académico sintético, versão revista.",
            "topics": [{"code": "enrolment", "label": "Matrículas"}],
            "services": [],
        },
        headers=world.admin,
    )
    versions = client.get("/api/v1/decision/catalog/versions", headers=world.admin).json()

    assert second.status_code == 201
    assert [(item["version"], item["is_active"]) for item in versions["items"]] == [
        (2, True),
        (1, False),
    ]
    for headers in (world.manager, world.student):
        assert client.get("/api/v1/decision/catalog", headers=headers).status_code == 403


def test_catalog_rejects_a_topic_with_two_services_and_services_without_contact(
    client: TestClient,
) -> None:
    world = make_world(client)
    base = {
        "scope_description": "Atendimento académico sintético para validação.",
        "topics": [{"code": "enrolment", "label": "Matrículas"}],
    }
    two_owners = client.put(
        "/api/v1/decision/catalog",
        json={
            **base,
            "services": [
                {"service_id": "a", "name": "A", "email": "a@example.org", "topics": ["enrolment"]},
                {"service_id": "b", "name": "B", "email": "b@example.org", "topics": ["enrolment"]},
            ],
        },
        headers=world.admin,
    )
    no_contact = client.put(
        "/api/v1/decision/catalog",
        json={**base, "services": [{"service_id": "a", "name": "A", "topics": ["enrolment"]}]},
        headers=world.admin,
    )

    assert two_owners.status_code == 422
    assert no_contact.status_code == 422


# --- Revogação concorrente e locks -------------------------------------------------------------


@pytest.mark.parametrize(
    ("sql", "status"),
    [
        ("UPDATE users SET is_active = false WHERE id = :id", 401),
        ("UPDATE users SET role = 'user' WHERE id = :id", 409),
    ],
    ids=["deactivated", "role-changed"],
)
def test_revocation_during_estimation_persists_nothing(
    client: TestClient,
    policy_enabled,
    install,
    test_session_factory,
    sql: str,
    status: int,
) -> None:
    """A estimação corre sem locks; a persistência relê conta e papel sob lock.

    As evidências admissíveis foram recolhidas para o papel inicial, por isso
    uma alteração de papel invalida o turno em vez de o gravar.
    """
    world = make_world(client)
    world.document(client, "Regulamento de matrículas", ENROLMENT)
    supported = support_by_title({"I1": "matrículas"})

    def revoke_then_assess(request):  # type: ignore[no-untyped-def]
        # Corre noutra sessão, com lock_timeout curto: um lock retido pelo
        # pedido durante a estimação faria este UPDATE falhar.
        with test_session_factory() as db:
            db.execute(text("SET LOCAL lock_timeout = '500ms'"))
            db.execute(text(sql), {"id": world.student_id})
            db.commit()
        return supported(request)

    install(ScriptedEstimator(result=analysis(), assess_with=revoke_then_assess))

    response = decide(client, world.conversation(client), world.student)

    assert response.status_code == status
    assert _count(test_session_factory, Message) == 0
    assert _count(test_session_factory, MessageSource) == 0
