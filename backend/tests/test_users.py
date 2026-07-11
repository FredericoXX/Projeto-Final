"""Tests for user creation, retrieval, listing and update, scoped to the
authenticated admin's institution.

Runs against the dedicated test database (see conftest.py). The
autouse `_clean_tables` fixture truncates every table before each
test, so tests don't need to track or delete the rows they create.
"""

import threading
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.core.exceptions import AuthorizationError, ConflictError
from app.models.institution import Institution
from app.models.user import User
from app.schemas.user import UserUpdate
from app.services import user_service

_USER_PASSWORD = "anothersecret123"
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


def _register_admin(client: TestClient, institution_id: str, **overrides: object) -> dict:
    """Registers an admin for the institution and returns the created user body."""
    payload: dict = {
        "institution_id": institution_id,
        "full_name": "Admin User",
        "email": f"admin-{uuid.uuid4().hex[:8]}@example.com",
        "password": _ADMIN_PASSWORD,
    }
    payload.update(overrides)
    response = client.post(
        "/api/v1/auth/register-initial-admin", json=payload, headers=BOOTSTRAP_HEADERS
    )
    assert response.status_code == 201
    return {**response.json(), "email": payload["email"], "password": payload["password"]}


def _login(client: TestClient, email: str, password: str) -> dict[str, str]:
    login = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200
    token = login.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _create_admin_and_login(client: TestClient, institution_id: str) -> dict[str, str]:
    """Registers the institution's initial admin and returns auth headers for it."""
    admin = _register_admin(client, institution_id)
    return _login(client, admin["email"], admin["password"])


def _create_second_admin_and_login(
    client: TestClient, institution_id: str, admin_headers: dict[str, str]
) -> tuple[dict, dict[str, str]]:
    """Creates a second admin (via POST /users, as an already-authenticated
    admin) and returns its user body and auth headers."""
    email = f"second-admin-{uuid.uuid4().hex[:8]}@example.com"
    created = client.post(
        "/api/v1/users",
        json={
            "full_name": "Second Admin",
            "email": email,
            "password": _ADMIN_PASSWORD,
            "role": "admin",
        },
        headers=admin_headers,
    )
    assert created.status_code == 201
    return created.json(), _login(client, email, _ADMIN_PASSWORD)


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


def test_admin_cannot_deactivate_own_account(client: TestClient) -> None:
    """Only an active admin can authenticate at all, so when an institution
    has a single active admin, any deactivation attempt on that admin is
    necessarily a self-deactivation attempt: this is the reachable form of
    both "an admin cannot deactivate itself" and "the last active admin
    cannot be deactivated"."""
    institution_id = _create_institution(client)
    admin = _register_admin(client, institution_id)
    headers = _login(client, admin["email"], admin["password"])

    response = client.patch(
        f"/api/v1/users/{admin['id']}",
        json={"is_active": False},
        headers=headers,
    )
    assert response.status_code == 403


def test_last_active_admin_role_cannot_be_changed(client: TestClient) -> None:
    institution_id = _create_institution(client)
    admin = _register_admin(client, institution_id)
    headers = _login(client, admin["email"], admin["password"])

    response = client.patch(
        f"/api/v1/users/{admin['id']}",
        json={"role": "staff"},
        headers=headers,
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "resource_conflict"


def test_admin_can_deactivate_other_admin_when_two_are_active(client: TestClient) -> None:
    institution_id = _create_institution(client)
    admin = _register_admin(client, institution_id)
    headers = _login(client, admin["email"], admin["password"])
    second_admin, _second_headers = _create_second_admin_and_login(
        client, institution_id, headers
    )

    response = client.patch(
        f"/api/v1/users/{second_admin['id']}",
        json={"is_active": False},
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["is_active"] is False


def test_concurrent_admin_deactivation_keeps_at_least_one_active_admin(
    test_session_factory: sessionmaker[Session],
) -> None:
    """Two admins, A and B, both active. Two threads race to deactivate
    *the other* admin at the same time, each using its own SQLAlchemy
    session/connection against the real test PostgreSQL database (not a
    mock). The SELECT ... FOR UPDATE lock taken on the institution row
    inside user_service.update_user must serialize these two attempts:
    whichever transaction commits first leaves the other admin as the
    institution's last active admin, so the second transaction's active
    admin count (re-read after the lock, i.e. after the first commit) must
    then correctly refuse it. At most one of the two operations may
    succeed, and the institution must never end up with zero active
    admins."""
    setup_session = test_session_factory()
    try:
        institution = Institution(
            name="Concurrency Test Institution",
            code=f"CONC-{uuid.uuid4().hex[:8].upper()}",
            default_language="pt",
            supported_languages=["pt", "en"],
        )
        setup_session.add(institution)
        setup_session.flush()

        admin_a = User(
            institution_id=institution.id,
            full_name="Admin A",
            email=f"admin-a-{uuid.uuid4().hex[:8]}@example.com",
            password_hash="not-a-real-hash",
            role="admin",
            is_active=True,
        )
        admin_b = User(
            institution_id=institution.id,
            full_name="Admin B",
            email=f"admin-b-{uuid.uuid4().hex[:8]}@example.com",
            password_hash="not-a-real-hash",
            role="admin",
            is_active=True,
        )
        setup_session.add_all([admin_a, admin_b])
        setup_session.commit()
        institution_id, admin_a_id, admin_b_id = institution.id, admin_a.id, admin_b.id
    finally:
        setup_session.close()

    outcomes: list[str] = []
    outcomes_lock = threading.Lock()
    barrier = threading.Barrier(2)

    def deactivate(acting_admin_id: uuid.UUID, target_id: uuid.UUID) -> None:
        session = test_session_factory()
        try:
            acting_admin = session.get(User, acting_admin_id)
            assert acting_admin is not None
            barrier.wait()
            try:
                user_service.update_user(
                    session, acting_admin, target_id, UserUpdate(is_active=False)
                )
                outcome = "ok"
            except ConflictError:
                outcome = "conflict"
            except AuthorizationError:
                outcome = "forbidden"
            with outcomes_lock:
                outcomes.append(outcome)
        finally:
            session.close()

    # Thread 1: A deactivates B. Thread 2: B deactivates A. Neither is a
    # self-deactivation attempt.
    t1 = threading.Thread(target=deactivate, args=(admin_a_id, admin_b_id))
    t2 = threading.Thread(target=deactivate, args=(admin_b_id, admin_a_id))
    t1.start()
    t2.start()
    t1.join(timeout=10)
    t2.join(timeout=10)

    assert outcomes.count("ok") == 1
    assert outcomes.count("conflict") == 1

    verify_session = test_session_factory()
    try:
        active_admins = verify_session.scalars(
            select(User).where(
                User.institution_id == institution_id,
                User.role == "admin",
                User.is_active.is_(True),
            )
        ).all()
        assert len(active_admins) == 1
    finally:
        verify_session.close()
