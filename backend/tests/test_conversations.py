"""Tests for conversations and messages, scoped to the authenticated
user's institution and, for regular users, to their own conversations.

Runs against the dedicated test database (see conftest.py). The
autouse `_clean_tables` fixture truncates every table before each
test, so tests don't need to track or delete the rows they create.
"""

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


def _create_institution(client: TestClient) -> str:
    response = client.post(
        "/api/v1/institutions", json=_institution_payload(), headers=BOOTSTRAP_HEADERS
    )
    assert response.status_code == 201
    return response.json()["id"]


def _create_admin_and_login(client: TestClient, institution_id: str) -> dict[str, str]:
    """Registers the institution's initial admin and returns auth headers for it."""
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


def _create_user_and_login(
    client: TestClient, admin_headers: dict[str, str]
) -> dict[str, str]:
    """Creates a regular user (as the admin) and returns auth headers for it."""
    email = f"user-{uuid.uuid4().hex[:8]}@example.com"
    created = client.post(
        "/api/v1/users",
        json={
            "full_name": "Regular User",
            "email": email,
            "password": _USER_PASSWORD,
            "role": "student",
        },
        headers=admin_headers,
    )
    assert created.status_code == 201

    login = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": _USER_PASSWORD},
    )
    assert login.status_code == 200
    token = login.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _create_conversation(client: TestClient, headers: dict[str, str], **overrides: object) -> dict:
    payload: dict = {"title": "Test Conversation", "language": "pt"}
    payload.update(overrides)
    response = client.post("/api/v1/conversations", json=payload, headers=headers)
    assert response.status_code == 201
    return response.json()


def test_create_conversation_requires_auth(client: TestClient) -> None:
    response = client.post("/api/v1/conversations", json={"title": "Hello"})
    assert response.status_code == 401


def test_create_conversation_assigns_institution_and_user(client: TestClient) -> None:
    institution_id = _create_institution(client)
    admin_headers = _create_admin_and_login(client, institution_id)
    user_headers = _create_user_and_login(client, admin_headers)

    me = client.get("/api/v1/auth/me", headers=user_headers)
    user_id = me.json()["id"]

    conversation = _create_conversation(client, user_headers)
    assert conversation["institution_id"] == institution_id
    assert conversation["user_id"] == user_id
    assert conversation["status"] == "active"
    assert conversation["title"] == "Test Conversation"


def test_list_conversations_regular_user_only_own(client: TestClient) -> None:
    institution_id = _create_institution(client)
    admin_headers = _create_admin_and_login(client, institution_id)

    user_a_headers = _create_user_and_login(client, admin_headers)
    user_b_headers = _create_user_and_login(client, admin_headers)

    _create_conversation(client, user_a_headers, title="User A conversation")
    _create_conversation(client, user_b_headers, title="User B conversation")

    response = client.get("/api/v1/conversations", headers=user_a_headers)
    assert response.status_code == 200

    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["title"] == "User A conversation"


def test_list_conversations_admin_lists_institution(client: TestClient) -> None:
    institution_id = _create_institution(client)
    admin_headers = _create_admin_and_login(client, institution_id)

    user_a_headers = _create_user_and_login(client, admin_headers)
    user_b_headers = _create_user_and_login(client, admin_headers)

    _create_conversation(client, user_a_headers, title="User A conversation")
    _create_conversation(client, user_b_headers, title="User B conversation")

    response = client.get("/api/v1/conversations", headers=admin_headers)
    assert response.status_code == 200
    assert response.json()["total"] == 2


def test_get_conversation_from_other_institution_returns_404(client: TestClient) -> None:
    institution_a = _create_institution(client)
    admin_a_headers = _create_admin_and_login(client, institution_a)
    conversation = _create_conversation(client, admin_a_headers)

    institution_b = _create_institution(client)
    admin_b_headers = _create_admin_and_login(client, institution_b)

    response = client.get(
        f"/api/v1/conversations/{conversation['id']}", headers=admin_b_headers
    )
    assert response.status_code == 404


def test_get_conversation_of_another_user_returns_404_for_regular_user(
    client: TestClient,
) -> None:
    institution_id = _create_institution(client)
    admin_headers = _create_admin_and_login(client, institution_id)

    user_a_headers = _create_user_and_login(client, admin_headers)
    user_b_headers = _create_user_and_login(client, admin_headers)

    conversation = _create_conversation(client, user_a_headers)

    response = client.get(
        f"/api/v1/conversations/{conversation['id']}", headers=user_b_headers
    )
    assert response.status_code == 404


def test_update_conversation_cannot_change_institution_or_user(client: TestClient) -> None:
    institution_id = _create_institution(client)
    admin_headers = _create_admin_and_login(client, institution_id)
    conversation = _create_conversation(client, admin_headers)

    response = client.patch(
        f"/api/v1/conversations/{conversation['id']}",
        json={"title": "Updated title", "status": "closed"},
        headers=admin_headers,
    )
    assert response.status_code == 200

    body = response.json()
    assert body["title"] == "Updated title"
    assert body["status"] == "closed"
    assert body["institution_id"] == institution_id


def test_create_message_requires_auth(client: TestClient) -> None:
    institution_id = _create_institution(client)
    admin_headers = _create_admin_and_login(client, institution_id)
    conversation = _create_conversation(client, admin_headers)

    response = client.post(
        f"/api/v1/conversations/{conversation['id']}/messages",
        json={"content": "Hello"},
    )
    assert response.status_code == 401


def test_create_message_in_conversation_from_other_institution_returns_404(
    client: TestClient,
) -> None:
    institution_a = _create_institution(client)
    admin_a_headers = _create_admin_and_login(client, institution_a)
    conversation = _create_conversation(client, admin_a_headers)

    institution_b = _create_institution(client)
    admin_b_headers = _create_admin_and_login(client, institution_b)

    response = client.post(
        f"/api/v1/conversations/{conversation['id']}/messages",
        json={"content": "Hello from another institution"},
        headers=admin_b_headers,
    )
    assert response.status_code == 404


def test_create_message_associates_conversation_institution_and_user(
    client: TestClient,
) -> None:
    institution_id = _create_institution(client)
    admin_headers = _create_admin_and_login(client, institution_id)
    user_headers = _create_user_and_login(client, admin_headers)

    me = client.get("/api/v1/auth/me", headers=user_headers)
    user_id = me.json()["id"]

    conversation = _create_conversation(client, user_headers)

    response = client.post(
        f"/api/v1/conversations/{conversation['id']}/messages",
        json={"content": "Hello assistant", "language": "pt"},
        headers=user_headers,
    )
    assert response.status_code == 201

    body = response.json()
    assert body["conversation_id"] == conversation["id"]
    assert body["institution_id"] == institution_id
    assert body["user_id"] == user_id
    assert body["role"] == "user"
    assert body["content"] == "Hello assistant"


def test_create_message_regular_user_cannot_use_system_role(client: TestClient) -> None:
    institution_id = _create_institution(client)
    admin_headers = _create_admin_and_login(client, institution_id)
    user_headers = _create_user_and_login(client, admin_headers)
    conversation = _create_conversation(client, user_headers)

    response = client.post(
        f"/api/v1/conversations/{conversation['id']}/messages",
        json={"content": "Trying to be system", "role": "system"},
        headers=user_headers,
    )
    assert response.status_code == 403


def test_create_message_admin_can_use_system_role(client: TestClient) -> None:
    institution_id = _create_institution(client)
    admin_headers = _create_admin_and_login(client, institution_id)
    conversation = _create_conversation(client, admin_headers)

    response = client.post(
        f"/api/v1/conversations/{conversation['id']}/messages",
        json={"content": "System note", "role": "system"},
        headers=admin_headers,
    )
    assert response.status_code == 201
    assert response.json()["role"] == "system"


def test_create_message_rejects_assistant_role(client: TestClient) -> None:
    institution_id = _create_institution(client)
    admin_headers = _create_admin_and_login(client, institution_id)
    conversation = _create_conversation(client, admin_headers)

    response = client.post(
        f"/api/v1/conversations/{conversation['id']}/messages",
        json={"content": "Auto reply", "role": "assistant"},
        headers=admin_headers,
    )
    assert response.status_code == 403


def test_list_messages_respects_institution_isolation(client: TestClient) -> None:
    institution_a = _create_institution(client)
    admin_a_headers = _create_admin_and_login(client, institution_a)
    conversation_a = _create_conversation(client, admin_a_headers)
    client.post(
        f"/api/v1/conversations/{conversation_a['id']}/messages",
        json={"content": "Message in institution A"},
        headers=admin_a_headers,
    )

    institution_b = _create_institution(client)
    admin_b_headers = _create_admin_and_login(client, institution_b)

    response = client.get(
        f"/api/v1/conversations/{conversation_a['id']}/messages", headers=admin_b_headers
    )
    assert response.status_code == 404


def test_list_messages_ordered_by_created_at_ascending(client: TestClient) -> None:
    institution_id = _create_institution(client)
    admin_headers = _create_admin_and_login(client, institution_id)
    conversation = _create_conversation(client, admin_headers)

    for text in ["first", "second", "third"]:
        client.post(
            f"/api/v1/conversations/{conversation['id']}/messages",
            json={"content": text},
            headers=admin_headers,
        )

    response = client.get(
        f"/api/v1/conversations/{conversation['id']}/messages", headers=admin_headers
    )
    assert response.status_code == 200

    body = response.json()
    assert body["total"] == 3
    assert [item["content"] for item in body["items"]] == ["first", "second", "third"]


def test_create_conversation_fails_when_institution_is_inactive(client: TestClient) -> None:
    institution_id = _create_institution(client)
    admin_headers = _create_admin_and_login(client, institution_id)

    deactivate = client.patch(
        f"/api/v1/institutions/{institution_id}",
        json={"is_active": False},
        headers=admin_headers,
    )
    assert deactivate.status_code == 200

    response = client.post(
        "/api/v1/conversations",
        json={"title": "Should not be created"},
        headers=admin_headers,
    )
    assert response.status_code == 401
