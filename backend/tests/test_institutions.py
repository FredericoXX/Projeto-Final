"""Tests for institution creation, retrieval, listing and update.

Creation is gated by a bootstrap token (there is no platform_admin role
yet); reading and updating require an authenticated institutional admin
and are always scoped to that admin's own institution — another tenant's
institution_id is treated as not found (404), never as forbidden (403),
so its existence is never confirmed.

Runs against the dedicated test database (see conftest.py). The
autouse `_clean_tables` fixture truncates every table before each
test, so tests don't need to track or delete the rows they create.
"""

import uuid

from fastapi.testclient import TestClient

from app.core.config import settings

BOOTSTRAP_HEADERS = {"X-Bootstrap-Token": settings.bootstrap_token or ""}


def _unique_code() -> str:
    return f"TST-{uuid.uuid4().hex[:8].upper()}"


def _payload(**overrides: object) -> dict:
    payload: dict = {
        "name": "Test Institution",
        "code": _unique_code(),
        "default_language": "pt",
        "supported_languages": ["pt", "en"],
    }
    payload.update(overrides)
    return payload


def _create_institution(client: TestClient, **overrides: object) -> dict:
    response = client.post(
        "/api/v1/institutions", json=_payload(**overrides), headers=BOOTSTRAP_HEADERS
    )
    assert response.status_code == 201
    return response.json()


def _create_admin_and_login(client: TestClient, institution_id: str) -> dict[str, str]:
    payload = {
        "institution_id": institution_id,
        "full_name": "Admin User",
        "email": f"admin-{uuid.uuid4().hex[:8]}@example.com",
        "password": "supersecret123",
    }
    response = client.post(
        "/api/v1/auth/register-initial-admin", json=payload, headers=BOOTSTRAP_HEADERS
    )
    assert response.status_code == 201

    login = client.post(
        "/api/v1/auth/login",
        json={"email": payload["email"], "password": payload["password"]},
    )
    assert login.status_code == 200
    token = login.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_create_institution_without_bootstrap_token_returns_401(client: TestClient) -> None:
    response = client.post("/api/v1/institutions", json=_payload())
    assert response.status_code == 401


def test_create_institution_with_wrong_bootstrap_token_returns_401(client: TestClient) -> None:
    response = client.post(
        "/api/v1/institutions",
        json=_payload(),
        headers={"X-Bootstrap-Token": "wrong-token"},
    )
    assert response.status_code == 401


def test_create_institution_with_bootstrap_token(client: TestClient) -> None:
    payload = _payload()
    response = client.post("/api/v1/institutions", json=payload, headers=BOOTSTRAP_HEADERS)
    assert response.status_code == 201

    body = response.json()
    assert body["name"] == payload["name"]
    assert body["code"] == payload["code"]
    assert body["default_language"] == "pt"
    assert body["supported_languages"] == ["pt", "en"]
    assert body["is_active"] is True
    assert "created_at" in body
    assert "updated_at" in body


def test_create_institution_duplicate_code_returns_409(client: TestClient) -> None:
    payload = _payload()
    first = client.post("/api/v1/institutions", json=payload, headers=BOOTSTRAP_HEADERS)
    assert first.status_code == 201

    second = client.post("/api/v1/institutions", json=payload, headers=BOOTSTRAP_HEADERS)
    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "resource_conflict"


# Garante que uma instituição não pode usar um idioma padrão
# fora da lista de idiomas suportados.
def test_create_institution_rejects_unsupported_default_language(client: TestClient) -> None:
    payload = _payload(default_language="fr", supported_languages=["pt", "en"])
    response = client.post("/api/v1/institutions", json=payload, headers=BOOTSTRAP_HEADERS)
    assert response.status_code == 422


def test_create_institution_rejects_whitespace_only_code(client: TestClient) -> None:
    payload = _payload(code="   ")
    response = client.post("/api/v1/institutions", json=payload, headers=BOOTSTRAP_HEADERS)
    assert response.status_code == 422


def test_create_institution_rejects_whitespace_only_name(client: TestClient) -> None:
    payload = _payload(name="   ")
    response = client.post("/api/v1/institutions", json=payload, headers=BOOTSTRAP_HEADERS)
    assert response.status_code == 422


def test_create_institution_normalizes_duplicate_languages(client: TestClient) -> None:
    payload = _payload(
        default_language="PT",
        supported_languages=["pt", "PT", "pt", "en", "EN"],
    )
    response = client.post("/api/v1/institutions", json=payload, headers=BOOTSTRAP_HEADERS)
    assert response.status_code == 201
    assert response.json()["supported_languages"] == ["pt", "en"]


def test_list_institutions_without_token_returns_401(client: TestClient) -> None:
    response = client.get("/api/v1/institutions")
    assert response.status_code == 401


def test_get_institution_without_token_returns_401(client: TestClient) -> None:
    response = client.get(f"/api/v1/institutions/{uuid.uuid4()}")
    assert response.status_code == 401


def test_update_institution_without_token_returns_401(client: TestClient) -> None:
    response = client.patch(
        f"/api/v1/institutions/{uuid.uuid4()}",
        json={"name": "Hacked"},
    )
    assert response.status_code == 401


def test_admin_lists_only_own_institution(client: TestClient) -> None:
    institution = _create_institution(client)
    other = _create_institution(client)
    headers = _create_admin_and_login(client, institution["id"])

    response = client.get("/api/v1/institutions", headers=headers)
    assert response.status_code == 200

    body = response.json()
    assert body["total"] == 1
    assert [item["id"] for item in body["items"]] == [institution["id"]]
    assert other["id"] not in [item["id"] for item in body["items"]]


def test_admin_can_get_own_institution(client: TestClient) -> None:
    institution = _create_institution(client)
    headers = _create_admin_and_login(client, institution["id"])

    response = client.get(f"/api/v1/institutions/{institution['id']}", headers=headers)
    assert response.status_code == 200
    assert response.json()["id"] == institution["id"]


def test_admin_can_update_own_institution(client: TestClient) -> None:
    institution = _create_institution(client)
    headers = _create_admin_and_login(client, institution["id"])

    response = client.patch(
        f"/api/v1/institutions/{institution['id']}",
        json={"name": "Renamed Institution"},
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["name"] == "Renamed Institution"


def test_admin_cannot_get_other_institution_returns_404(client: TestClient) -> None:
    own = _create_institution(client)
    other = _create_institution(client)
    headers = _create_admin_and_login(client, own["id"])

    response = client.get(f"/api/v1/institutions/{other['id']}", headers=headers)
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "resource_not_found"


def test_admin_cannot_update_other_institution_returns_404(client: TestClient) -> None:
    own = _create_institution(client)
    other = _create_institution(client)
    headers = _create_admin_and_login(client, own["id"])

    response = client.patch(
        f"/api/v1/institutions/{other['id']}",
        json={"name": "Hacked Name"},
        headers=headers,
    )
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "resource_not_found"


def test_update_rejects_default_language_outside_supported(client: TestClient) -> None:
    institution = _create_institution(client)
    headers = _create_admin_and_login(client, institution["id"])

    response = client.patch(
        f"/api/v1/institutions/{institution['id']}",
        json={"default_language": "fr"},
        headers=headers,
    )
    assert response.status_code == 422


def test_update_rejects_invalid_language_configuration(client: TestClient) -> None:
    institution = _create_institution(client)
    headers = _create_admin_and_login(client, institution["id"])

    response = client.patch(
        f"/api/v1/institutions/{institution['id']}",
        json={"supported_languages": ["en"]},
        headers=headers,
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "domain_validation_error"


def test_update_to_existing_code_returns_409(client: TestClient) -> None:
    other = _create_institution(client)
    own = _create_institution(client)
    headers = _create_admin_and_login(client, own["id"])

    response = client.patch(
        f"/api/v1/institutions/{own['id']}",
        json={"code": other["code"]},
        headers=headers,
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "resource_conflict"
