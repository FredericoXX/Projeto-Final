"""Tests that write payloads reject unknown fields with 422.

Every write schema now uses extra="forbid", so a payload carrying a
field the endpoint does not accept — especially identity fields like
institution_id, user_id or password_hash, which are always derived from
the authenticated context, never from the client — fails loudly with
422 instead of being silently ignored. The cases for
InstitutionAdminUpdate (is_active) and the bootstrap status endpoint
(extra fields) already live in test_institutions.py.

Runs against the dedicated test database (see conftest.py). The
autouse `_clean_tables` fixture truncates every table before each
test, so tests don't need to track or delete the rows they create.
"""

import uuid

from fastapi.testclient import TestClient

from app.core.config import settings

_ADMIN_PASSWORD = "supersecret123"

BOOTSTRAP_HEADERS = {"X-Bootstrap-Token": settings.bootstrap_token or ""}


def _institution_payload(**overrides: object) -> dict:
    payload: dict = {
        "name": "Test Institution",
        "code": f"TST-{uuid.uuid4().hex[:8].upper()}",
        "default_language": "pt",
        "supported_languages": ["pt", "en"],
    }
    payload.update(overrides)
    return payload


def _create_institution(client: TestClient) -> str:
    response = client.post(
        "/api/v1/institutions", json=_institution_payload(), headers=BOOTSTRAP_HEADERS
    )
    assert response.status_code == 201
    return response.json()["id"]


def _create_admin_and_login(client: TestClient, institution_id: str) -> dict[str, str]:
    payload = {
        "institution_id": institution_id,
        "full_name": "Admin User",
        "email": f"admin-{uuid.uuid4().hex[:8]}@example.com",
        "password": _ADMIN_PASSWORD,
    }
    response = client.post(
        "/api/v1/auth/register-initial-admin", json=payload, headers=BOOTSTRAP_HEADERS
    )
    assert response.status_code == 201

    login = client.post(
        "/api/v1/auth/login",
        json={"email": payload["email"], "password": _ADMIN_PASSWORD},
    )
    assert login.status_code == 200
    token = login.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _user_payload(**overrides: object) -> dict:
    payload: dict = {
        "full_name": "Regular User",
        "email": f"user-{uuid.uuid4().hex[:8]}@example.com",
        "password": "anothersecret123",
        "role": "student",
    }
    payload.update(overrides)
    return payload


def test_create_user_rejects_institution_id_in_payload(client: TestClient) -> None:
    institution_id = _create_institution(client)
    headers = _create_admin_and_login(client, institution_id)

    response = client.post(
        "/api/v1/users",
        json=_user_payload(institution_id=str(uuid.uuid4())),
        headers=headers,
    )
    assert response.status_code == 422


def test_update_user_rejects_password_hash_in_payload(client: TestClient) -> None:
    institution_id = _create_institution(client)
    headers = _create_admin_and_login(client, institution_id)
    created = client.post("/api/v1/users", json=_user_payload(), headers=headers)
    user_id = created.json()["id"]

    response = client.patch(
        f"/api/v1/users/{user_id}",
        json={"full_name": "Updated Name", "password_hash": "injected-hash"},
        headers=headers,
    )
    assert response.status_code == 422

    # O campo válido do mesmo payload também não foi aplicado: o pedido
    # inteiro é rejeitado antes de qualquer alteração.
    unchanged = client.get(f"/api/v1/users/{user_id}", headers=headers)
    assert unchanged.json()["full_name"] == "Regular User"


def test_create_conversation_rejects_user_id_in_payload(client: TestClient) -> None:
    institution_id = _create_institution(client)
    headers = _create_admin_and_login(client, institution_id)

    response = client.post(
        "/api/v1/conversations",
        json={"title": "Hijack attempt", "user_id": str(uuid.uuid4())},
        headers=headers,
    )
    assert response.status_code == 422


def test_create_conversation_rejects_institution_id_in_payload(client: TestClient) -> None:
    institution_id = _create_institution(client)
    headers = _create_admin_and_login(client, institution_id)

    response = client.post(
        "/api/v1/conversations",
        json={"title": "Hijack attempt", "institution_id": str(uuid.uuid4())},
        headers=headers,
    )
    assert response.status_code == 422


def test_create_message_rejects_user_id_in_payload(client: TestClient) -> None:
    institution_id = _create_institution(client)
    headers = _create_admin_and_login(client, institution_id)
    conversation = client.post(
        "/api/v1/conversations", json={"title": "Test"}, headers=headers
    ).json()

    response = client.post(
        f"/api/v1/conversations/{conversation['id']}/messages",
        json={"content": "Hello", "user_id": str(uuid.uuid4())},
        headers=headers,
    )
    assert response.status_code == 422


def test_login_rejects_unknown_fields(client: TestClient) -> None:
    institution_id = _create_institution(client)
    _create_admin_and_login(client, institution_id)

    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "whoever@example.com",
            "password": "whatever123",
            "remember_me": True,
        },
    )
    assert response.status_code == 422


def test_register_initial_admin_rejects_unknown_fields(client: TestClient) -> None:
    institution_id = _create_institution(client)

    response = client.post(
        "/api/v1/auth/register-initial-admin",
        json={
            "institution_id": institution_id,
            "full_name": "Admin User",
            "email": f"admin-{uuid.uuid4().hex[:8]}@example.com",
            "password": _ADMIN_PASSWORD,
            "role": "admin",
        },
        headers=BOOTSTRAP_HEADERS,
    )
    assert response.status_code == 422


def test_create_institution_rejects_unknown_fields(client: TestClient) -> None:
    response = client.post(
        "/api/v1/institutions",
        json=_institution_payload(owner="someone"),
        headers=BOOTSTRAP_HEADERS,
    )
    assert response.status_code == 422
