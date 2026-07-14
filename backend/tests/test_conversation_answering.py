"""Integração do answering persistido em conversas.

O retriever é sempre o lexical real sobre PostgreSQL e documentos realmente
processados. Só o ``AnswerGenerator`` é substituído, garantindo que a suíte
não depende de credenciais nem faz chamadas de rede.
"""

import hashlib
import io
import uuid
from collections.abc import Callable, Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.answering.base import (
    AnswerGenerationError,
    AnswerGenerator,
    AnswerGeneratorUnavailableError,
    AnsweringContext,
    GeneratedAnswer,
)
from app.answering.dependencies import get_answer_generator
from app.core.config import settings
from app.core.text_normalization import normalize_text
from app.main import app
from app.models.conversation import Conversation
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.document_version import DocumentVersion
from app.models.message import Message
from app.models.message_source import MessageSource
from app.models.user import User
from app.services import conversation_answering_service

BOOTSTRAP_HEADERS = {"X-Bootstrap-Token": settings.bootstrap_token or ""}
_ADMIN_PASSWORD = "supersecret123"
_USER_PASSWORD = "anothersecret123"


class FakeAnswerGenerator:
    """Gerador determinístico e inspecionável, sem SDK nem rede."""

    def __init__(
        self,
        result: GeneratedAnswer | None = None,
        exception: Exception | None = None,
        callback: Callable[[AnsweringContext], None] | None = None,
    ) -> None:
        self.result = result
        self.exception = exception
        self.callback = callback
        self.calls: list[AnsweringContext] = []

    def generate(self, context: AnsweringContext) -> GeneratedAnswer:
        self.calls.append(context)
        if self.callback is not None:
            self.callback(context)
        if self.exception is not None:
            raise self.exception
        if self.result is not None:
            return self.result
        return GeneratedAnswer(
            answer="Resposta fundamentada na documentação institucional.",
            cited_evidence_ids=(context.evidence[0].evidence_id,),
        )


@pytest.fixture
def override_generator() -> Iterator[Callable[[AnswerGenerator], AnswerGenerator]]:
    """Instala um gerador por dependency override e remove-o no fim."""

    def _install(generator: AnswerGenerator) -> AnswerGenerator:
        app.dependency_overrides[get_answer_generator] = lambda: generator
        return generator

    yield _install
    app.dependency_overrides.pop(get_answer_generator, None)


def _create_institution(client: TestClient, *, name: str = "Conversation Institution") -> dict:
    response = client.post(
        "/api/v1/institutions",
        json={
            "name": name,
            "code": f"CNV-{uuid.uuid4().hex[:8].upper()}",
            "default_language": "pt",
            "supported_languages": ["pt", "en"],
        },
        headers=BOOTSTRAP_HEADERS,
    )
    assert response.status_code == 201
    return response.json()


def _create_admin(client: TestClient, institution_id: str) -> tuple[dict[str, str], str]:
    email = f"admin-{uuid.uuid4().hex[:8]}@example.com"
    response = client.post(
        "/api/v1/auth/register-initial-admin",
        json={
            "institution_id": institution_id,
            "full_name": "Admin Conversation",
            "email": email,
            "password": _ADMIN_PASSWORD,
        },
        headers=BOOTSTRAP_HEADERS,
    )
    assert response.status_code == 201
    login = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": _ADMIN_PASSWORD},
    )
    assert login.status_code == 200
    return (
        {"Authorization": f"Bearer {login.json()['access_token']}"},
        response.json()["id"],
    )


def _create_user(
    client: TestClient,
    admin_headers: dict[str, str],
    *,
    role: str = "student",
) -> tuple[dict[str, str], str]:
    email = f"user-{uuid.uuid4().hex[:8]}@example.com"
    response = client.post(
        "/api/v1/users",
        json={
            "full_name": "Conversation User",
            "email": email,
            "password": _USER_PASSWORD,
            "role": role,
        },
        headers=admin_headers,
    )
    assert response.status_code == 201
    login = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": _USER_PASSWORD},
    )
    assert login.status_code == 200
    return (
        {"Authorization": f"Bearer {login.json()['access_token']}"},
        response.json()["id"],
    )


def _create_conversation(
    client: TestClient,
    headers: dict[str, str],
    *,
    language: str = "pt",
) -> dict:
    response = client.post(
        "/api/v1/conversations",
        json={"title": "Perguntas institucionais", "language": language},
        headers=headers,
    )
    assert response.status_code == 201
    return response.json()


def _create_searchable_document(
    client: TestClient,
    headers: dict[str, str],
    content: str,
    *,
    title: str,
    source_url: str,
    language: str = "pt",
) -> tuple[dict, dict]:
    document = client.post(
        "/api/v1/documents",
        json={
            "title": title,
            "language": language,
            "official_source": True,
            "source_url": source_url,
        },
        headers=headers,
    )
    assert document.status_code == 201
    version = client.post(
        f"/api/v1/documents/{document.json()['id']}/versions",
        files={
            "file": (
                f"{uuid.uuid4().hex}.txt",
                io.BytesIO(content.encode("utf-8")),
                "text/plain",
            )
        },
        headers=headers,
    )
    assert version.status_code == 201
    assert version.json()["processing_status"] == "processed"
    return document.json(), version.json()


def _ask(
    client: TestClient,
    conversation_id: str,
    headers: dict[str, str],
    **overrides: object,
):
    payload: dict = {"query": "matricula prazo"}
    payload.update(overrides)
    return client.post(
        f"/api/v1/conversations/{conversation_id}/ask",
        json=payload,
        headers=headers,
    )


def _row_counts(
    test_session_factory: sessionmaker[Session],
) -> tuple[int, int]:
    with test_session_factory() as db:
        message_count = db.scalar(select(func.count()).select_from(Message)) or 0
        source_count = db.scalar(select(func.count()).select_from(MessageSource)) or 0
    return message_count, source_count


def _setup_admin_conversation(
    client: TestClient,
    *,
    language: str = "pt",
) -> tuple[dict, dict[str, str], str, dict]:
    institution = _create_institution(client)
    headers, admin_id = _create_admin(client, institution["id"])
    conversation = _create_conversation(client, headers, language=language)
    return institution, headers, admin_id, conversation


def test_answered_turn_persists_messages_citations_snapshots_and_history(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
    override_generator,
) -> None:
    institution = _create_institution(client)
    admin_headers, _ = _create_admin(client, institution["id"])
    user_headers, user_id = _create_user(client, admin_headers)
    conversation = _create_conversation(client, user_headers)

    for index in range(3):
        _create_searchable_document(
            client,
            admin_headers,
            f"matricula prazo regulamento institucional documento {index}",
            title=f"Regulamento {index}",
            source_url=f"https://example.edu/regulamento-{index}",
        )

    generator = override_generator(
        FakeAnswerGenerator(
            GeneratedAnswer(
                answer="A matrícula segue os prazos dos regulamentos citados.",
                cited_evidence_ids=("E2", "E1"),
            )
        )
    )
    response = _ask(
        client,
        conversation["id"],
        user_headers,
        top_k=3,
        official_only=True,
    )
    assert response.status_code == 201

    body = response.json()
    assert body["status"] == "answered"
    assert body["conversation_id"] == conversation["id"]
    user_message = body["user_message"]
    assistant_message = body["assistant_message"]
    assert user_message["role"] == "user"
    assert user_message["content"] == "matricula prazo"
    assert user_message["user_id"] == user_id
    assert user_message["reply_to_message_id"] is None
    assert user_message["sources"] == []
    assert user_message["extra_metadata"] == {"turn_type": "institutional_question"}
    assert assistant_message["role"] == "assistant"
    assert assistant_message["user_id"] is None
    assert assistant_message["reply_to_message_id"] == user_message["id"]
    assert assistant_message["extra_metadata"] == {"answer_status": "answered"}
    assert [source["evidence_id"] for source in assistant_message["sources"]] == [
        "E2",
        "E1",
    ]
    assert "content_sha256" not in response.text
    assert len(generator.calls) == 1
    assert len(generator.calls[0].evidence) == 3

    evidence_by_id = {item.evidence_id: item.evidence for item in generator.calls[0].evidence}
    for source, evidence_id in zip(assistant_message["sources"], ("E2", "E1"), strict=True):
        evidence = evidence_by_id[evidence_id]
        assert source["document_id"] == str(evidence.document_id)
        assert source["chunk_id"] == str(evidence.chunk_id)
        assert source["document_version_id"] == str(evidence.document_version_id)
        assert source["document_title"] == evidence.document_title
        assert source["source_url"] == evidence.source_url

    with test_session_factory() as db:
        stored_messages = list(
            db.scalars(
                select(Message).where(Message.conversation_id == uuid.UUID(conversation["id"]))
            ).all()
        )
        stored_sources = list(
            db.scalars(
                select(MessageSource)
                .where(MessageSource.message_id == uuid.UUID(assistant_message["id"]))
                .order_by(MessageSource.citation_index)
            ).all()
        )
        assert len(stored_messages) == 2
        assert [source.citation_index for source in stored_sources] == [0, 1]
        assert [source.evidence_id for source in stored_sources] == ["E2", "E1"]
        for source in stored_sources:
            chunk = db.get(DocumentChunk, source.chunk_id)
            assert chunk is not None
            expected_hash = hashlib.sha256(chunk.content.encode("utf-8")).hexdigest()
            assert source.content_sha256 == chunk.content_sha256 == expected_hash

        original_sources = [dict(source) for source in assistant_message["sources"]]
        for index, source in enumerate(original_sources):
            document = db.get(Document, uuid.UUID(source["document_id"]))
            assert document is not None
            document.title = f"Título alterado {index}"
            document.source_url = f"https://changed.example/{index}"
            document.official_source = False
        db.commit()

    owner_history = client.get(
        f"/api/v1/conversations/{conversation['id']}/messages",
        headers=user_headers,
    )
    admin_history = client.get(
        f"/api/v1/conversations/{conversation['id']}/messages",
        headers=admin_headers,
    )
    assert owner_history.status_code == admin_history.status_code == 200
    assert owner_history.json() == admin_history.json()
    assert owner_history.json()["total"] == 2
    assert [item["role"] for item in owner_history.json()["items"]] == [
        "user",
        "assistant",
    ]
    assert owner_history.json()["items"][1]["sources"] == original_sources

    first_page = client.get(
        f"/api/v1/conversations/{conversation['id']}/messages?limit=1&offset=0",
        headers=user_headers,
    ).json()
    second_page = client.get(
        f"/api/v1/conversations/{conversation['id']}/messages?limit=1&offset=1",
        headers=user_headers,
    ).json()
    assert first_page["total"] == second_page["total"] == 2
    assert [first_page["items"][0]["role"], second_page["items"][0]["role"]] == [
        "user",
        "assistant",
    ]


@pytest.mark.parametrize(
    ("language", "expected_answer"),
    [
        (
            "pt",
            "Não encontrei informação institucional suficiente para responder com segurança.",
        ),
        (
            "en",
            "I could not find sufficient institutional information to answer safely.",
        ),
    ],
)
def test_insufficient_evidence_persists_two_messages_without_sources_or_provider_call(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
    override_generator,
    language: str,
    expected_answer: str,
) -> None:
    _, headers, user_id, conversation = _setup_admin_conversation(client, language=language)
    generator = override_generator(
        FakeAnswerGenerator(exception=AssertionError("provider must not be called"))
    )

    response = _ask(
        client,
        conversation["id"],
        headers,
        query="transporte interplanetario inexistente",
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "insufficient_evidence"
    assert body["user_message"]["language"] == language
    assert body["assistant_message"]["language"] == language
    assert body["assistant_message"]["content"] == expected_answer
    assert body["assistant_message"]["reply_to_message_id"] == body["user_message"]["id"]
    assert body["user_message"]["user_id"] == user_id
    assert body["user_message"]["sources"] == []
    assert body["assistant_message"]["sources"] == []
    assert generator.calls == []
    assert _row_counts(test_session_factory) == (2, 0)


def test_ask_requires_authentication_and_rejects_invalid_payloads_without_writes(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
    override_generator,
) -> None:
    _, headers, _, conversation = _setup_admin_conversation(client)
    generator = override_generator(FakeAnswerGenerator())

    assert _ask(client, conversation["id"], {}).status_code == 401
    assert (
        _ask(
            client,
            conversation["id"],
            {"Authorization": "Bearer invalid"},
        ).status_code
        == 401
    )

    invalid_payloads = [
        {},
        {"query": ""},
        {"query": "   "},
        {"query": "x" * 1001},
        {"query": "matricula", "top_k": 0},
        {"query": "matricula", "top_k": 101},
        {"query": "matricula", "language": "fr"},
        {"query": "matricula", "institution_id": str(uuid.uuid4())},
        {"query": "matricula", "user_id": str(uuid.uuid4())},
        {"query": "matricula", "conversation_id": str(uuid.uuid4())},
        {"query": "matricula", "unknown": True},
    ]
    for payload in invalid_payloads:
        response = client.post(
            f"/api/v1/conversations/{conversation['id']}/ask",
            json=payload,
            headers=headers,
        )
        assert response.status_code == 422, payload

    assert generator.calls == []
    assert _row_counts(test_session_factory) == (0, 0)


@pytest.mark.parametrize("conversation_status", ["closed", "archived"])
def test_closed_or_archived_conversation_rejects_ask_before_retrieval(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
    override_generator,
    conversation_status: str,
) -> None:
    _, headers, _, conversation = _setup_admin_conversation(client)
    changed = client.patch(
        f"/api/v1/conversations/{conversation['id']}",
        json={"status": conversation_status},
        headers=headers,
    )
    assert changed.status_code == 200
    generator = override_generator(FakeAnswerGenerator())

    response = _ask(client, conversation["id"], headers)
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "resource_conflict"
    assert generator.calls == []
    assert _row_counts(test_session_factory) == (0, 0)


def test_access_rules_and_retrieval_are_isolated_for_user_admin_and_tenant(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
    override_generator,
) -> None:
    institution_a = _create_institution(client, name="Institution A")
    admin_a, admin_a_id = _create_admin(client, institution_a["id"])
    owner_a, owner_a_id = _create_user(client, admin_a)
    stranger_a, _ = _create_user(client, admin_a)
    conversation_a = _create_conversation(client, owner_a)
    document_a, _ = _create_searchable_document(
        client,
        admin_a,
        "isolamento comum matricula prazo alfa",
        title="Fonte A",
        source_url="https://a.example.edu/fonte",
    )

    institution_b = _create_institution(client, name="Institution B")
    admin_b, _ = _create_admin(client, institution_b["id"])
    document_b, _ = _create_searchable_document(
        client,
        admin_b,
        "isolamento comum matricula prazo beta",
        title="Fonte B",
        source_url="https://b.example.edu/fonte",
    )
    generator = override_generator(FakeAnswerGenerator())

    same_tenant_denied = _ask(client, conversation_a["id"], stranger_a)
    other_tenant_denied = _ask(client, conversation_a["id"], admin_b)
    assert same_tenant_denied.status_code == other_tenant_denied.status_code == 404
    assert generator.calls == []

    owner_response = _ask(client, conversation_a["id"], owner_a)
    admin_response = _ask(client, conversation_a["id"], admin_a)
    assert owner_response.status_code == admin_response.status_code == 201
    assert owner_response.json()["user_message"]["user_id"] == owner_a_id
    assert admin_response.json()["user_message"]["user_id"] == admin_a_id
    for response in (owner_response, admin_response):
        source = response.json()["assistant_message"]["sources"][0]
        assert source["document_id"] == document_a["id"]
        assert document_b["id"] not in response.text
        assert institution_b["id"] not in response.text
    assert len(generator.calls) == 2
    assert all(
        {entry.evidence.document_id for entry in context.evidence} == {uuid.UUID(document_a["id"])}
        for context in generator.calls
    )

    owner_history = client.get(
        f"/api/v1/conversations/{conversation_a['id']}/messages",
        headers=owner_a,
    )
    admin_history = client.get(
        f"/api/v1/conversations/{conversation_a['id']}/messages",
        headers=admin_a,
    )
    assert owner_history.status_code == admin_history.status_code == 200
    assert owner_history.json() == admin_history.json()
    assert [item["role"] for item in owner_history.json()["items"]] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]
    assert _row_counts(test_session_factory) == (4, 2)


@pytest.mark.parametrize(
    ("failure_kind", "expected_status", "expected_code"),
    [
        ("unavailable", 503, "service_unavailable"),
        ("provider", 502, "upstream_error"),
        ("invalid", 502, "upstream_error"),
    ],
)
def test_provider_and_invalid_output_failures_do_not_persist_partial_turns(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
    override_generator,
    failure_kind: str,
    expected_status: int,
    expected_code: str,
) -> None:
    _, headers, _, conversation = _setup_admin_conversation(client)
    _create_searchable_document(
        client,
        headers,
        "matricula prazo institucional",
        title="Regulamento",
        source_url="https://example.edu/regulamento",
    )
    if failure_kind == "unavailable":
        generator = FakeAnswerGenerator(
            exception=AnswerGeneratorUnavailableError("The answer generator is not configured.")
        )
    elif failure_kind == "provider":
        generator = FakeAnswerGenerator(
            exception=AnswerGenerationError(
                "The answer generator failed to produce a usable response."
            )
        )
    else:
        generator = FakeAnswerGenerator(
            result=GeneratedAnswer(
                answer="Resposta com fonte inventada.",
                cited_evidence_ids=("E999",),
            )
        )
    override_generator(generator)

    response = _ask(client, conversation["id"], headers)
    assert response.status_code == expected_status
    assert response.json()["detail"]["code"] == expected_code
    assert "E999" not in response.text
    assert len(generator.calls) == 1
    assert _row_counts(test_session_factory) == (0, 0)


def test_source_changed_during_generation_returns_conflict_without_messages(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
    override_generator,
) -> None:
    _, headers, _, conversation = _setup_admin_conversation(client)
    document, _ = _create_searchable_document(
        client,
        headers,
        "matricula prazo institucional",
        title="Regulamento original",
        source_url="https://example.edu/original",
    )

    def change_source(_: AnsweringContext) -> None:
        with test_session_factory() as db:
            stored = db.get(Document, uuid.UUID(document["id"]))
            assert stored is not None
            stored.title = "Regulamento alterado durante a geração"
            db.commit()

    generator = override_generator(FakeAnswerGenerator(callback=change_source))
    response = _ask(client, conversation["id"], headers)

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "resource_conflict"
    assert len(generator.calls) == 1
    assert _row_counts(test_session_factory) == (0, 0)


def test_chunk_content_changed_during_generation_returns_conflict_without_messages(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
    override_generator,
) -> None:
    _, headers, _, conversation = _setup_admin_conversation(client)
    _create_searchable_document(
        client,
        headers,
        "matricula prazo institucional",
        title="Regulamento",
        source_url="https://example.edu/regulamento",
    )

    def change_chunk_and_extracted_text(context: AnsweringContext) -> None:
        retrieved = context.evidence[0].evidence
        replacement = "matricula prazo adulterado"
        with test_session_factory() as db:
            chunk = db.get(DocumentChunk, retrieved.chunk_id)
            version = db.get(DocumentVersion, retrieved.document_version_id)
            assert chunk is not None
            assert version is not None
            chunk.content = replacement
            chunk.normalized_content = normalize_text(replacement)
            chunk.content_sha256 = hashlib.sha256(replacement.encode()).hexdigest()
            chunk.start_char = 0
            chunk.end_char = len(replacement)
            version.extracted_text = replacement
            db.commit()

    generator = override_generator(
        FakeAnswerGenerator(callback=change_chunk_and_extracted_text)
    )
    response = _ask(client, conversation["id"], headers)

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "resource_conflict"
    assert len(generator.calls) == 1
    assert _row_counts(test_session_factory) == (0, 0)


def test_conversation_closed_during_generation_returns_conflict_without_messages(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
    override_generator,
) -> None:
    _, headers, _, conversation = _setup_admin_conversation(client)
    _create_searchable_document(
        client,
        headers,
        "matricula prazo institucional",
        title="Regulamento",
        source_url="https://example.edu/regulamento",
    )

    def close_conversation(_: AnsweringContext) -> None:
        with test_session_factory() as db:
            stored = db.get(Conversation, uuid.UUID(conversation["id"]))
            assert stored is not None
            stored.status = "closed"
            db.commit()

    generator = override_generator(FakeAnswerGenerator(callback=close_conversation))
    response = _ask(client, conversation["id"], headers)

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "resource_conflict"
    assert len(generator.calls) == 1
    assert _row_counts(test_session_factory) == (0, 0)


def test_user_role_is_reauthorized_after_generation_before_persistence(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
    override_generator,
) -> None:
    institution = _create_institution(client)
    admin_headers, admin_id = _create_admin(client, institution["id"])
    owner_headers, _ = _create_user(client, admin_headers)
    owner_conversation = _create_conversation(client, owner_headers)
    _create_searchable_document(
        client,
        admin_headers,
        "matricula prazo institucional",
        title="Regulamento",
        source_url="https://example.edu/regulamento",
    )

    def remove_admin_access(_: AnsweringContext) -> None:
        with test_session_factory() as db:
            stored = db.get(User, uuid.UUID(admin_id))
            assert stored is not None
            stored.role = "student"
            db.commit()

    generator = override_generator(
        FakeAnswerGenerator(callback=remove_admin_access)
    )
    response = _ask(client, owner_conversation["id"], admin_headers)

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "resource_not_found"
    assert len(generator.calls) == 1
    assert _row_counts(test_session_factory) == (0, 0)


def test_successful_turn_uses_exactly_one_persistence_commit(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
    override_generator,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, headers, _, conversation = _setup_admin_conversation(client)
    _create_searchable_document(
        client,
        headers,
        "matricula prazo institucional",
        title="Regulamento",
        source_url="https://example.edu/regulamento",
    )

    original_commit = Session.commit
    commit_count = 0

    def install_commit_counter(_: AnsweringContext) -> None:
        def count_commit(session: Session) -> None:
            nonlocal commit_count
            commit_count += 1
            original_commit(session)

        monkeypatch.setattr(Session, "commit", count_commit)

    generator = override_generator(
        FakeAnswerGenerator(callback=install_commit_counter)
    )
    response = _ask(client, conversation["id"], headers)

    assert response.status_code == 201
    assert response.json()["status"] == "answered"
    assert commit_count == 1
    assert len(generator.calls) == 1
    assert _row_counts(test_session_factory) == (2, 1)


@pytest.mark.parametrize("failure_stage", ["flush", "source", "commit"])
def test_transaction_rolls_back_everything_on_persistence_failure(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
    override_generator,
    monkeypatch: pytest.MonkeyPatch,
    failure_stage: str,
) -> None:
    _, headers, _, conversation = _setup_admin_conversation(client)
    _create_searchable_document(
        client,
        headers,
        "matricula prazo institucional",
        title="Regulamento",
        source_url="https://example.edu/regulamento",
    )

    callback: Callable[[AnsweringContext], None] | None = None
    original_create_sources = (
        conversation_answering_service.message_source_service.create_message_sources
    )
    if failure_stage == "flush":
        original_flush = Session.flush

        def install_flush_failure(_: AnsweringContext) -> None:
            def fail_with_pending_rows(session: Session, objects: object | None = None) -> None:
                if session.new:
                    monkeypatch.setattr(Session, "flush", original_flush)
                    raise RuntimeError("forced flush failure")
                original_flush(session, objects)  # type: ignore[arg-type]

            monkeypatch.setattr(Session, "flush", fail_with_pending_rows)

        callback = install_flush_failure
    elif failure_stage == "source":

        def fail_sources(*args: object, **kwargs: object) -> None:
            raise RuntimeError("forced source failure")

        monkeypatch.setattr(
            conversation_answering_service.message_source_service,
            "create_message_sources",
            fail_sources,
        )
    else:
        original_commit = Session.commit

        def install_commit_failure(_: AnsweringContext) -> None:
            def fail_commit(session: Session) -> None:
                monkeypatch.setattr(Session, "commit", original_commit)
                raise RuntimeError("forced commit failure")

            monkeypatch.setattr(Session, "commit", fail_commit)

        callback = install_commit_failure

    generator = FakeAnswerGenerator(callback=callback)
    override_generator(generator)
    with pytest.raises(RuntimeError, match=f"forced {failure_stage} failure"):
        _ask(client, conversation["id"], headers)

    assert len(generator.calls) == 1
    assert _row_counts(test_session_factory) == (0, 0)

    # Retry manual: a falha anterior não pode deixar a sessão/turno num
    # estado parcial, nem provocar duplicações no pedido seguinte.
    monkeypatch.setattr(
        conversation_answering_service.message_source_service,
        "create_message_sources",
        original_create_sources,
    )
    generator.callback = None
    retry = _ask(client, conversation["id"], headers)
    assert retry.status_code == 201
    assert retry.json()["status"] == "answered"
    assert len(retry.json()["assistant_message"]["sources"]) == 1
    assert len(generator.calls) == 2
    assert _row_counts(test_session_factory) == (2, 1)
