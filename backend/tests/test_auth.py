"""Tests for authentication: initial admin registration, login and /me.

Runs against the dedicated test database (see conftest.py). The
autouse `_clean_tables` fixture truncates every table before each
test, so tests don't need to track or delete the rows they create.
"""

import uuid

from fastapi.testclient import TestClient


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
    response = client.post("/api/v1/institutions", json=_institution_payload())
    assert response.status_code == 201
    return response.json()["id"]


def _register_admin_payload(institution_id: str, **overrides: object) -> dict:
    payload: dict = {
        "institution_id": institution_id,
        "full_name": "Admin User",
        "email": f"admin-{uuid.uuid4().hex[:8]}@example.com",
        "password": "supersecret123",
    }
    payload.update(overrides)
    return payload


def test_register_initial_admin_creates_admin(client: TestClient) -> None:
    institution_id = _create_institution(client)
    payload = _register_admin_payload(institution_id)

    response = client.post("/api/v1/auth/register-initial-admin", json=payload)
    assert response.status_code == 201

    body = response.json()
    assert body["role"] == "admin"
    assert body["institution_id"] == institution_id
    assert body["email"] == payload["email"]
    assert "password_hash" not in body
    assert "password" not in body


def test_register_initial_admin_fails_if_institution_not_found(client: TestClient) -> None:
    payload = _register_admin_payload(str(uuid.uuid4()))

    response = client.post("/api/v1/auth/register-initial-admin", json=payload)
    assert response.status_code == 404


def test_register_initial_admin_fails_if_institution_already_has_admin(
    client: TestClient,
) -> None:
    institution_id = _create_institution(client)
    first = client.post(
        "/api/v1/auth/register-initial-admin",
        json=_register_admin_payload(institution_id),
    )
    assert first.status_code == 201

    second = client.post(
        "/api/v1/auth/register-initial-admin",
        json=_register_admin_payload(institution_id),
    )
    assert second.status_code == 409


def test_login_with_valid_credentials_returns_token(client: TestClient) -> None:
    institution_id = _create_institution(client)
    payload = _register_admin_payload(institution_id)
    client.post("/api/v1/auth/register-initial-admin", json=payload)

    response = client.post(
        "/api/v1/auth/login",
        json={"email": payload["email"], "password": payload["password"]},
    )
    assert response.status_code == 200

    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]


def test_login_with_wrong_password_returns_401(client: TestClient) -> None:
    institution_id = _create_institution(client)
    payload = _register_admin_payload(institution_id)
    client.post("/api/v1/auth/register-initial-admin", json=payload)

    response = client.post(
        "/api/v1/auth/login",
        json={"email": payload["email"], "password": "wrong-password"},
    )
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "authentication_failed"


def test_login_with_unknown_email_returns_401_without_revealing_detail(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@example.com", "password": "whatever123"},
    )
    assert response.status_code == 401

    body = response.json()
    assert body["detail"]["code"] == "authentication_failed"
    message = body["detail"]["message"].lower()
    assert "not found" not in message
    assert "exist" not in message


def test_me_returns_authenticated_user(client: TestClient) -> None:
    institution_id = _create_institution(client)
    payload = _register_admin_payload(institution_id)
    client.post("/api/v1/auth/register-initial-admin", json=payload)

    login_response = client.post(
        "/api/v1/auth/login",
        json={"email": payload["email"], "password": payload["password"]},
    )
    token = login_response.json()["access_token"]

    response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200

    body = response.json()
    assert body["email"] == payload["email"]
    assert body["role"] == "admin"


def test_me_without_token_returns_401(client: TestClient) -> None:
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401


def test_inactive_user_cannot_login_or_use_me(client: TestClient) -> None:
    institution_id = _create_institution(client)
    payload = _register_admin_payload(institution_id)
    register_response = client.post("/api/v1/auth/register-initial-admin", json=payload)
    admin_id = register_response.json()["id"]

    login_response = client.post(
        "/api/v1/auth/login",
        json={"email": payload["email"], "password": payload["password"]},
    )
    token = login_response.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    deactivate_response = client.patch(
        f"/api/v1/users/{admin_id}",
        json={"is_active": False},
        headers=headers,
    )
    assert deactivate_response.status_code == 200

    second_login = client.post(
        "/api/v1/auth/login",
        json={"email": payload["email"], "password": payload["password"]},
    )
    assert second_login.status_code == 401

    me_response = client.get("/api/v1/auth/me", headers=headers)
    assert me_response.status_code == 401
