"""Testes dos documentos lógicos: criação, listagem, filtros, atualização,
permissões e isolamento institucional.

Corre contra a base de dados de teste dedicada (ver conftest.py); a
fixture autouse `_clean_tables` trunca todas as tabelas antes de cada
teste e `_document_storage_tmp` redireciona o armazenamento para um
diretório temporário.
"""

import io
import uuid

from fastapi.testclient import TestClient

from app.core.config import settings

_ADMIN_PASSWORD = "supersecret123"
_USER_PASSWORD = "anothersecret123"

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


def _create_institution(client: TestClient, **overrides: object) -> str:
    response = client.post(
        "/api/v1/institutions",
        json=_institution_payload(**overrides),
        headers=BOOTSTRAP_HEADERS,
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
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _create_user_and_login(
    client: TestClient, admin_headers: dict[str, str]
) -> dict[str, str]:
    email = f"user-{uuid.uuid4().hex[:8]}@example.com"
    created = client.post(
        "/api/v1/users",
        json={
            "full_name": "Regular User",
            "email": email,
            "password": _USER_PASSWORD,
            "role": "staff",
        },
        headers=admin_headers,
    )
    assert created.status_code == 201

    login = client.post(
        "/api/v1/auth/login", json={"email": email, "password": _USER_PASSWORD}
    )
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _document_payload(**overrides: object) -> dict:
    payload: dict = {"title": "Test Document"}
    payload.update(overrides)
    return payload


def _create_document(client: TestClient, headers: dict[str, str], **overrides: object) -> dict:
    response = client.post(
        "/api/v1/documents", json=_document_payload(**overrides), headers=headers
    )
    assert response.status_code == 201
    return response.json()


def _upload_version(
    client: TestClient,
    headers: dict[str, str],
    document_id: str,
    content: bytes = b"some text content",
    filename: str = "notes.txt",
    content_type: str = "text/plain",
):
    return client.post(
        f"/api/v1/documents/{document_id}/versions",
        files={"file": (filename, io.BytesIO(content), content_type)},
        headers=headers,
    )


# --- Criação --------------------------------------------------------------


def test_create_document_requires_auth(client: TestClient) -> None:
    response = client.post("/api/v1/documents", json=_document_payload())
    assert response.status_code == 401


def test_create_document_forbidden_for_non_admin(client: TestClient) -> None:
    institution_id = _create_institution(client)
    admin_headers = _create_admin_and_login(client, institution_id)
    user_headers = _create_user_and_login(client, admin_headers)

    response = client.post(
        "/api/v1/documents", json=_document_payload(), headers=user_headers
    )
    assert response.status_code == 403


def test_create_document_assigns_institution_and_creator(client: TestClient) -> None:
    institution_id = _create_institution(client)
    headers = _create_admin_and_login(client, institution_id)

    me = client.get("/api/v1/auth/me", headers=headers)
    admin_id = me.json()["id"]

    body = _create_document(client, headers, title="  Regulamento Académico  ")
    assert body["institution_id"] == institution_id
    assert body["created_by_user_id"] == admin_id
    assert body["title"] == "Regulamento Académico"
    assert body["is_active"] is True
    assert body["official_source"] is False


def test_create_document_without_language_uses_institution_default(
    client: TestClient,
) -> None:
    institution_id = _create_institution(client)
    headers = _create_admin_and_login(client, institution_id)

    body = _create_document(client, headers)
    assert body["language"] == "pt"


def test_create_document_with_supported_language_works(client: TestClient) -> None:
    institution_id = _create_institution(client)
    headers = _create_admin_and_login(client, institution_id)

    body = _create_document(client, headers, language="en")
    assert body["language"] == "en"


def test_create_document_with_unsupported_language_returns_422(client: TestClient) -> None:
    institution_id = _create_institution(client)
    headers = _create_admin_and_login(client, institution_id)

    response = client.post(
        "/api/v1/documents", json=_document_payload(language="fr"), headers=headers
    )
    assert response.status_code == 422


def test_create_document_with_valid_validity_range(client: TestClient) -> None:
    institution_id = _create_institution(client)
    headers = _create_admin_and_login(client, institution_id)

    body = _create_document(
        client, headers, valid_from="2026-01-01", valid_until="2026-12-31"
    )
    assert body["valid_from"] == "2026-01-01"
    assert body["valid_until"] == "2026-12-31"


def test_create_document_with_invalid_validity_range_returns_422(
    client: TestClient,
) -> None:
    institution_id = _create_institution(client)
    headers = _create_admin_and_login(client, institution_id)

    response = client.post(
        "/api/v1/documents",
        json=_document_payload(valid_from="2026-12-31", valid_until="2026-01-01"),
        headers=headers,
    )
    assert response.status_code == 422


def test_create_document_rejects_unknown_fields(client: TestClient) -> None:
    institution_id = _create_institution(client)
    headers = _create_admin_and_login(client, institution_id)

    response = client.post(
        "/api/v1/documents",
        json=_document_payload(institution_id=str(uuid.uuid4())),
        headers=headers,
    )
    assert response.status_code == 422


def test_create_document_rejects_non_http_source_url(client: TestClient) -> None:
    institution_id = _create_institution(client)
    headers = _create_admin_and_login(client, institution_id)

    response = client.post(
        "/api/v1/documents",
        json=_document_payload(source_url="ftp://example.com/file.pdf"),
        headers=headers,
    )
    assert response.status_code == 422


def test_create_document_rejects_blank_title(client: TestClient) -> None:
    institution_id = _create_institution(client)
    headers = _create_admin_and_login(client, institution_id)

    response = client.post(
        "/api/v1/documents", json=_document_payload(title="   "), headers=headers
    )
    assert response.status_code == 422


# --- Listagem e isolamento -------------------------------------------------


def test_list_documents_returns_only_own_institution(client: TestClient) -> None:
    institution_a = _create_institution(client)
    headers_a = _create_admin_and_login(client, institution_a)
    _create_document(client, headers_a, title="Doc A")

    institution_b = _create_institution(client)
    headers_b = _create_admin_and_login(client, institution_b)
    _create_document(client, headers_b, title="Doc B")

    response = client.get("/api/v1/documents", headers=headers_a)
    assert response.status_code == 200

    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["title"] == "Doc A"
    assert all(item["institution_id"] == institution_a for item in body["items"])


def test_list_documents_filters(client: TestClient) -> None:
    institution_id = _create_institution(client)
    headers = _create_admin_and_login(client, institution_id)

    _create_document(client, headers, title="Oficial PT", official_source=True)
    inactive = _create_document(client, headers, title="Inativo", language="en")
    client.patch(
        f"/api/v1/documents/{inactive['id']}",
        json={"is_active": False},
        headers=headers,
    )
    _create_document(client, headers, title="Normal EN", language="en")

    by_official = client.get("/api/v1/documents?official_source=true", headers=headers)
    assert by_official.json()["total"] == 1
    assert by_official.json()["items"][0]["title"] == "Oficial PT"

    by_active = client.get("/api/v1/documents?is_active=false", headers=headers)
    assert by_active.json()["total"] == 1
    assert by_active.json()["items"][0]["title"] == "Inativo"

    by_language = client.get("/api/v1/documents?language=en", headers=headers)
    assert by_language.json()["total"] == 2

    combined = client.get(
        "/api/v1/documents?language=en&is_active=true", headers=headers
    )
    assert combined.json()["total"] == 1
    assert combined.json()["items"][0]["title"] == "Normal EN"


def test_get_document_from_other_institution_returns_404(client: TestClient) -> None:
    institution_a = _create_institution(client)
    headers_a = _create_admin_and_login(client, institution_a)
    document = _create_document(client, headers_a)

    institution_b = _create_institution(client)
    headers_b = _create_admin_and_login(client, institution_b)

    response = client.get(f"/api/v1/documents/{document['id']}", headers=headers_b)
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "resource_not_found"


# --- Atualização ------------------------------------------------------------


def test_update_document_works(client: TestClient) -> None:
    institution_id = _create_institution(client)
    headers = _create_admin_and_login(client, institution_id)
    document = _create_document(client, headers)

    response = client.patch(
        f"/api/v1/documents/{document['id']}",
        json={
            "title": "Updated Title",
            "description": "Nova descrição",
            "official_source": True,
        },
        headers=headers,
    )
    assert response.status_code == 200

    body = response.json()
    assert body["title"] == "Updated Title"
    assert body["description"] == "Nova descrição"
    assert body["official_source"] is True


def test_update_document_deactivation_works(client: TestClient) -> None:
    institution_id = _create_institution(client)
    headers = _create_admin_and_login(client, institution_id)
    document = _create_document(client, headers)

    response = client.patch(
        f"/api/v1/documents/{document['id']}",
        json={"is_active": False},
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["is_active"] is False


def test_update_document_from_other_institution_returns_404(client: TestClient) -> None:
    institution_a = _create_institution(client)
    headers_a = _create_admin_and_login(client, institution_a)
    document = _create_document(client, headers_a)

    institution_b = _create_institution(client)
    headers_b = _create_admin_and_login(client, institution_b)

    response = client.patch(
        f"/api/v1/documents/{document['id']}",
        json={"title": "Hacked"},
        headers=headers_b,
    )
    assert response.status_code == 404


def test_update_document_rejects_invalid_final_validity_range(client: TestClient) -> None:
    institution_id = _create_institution(client)
    headers = _create_admin_and_login(client, institution_id)
    document = _create_document(client, headers, valid_until="2026-06-30")

    # O payload só traz valid_from, mas o estado final (com o valid_until
    # já existente) fica inválido.
    response = client.patch(
        f"/api/v1/documents/{document['id']}",
        json={"valid_from": "2026-07-15"},
        headers=headers,
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "domain_validation_error"


def test_update_document_rejects_unknown_fields(client: TestClient) -> None:
    institution_id = _create_institution(client)
    headers = _create_admin_and_login(client, institution_id)
    document = _create_document(client, headers)

    response = client.patch(
        f"/api/v1/documents/{document['id']}",
        json={"created_by_user_id": str(uuid.uuid4())},
        headers=headers,
    )
    assert response.status_code == 422


def test_update_language_without_versions_works(client: TestClient) -> None:
    institution_id = _create_institution(client)
    headers = _create_admin_and_login(client, institution_id)
    document = _create_document(client, headers)

    response = client.patch(
        f"/api/v1/documents/{document['id']}",
        json={"language": "en"},
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["language"] == "en"


def test_update_language_after_version_exists_returns_409(client: TestClient) -> None:
    institution_id = _create_institution(client)
    headers = _create_admin_and_login(client, institution_id)
    document = _create_document(client, headers)

    upload = _upload_version(client, headers, document["id"])
    assert upload.status_code == 201

    response = client.patch(
        f"/api/v1/documents/{document['id']}",
        json={"language": "en"},
        headers=headers,
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "resource_conflict"


def test_update_language_to_unsupported_returns_422(client: TestClient) -> None:
    institution_id = _create_institution(client)
    headers = _create_admin_and_login(client, institution_id)
    document = _create_document(client, headers)

    response = client.patch(
        f"/api/v1/documents/{document['id']}",
        json={"language": "fr"},
        headers=headers,
    )
    assert response.status_code == 422
