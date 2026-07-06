"""Tests for institution creation, retrieval, listing and update.

Runs against the dedicated test database (see conftest.py). The
autouse `_clean_tables` fixture truncates every table before each
test, so tests don't need to track or delete the rows they create.
"""

import uuid

from fastapi.testclient import TestClient


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

# Test the creation of a new institution
def test_create_institution(client: TestClient) -> None:
    payload = _payload()
    response = client.post("/api/v1/institutions", json=payload)
    assert response.status_code == 201

    body = response.json()
    assert body["name"] == payload["name"]
    assert body["code"] == payload["code"]
    assert body["default_language"] == "pt"
    assert body["supported_languages"] == ["pt", "en"]
    assert body["is_active"] is True
    assert "created_at" in body
    assert "updated_at" in body

# Test that creating an institution with a duplicate code returns a 409 Conflict    
def test_create_institution_duplicate_code_returns_409(client: TestClient) -> None:
    payload = _payload()
    first = client.post("/api/v1/institutions", json=payload)
    assert first.status_code == 201

    second = client.post("/api/v1/institutions", json=payload)
    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "resource_conflict"

# Test that creating an institution with a default language not in the supported languages returns a 422 Unprocessable Entity
def test_create_institution_rejects_unsupported_default_language(client: TestClient) -> None:
    payload = _payload(default_language="fr", supported_languages=["pt", "en"])
    response = client.post("/api/v1/institutions", json=payload)
    assert response.status_code == 422


def test_create_institution_rejects_whitespace_only_code(client: TestClient) -> None:
    payload = _payload(code="   ")
    response = client.post("/api/v1/institutions", json=payload)
    assert response.status_code == 422


def test_create_institution_rejects_whitespace_only_name(client: TestClient) -> None:
    payload = _payload(name="   ")
    response = client.post("/api/v1/institutions", json=payload)
    assert response.status_code == 422


def test_create_institution_normalizes_duplicate_languages(client: TestClient) -> None:
    payload = _payload(
        default_language="PT",
        supported_languages=["pt", "PT", "pt", "en", "EN"],
    )
    response = client.post("/api/v1/institutions", json=payload)
    assert response.status_code == 201
    assert response.json()["supported_languages"] == ["pt", "en"]


def test_get_institution(client: TestClient) -> None:
    created = client.post("/api/v1/institutions", json=_payload())
    institution_id = created.json()["id"]

    response = client.get(f"/api/v1/institutions/{institution_id}")
    assert response.status_code == 200
    assert response.json()["id"] == institution_id


def test_get_institution_not_found_returns_404(client: TestClient) -> None:
    response = client.get(f"/api/v1/institutions/{uuid.uuid4()}")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "resource_not_found"


def test_list_institutions_contains_created(client: TestClient) -> None:
    created = client.post("/api/v1/institutions", json=_payload())
    institution_id = created.json()["id"]

    response = client.get("/api/v1/institutions", params={"limit": 100})
    assert response.status_code == 200

    body = response.json()
    assert body["total"] >= 1
    assert any(item["id"] == institution_id for item in body["items"])


def test_list_institutions_total_matches_created_count(client: TestClient) -> None:
    for _ in range(3):
        client.post("/api/v1/institutions", json=_payload())

    response = client.get("/api/v1/institutions", params={"limit": 100})
    assert response.status_code == 200
    assert response.json()["total"] == 3


def test_update_institution_name(client: TestClient) -> None:
    created = client.post("/api/v1/institutions", json=_payload())
    institution_id = created.json()["id"]

    response = client.patch(
        f"/api/v1/institutions/{institution_id}",
        json={"name": "Renamed Institution"},
    )
    assert response.status_code == 200
    assert response.json()["name"] == "Renamed Institution"


def test_update_rejects_default_language_outside_supported(client: TestClient) -> None:
    created = client.post("/api/v1/institutions", json=_payload())
    institution_id = created.json()["id"]

    response = client.patch(
        f"/api/v1/institutions/{institution_id}",
        json={"default_language": "fr"},
    )
    assert response.status_code == 422


def test_update_rejects_invalid_language_configuration(client: TestClient) -> None:
    created = client.post("/api/v1/institutions", json=_payload())
    institution_id = created.json()["id"]

    response = client.patch(
        f"/api/v1/institutions/{institution_id}",
        json={"supported_languages": ["en"]},
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "domain_validation_error"


def test_update_to_existing_code_returns_409(client: TestClient) -> None:
    first = client.post("/api/v1/institutions", json=_payload())
    second = client.post("/api/v1/institutions", json=_payload())
    second_id = second.json()["id"]

    response = client.patch(
        f"/api/v1/institutions/{second_id}",
        json={"code": first.json()["code"]},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "resource_conflict"
