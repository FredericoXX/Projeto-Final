"""Utilitários partilhados pelos testes de caracterização do Momento 6.

Este módulo **não** contém testes: reúne apenas os helpers de construção de
cenário (instituição, administrador, documento pesquisável, conversa) que os
quatro ficheiros ``test_moment06_*`` usariam em duplicado.

Os helpers atravessam sempre a API HTTP real, para que o cenário fixado
corresponda ao que a aplicação faz — e não a linhas inseridas à mão. Onde um
teste precisa deliberadamente de contornar uma invariante mantida pelos
services (ver a divergência D2 da issue #24), esse desvio é feito no próprio
teste, explicitamente, nunca aqui.

Nenhum helper depende de rede ou de credenciais do fornecedor.
"""

import io
import uuid
from collections.abc import Callable

from fastapi.testclient import TestClient

from app.answering.base import AnsweringContext, GeneratedAnswer
from app.core.config import settings

BOOTSTRAP_HEADERS = {"X-Bootstrap-Token": settings.bootstrap_token or ""}
ADMIN_PASSWORD = "supersecret123"
USER_PASSWORD = "anothersecret123"

# Termos cuja forma lexical é idêntica nas configurações FTS 'portuguese' e
# 'english' (verificado contra o PostgreSQL da suite). Um cenário que precise
# de divergir o idioma do chunk do idioma do documento sem que o *stemming*
# se torne a verdadeira causa da exclusão tem de usar termos destes.
CONFIG_INVARIANT_TERMS = ("campus", "erasmus", "alfa", "provedor")


class RecordingAnswerGenerator:
    """Gerador determinístico e inspecionável, sem SDK nem rede.

    Equivalente ao ``FakeAnswerGenerator`` já usado noutras suites; existe
    aqui para que os ficheiros do Momento 6 não importem de um módulo de
    teste alheio. ``callback`` é o seam de interleaving que a issue #24
    exige para o teste de proveniência histórica.
    """

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


def create_institution(
    client: TestClient,
    *,
    name: str = "Instituição do Momento 6",
    default_language: str = "pt",
    supported_languages: list[str] | None = None,
) -> dict:
    response = client.post(
        "/api/v1/institutions",
        json={
            "name": name,
            "code": f"M06-{uuid.uuid4().hex[:8].upper()}",
            "default_language": default_language,
            "supported_languages": supported_languages or ["pt", "en"],
        },
        headers=BOOTSTRAP_HEADERS,
    )
    assert response.status_code == 201, response.text
    return response.json()


def create_admin(client: TestClient, institution_id: str) -> tuple[dict[str, str], str]:
    email = f"admin-{uuid.uuid4().hex[:8]}@example.com"
    registered = client.post(
        "/api/v1/auth/register-initial-admin",
        json={
            "institution_id": institution_id,
            "full_name": "Admin Momento 6",
            "email": email,
            "password": ADMIN_PASSWORD,
        },
        headers=BOOTSTRAP_HEADERS,
    )
    assert registered.status_code == 201, registered.text
    login = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": ADMIN_PASSWORD},
    )
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    return headers, registered.json()["id"]


def create_regular_user(
    client: TestClient,
    admin_headers: dict[str, str],
    *,
    role: str = "student",
) -> tuple[dict[str, str], str]:
    email = f"user-{uuid.uuid4().hex[:8]}@example.com"
    created = client.post(
        "/api/v1/users",
        json={
            "full_name": "Utilizador Momento 6",
            "email": email,
            "password": USER_PASSWORD,
            "role": role,
        },
        headers=admin_headers,
    )
    assert created.status_code == 201, created.text
    login = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": USER_PASSWORD},
    )
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    return headers, created.json()["id"]


def setup_institution_with_admin(
    client: TestClient, **institution_overrides: object
) -> tuple[dict, dict[str, str], str]:
    institution = create_institution(client, **institution_overrides)  # type: ignore[arg-type]
    headers, admin_id = create_admin(client, institution["id"])
    return institution, headers, admin_id


def create_document(
    client: TestClient,
    headers: dict[str, str],
    **overrides: object,
) -> dict:
    payload: dict = {
        "title": f"Documento {uuid.uuid4().hex[:6]}",
        "language": "pt",
        "official_source": True,
        "source_url": f"https://example.edu/{uuid.uuid4().hex[:8]}",
    }
    payload.update(overrides)
    response = client.post("/api/v1/documents", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def upload_version(
    client: TestClient,
    headers: dict[str, str],
    document_id: str,
    content: str,
    *,
    expect_processed: bool = True,
) -> dict:
    response = client.post(
        f"/api/v1/documents/{document_id}/versions",
        files={
            "file": (
                f"{uuid.uuid4().hex[:10]}.txt",
                io.BytesIO(content.encode("utf-8")),
                "text/plain",
            )
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    if expect_processed:
        assert response.json()["processing_status"] == "processed", response.text
    return response.json()


def create_searchable_document(
    client: TestClient,
    headers: dict[str, str],
    content: str,
    **document_overrides: object,
) -> tuple[dict, dict]:
    document = create_document(client, headers, **document_overrides)
    version = upload_version(client, headers, document["id"], content)
    return document, version


def create_conversation(
    client: TestClient,
    headers: dict[str, str],
    *,
    language: str = "pt",
    title: str | None = "Perguntas institucionais",
) -> dict:
    payload: dict = {"language": language}
    if title is not None:
        payload["title"] = title
    response = client.post("/api/v1/conversations", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def ask(
    client: TestClient,
    headers: dict[str, str],
    query: str,
    **overrides: object,
):
    payload: dict = {"query": query}
    payload.update(overrides)
    return client.post("/api/v1/answering/ask", json=payload, headers=headers)


def ask_in_conversation(
    client: TestClient,
    headers: dict[str, str],
    conversation_id: str,
    query: str,
    **overrides: object,
):
    payload: dict = {"query": query}
    payload.update(overrides)
    return client.post(
        f"/api/v1/conversations/{conversation_id}/ask",
        json=payload,
        headers=headers,
    )


def search(
    client: TestClient,
    headers: dict[str, str],
    query: str,
    **overrides: object,
):
    payload: dict = {"query": query}
    payload.update(overrides)
    return client.post("/api/v1/retrieval/search", json=payload, headers=headers)
