"""Testes do endpoint POST /api/v1/answering/ask.

O gerador é substituído por dependency override (FakeAnswerGenerator);
o retriever é o real, sobre documentos carregados na base de teste.
Nenhum teste faz chamadas de rede nem exige OPENAI_API_KEY.
"""

import io
import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.answering.base import (
    AnswerGenerationError,
    AnswerGenerator,
    AnsweringContext,
    GeneratedAnswer,
)
from app.answering.dependencies import get_answer_generator
from app.core.config import settings
from app.main import app
from app.models.institution import Institution
from app.models.user import User

BOOTSTRAP_HEADERS = {"X-Bootstrap-Token": settings.bootstrap_token or ""}
_ADMIN_PASSWORD = "supersecret123"
_USER_PASSWORD = "anothersecret123"


class FakeAnswerGenerator:
    def __init__(
        self,
        result: GeneratedAnswer | None = None,
        exception: Exception | None = None,
    ) -> None:
        self.result = result
        self.exception = exception
        self.calls: list[AnsweringContext] = []

    def generate(self, context: AnsweringContext) -> GeneratedAnswer:
        self.calls.append(context)
        if self.exception is not None:
            raise self.exception
        if self.result is not None:
            return self.result
        return GeneratedAnswer(
            answer="O prazo de matrícula decorre em setembro.",
            cited_evidence_ids=(context.evidence[0].evidence_id,),
        )


@pytest.fixture
def override_generator() -> Iterator:
    """Substitui a dependency do gerador durante o teste, com limpeza."""

    def _install(generator: AnswerGenerator) -> AnswerGenerator:
        app.dependency_overrides[get_answer_generator] = lambda: generator
        return generator

    yield _install
    app.dependency_overrides.pop(get_answer_generator, None)


def _create_institution(client: TestClient) -> dict:
    response = client.post(
        "/api/v1/institutions",
        json={
            "name": "Answering Institution",
            "code": f"ASK-{uuid.uuid4().hex[:8].upper()}",
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
            "full_name": "Admin Ask",
            "email": email,
            "password": _ADMIN_PASSWORD,
        },
        headers=BOOTSTRAP_HEADERS,
    )
    assert response.status_code == 201
    login = client.post(
        "/api/v1/auth/login", json={"email": email, "password": _ADMIN_PASSWORD}
    )
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}, response.json()["id"]


def _create_regular_user(client: TestClient, admin_headers: dict[str, str]) -> dict[str, str]:
    email = f"staff-{uuid.uuid4().hex[:8]}@example.com"
    response = client.post(
        "/api/v1/users",
        json={
            "full_name": "Staff Ask",
            "email": email,
            "password": _USER_PASSWORD,
            "role": "staff",
        },
        headers=admin_headers,
    )
    assert response.status_code == 201
    login = client.post(
        "/api/v1/auth/login", json={"email": email, "password": _USER_PASSWORD}
    )
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _create_searchable_document(
    client: TestClient,
    headers: dict[str, str],
    content: str = "O prazo de matrícula decorre entre agosto e setembro.",
    *,
    title: str = "Calendário Académico",
    source_url: str = "https://example.edu/calendario",
) -> dict:
    document = client.post(
        "/api/v1/documents",
        json={
            "title": title,
            "language": "pt",
            "official_source": True,
            "source_url": source_url,
        },
        headers=headers,
    )
    assert document.status_code == 201
    upload = client.post(
        f"/api/v1/documents/{document.json()['id']}/versions",
        files={"file": ("cal.txt", io.BytesIO(content.encode()), "text/plain")},
        headers=headers,
    )
    assert upload.status_code == 201
    assert upload.json()["processing_status"] == "processed"
    return document.json()


def _ask(client: TestClient, headers: dict[str, str], **overrides: object):
    # A baseline lexical usa websearch_to_tsquery (AND entre termos), por
    # isso a pergunta usa apenas termos presentes no documento de teste.
    payload: dict = {"query": "prazo de matrícula"}
    payload.update(overrides)
    return client.post("/api/v1/answering/ask", json=payload, headers=headers)


def _setup(client: TestClient) -> tuple[dict, dict[str, str], str]:
    institution = _create_institution(client)
    headers, admin_id = _create_admin(client, institution["id"])
    return institution, headers, admin_id


# --- Autenticação e estados ------------------------------------------------------


def test_ask_requires_authentication(client: TestClient) -> None:
    assert _ask(client, {}).status_code == 401
    assert _ask(client, {"Authorization": "Bearer invalid"}).status_code == 401


def test_regular_user_and_admin_can_ask(
    client: TestClient, override_generator
) -> None:
    _, admin_headers, _ = _setup(client)
    user_headers = _create_regular_user(client, admin_headers)
    _create_searchable_document(client, admin_headers)
    override_generator(FakeAnswerGenerator())

    assert _ask(client, admin_headers).status_code == 200
    assert _ask(client, user_headers).status_code == 200


def test_inactive_user_and_institution_are_blocked(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
    override_generator,
) -> None:
    institution, headers, admin_id = _setup(client)
    override_generator(FakeAnswerGenerator())

    session = test_session_factory()
    try:
        user = session.get(User, uuid.UUID(admin_id))
        assert user is not None
        user.is_active = False
        session.commit()
    finally:
        session.close()
    assert _ask(client, headers).status_code == 401

    other = _create_institution(client)
    other_headers, _ = _create_admin(client, other["id"])
    session = test_session_factory()
    try:
        stored = session.get(Institution, uuid.UUID(other["id"]))
        assert stored is not None
        stored.is_active = False
        session.commit()
    finally:
        session.close()
    assert _ask(client, other_headers).status_code == 401


# --- Fluxos principais -------------------------------------------------------------


def test_valid_question_returns_answered_with_structured_sources(
    client: TestClient, override_generator
) -> None:
    _, headers, _ = _setup(client)
    document = _create_searchable_document(client, headers)
    override_generator(FakeAnswerGenerator())

    response = _ask(client, headers, language="pt", top_k=5, official_only=True)
    assert response.status_code == 200

    body = response.json()
    assert body["status"] == "answered"
    assert body["query"] == "prazo de matrícula"
    assert body["language"] == "pt"
    assert body["answer"] == "O prazo de matrícula decorre em setembro."
    assert len(body["sources"]) == 1
    source = body["sources"][0]
    assert source["evidence_id"] == "E1"
    assert source["document_id"] == document["id"]
    assert source["document_title"] == "Calendário Académico"
    assert source["official_source"] is True
    assert source["source_url"] == "https://example.edu/calendario"
    assert uuid.UUID(source["chunk_id"])
    assert uuid.UUID(source["document_version_id"])
    assert source["chunk_index"] == 0
    assert source["language"] == "pt"


def test_question_without_evidence_returns_insufficient_evidence(
    client: TestClient, override_generator
) -> None:
    _, headers, _ = _setup(client)
    _create_searchable_document(client, headers)
    generator = override_generator(FakeAnswerGenerator())

    response = _ask(client, headers, query="transporte interplanetário")
    assert response.status_code == 200

    body = response.json()
    assert body["status"] == "insufficient_evidence"
    assert body["sources"] == []
    assert body["answer"].startswith("Não encontrei informação institucional")
    # O gerador nunca é chamado sem evidências.
    assert generator.calls == []


def test_answering_isolates_sources_between_institutions(
    client: TestClient, override_generator
) -> None:
    institution_a, admin_a, _ = _setup(client)
    user_a = _create_regular_user(client, admin_a)
    document_a = _create_searchable_document(
        client,
        admin_a,
        "isolamento comum fonte exclusiva alfa",
        title="Fonte da instituição A",
        source_url="https://a.example.edu/isolamento",
    )

    institution_b = _create_institution(client)
    admin_b, _ = _create_admin(client, institution_b["id"])
    user_b = _create_regular_user(client, admin_b)
    document_b = _create_searchable_document(
        client,
        admin_b,
        "isolamento comum fonte exclusiva beta",
        title="Fonte da instituição B",
        source_url="https://b.example.edu/isolamento",
    )
    override_generator(FakeAnswerGenerator())

    def ask_source(headers: dict[str, str]) -> tuple[dict, str]:
        response = _ask(client, headers, query="isolamento comum")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "answered"
        assert len(body["sources"]) == 1
        assert "institution_id" not in response.text
        return body["sources"][0], response.text

    source_a_admin, response_a_admin = ask_source(admin_a)
    source_a_user, response_a_user = ask_source(user_a)
    source_b_user, response_b_user = ask_source(user_b)

    assert source_a_admin == source_a_user
    assert source_a_admin["document_id"] == document_a["id"]
    assert source_b_user["document_id"] == document_b["id"]
    assert source_a_admin["source_url"] == "https://a.example.edu/isolamento"
    assert source_b_user["source_url"] == "https://b.example.edu/isolamento"
    for field in ("chunk_id", "document_id", "document_version_id", "source_url"):
        assert source_b_user[field] not in response_a_admin
        assert source_b_user[field] not in response_a_user
        assert source_a_admin[field] not in response_b_user
    assert institution_a["id"] != institution_b["id"]


# --- Payloads inválidos --------------------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        {"query": ""},
        {"query": "   "},
        {"query": "x" * 1001},
        {"query": "matricula", "top_k": 0},
        {"query": "matricula", "top_k": 11},
        {"query": "matricula", "top_k": 101},
        {"query": "matricula", "language": "fr"},
        {"query": "matricula", "institution_id": str(uuid.uuid4())},
        {"query": "matricula", "user_id": str(uuid.uuid4())},
        {"query": "matricula", "unknown_field": True},
    ],
)
def test_invalid_ask_payloads_return_422(
    client: TestClient, override_generator, payload: dict
) -> None:
    _, headers, _ = _setup(client)
    override_generator(FakeAnswerGenerator())
    response = client.post("/api/v1/answering/ask", json=payload, headers=headers)
    assert response.status_code == 422


# --- Provider não configurado / falhas ------------------------------------------------


def test_unconfigured_provider_returns_503_only_when_generation_is_needed(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sem override: usa o OpenAIAnswerGenerator real, sem chave nem modelo.

    Perguntas sem evidências continuam a devolver fallback (o provider
    nunca é contactado); com evidências, o endpoint devolve 503.
    """
    monkeypatch.setattr(settings, "openai_api_key", None)
    monkeypatch.setattr(settings, "openai_model", None)
    _, headers, _ = _setup(client)
    _create_searchable_document(client, headers)

    without_evidence = _ask(client, headers, query="transporte interplanetário")
    assert without_evidence.status_code == 200
    assert without_evidence.json()["status"] == "insufficient_evidence"

    with_evidence = _ask(client, headers)
    assert with_evidence.status_code == 503
    assert with_evidence.json()["detail"]["code"] == "service_unavailable"


def test_provider_failure_returns_safe_502(
    client: TestClient, override_generator
) -> None:
    _, headers, _ = _setup(client)
    _create_searchable_document(client, headers)
    override_generator(
        FakeAnswerGenerator(
            exception=AnswerGenerationError(
                "The answer generator failed to produce a usable response."
            )
        )
    )

    response = _ask(client, headers)
    assert response.status_code == 502
    body = response.json()
    assert body["detail"]["code"] == "upstream_error"
    assert "Traceback" not in response.text
    assert "openai" not in response.text.lower()


def test_invalid_generated_answer_returns_safe_502(
    client: TestClient, override_generator
) -> None:
    _, headers, _ = _setup(client)
    _create_searchable_document(client, headers)
    override_generator(
        FakeAnswerGenerator(
            result=GeneratedAnswer(answer="Resposta.", cited_evidence_ids=("E9",))
        )
    )

    response = _ask(client, headers)
    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "upstream_error"
    assert "E9" not in response.text


# --- Não exposição de dados internos ---------------------------------------------------


def test_response_never_exposes_internal_data(
    client: TestClient, override_generator, monkeypatch: pytest.MonkeyPatch
) -> None:
    sentinel_key = "sk-super-secret-test-key"
    monkeypatch.setattr(settings, "openai_api_key", sentinel_key)
    _, headers, _ = _setup(client)
    _create_searchable_document(client, headers)
    override_generator(FakeAnswerGenerator())

    response = _ask(client, headers)
    assert response.status_code == 200
    for forbidden in (
        sentinel_key,
        "institution_id",
        "normalized_content",
        "search_vector",
        "storage_path",
        "content_sha256",
        "BEGIN INSTITUTIONAL EVIDENCE",
        "system",
    ):
        assert forbidden not in response.text
