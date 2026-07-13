"""Integração da baseline lexical: endpoint, filtros e versionamento."""

import io
import uuid
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.models.document_chunk import DocumentChunk
from app.models.document_version import DocumentVersion
from app.models.institution import Institution
from app.models.user import User

BOOTSTRAP_HEADERS = {"X-Bootstrap-Token": settings.bootstrap_token or ""}
_ADMIN_PASSWORD = "supersecret123"
_USER_PASSWORD = "anothersecret123"


def _create_institution(
    client: TestClient,
    *,
    default_language: str = "pt",
    supported_languages: list[str] | None = None,
) -> dict:
    response = client.post(
        "/api/v1/institutions",
        json={
            "name": "Retrieval Institution",
            "code": f"RET-{uuid.uuid4().hex[:8].upper()}",
            "default_language": default_language,
            "supported_languages": supported_languages or ["pt", "en"],
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
            "full_name": "Admin Retrieval",
            "email": email,
            "password": _ADMIN_PASSWORD,
        },
        headers=BOOTSTRAP_HEADERS,
    )
    assert response.status_code == 201
    user_id = response.json()["id"]
    login = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": _ADMIN_PASSWORD},
    )
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}, user_id


def _create_regular_user(
    client: TestClient, admin_headers: dict[str, str]
) -> tuple[dict[str, str], str]:
    email = f"staff-{uuid.uuid4().hex[:8]}@example.com"
    response = client.post(
        "/api/v1/users",
        json={
            "full_name": "Staff Retrieval",
            "email": email,
            "password": _USER_PASSWORD,
            "role": "staff",
        },
        headers=admin_headers,
    )
    assert response.status_code == 201
    user_id = response.json()["id"]
    login = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": _USER_PASSWORD},
    )
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}, user_id


def _create_document(
    client: TestClient,
    headers: dict[str, str],
    **overrides: object,
) -> dict:
    payload: dict = {
        "title": f"Documento {uuid.uuid4().hex[:6]}",
        "language": "pt",
        "official_source": True,
        "source_url": "https://example.edu/documento",
    }
    payload.update(overrides)
    response = client.post("/api/v1/documents", json=payload, headers=headers)
    assert response.status_code == 201
    return response.json()


def _upload(
    client: TestClient,
    headers: dict[str, str],
    document_id: str,
    content: bytes,
) -> dict:
    response = client.post(
        f"/api/v1/documents/{document_id}/versions",
        files={"file": ("evidence.txt", io.BytesIO(content), "text/plain")},
        headers=headers,
    )
    assert response.status_code == 201
    return response.json()


def _search(
    client: TestClient,
    headers: dict[str, str],
    query: str,
    **overrides: object,
):
    payload: dict = {"query": query}
    payload.update(overrides)
    return client.post("/api/v1/retrieval/search", json=payload, headers=headers)


def _setup(client: TestClient) -> tuple[dict, dict[str, str], str]:
    institution = _create_institution(client)
    headers, user_id = _create_admin(client, institution["id"])
    return institution, headers, user_id


def _create_searchable(
    client: TestClient,
    headers: dict[str, str],
    content: str,
    **document_overrides: object,
) -> tuple[dict, dict]:
    document = _create_document(client, headers, **document_overrides)
    version = _upload(client, headers, document["id"], content.encode())
    assert version["processing_status"] == "processed"
    return document, version


# --- Endpoint, ranking e segurança do schema ---------------------------------


def test_search_requires_authentication(client: TestClient) -> None:
    assert _search(client, {}, "matricula").status_code == 401
    assert _search(client, {"Authorization": "Bearer invalid"}, "matricula").status_code == 401


def test_regular_user_and_admin_can_search(client: TestClient) -> None:
    institution, admin_headers, _ = _setup(client)
    user_headers, _ = _create_regular_user(client, admin_headers)
    _create_searchable(client, admin_headers, "O prazo de matrícula termina em setembro.")

    assert _search(client, admin_headers, "matricula").status_code == 200
    assert _search(client, user_headers, "matricula").status_code == 200
    assert institution["id"]


def test_existing_term_returns_evidence_without_internal_fields(client: TestClient) -> None:
    _, headers, _ = _setup(client)
    document, version = _create_searchable(
        client,
        headers,
        "O período de matrícula decorre entre agosto e setembro.",
        title="Calendário Académico",
    )

    response = _search(client, headers, "  matrícula  ", language="PT", top_k=5)
    assert response.status_code == 200
    body = response.json()
    assert body["query"] == "matrícula"
    assert body["language"] == "pt"
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["document_id"] == document["id"]
    assert item["document_version_id"] == version["id"]
    assert item["document_title"] == "Calendário Académico"
    assert item["score"] > 0
    assert item["content"].startswith("O período")
    assert item["official_source"] is True
    assert item["source_url"] == "https://example.edu/documento"
    assert item["valid_from"] is None
    assert item["valid_until"] is None
    forbidden = {
        "institution_id",
        "normalized_content",
        "search_vector",
        "storage_path",
        "content_sha256",
        "extracted_text",
        "uploaded_by_user_id",
    }
    assert forbidden.isdisjoint(item)


def test_missing_term_and_punctuation_return_empty_items(client: TestClient) -> None:
    _, headers, _ = _setup(client)
    _create_searchable(client, headers, "Calendário académico e matrículas.")
    assert _search(client, headers, "meteorologia").json()["items"] == []
    punctuation = _search(client, headers, "!!! ... ---")
    assert punctuation.status_code == 200
    assert punctuation.json()["items"] == []


def test_accented_and_unaccented_queries_match_normalized_content(client: TestClient) -> None:
    _, headers, _ = _setup(client)
    _create_searchable(client, headers, "Informações sobre matrícula e inscrição académica.")
    assert _search(client, headers, "matrícula").json()["items"]
    assert _search(client, headers, "matricula").json()["items"]


def test_portuguese_and_english_searches_work(client: TestClient) -> None:
    _, headers, _ = _setup(client)
    _create_searchable(client, headers, "Prazo de matrícula institucional.")
    _create_searchable(
        client,
        headers,
        "Enrollment deadline for international students.",
        language="en",
        title="Enrollment guide",
    )
    assert _search(client, headers, "prazo", language="pt").json()["items"]
    assert _search(client, headers, "enrollment", language="en").json()["items"]
    assert _search(client, headers, "enrollment", language="pt").json()["items"] == []


def test_top_k_score_order_and_deterministic_ties(client: TestClient) -> None:
    _, headers, _ = _setup(client)
    for index in range(4):
        suffix = ("alpha", "bravo", "charlie", "delta")[index]
        _create_searchable(
            client,
            headers,
            (
                f"matricula matricula prazo {suffix}"
                if index == 0
                else f"matricula prazo {suffix}"
            ),
            title=f"Documento {index}",
        )
    response = _search(client, headers, "matricula", top_k=3)
    items = response.json()["items"]
    assert len(items) == 3
    scores = [item["score"] for item in items]
    assert scores == sorted(scores, reverse=True)
    tied = [item for item in items if item["score"] == items[-1]["score"]]
    tied_ids = [uuid.UUID(item["document_id"]) for item in tied]
    assert tied_ids == sorted(tied_ids)


def test_websearch_operators_are_parameterized_and_safe(client: TestClient) -> None:
    _, headers, _ = _setup(client)
    _create_searchable(client, headers, "matricula estudantes regulamento")
    response = _search(client, headers, 'matricula OR "regulamento" -meteorologia')
    assert response.status_code == 200
    assert response.json()["items"]


@pytest.mark.parametrize(
    "payload",
    [
        {"query": ""},
        {"query": "   "},
        {"query": "x" * 1001},
        {"query": "matricula", "top_k": 0},
        {"query": "matricula", "top_k": 21},
        {"query": "matricula", "institution_id": str(uuid.uuid4())},
        {"query": "matricula", "user_id": str(uuid.uuid4())},
        {"query": "matricula", "unknown": True},
    ],
)
def test_invalid_search_payloads_return_422(
    client: TestClient, payload: dict
) -> None:
    _, headers, _ = _setup(client)
    response = client.post("/api/v1/retrieval/search", json=payload, headers=headers)
    assert response.status_code == 422


# --- Credibilidade, validade, idioma e isolamento -----------------------------


def test_active_official_and_nullable_validity_document_appears(client: TestClient) -> None:
    _, headers, _ = _setup(client)
    _create_searchable(client, headers, "evidencia oficial vigente")
    assert _search(client, headers, "vigente").json()["items"]


def test_inactive_future_and_expired_documents_are_excluded(client: TestClient) -> None:
    _, headers, _ = _setup(client)
    today = date.today()
    inactive, _ = _create_searchable(client, headers, "termo inativo")
    client.patch(
        f"/api/v1/documents/{inactive['id']}",
        json={"is_active": False},
        headers=headers,
    )
    _create_searchable(
        client,
        headers,
        "termo futuro",
        valid_from=(today + timedelta(days=1)).isoformat(),
    )
    _create_searchable(
        client,
        headers,
        "termo expirado",
        valid_until=(today - timedelta(days=1)).isoformat(),
    )
    assert _search(client, headers, "inativo").json()["items"] == []
    assert _search(client, headers, "futuro").json()["items"] == []
    assert _search(client, headers, "expirado").json()["items"] == []


def test_official_only_defaults_true_and_false_allows_both(client: TestClient) -> None:
    _, headers, _ = _setup(client)
    _create_searchable(client, headers, "bolsa institucional", title="Oficial")
    _create_searchable(
        client,
        headers,
        "bolsa estudantil",
        title="Não oficial",
        official_source=False,
    )
    default_items = _search(client, headers, "bolsa").json()["items"]
    assert len(default_items) == 1
    assert default_items[0]["official_source"] is True
    all_items = _search(client, headers, "bolsa", official_only=False).json()["items"]
    assert {item["official_source"] for item in all_items} == {True, False}


def test_default_language_and_unsupported_language(client: TestClient) -> None:
    _, headers, _ = _setup(client)
    _create_searchable(client, headers, "matricula por defeito")
    response = _search(client, headers, "matricula")
    assert response.status_code == 200
    assert response.json()["language"] == "pt"
    unsupported = _search(client, headers, "matricula", language="fr")
    assert unsupported.status_code == 422


def test_institution_isolation_applies_to_regular_user_and_admin(client: TestClient) -> None:
    institution_a, admin_a, _ = _setup(client)
    user_a, _ = _create_regular_user(client, admin_a)
    document_a, _ = _create_searchable(client, admin_a, "segredo alfa institucional")

    institution_b = _create_institution(client)
    admin_b, _ = _create_admin(client, institution_b["id"])
    document_b, _ = _create_searchable(client, admin_b, "segredo beta institucional")

    assert _search(client, admin_a, "beta").json()["items"] == []
    assert _search(client, user_a, "beta").json()["items"] == []
    assert _search(client, admin_b, "alfa").json()["items"] == []
    assert institution_a["id"] != institution_b["id"]
    assert document_a["id"] != document_b["id"]


def test_inactive_user_and_institution_cannot_search(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> None:
    institution, headers, admin_id = _setup(client)
    session = test_session_factory()
    try:
        user = session.get(User, uuid.UUID(admin_id))
        assert user is not None
        user.is_active = False
        session.commit()
    finally:
        session.close()
    assert _search(client, headers, "qualquer").status_code == 401

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
    assert _search(client, other_headers, "qualquer").status_code == 401


# --- Seleção da versão processed mais recente ---------------------------------


def test_latest_processed_version_replaces_older_in_search(client: TestClient) -> None:
    _, headers, _ = _setup(client)
    document = _create_document(client, headers)
    version_1 = _upload(client, headers, document["id"], b"termo antigo exclusivo")
    version_2 = _upload(client, headers, document["id"], b"termo recente exclusivo")
    assert _search(client, headers, "antigo").json()["items"] == []
    recent = _search(client, headers, "recente").json()["items"]
    assert recent[0]["document_version_id"] == version_2["id"]
    assert version_1["id"] != version_2["id"]


@pytest.mark.parametrize("latest_status", ["failed", "pending", "processing"])
def test_nonprocessed_latest_version_does_not_hide_previous_processed(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
    latest_status: str,
) -> None:
    _, headers, _ = _setup(client)
    document = _create_document(client, headers)
    version_1 = _upload(client, headers, document["id"], b"evidencia anterior valida")
    if latest_status == "failed":
        version_2 = _upload(client, headers, document["id"], b"\xff\xfe invalid")
    else:
        version_2 = _upload(client, headers, document["id"], b"conteudo posterior distinto")
        session = test_session_factory()
        try:
            stored = session.get(DocumentVersion, uuid.UUID(version_2["id"]))
            assert stored is not None
            stored.processing_status = latest_status
            session.commit()
        finally:
            session.close()
    items = _search(client, headers, "anterior").json()["items"]
    assert items[0]["document_version_id"] == version_1["id"]


def test_document_without_processed_version_is_not_searched(
    client: TestClient,
) -> None:
    _, headers, _ = _setup(client)
    document = _create_document(client, headers)
    failed = _upload(client, headers, document["id"], b"\xff\xfe invalid")
    assert failed["processing_status"] == "failed"
    assert _search(client, headers, "invalid").json()["items"] == []


def test_historical_chunks_remain_stored_but_are_not_searched(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
) -> None:
    _, headers, _ = _setup(client)
    document = _create_document(client, headers)
    old = _upload(client, headers, document["id"], b"arquivo historico preservado")
    new = _upload(client, headers, document["id"], b"arquivo corrente pesquisavel")
    session = test_session_factory()
    try:
        old_chunks = list(
            session.scalars(
                select(DocumentChunk).where(
                    DocumentChunk.document_version_id == uuid.UUID(old["id"])
                )
            ).all()
        )
        assert old_chunks
    finally:
        session.close()
    assert _search(client, headers, "historico").json()["items"] == []
    assert _search(client, headers, "corrente").json()["items"][0][
        "document_version_id"
    ] == new["id"]
