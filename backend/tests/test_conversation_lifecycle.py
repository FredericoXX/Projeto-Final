"""Título automático, renomeação e ordenação por atividade das conversas.

O retriever é o lexical real sobre PostgreSQL; o AnswerGenerator é
substituído por dependency override — sem rede e sem credenciais.
"""

import threading
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.answering.base import AnswerGeneratorUnavailableError
from app.core.conversation_title import MAX_TITLE_LENGTH
from app.models.conversation import Conversation
from app.models.document import Document
from app.models.message import Message
from tests.test_conversation_answering import (
    FakeAnswerGenerator,
    _ask,
    _create_admin,
    _create_conversation,
    _create_institution,
    _create_searchable_document,
    _create_user,
    _row_counts,
    override_generator,  # noqa: F401 - fixture reexportada para este módulo
)

NATURAL_QUESTION = "Quando começam as aulas?"
EXPECTED_TITLE = "Quando começam as aulas"
CLASSES_CONTENT = "As aulas do primeiro semestre iniciam-se em 21 de setembro de 2026."


def _create_untitled_conversation(client: TestClient, headers: dict[str, str]) -> dict:
    """Conversa criada como o frontend passa a fazer: payload vazio, sem
    título — o título automático só se aplica a conversas sem título."""
    response = client.post("/api/v1/conversations", json={}, headers=headers)
    assert response.status_code == 201
    assert response.json()["title"] is None
    return response.json()


def _setup_with_document(
    client: TestClient,
) -> tuple[dict, dict[str, str], str, dict]:
    institution = _create_institution(client)
    headers, admin_id = _create_admin(client, institution["id"])
    _create_searchable_document(
        client,
        headers,
        CLASSES_CONTENT,
        title="Calendário Letivo",
        source_url="https://example.edu/calendario",
    )
    conversation = _create_untitled_conversation(client, headers)
    return institution, headers, admin_id, conversation


def _get_conversation(client: TestClient, conversation_id: str, headers: dict) -> dict:
    response = client.get(f"/api/v1/conversations/{conversation_id}", headers=headers)
    assert response.status_code == 200
    return response.json()


def _rename(client: TestClient, conversation_id: str, headers: dict, **payload: object):
    return client.patch(
        f"/api/v1/conversations/{conversation_id}", json=payload, headers=headers
    )


def _listing_ids(client: TestClient, headers: dict) -> list[str]:
    response = client.get("/api/v1/conversations", headers=headers)
    assert response.status_code == 200
    return [item["id"] for item in response.json()["items"]]


# --- Título automático -----------------------------------------------------------


def test_first_answered_turn_sets_title_and_preserves_query(
    client: TestClient, override_generator  # noqa: F811 - fixture
) -> None:
    _, headers, _, conversation = _setup_with_document(client)
    override_generator(FakeAnswerGenerator())

    response = _ask(client, conversation["id"], headers, query=NATURAL_QUESTION)
    assert response.status_code == 201
    assert response.json()["status"] == "answered"

    stored = _get_conversation(client, conversation["id"], headers)
    assert stored["title"] == EXPECTED_TITLE
    # A pergunta original (com pontuação) permanece na mensagem.
    assert response.json()["user_message"]["content"] == NATURAL_QUESTION
    # As fontes continuam persistidas normalmente.
    assert len(response.json()["assistant_message"]["sources"]) == 1


def test_first_insufficient_evidence_turn_also_sets_title(
    client: TestClient, override_generator  # noqa: F811 - fixture
) -> None:
    _, headers, _, conversation = _setup_with_document(client)
    generator = override_generator(FakeAnswerGenerator())

    response = _ask(
        client, conversation["id"], headers, query="Qual é o preço do estacionamento?"
    )
    assert response.status_code == 201
    assert response.json()["status"] == "insufficient_evidence"
    assert generator.calls == []

    stored = _get_conversation(client, conversation["id"], headers)
    assert stored["title"] == "Qual é o preço do estacionamento"


def test_manual_title_from_creation_is_preserved(
    client: TestClient, override_generator  # noqa: F811 - fixture
) -> None:
    _, headers, _, _ = _setup_with_document(client)
    override_generator(FakeAnswerGenerator())
    response = client.post(
        "/api/v1/conversations",
        json={"title": "Título manual", "language": "pt"},
        headers=headers,
    )
    conversation_id = response.json()["id"]

    assert _ask(client, conversation_id, headers, query=NATURAL_QUESTION).status_code == 201
    assert _get_conversation(client, conversation_id, headers)["title"] == "Título manual"


def test_second_question_never_changes_title(
    client: TestClient, override_generator  # noqa: F811 - fixture
) -> None:
    _, headers, _, conversation = _setup_with_document(client)
    override_generator(FakeAnswerGenerator())

    assert _ask(client, conversation["id"], headers, query=NATURAL_QUESTION).status_code == 201
    assert (
        _ask(client, conversation["id"], headers, query="Qual é o período dos exames?")
        .status_code
        == 201
    )

    assert _get_conversation(client, conversation["id"], headers)["title"] == EXPECTED_TITLE


def test_conversation_with_messages_and_null_title_is_not_retitled(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
    override_generator,  # noqa: F811 - fixture
) -> None:
    """O primeiro turno é decidido pela existência de mensagens, não por
    title is null: um cliente antigo que limpe o título não reativa a
    titulação automática."""
    _, headers, _, conversation = _setup_with_document(client)
    override_generator(FakeAnswerGenerator())
    assert _ask(client, conversation["id"], headers, query=NATURAL_QUESTION).status_code == 201

    with test_session_factory() as db:
        stored = db.get(Conversation, uuid.UUID(conversation["id"]))
        assert stored is not None
        stored.title = None
        db.commit()

    assert (
        _ask(client, conversation["id"], headers, query="Outra pergunta sobre aulas?")
        .status_code
        == 201
    )
    assert _get_conversation(client, conversation["id"], headers)["title"] is None


def test_provider_502_failure_sets_no_title_and_no_messages(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
    override_generator,  # noqa: F811 - fixture
) -> None:
    from app.answering.base import AnswerGenerationError

    _, headers, _, conversation = _setup_with_document(client)
    override_generator(
        FakeAnswerGenerator(exception=AnswerGenerationError("provider failed"))
    )

    response = _ask(client, conversation["id"], headers, query=NATURAL_QUESTION)
    assert response.status_code == 502
    assert _get_conversation(client, conversation["id"], headers)["title"] is None
    assert _row_counts(test_session_factory) == (0, 0)


def test_provider_503_unavailable_sets_no_title(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
    override_generator,  # noqa: F811 - fixture
) -> None:
    _, headers, _, conversation = _setup_with_document(client)
    override_generator(
        FakeAnswerGenerator(exception=AnswerGeneratorUnavailableError("not configured"))
    )

    response = _ask(client, conversation["id"], headers, query=NATURAL_QUESTION)
    assert response.status_code == 503
    assert _get_conversation(client, conversation["id"], headers)["title"] is None
    assert _row_counts(test_session_factory) == (0, 0)


def test_revalidation_failure_sets_no_title(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
    override_generator,  # noqa: F811 - fixture
) -> None:
    """O documento muda durante a geração: a revalidação falha (409) e nem
    título nem mensagens são persistidos."""
    _, headers, _, conversation = _setup_with_document(client)

    def change_document_mid_generation(_context: object) -> None:
        with test_session_factory() as db:
            document = db.scalar(
                select(Document).where(Document.title == "Calendário Letivo")
            )
            assert document is not None
            document.title = "Calendário Letivo (alterado)"
            db.commit()

    override_generator(FakeAnswerGenerator(callback=change_document_mid_generation))

    response = _ask(client, conversation["id"], headers, query=NATURAL_QUESTION)
    assert response.status_code == 409
    assert _get_conversation(client, conversation["id"], headers)["title"] is None
    assert _row_counts(test_session_factory) == (0, 0)


def test_closed_conversation_gets_no_title(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
    override_generator,  # noqa: F811 - fixture
) -> None:
    _, headers, _, conversation = _setup_with_document(client)
    override_generator(FakeAnswerGenerator())
    assert (
        _rename(client, conversation["id"], headers, status="closed").status_code == 200
    )

    response = _ask(client, conversation["id"], headers, query=NATURAL_QUESTION)
    assert response.status_code == 409
    assert _get_conversation(client, conversation["id"], headers)["title"] is None
    assert _row_counts(test_session_factory) == (0, 0)


def test_generated_title_respects_length_limit(
    client: TestClient, override_generator  # noqa: F811 - fixture
) -> None:
    _, headers, _, conversation = _setup_with_document(client)
    override_generator(FakeAnswerGenerator())

    long_question = ("Quando começam as aulas do curso de engenharia informática " * 20)[:1000]
    assert _ask(client, conversation["id"], headers, query=long_question).status_code == 201

    title = _get_conversation(client, conversation["id"], headers)["title"]
    assert title is not None
    assert len(title) <= MAX_TITLE_LENGTH
    assert title.endswith("…")


def test_updated_at_changes_on_success_and_not_on_failure(
    client: TestClient, override_generator  # noqa: F811 - fixture
) -> None:
    from app.answering.base import AnswerGenerationError

    _, headers, _, conversation = _setup_with_document(client)
    generator = override_generator(FakeAnswerGenerator())
    before = _get_conversation(client, conversation["id"], headers)["updated_at"]

    assert _ask(client, conversation["id"], headers, query=NATURAL_QUESTION).status_code == 201
    after_success = _get_conversation(client, conversation["id"], headers)["updated_at"]
    assert after_success > before

    # A pergunta de falha tem de encontrar evidência: só assim o gerador
    # (que lança o erro) chega a ser chamado.
    generator.exception = AnswerGenerationError("provider failed")
    assert (
        _ask(client, conversation["id"], headers, query="Quando começam as aulas de 2026?")
        .status_code
        == 502
    )
    after_failure = _get_conversation(client, conversation["id"], headers)["updated_at"]
    assert after_failure == after_success


def test_concurrent_first_questions_stay_consistent(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
    override_generator,  # noqa: F811 - fixture
) -> None:
    """Duas primeiras perguntas em simultâneo: o lock da conversa serializa
    os turnos; o título fica derivado da pergunta que ganhou a corrida e
    nunca é substituído pela segunda."""
    _, headers, _, conversation = _setup_with_document(client)
    override_generator(FakeAnswerGenerator())

    first_question = "Quando começam as aulas?"
    second_question = "Qual é o período dos exames?"
    barrier = threading.Barrier(2)
    statuses: list[int] = []
    lock = threading.Lock()

    def worker(question: str) -> None:
        barrier.wait()
        response = _ask(client, conversation["id"], headers, query=question)
        with lock:
            statuses.append(response.status_code)

    threads = [
        threading.Thread(target=worker, args=(question,))
        for question in (first_question, second_question)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
        assert not thread.is_alive()

    assert statuses == [201, 201]
    stored = _get_conversation(client, conversation["id"], headers)
    assert stored["title"] in {"Quando começam as aulas", "Qual é o período dos exames"}
    with test_session_factory() as db:
        message_count = len(
            db.scalars(
                select(Message).where(
                    Message.conversation_id == uuid.UUID(conversation["id"])
                )
            ).all()
        )
    assert message_count == 4


# --- Renomeação -------------------------------------------------------------------


def test_owner_renames_active_conversation_with_trim(client: TestClient) -> None:
    institution = _create_institution(client)
    admin_headers, _ = _create_admin(client, institution["id"])
    user_headers, _ = _create_user(client, admin_headers)
    conversation = _create_conversation(client, user_headers)

    response = _rename(client, conversation["id"], user_headers, title="  Novo nome  ")
    assert response.status_code == 200
    assert response.json()["title"] == "Novo nome"


def test_admin_renames_conversation_of_own_institution(client: TestClient) -> None:
    institution = _create_institution(client)
    admin_headers, _ = _create_admin(client, institution["id"])
    user_headers, _ = _create_user(client, admin_headers)
    conversation = _create_conversation(client, user_headers)

    response = _rename(client, conversation["id"], admin_headers, title="Renomeada pelo admin")
    assert response.status_code == 200
    assert response.json()["title"] == "Renomeada pelo admin"


def test_regular_user_cannot_rename_another_users_conversation(client: TestClient) -> None:
    institution = _create_institution(client)
    admin_headers, _ = _create_admin(client, institution["id"])
    owner_headers, _ = _create_user(client, admin_headers)
    other_headers, _ = _create_user(client, admin_headers)
    conversation = _create_conversation(client, owner_headers)

    response = _rename(client, conversation["id"], other_headers, title="Intruso")
    assert response.status_code == 404


def test_other_institution_gets_404_on_rename(client: TestClient) -> None:
    institution_a = _create_institution(client)
    headers_a, _ = _create_admin(client, institution_a["id"])
    conversation = _create_conversation(client, headers_a)

    institution_b = _create_institution(client)
    headers_b, _ = _create_admin(client, institution_b["id"])

    assert _rename(client, conversation["id"], headers_b, title="Cruzado").status_code == 404


@pytest.mark.parametrize(
    "payload",
    [
        {"title": "   "},
        {"title": "x" * 256},
        {"unknown_field": "x"},
        {"institution_id": str(uuid.uuid4())},
        {"user_id": str(uuid.uuid4())},
    ],
)
def test_invalid_rename_payloads_return_422(client: TestClient, payload: dict) -> None:
    institution = _create_institution(client)
    headers, _ = _create_admin(client, institution["id"])
    conversation = _create_conversation(client, headers)

    response = client.patch(
        f"/api/v1/conversations/{conversation['id']}", json=payload, headers=headers
    )
    assert response.status_code == 422


@pytest.mark.parametrize("final_status", ["closed", "archived"])
def test_final_states_accept_title_only_but_reject_status_changes(
    client: TestClient, final_status: str
) -> None:
    institution = _create_institution(client)
    headers, _ = _create_admin(client, institution["id"])
    conversation = _create_conversation(client, headers)
    assert _rename(client, conversation["id"], headers, status=final_status).status_code == 200

    # title-only: permitido, sem reabrir.
    renamed = _rename(client, conversation["id"], headers, title="Nome final")
    assert renamed.status_code == 200
    assert renamed.json()["title"] == "Nome final"
    assert renamed.json()["status"] == final_status

    # status (mesmo de volta a active): 409.
    assert _rename(client, conversation["id"], headers, status="active").status_code == 409

    # title + status: 409 e o título NÃO muda.
    combined = _rename(
        client, conversation["id"], headers, title="Não deve ficar", status="active"
    )
    assert combined.status_code == 409
    assert _get_conversation(client, conversation["id"], headers)["title"] == "Nome final"


# --- Ordenação por atividade recente ------------------------------------------------


def test_listing_orders_by_recent_activity_with_id_tiebreak(
    client: TestClient, override_generator  # noqa: F811 - fixture
) -> None:
    _, headers, _, first = _setup_with_document(client)
    override_generator(FakeAnswerGenerator())
    second = _create_conversation(client, headers)
    third = _create_conversation(client, headers)

    # Sem turnos, a ordem é por updated_at (criação) desc; um turno na
    # primeira conversa move-a para o topo.
    assert _ask(client, first["id"], headers, query=NATURAL_QUESTION).status_code == 201

    listing = client.get("/api/v1/conversations", headers=headers).json()
    ids = [item["id"] for item in listing["items"]]
    assert ids[0] == first["id"]
    assert set(ids) == {first["id"], second["id"], third["id"]}

    # Turno posterior noutra conversa volta a reordenar.
    later = _ask(client, second["id"], headers, query="Qual é o período dos exames?")
    assert later.status_code == 201
    ids = _listing_ids(client, headers)
    assert ids[0] == second["id"]
    assert ids[1] == first["id"]


def test_failed_turn_does_not_change_listing_order(
    client: TestClient, override_generator  # noqa: F811 - fixture
) -> None:
    from app.answering.base import AnswerGenerationError

    _, headers, _, first = _setup_with_document(client)
    generator = override_generator(FakeAnswerGenerator())
    second = _create_conversation(client, headers)
    assert _ask(client, first["id"], headers, query=NATURAL_QUESTION).status_code == 201
    ids_before = _listing_ids(client, headers)
    assert ids_before[0] == first["id"]

    # Pergunta com evidência + gerador a falhar: o turno falha (502) e a
    # posição da conversa não muda.
    generator.exception = AnswerGenerationError("provider failed")
    assert (
        _ask(client, second["id"], headers, query="Quando começam as aulas de 2026?")
        .status_code
        == 502
    )

    ids_after = _listing_ids(client, headers)
    assert ids_after == ids_before


def test_rename_moves_conversation_in_listing(client: TestClient) -> None:
    institution = _create_institution(client)
    headers, _ = _create_admin(client, institution["id"])
    first = _create_conversation(client, headers)
    second = _create_conversation(client, headers)

    ids = _listing_ids(client, headers)
    assert ids[0] == second["id"]

    assert _rename(client, first["id"], headers, title="Renomeada").status_code == 200
    ids = _listing_ids(client, headers)
    assert ids[0] == first["id"]


def test_listing_pagination_and_isolation_remain_correct(client: TestClient) -> None:
    institution = _create_institution(client)
    admin_headers, _ = _create_admin(client, institution["id"])
    user_headers, _ = _create_user(client, admin_headers)
    for _ in range(3):
        _create_conversation(client, user_headers)
    _create_conversation(client, admin_headers)

    # Utilizador comum vê apenas as suas; paginação correta.
    page = client.get("/api/v1/conversations?limit=2&offset=0", headers=user_headers).json()
    assert page["total"] == 3
    assert len(page["items"]) == 2
    rest = client.get("/api/v1/conversations?limit=2&offset=2", headers=user_headers).json()
    assert len(rest["items"]) == 1

    # Outra instituição nunca influencia a lista.
    institution_b = _create_institution(client)
    headers_b, _ = _create_admin(client, institution_b["id"])
    _create_conversation(client, headers_b)
    assert client.get("/api/v1/conversations", headers=admin_headers).json()["total"] == 4
