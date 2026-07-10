"""Tests for user creation, retrieval, listing and update, scoped to the
authenticated admin's institution.

Runs against the dedicated test database (see conftest.py). The
autouse `_clean_tables` fixture truncates every table before each
test, so tests don't need to track or delete the rows they create.
"""

import uuid

from fastapi.testclient import TestClient

_USER_PASSWORD = "anothersecret123"


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


def _create_admin_and_login(client: TestClient, institution_id: str) -> dict[str, str]:
    """Registers the institution's initial admin and returns auth headers for it."""
    payload = {
        "institution_id": institution_id,
        "full_name": "Admin User",
        "email": f"admin-{uuid.uuid4().hex[:8]}@example.com",
        "password": "supersecret123",
    }
    response = client.post("/api/v1/auth/register-initial-admin", json=payload)
    assert response.status_code == 201

    login = client.post(
        "/api/v1/auth/login",
        json={"email": payload["email"], "password": payload["password"]},
    )
    assert login.status_code == 200
    token = login.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _user_payload(**overrides: object) -> dict:
    payload: dict = {
        "full_name": "Regular User",
        "email": f"user-{uuid.uuid4().hex[:8]}@example.com",
        "password": _USER_PASSWORD,
        "role": "student",
    }
    payload.update(overrides)
    return payload


def test_create_user_requires_admin(client: TestClient) -> None:
    response = client.post("/api/v1/users", json=_user_payload())
    assert response.status_code == 401


def test_create_user_forbidden_for_non_admin(client: TestClient) -> None:
    institution_id = _create_institution(client)
    headers = _create_admin_and_login(client, institution_id)

    created = client.post(
        "/api/v1/users", json=_user_payload(role="staff"), headers=headers
    )
    staff_email = created.json()["email"]

    staff_login = client.post(
        "/api/v1/auth/login",
        json={"email": staff_email, "password": _USER_PASSWORD},
    )
    staff_headers = {"Authorization": f"Bearer {staff_login.json()['access_token']}"}

    response = client.post("/api/v1/users", json=_user_payload(), headers=staff_headers)
    assert response.status_code == 403


def test_create_user_adds_to_admin_institution(client: TestClient) -> None:
    institution_id = _create_institution(client)
    headers = _create_admin_and_login(client, institution_id)

    response = client.post("/api/v1/users", json=_user_payload(), headers=headers)
    assert response.status_code == 201

    body = response.json()
    assert body["institution_id"] == institution_id
    assert "password_hash" not in body
    assert "password" not in body


def test_create_user_normalizes_email(client: TestClient) -> None:
    institution_id = _create_institution(client)
    headers = _create_admin_and_login(client, institution_id)

    response = client.post(
        "/api/v1/users",
        json=_user_payload(email="  MixedCase@Example.com  "),
        headers=headers,
    )
    assert response.status_code == 201
    assert response.json()["email"] == "mixedcase@example.com"


def test_create_user_rejects_blank_full_name(client: TestClient) -> None:
    institution_id = _create_institution(client)
    headers = _create_admin_and_login(client, institution_id)

    response = client.post(
        "/api/v1/users",
        json=_user_payload(full_name="   "),
        headers=headers,
    )
    assert response.status_code == 422


def test_create_user_duplicate_email_returns_409(client: TestClient) -> None:
    institution_id = _create_institution(client)
    headers = _create_admin_and_login(client, institution_id)

    payload = _user_payload()
    first = client.post("/api/v1/users", json=payload, headers=headers)
    assert first.status_code == 201

    second = client.post("/api/v1/users", json=payload, headers=headers)
    assert second.status_code == 409


def test_list_users_returns_only_own_institution(client: TestClient) -> None:
    institution_a = _create_institution(client)
    headers_a = _create_admin_and_login(client, institution_a)
    client.post("/api/v1/users", json=_user_payload(), headers=headers_a)

    institution_b = _create_institution(client)
    headers_b = _create_admin_and_login(client, institution_b)
    client.post("/api/v1/users", json=_user_payload(), headers=headers_b)

    response = client.get("/api/v1/users", headers=headers_a)
    assert response.status_code == 200

    body = response.json()
    # O próprio admin mais o utilizador criado acima.
    assert body["total"] == 2
    assert all(item["institution_id"] == institution_a for item in body["items"])


def test_get_user_from_other_institution_returns_404(client: TestClient) -> None:
    institution_a = _create_institution(client)
    headers_a = _create_admin_and_login(client, institution_a)

    institution_b = _create_institution(client)
    headers_b = _create_admin_and_login(client, institution_b)
    created = client.post("/api/v1/users", json=_user_payload(), headers=headers_b)
    other_user_id = created.json()["id"]

    response = client.get(f"/api/v1/users/{other_user_id}", headers=headers_a)
    assert response.status_code == 404


def test_update_user_from_other_institution_returns_404(client: TestClient) -> None:
    institution_a = _create_institution(client)
    headers_a = _create_admin_and_login(client, institution_a)

    institution_b = _create_institution(client)
    headers_b = _create_admin_and_login(client, institution_b)
    created = client.post("/api/v1/users", json=_user_payload(), headers=headers_b)
    other_user_id = created.json()["id"]

    response = client.patch(
        f"/api/v1/users/{other_user_id}",
        json={"full_name": "Hacked Name"},
        headers=headers_a,
    )
    assert response.status_code == 404


def test_update_user_within_own_institution(client: TestClient) -> None:
    institution_id = _create_institution(client)
    headers = _create_admin_and_login(client, institution_id)
    created = client.post("/api/v1/users", json=_user_payload(), headers=headers)
    user_id = created.json()["id"]

    response = client.patch(
        f"/api/v1/users/{user_id}",
        json={"full_name": "Updated Name", "role": "staff"},
        headers=headers,
    )
    assert response.status_code == 200

    body = response.json()
    assert body["full_name"] == "Updated Name"
    assert body["role"] == "staff"
