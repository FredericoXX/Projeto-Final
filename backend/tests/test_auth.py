"""Tests for authentication: initial admin registration, login and /me.

Runs against the dedicated test database (see conftest.py). The
autouse `_clean_tables` fixture truncates every table before each
test, so tests don't need to track or delete the rows they create.
"""

import uuid

from fastapi.testclient import TestClient

from app.core.config import settings

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
        "/api/v1/institutions", json=_institution_payload(**overrides), headers=BOOTSTRAP_HEADERS
    )
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


def test_register_initial_admin_without_bootstrap_token_returns_401(client: TestClient) -> None:
    institution_id = _create_institution(client)
    payload = _register_admin_payload(institution_id)

    response = client.post("/api/v1/auth/register-initial-admin", json=payload)
    assert response.status_code == 401


def test_register_initial_admin_creates_admin(client: TestClient) -> None:
    institution_id = _create_institution(client)
    payload = _register_admin_payload(institution_id)

    response = client.post(
        "/api/v1/auth/register-initial-admin", json=payload, headers=BOOTSTRAP_HEADERS
    )
    assert response.status_code == 201

    body = response.json()
    assert body["role"] == "admin"
    assert body["institution_id"] == institution_id
    assert body["email"] == payload["email"]
    assert "password_hash" not in body
    assert "password" not in body


def test_register_initial_admin_fails_if_institution_not_found(client: TestClient) -> None:
    payload = _register_admin_payload(str(uuid.uuid4()))

    response = client.post(
        "/api/v1/auth/register-initial-admin", json=payload, headers=BOOTSTRAP_HEADERS
    )
    assert response.status_code == 404


def test_register_initial_admin_fails_if_institution_already_has_admin(
    client: TestClient,
) -> None:
    institution_id = _create_institution(client)
    first = client.post(
        "/api/v1/auth/register-initial-admin",
        json=_register_admin_payload(institution_id),
        headers=BOOTSTRAP_HEADERS,
    )
    assert first.status_code == 201

    second = client.post(
        "/api/v1/auth/register-initial-admin",
        json=_register_admin_payload(institution_id),
        headers=BOOTSTRAP_HEADERS,
    )
    assert second.status_code == 409


def test_register_initial_admin_concurrent_requests_create_only_one_admin(
    client: TestClient,
) -> None:
    """The row lock (SELECT ... FOR UPDATE) taken on the institution inside
    register_initial_admin serializes concurrent registrations for the
    same institution, so only one of two racing requests can succeed."""
    import threading

    institution_id = _create_institution(client)
    results: list[int] = []
    lock = threading.Lock()

    def register(index: int) -> None:
        response = client.post(
            "/api/v1/auth/register-initial-admin",
            json=_register_admin_payload(
                institution_id, email=f"racer-{index}-{uuid.uuid4().hex[:8]}@example.com"
            ),
            headers=BOOTSTRAP_HEADERS,
        )
        with lock:
            results.append(response.status_code)

    threads = [threading.Thread(target=register, args=(i,)) for i in range(5)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert results.count(201) == 1
    assert results.count(409) == len(results) - 1


def test_login_with_valid_credentials_returns_token(client: TestClient) -> None:
    institution_id = _create_institution(client)
    payload = _register_admin_payload(institution_id)
    client.post(
        "/api/v1/auth/register-initial-admin", json=payload, headers=BOOTSTRAP_HEADERS
    )

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
    client.post(
        "/api/v1/auth/register-initial-admin", json=payload, headers=BOOTSTRAP_HEADERS
    )

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
    client.post(
        "/api/v1/auth/register-initial-admin", json=payload, headers=BOOTSTRAP_HEADERS
    )

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
    register_response = client.post(
        "/api/v1/auth/register-initial-admin", json=payload, headers=BOOTSTRAP_HEADERS
    )
    admin_id = register_response.json()["id"]

    login_response = client.post(
        "/api/v1/auth/login",
        json={"email": payload["email"], "password": payload["password"]},
    )
    token = login_response.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Um segundo admin é necessário: o próprio admin já não se pode
    # desativar (ver test_users.py), por isso é outro admin ativo que o
    # faz. register-initial-admin só cria o primeiro admin de uma
    # instituição, por isso o segundo é criado via POST /users.
    second_admin_email = f"second-admin-{uuid.uuid4().hex[:8]}@example.com"
    client.post(
        "/api/v1/users",
        json={
            "full_name": "Second Admin",
            "email": second_admin_email,
            "password": "anothersecret123",
            "role": "admin",
        },
        headers=headers,
    )
    second_login = client.post(
        "/api/v1/auth/login",
        json={"email": second_admin_email, "password": "anothersecret123"},
    )
    second_admin_headers = {
        "Authorization": f"Bearer {second_login.json()['access_token']}"
    }

    deactivate_response = client.patch(
        f"/api/v1/users/{admin_id}",
        json={"is_active": False},
        headers=second_admin_headers,
    )
    assert deactivate_response.status_code == 200

    second_login_attempt = client.post(
        "/api/v1/auth/login",
        json={"email": payload["email"], "password": payload["password"]},
    )
    assert second_login_attempt.status_code == 401

    me_response = client.get("/api/v1/auth/me", headers=headers)
    assert me_response.status_code == 401


def _login_headers(client: TestClient, payload: dict) -> dict[str, str]:
    login = client.post(
        "/api/v1/auth/login",
        json={"email": payload["email"], "password": payload["password"]},
    )
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _deactivate_institution(client: TestClient, institution_id: str) -> None:
    # is_active só pode ser alterado pelo endpoint de bootstrap (ver
    # test_institutions.py) — um admin institucional já não o consegue
    # fazer através de PATCH /institutions/{id}.
    response = client.patch(
        f"/api/v1/bootstrap/institutions/{institution_id}/status",
        json={"is_active": False},
        headers=BOOTSTRAP_HEADERS,
    )
    assert response.status_code == 200


def test_login_fails_when_institution_is_inactive(client: TestClient) -> None:
    institution_id = _create_institution(client)
    payload = _register_admin_payload(institution_id)
    client.post(
        "/api/v1/auth/register-initial-admin", json=payload, headers=BOOTSTRAP_HEADERS
    )

    _deactivate_institution(client, institution_id)

    response = client.post(
        "/api/v1/auth/login",
        json={"email": payload["email"], "password": payload["password"]},
    )
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "authentication_failed"


def test_me_fails_when_institution_is_inactive(client: TestClient) -> None:
    institution_id = _create_institution(client)
    payload = _register_admin_payload(institution_id)
    client.post(
        "/api/v1/auth/register-initial-admin", json=payload, headers=BOOTSTRAP_HEADERS
    )
    headers = _login_headers(client, payload)

    still_works = client.get("/api/v1/auth/me", headers=headers)
    assert still_works.status_code == 200

    _deactivate_institution(client, institution_id)

    response = client.get("/api/v1/auth/me", headers=headers)
    assert response.status_code == 401


# --- Admin inicial em instituição inativa -------------------------------


def test_register_initial_admin_fails_if_institution_is_inactive(client: TestClient) -> None:
    institution_id = _create_institution(client)
    _deactivate_institution(client, institution_id)

    response = client.post(
        "/api/v1/auth/register-initial-admin",
        json=_register_admin_payload(institution_id),
        headers=BOOTSTRAP_HEADERS,
    )
    assert response.status_code == 409


def test_register_initial_admin_creates_no_user_when_institution_is_inactive(
    client: TestClient,
) -> None:
    institution_id = _create_institution(client)
    _deactivate_institution(client, institution_id)

    payload = _register_admin_payload(institution_id)
    response = client.post(
        "/api/v1/auth/register-initial-admin", json=payload, headers=BOOTSTRAP_HEADERS
    )
    assert response.status_code == 409

    # Confirma que nenhuma linha de utilizador foi criada: reativar a
    # instituição e repetir o registo com o mesmo email deve continuar a
    # funcionar, o que só é possível se o primeiro pedido não tiver criado
    # (nem parcialmente) o utilizador.
    client.patch(
        f"/api/v1/bootstrap/institutions/{institution_id}/status",
        json={"is_active": True},
        headers=BOOTSTRAP_HEADERS,
    )
    retry = client.post(
        "/api/v1/auth/register-initial-admin", json=payload, headers=BOOTSTRAP_HEADERS
    )
    assert retry.status_code == 201
    assert retry.json()["email"] == payload["email"]


def test_register_initial_admin_succeeds_when_institution_is_active(
    client: TestClient,
) -> None:
    institution_id = _create_institution(client)

    response = client.post(
        "/api/v1/auth/register-initial-admin",
        json=_register_admin_payload(institution_id),
        headers=BOOTSTRAP_HEADERS,
    )
    assert response.status_code == 201


# --- HTTP Bearer (Swagger "Authorize") ----------------------------------
#
# Login continua a ser JSON simples (email/password); apenas o esquema
# usado para proteger os restantes endpoints mudou de OAuth2PasswordBearer
# para HTTPBearer, para que o botão "Authorize" do Swagger peça só um
# token, em vez de tentar montar o fluxo OAuth2 por formulário.


def test_protected_endpoint_without_bearer_token_returns_401(client: TestClient) -> None:
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "authentication_failed"


def test_protected_endpoint_with_non_bearer_authorization_returns_401(
    client: TestClient,
) -> None:
    response = client.get(
        "/api/v1/auth/me", headers={"Authorization": "Basic dXNlcjpwYXNz"}
    )
    assert response.status_code == 401


def test_protected_endpoint_with_invalid_bearer_token_returns_401(client: TestClient) -> None:
    response = client.get(
        "/api/v1/auth/me", headers={"Authorization": "Bearer not-a-real-token"}
    )
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "authentication_failed"


def test_protected_endpoint_with_valid_bearer_token_works(client: TestClient) -> None:
    institution_id = _create_institution(client)
    payload = _register_admin_payload(institution_id)
    client.post(
        "/api/v1/auth/register-initial-admin", json=payload, headers=BOOTSTRAP_HEADERS
    )
    headers = _login_headers(client, payload)

    response = client.get("/api/v1/auth/me", headers=headers)
    assert response.status_code == 200
    assert response.json()["email"] == payload["email"]


def test_openapi_declares_http_bearer_not_oauth2_password(client: TestClient) -> None:
    response = client.get("/openapi.json")
    assert response.status_code == 200

    schemes = response.json()["components"]["securitySchemes"]
    assert len(schemes) == 1
    (scheme,) = schemes.values()
    assert scheme["type"] == "http"
    assert scheme["scheme"] == "bearer"
