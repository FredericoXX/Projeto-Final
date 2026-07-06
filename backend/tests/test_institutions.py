"""Tests for institution creation, retrieval, listing and update.

Runs against the dedicated test database (see conftest.py), not the
development database. Each test uses a unique institution code and
cleans up the rows it creates, so repeated runs don't accumulate data.
"""

import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.main import app
from app.models.institution import Institution

client = TestClient(app)


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


@pytest.fixture
def created_ids(test_session_factory: sessionmaker[Session]) -> Iterator[list[str]]:
    ids: list[str] = []
    yield ids
    with test_session_factory() as db:
        for institution_id in ids:
            institution = db.get(Institution, uuid.UUID(institution_id))
            if institution is not None:
                db.delete(institution)
        db.commit()


def test_create_institution(created_ids: list[str]) -> None:
    payload = _payload()
    response = client.post("/api/v1/institutions", json=payload)
    assert response.status_code == 201

    body = response.json()
    created_ids.append(body["id"])

    assert body["name"] == payload["name"]
    assert body["code"] == payload["code"]
    assert body["default_language"] == "pt"
    assert body["supported_languages"] == ["pt", "en"]
    assert body["is_active"] is True
    assert "created_at" in body
    assert "updated_at" in body


def test_create_institution_duplicate_code_returns_409(
    created_ids: list[str],
) -> None:
    payload = _payload()
    first = client.post("/api/v1/institutions", json=payload)
    assert first.status_code == 201
    created_ids.append(first.json()["id"])

    second = client.post("/api/v1/institutions", json=payload)
    assert second.status_code == 409


def test_create_institution_rejects_unsupported_default_language() -> None:
    payload = _payload(default_language="fr", supported_languages=["pt", "en"])
    response = client.post("/api/v1/institutions", json=payload)
    assert response.status_code == 422


def test_get_institution(created_ids: list[str]) -> None:
    created = client.post("/api/v1/institutions", json=_payload())
    institution_id = created.json()["id"]
    created_ids.append(institution_id)

    response = client.get(f"/api/v1/institutions/{institution_id}")
    assert response.status_code == 200
    assert response.json()["id"] == institution_id


def test_get_institution_not_found_returns_404() -> None:
    response = client.get(f"/api/v1/institutions/{uuid.uuid4()}")
    assert response.status_code == 404


def test_list_institutions_contains_created(created_ids: list[str]) -> None:
    created = client.post("/api/v1/institutions", json=_payload())
    institution_id = created.json()["id"]
    created_ids.append(institution_id)

    response = client.get("/api/v1/institutions", params={"limit": 100})
    assert response.status_code == 200

    body = response.json()
    assert body["total"] >= 1
    assert any(item["id"] == institution_id for item in body["items"])


def test_update_institution_name(created_ids: list[str]) -> None:
    created = client.post("/api/v1/institutions", json=_payload())
    institution_id = created.json()["id"]
    created_ids.append(institution_id)

    response = client.patch(
        f"/api/v1/institutions/{institution_id}",
        json={"name": "Renamed Institution"},
    )
    assert response.status_code == 200
    assert response.json()["name"] == "Renamed Institution"


def test_update_rejects_default_language_outside_supported(
    created_ids: list[str],
) -> None:
    created = client.post("/api/v1/institutions", json=_payload())
    institution_id = created.json()["id"]
    created_ids.append(institution_id)

    response = client.patch(
        f"/api/v1/institutions/{institution_id}",
        json={"default_language": "fr"},
    )
    assert response.status_code == 422
