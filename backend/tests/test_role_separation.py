"""Separação de perfis: matriz de permissões e mudança do contrato de admin.

Fixa as quatro garantias deste incremento, todas verificadas no backend e não
apenas na interface:

- nenhum papel lê, lista, conta ou altera conversas de outra conta — o admin
  institucional incluído;
- a gestão documental pertence a ``knowledge_manager`` e deixou de ser uma
  permissão implícita de ``admin``;
- ``knowledge_manager`` não gere contas nem a instituição;
- o papel é sempre o persistido: alterações de papel e desativação produzem
  efeito no pedido seguinte, sem novo login.
"""

import io
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.core.exceptions import AuthenticationError, AuthorizationError
from app.core.permissions import (
    ROLE_PERMISSIONS,
    Permission,
    Role,
    has_permission,
    permissions_for_role,
)
from app.models.user import User
from app.schemas.message import MessageCreate
from app.services import message_service
from tests.role_support import create_account_and_login, create_knowledge_manager

BOOTSTRAP_HEADERS = {"X-Bootstrap-Token": settings.bootstrap_token or ""}
ADMIN_PASSWORD = "supersecret123"


def _create_institution(client: TestClient) -> str:
    response = client.post(
        "/api/v1/institutions",
        json={
            "name": "Role Separation Institution",
            "code": f"ROL-{uuid.uuid4().hex[:8].upper()}",
            "default_language": "pt",
            "supported_languages": ["pt", "en"],
        },
        headers=BOOTSTRAP_HEADERS,
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _create_admin(client: TestClient, institution_id: str) -> tuple[dict[str, str], str]:
    email = f"admin-{uuid.uuid4().hex[:8]}@example.com"
    registered = client.post(
        "/api/v1/auth/register-initial-admin",
        json={
            "institution_id": institution_id,
            "full_name": "Admin",
            "email": email,
            "password": ADMIN_PASSWORD,
        },
        headers=BOOTSTRAP_HEADERS,
    )
    assert registered.status_code == 201, registered.text
    login = client.post("/api/v1/auth/login", json={"email": email, "password": ADMIN_PASSWORD})
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}, registered.json()["id"]


def _create_conversation(client: TestClient, headers: dict[str, str]) -> dict:
    response = client.post("/api/v1/conversations", json={"title": "Minha"}, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def _create_document(client: TestClient, headers: dict[str, str]):
    return client.post("/api/v1/documents", json={"title": "Regulamento"}, headers=headers)


# --- Matriz ------------------------------------------------------------------


def test_matrix_covers_every_role_and_no_role_inherits_another() -> None:
    assert set(ROLE_PERMISSIONS) == set(Role)
    assert ROLE_PERMISSIONS[Role.ADMIN] == {
        Permission.USERS_MANAGE,
        Permission.INSTITUTION_MANAGE,
        Permission.EXTERNAL_IDENTITY_MANAGE,
        Permission.CONVERSATION_SYSTEM_MESSAGES,
    }
    assert ROLE_PERMISSIONS[Role.KNOWLEDGE_MANAGER] == {Permission.DOCUMENTS_MANAGE}
    assert ROLE_PERMISSIONS[Role.STAFF] == frozenset()
    assert ROLE_PERMISSIONS[Role.STUDENT] == {Permission.ACADEMIC_REQUESTS_READ_OWN}
    assert ROLE_PERMISSIONS[Role.USER] == {Permission.ACADEMIC_REQUESTS_READ_OWN}


def test_admin_no_longer_holds_document_management() -> None:
    assert not has_permission("admin", Permission.DOCUMENTS_MANAGE)
    assert not has_permission("admin", Permission.ACADEMIC_REQUESTS_READ_OWN)


def test_knowledge_manager_holds_no_account_or_individual_record_permission() -> None:
    granted = permissions_for_role("knowledge_manager")
    for permission in (
        Permission.USERS_MANAGE,
        Permission.INSTITUTION_MANAGE,
        Permission.EXTERNAL_IDENTITY_MANAGE,
        Permission.ACADEMIC_REQUESTS_READ_OWN,
    ):
        assert permission not in granted


def test_unknown_role_fails_closed() -> None:
    assert permissions_for_role("platform_admin") == frozenset()
    assert permissions_for_role("") == frozenset()


def test_no_permission_grants_reading_other_accounts_conversations() -> None:
    """Não existe, de todo, uma permissão de leitura de conversas alheias."""
    assert not any("conversations.read" in permission.value for permission in Permission)


def test_auth_me_exposes_the_permissions_of_the_persisted_role(client: TestClient) -> None:
    institution_id = _create_institution(client)
    admin_headers, _ = _create_admin(client, institution_id)
    manager_headers = create_knowledge_manager(client, admin_headers)

    admin_me = client.get("/api/v1/auth/me", headers=admin_headers).json()
    manager_me = client.get("/api/v1/auth/me", headers=manager_headers).json()

    assert admin_me["role"] == "admin"
    assert "documents.manage" not in admin_me["permissions"]
    assert "users.manage" in admin_me["permissions"]
    assert manager_me["role"] == "knowledge_manager"
    assert manager_me["permissions"] == ["documents.manage"]


# --- Criação do knowledge_manager ---------------------------------------------


def test_admin_creates_a_knowledge_manager_account(client: TestClient) -> None:
    institution_id = _create_institution(client)
    admin_headers, _ = _create_admin(client, institution_id)

    response = client.post(
        "/api/v1/users",
        json={
            "full_name": "Gestor Sintético",
            "email": f"km-{uuid.uuid4().hex[:8]}@example.com",
            "password": "kmsecret123",
            "role": "knowledge_manager",
        },
        headers=admin_headers,
    )

    assert response.status_code == 201
    assert response.json()["role"] == "knowledge_manager"
    assert response.json()["institution_id"] == institution_id


def test_unknown_role_is_still_rejected_on_creation(client: TestClient) -> None:
    institution_id = _create_institution(client)
    admin_headers, _ = _create_admin(client, institution_id)

    response = client.post(
        "/api/v1/users",
        json={
            "full_name": "Visitante",
            "email": f"visitor-{uuid.uuid4().hex[:8]}@example.com",
            "password": "visitor12345",
            "role": "visitor",
        },
        headers=admin_headers,
    )
    assert response.status_code == 422


def test_knowledge_manager_cannot_manage_accounts_or_institution(client: TestClient) -> None:
    institution_id = _create_institution(client)
    admin_headers, admin_id = _create_admin(client, institution_id)
    manager_headers = create_knowledge_manager(client, admin_headers)

    assert client.get("/api/v1/users", headers=manager_headers).status_code == 403
    assert client.get(f"/api/v1/users/{admin_id}", headers=manager_headers).status_code == 403
    created = client.post(
        "/api/v1/users",
        json={
            "full_name": "Intruso",
            "email": f"x-{uuid.uuid4().hex[:8]}@example.com",
            "password": "intruder123",
            "role": "admin",
        },
        headers=manager_headers,
    )
    assert created.status_code == 403
    assert (
        client.get(f"/api/v1/institutions/{institution_id}", headers=manager_headers).status_code
        == 403
    )
    assert (
        client.put(
            f"/api/v1/users/{admin_id}/external-identity",
            json={"external_subject": "SYNTH-STUDENT-0001"},
            headers=manager_headers,
        ).status_code
        == 403
    )


# --- Gestão documental --------------------------------------------------------


def test_admin_cannot_manage_documents(client: TestClient) -> None:
    """Mudança intencional do contrato de autorização: admin deixa de gerir
    documentos. Antes deste incremento este pedido devolvia 201."""
    institution_id = _create_institution(client)
    admin_headers, _ = _create_admin(client, institution_id)
    manager_headers = create_knowledge_manager(client, admin_headers)
    document = _create_document(client, manager_headers).json()

    assert _create_document(client, admin_headers).status_code == 403
    assert client.get("/api/v1/documents", headers=admin_headers).status_code == 403
    assert (
        client.get(f"/api/v1/documents/{document['id']}", headers=admin_headers).status_code
        == 403
    )
    assert (
        client.patch(
            f"/api/v1/documents/{document['id']}",
            json={"is_active": False},
            headers=admin_headers,
        ).status_code
        == 403
    )
    upload = client.post(
        f"/api/v1/documents/{document['id']}/versions",
        files={"file": ("a.txt", io.BytesIO(b"texto sintetico"), "text/plain")},
        headers=admin_headers,
    )
    assert upload.status_code == 403
    assert (
        client.delete(f"/api/v1/documents/{document['id']}", headers=admin_headers).status_code
        == 403
    )


@pytest.mark.parametrize("role", ["staff", "student", "user"])
def test_other_roles_cannot_manage_documents(client: TestClient, role: str) -> None:
    institution_id = _create_institution(client)
    admin_headers, _ = _create_admin(client, institution_id)
    headers, _ = create_account_and_login(client, admin_headers, role=role)

    assert _create_document(client, headers).status_code == 403
    assert client.get("/api/v1/documents", headers=headers).status_code == 403


def test_knowledge_manager_manages_documents_of_own_institution_only(client: TestClient) -> None:
    institution_a = _create_institution(client)
    admin_a, _ = _create_admin(client, institution_a)
    manager_a = create_knowledge_manager(client, admin_a)
    institution_b = _create_institution(client)
    admin_b, _ = _create_admin(client, institution_b)
    manager_b = create_knowledge_manager(client, admin_b)

    created = _create_document(client, manager_a)
    assert created.status_code == 201
    document_id = created.json()["id"]

    assert client.get(f"/api/v1/documents/{document_id}", headers=manager_a).status_code == 200
    # Outra instituição: inexistente, não proibido.
    assert client.get(f"/api/v1/documents/{document_id}", headers=manager_b).status_code == 404
    assert client.get("/api/v1/documents", headers=manager_b).json()["total"] == 0


# --- Conversas de terceiros ---------------------------------------------------


def test_admin_cannot_read_list_count_or_mutate_other_accounts_conversations(
    client: TestClient,
) -> None:
    """Mudança intencional: antes deste incremento o admin listava, lia e
    escrevia em qualquer conversa da sua instituição."""
    institution_id = _create_institution(client)
    admin_headers, _ = _create_admin(client, institution_id)
    student_headers, _ = create_account_and_login(client, admin_headers, role="student")
    conversation = _create_conversation(client, student_headers)
    own = _create_conversation(client, admin_headers)
    conversation_url = f"/api/v1/conversations/{conversation['id']}"

    listed = client.get("/api/v1/conversations", headers=admin_headers).json()
    assert [item["id"] for item in listed["items"]] == [own["id"]]
    assert listed["total"] == 1

    assert client.get(conversation_url, headers=admin_headers).status_code == 404
    assert client.get(f"{conversation_url}/messages", headers=admin_headers).status_code == 404
    renamed = client.patch(conversation_url, json={"title": "Admin"}, headers=admin_headers)
    assert renamed.status_code == 404
    system_message = client.post(
        f"{conversation_url}/messages",
        json={"content": "Aviso", "role": "system"},
        headers=admin_headers,
    )
    assert system_message.status_code == 404
    handoff = client.post(f"{conversation_url}/handoff", headers=admin_headers)
    assert handoff.status_code == 404

    # A conversa do aluno ficou intacta.
    student_view = client.get(conversation_url, headers=student_headers).json()
    assert student_view["title"] == "Minha"
    history = client.get(f"{conversation_url}/messages", headers=student_headers).json()
    assert history["total"] == 0


@pytest.mark.parametrize("role", ["knowledge_manager", "staff", "user", "student"])
def test_no_role_reaches_another_accounts_conversation(client: TestClient, role: str) -> None:
    institution_id = _create_institution(client)
    admin_headers, _ = _create_admin(client, institution_id)
    owner_headers, _ = create_account_and_login(client, admin_headers, role="student")
    other_headers, _ = create_account_and_login(client, admin_headers, role=role)
    conversation = _create_conversation(client, owner_headers)

    assert (
        client.get(f"/api/v1/conversations/{conversation['id']}", headers=other_headers)
        .status_code
        == 404
    )
    assert client.get("/api/v1/conversations", headers=other_headers).json()["total"] == 0


def test_admin_keeps_own_conversations_and_system_messages(client: TestClient) -> None:
    institution_id = _create_institution(client)
    admin_headers, admin_id = _create_admin(client, institution_id)
    conversation = _create_conversation(client, admin_headers)

    response = client.post(
        f"/api/v1/conversations/{conversation['id']}/messages",
        json={"content": "Nota de sistema", "role": "system"},
        headers=admin_headers,
    )
    assert response.status_code == 201
    assert response.json()["user_id"] == admin_id


@pytest.mark.parametrize("role", ["knowledge_manager", "staff", "student", "user"])
def test_only_admin_may_write_system_messages(client: TestClient, role: str) -> None:
    institution_id = _create_institution(client)
    admin_headers, _ = _create_admin(client, institution_id)
    headers, _ = create_account_and_login(client, admin_headers, role=role)
    conversation = _create_conversation(client, headers)

    response = client.post(
        f"/api/v1/conversations/{conversation['id']}/messages",
        json={"content": "Nota", "role": "system"},
        headers=headers,
    )
    assert response.status_code == 403


# --- Alterações de papel e desativação ------------------------------------------


def test_role_change_takes_effect_on_the_next_request(client: TestClient) -> None:
    institution_id = _create_institution(client)
    admin_headers, _ = _create_admin(client, institution_id)
    manager_headers, manager_id = create_account_and_login(
        client, admin_headers, role="knowledge_manager"
    )
    assert _create_document(client, manager_headers).status_code == 201

    demoted = client.patch(
        f"/api/v1/users/{manager_id}", json={"role": "student"}, headers=admin_headers
    )
    assert demoted.status_code == 200
    # O mesmo token: o papel é relido da base de dados, nunca do token.
    assert _create_document(client, manager_headers).status_code == 403

    promoted = client.patch(
        f"/api/v1/users/{manager_id}", json={"role": "knowledge_manager"}, headers=admin_headers
    )
    assert promoted.status_code == 200
    assert _create_document(client, manager_headers).status_code == 201


def test_promoting_to_admin_does_not_open_other_accounts_conversations(
    client: TestClient,
) -> None:
    institution_id = _create_institution(client)
    admin_headers, _ = _create_admin(client, institution_id)
    owner_headers, _ = create_account_and_login(client, admin_headers, role="student")
    promoted_headers, promoted_id = create_account_and_login(client, admin_headers, role="staff")
    conversation = _create_conversation(client, owner_headers)

    assert (
        client.patch(
            f"/api/v1/users/{promoted_id}", json={"role": "admin"}, headers=admin_headers
        ).status_code
        == 200
    )
    assert (
        client.get(f"/api/v1/conversations/{conversation['id']}", headers=promoted_headers)
        .status_code
        == 404
    )


def test_deactivated_knowledge_manager_loses_access_immediately(client: TestClient) -> None:
    institution_id = _create_institution(client)
    admin_headers, _ = _create_admin(client, institution_id)
    manager_headers, manager_id = create_account_and_login(
        client, admin_headers, role="knowledge_manager"
    )

    deactivated = client.patch(
        f"/api/v1/users/{manager_id}", json={"is_active": False}, headers=admin_headers
    )
    assert deactivated.status_code == 200
    assert _create_document(client, manager_headers).status_code == 401


def test_concurrent_demotion_blocks_a_system_message_from_a_stale_identity(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
) -> None:
    """A mensagem de sistema usa o papel relido sob lock, não o da autenticação.

    Simula a janela entre ``get_current_user`` e a escrita: a linha já diz
    ``staff``, o objeto de identidade ainda diz ``admin``.
    """
    institution_id = _create_institution(client)
    admin_headers, _ = _create_admin(client, institution_id)
    other_admin_headers, other_admin_id = create_account_and_login(
        client, admin_headers, role="admin"
    )
    conversation = _create_conversation(client, other_admin_headers)
    assert (
        client.patch(
            f"/api/v1/users/{other_admin_id}", json={"role": "staff"}, headers=admin_headers
        ).status_code
        == 200
    )

    stale = User(
        id=uuid.UUID(other_admin_id),
        institution_id=uuid.UUID(institution_id),
        role="admin",
        is_active=True,
        full_name="Stale",
        email="stale@example.com",
        password_hash="unused",
    )
    with test_session_factory() as db:
        with pytest.raises(AuthorizationError):
            message_service.create_message(
                db,
                stale,
                uuid.UUID(conversation["id"]),
                MessageCreate(content="Nota", role="system"),
            )


def test_concurrent_deactivation_blocks_a_message_from_a_stale_identity(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
) -> None:
    institution_id = _create_institution(client)
    admin_headers, _ = _create_admin(client, institution_id)
    student_headers, student_id = create_account_and_login(client, admin_headers, role="student")
    conversation = _create_conversation(client, student_headers)

    with test_session_factory() as db:
        db.execute(
            text("UPDATE users SET is_active = false WHERE id = :id"), {"id": student_id}
        )
        db.commit()

    stale = User(
        id=uuid.UUID(student_id),
        institution_id=uuid.UUID(institution_id),
        role="student",
        is_active=True,
        full_name="Stale",
        email="stale-student@example.com",
        password_hash="unused",
    )
    with test_session_factory() as db:
        with pytest.raises(AuthenticationError):
            message_service.create_message(
                db,
                stale,
                uuid.UUID(conversation["id"]),
                MessageCreate(content="Olá"),
            )
