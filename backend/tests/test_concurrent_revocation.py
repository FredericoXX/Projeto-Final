"""Revogação concorrente: a autorização é reconfirmada no ponto sensível.

Reproduz a técnica da auditoria de 2026-10-09 (F1): a dependência de
autorização real corre, e **imediatamente antes** do service original outra
sessão grava — com commit — uma despromoção, uma desativação da conta ou da
instituição. Antes da correção, as operações abaixo completavam com a
autorização já revogada (201/200). Agora cada service relê a conta e a
instituição sob lock (``app.services.authorization_service``) e recusa: 401
para conta/instituição inativa, 403 para papel sem a permissão.

Cada caso verifica também que nada foi gravado.
"""

import io
import re
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.answering.base import AnsweringContext, GeneratedAnswer
from app.answering.dependencies import get_answer_generator
from app.core.config import settings
from app.main import app
from app.models.conversation import Conversation
from app.models.document import Document
from app.models.document_version import DocumentVersion
from app.models.message import Message
from app.models.user import User
from app.models.user_external_identity import UserExternalIdentity
from app.services import (
    conversation_answering_service,
    conversation_service,
    document_service,
    document_version_service,
    external_identity_service,
    human_handoff_service,
    institution_service,
    message_service,
    retrieval_service,
    user_service,
)
from tests.role_support import create_account_and_login
from tests.test_academic_requests import _setup as _setup_demo_institution
from tests.test_role_separation import _create_admin, _create_institution

DEACTIVATE = "UPDATE users SET is_active = false WHERE id = :id"
DEMOTE_TO_STUDENT = "UPDATE users SET role = 'student' WHERE id = :id"
DEACTIVATE_INSTITUTION = (
    "UPDATE institutions SET is_active = false WHERE id = "
    "(SELECT institution_id FROM users WHERE id = :id)"
)


def _commit(factory: sessionmaker[Session], sql: str, user_id: str) -> None:
    with factory() as db:
        db.execute(text(sql), {"id": user_id})
        db.commit()


def _interpose(
    monkeypatch: pytest.MonkeyPatch,
    module: object,
    name: str,
    action: Callable[[], None],
) -> None:
    """Corre ``action`` entre a autorização da rota e o service original."""
    original = getattr(module, name)

    def wrapped(*args, **kwargs):  # type: ignore[no-untyped-def]
        action()
        return original(*args, **kwargs)

    monkeypatch.setattr(module, name, wrapped)


def _count(factory: sessionmaker[Session], model: type) -> int:
    with factory() as db:
        return db.scalar(select(func.count()).select_from(model)) or 0


@pytest.fixture
def institution(client: TestClient) -> tuple[str, dict[str, str], str]:
    institution_id = _create_institution(client)
    admin_headers, admin_id = _create_admin(client, institution_id)
    return institution_id, admin_headers, admin_id


# --- Núcleo documental ----------------------------------------------------------


@pytest.mark.parametrize(
    ("revocation", "status"),
    [(DEMOTE_TO_STUDENT, 403), (DEACTIVATE, 401), (DEACTIVATE_INSTITUTION, 401)],
    ids=["demoted", "deactivated", "institution-deactivated"],
)
def test_document_creation_after_revocation_is_refused(
    client: TestClient,
    institution,
    monkeypatch: pytest.MonkeyPatch,
    test_session_factory: sessionmaker[Session],
    revocation: str,
    status: int,
) -> None:
    _, admin_headers, _ = institution
    headers, manager_id = create_account_and_login(
        client, admin_headers, role="knowledge_manager"
    )
    _interpose(
        monkeypatch,
        document_service,
        "create_document",
        lambda: _commit(test_session_factory, revocation, manager_id),
    )

    response = client.post("/api/v1/documents", json={"title": "Regulamento"}, headers=headers)

    assert response.status_code == status
    assert _count(test_session_factory, Document) == 0


@pytest.mark.parametrize(
    "operation",
    ["read", "list", "update", "delete", "upload", "versions"],
)
def test_document_operations_after_demotion_are_refused(
    client: TestClient,
    institution,
    monkeypatch: pytest.MonkeyPatch,
    test_session_factory: sessionmaker[Session],
    operation: str,
) -> None:
    _, admin_headers, _ = institution
    headers, manager_id = create_account_and_login(
        client, admin_headers, role="knowledge_manager"
    )
    document = client.post("/api/v1/documents", json={"title": "Doc"}, headers=headers).json()
    url = f"/api/v1/documents/{document['id']}"
    targets = {
        "read": (document_service, "get_accessible_document"),
        "list": (document_service, "list_documents"),
        "update": (document_service, "update_document"),
        "delete": (document_service, "delete_document"),
        "upload": (document_version_service, "create_version"),
        "versions": (document_version_service, "list_versions"),
    }
    module, name = targets[operation]
    _interpose(
        monkeypatch,
        module,
        name,
        lambda: _commit(test_session_factory, DEMOTE_TO_STUDENT, manager_id),
    )

    if operation == "read":
        response = client.get(url, headers=headers)
    elif operation == "list":
        response = client.get("/api/v1/documents", headers=headers)
    elif operation == "update":
        response = client.patch(url, json={"title": "Alterado"}, headers=headers)
    elif operation == "delete":
        response = client.delete(url, headers=headers)
    elif operation == "upload":
        response = client.post(
            f"{url}/versions",
            files={"file": ("a.txt", io.BytesIO(b"texto sintetico"), "text/plain")},
            headers=headers,
        )
    else:
        response = client.get(f"{url}/versions", headers=headers)

    assert response.status_code == 403
    with test_session_factory() as db:
        stored = db.get(Document, uuid.UUID(document["id"]))
        assert stored is not None
        assert stored.title == "Doc"
    assert _count(test_session_factory, DocumentVersion) == 0


def _version_state(factory: sessionmaker[Session], version_id: str) -> tuple[object, ...]:
    with factory() as db:
        version = db.get(DocumentVersion, uuid.UUID(version_id))
        assert version is not None
        return (version.processing_status, version.processed_at, version.updated_at)


def test_reprocessing_after_demotion_is_refused(
    client: TestClient,
    institution,
    monkeypatch: pytest.MonkeyPatch,
    test_session_factory: sessionmaker[Session],
) -> None:
    _, admin_headers, _ = institution
    headers, manager_id = create_account_and_login(
        client, admin_headers, role="knowledge_manager"
    )
    document_id, version_id = _indexed_document(client, headers)
    before = _version_state(test_session_factory, version_id)
    _interpose(
        monkeypatch,
        document_version_service,
        "get_accessible_version",
        lambda: _commit(test_session_factory, DEMOTE_TO_STUDENT, manager_id),
    )

    response = client.post(
        f"/api/v1/documents/{document_id}/versions/{version_id}/reprocess", headers=headers
    )

    assert response.status_code == 403
    assert _version_state(test_session_factory, version_id) == before


# --- Contas, instituição e associação externa -------------------------------------


def _second_admin(
    client: TestClient, admin_headers: dict[str, str]
) -> tuple[dict[str, str], str]:
    return create_account_and_login(client, admin_headers, role="admin")


_ADMIN_REVOCATIONS = pytest.mark.parametrize(
    ("revocation", "status"),
    [(DEMOTE_TO_STUDENT, 403), (DEACTIVATE, 401)],
    ids=["demoted", "deactivated"],
)


@_ADMIN_REVOCATIONS
def test_external_identity_link_after_admin_revocation_is_refused(
    client: TestClient,
    institution,
    monkeypatch: pytest.MonkeyPatch,
    test_session_factory: sessionmaker[Session],
    revocation: str,
    status: int,
) -> None:
    """Antes da correção, com o admin despromovido: 200 e associação criada."""
    _, admin_headers, _ = institution
    acting_headers, acting_id = _second_admin(client, admin_headers)
    _, student_id = create_account_and_login(client, admin_headers, role="student")
    _interpose(
        monkeypatch,
        external_identity_service,
        "link_account",
        lambda: _commit(test_session_factory, revocation, acting_id),
    )

    response = client.put(
        f"/api/v1/users/{student_id}/external-identity",
        json={"external_subject": "SYNTH-STUDENT-0001"},
        headers=acting_headers,
    )

    assert response.status_code == status
    assert _count(test_session_factory, UserExternalIdentity) == 0


@_ADMIN_REVOCATIONS
def test_external_identity_unlink_after_admin_revocation_is_refused(
    client: TestClient,
    institution,
    monkeypatch: pytest.MonkeyPatch,
    test_session_factory: sessionmaker[Session],
    revocation: str,
    status: int,
) -> None:
    _, admin_headers, _ = institution
    acting_headers, acting_id = _second_admin(client, admin_headers)
    _, student_id = create_account_and_login(client, admin_headers, role="student")
    client.put(
        f"/api/v1/users/{student_id}/external-identity",
        json={"external_subject": "SYNTH-STUDENT-0001"},
        headers=admin_headers,
    )
    _interpose(
        monkeypatch,
        external_identity_service,
        "unlink_account",
        lambda: _commit(test_session_factory, revocation, acting_id),
    )

    response = client.delete(
        f"/api/v1/users/{student_id}/external-identity", headers=acting_headers
    )

    assert response.status_code == status
    assert _count(test_session_factory, UserExternalIdentity) == 1


@pytest.mark.parametrize("operation", ["create", "update", "list", "read"])
def test_account_management_after_admin_demotion_is_refused(
    client: TestClient,
    institution,
    monkeypatch: pytest.MonkeyPatch,
    test_session_factory: sessionmaker[Session],
    operation: str,
) -> None:
    _, admin_headers, _ = institution
    acting_headers, acting_id = _second_admin(client, admin_headers)
    _, student_id = create_account_and_login(client, admin_headers, role="student")
    targets = {
        "create": "create_user",
        "update": "update_user",
        "list": "list_users",
        "read": "get_user_for_admin",
    }
    _interpose(
        monkeypatch,
        user_service,
        targets[operation],
        lambda: _commit(test_session_factory, DEMOTE_TO_STUDENT, acting_id),
    )
    users_before = _count(test_session_factory, User)

    if operation == "create":
        response = client.post(
            "/api/v1/users",
            json={
                "full_name": "Nova Conta",
                "email": f"new-{uuid.uuid4().hex[:8]}@example.com",
                "password": "newaccount123",
                "role": "admin",
            },
            headers=acting_headers,
        )
    elif operation == "update":
        response = client.patch(
            f"/api/v1/users/{student_id}", json={"role": "admin"}, headers=acting_headers
        )
    elif operation == "list":
        response = client.get("/api/v1/users", headers=acting_headers)
    else:
        response = client.get(f"/api/v1/users/{student_id}", headers=acting_headers)

    assert response.status_code == 403
    assert _count(test_session_factory, User) == users_before
    with test_session_factory() as db:
        student = db.get(User, uuid.UUID(student_id))
        assert student is not None
        assert student.role == "student"


@pytest.mark.parametrize("operation", ["read", "update"])
def test_institution_management_after_admin_deactivation_is_refused(
    client: TestClient,
    institution,
    monkeypatch: pytest.MonkeyPatch,
    test_session_factory: sessionmaker[Session],
    operation: str,
) -> None:
    institution_id, admin_headers, _ = institution
    acting_headers, acting_id = _second_admin(client, admin_headers)
    name = "get_institution_for_admin" if operation == "read" else "update_institution_for_admin"
    _interpose(
        monkeypatch,
        institution_service,
        name,
        lambda: _commit(test_session_factory, DEACTIVATE, acting_id),
    )

    if operation == "read":
        response = client.get(f"/api/v1/institutions/{institution_id}", headers=acting_headers)
    else:
        response = client.patch(
            f"/api/v1/institutions/{institution_id}",
            json={"name": "Renomeada"},
            headers=acting_headers,
        )

    assert response.status_code == 401
    current = client.get(f"/api/v1/institutions/{institution_id}", headers=admin_headers)
    assert current.json()["name"] != "Renomeada"


# --- Conversas próprias -------------------------------------------------------------


@pytest.mark.parametrize("operation", ["rename", "read", "list", "create", "messages"])
def test_own_conversation_operations_after_deactivation_are_refused(
    client: TestClient,
    institution,
    monkeypatch: pytest.MonkeyPatch,
    test_session_factory: sessionmaker[Session],
    operation: str,
) -> None:
    """Antes da correção, a renomeação completava com 200."""
    _, admin_headers, _ = institution
    headers, student_id = create_account_and_login(client, admin_headers, role="student")
    conversation = client.post(
        "/api/v1/conversations", json={"title": "Original"}, headers=headers
    ).json()
    url = f"/api/v1/conversations/{conversation['id']}"
    targets = {
        "rename": (conversation_service, "update_conversation"),
        "read": (conversation_service, "get_accessible_conversation"),
        "list": (conversation_service, "list_conversations"),
        "create": (conversation_service, "create_conversation"),
        "messages": (message_service, "list_messages"),
    }
    module, name = targets[operation]
    _interpose(
        monkeypatch,
        module,
        name,
        lambda: _commit(test_session_factory, DEACTIVATE, student_id),
    )

    if operation == "rename":
        response = client.patch(url, json={"title": "Alterado"}, headers=headers)
    elif operation == "read":
        response = client.get(url, headers=headers)
    elif operation == "list":
        response = client.get("/api/v1/conversations", headers=headers)
    elif operation == "create":
        response = client.post("/api/v1/conversations", json={"title": "Nova"}, headers=headers)
    else:
        response = client.get(f"{url}/messages", headers=headers)

    assert response.status_code == 401
    assert _count(test_session_factory, Conversation) == 1
    with test_session_factory() as db:
        stored = db.get(Conversation, uuid.UUID(conversation["id"]))
        assert stored is not None
        assert stored.title == "Original"


# --- Pesquisa e resposta sem conversa --------------------------------------------------


def test_evidence_search_after_deactivation_is_refused(
    client: TestClient,
    institution,
    monkeypatch: pytest.MonkeyPatch,
    test_session_factory: sessionmaker[Session],
) -> None:
    _, admin_headers, _ = institution
    headers, student_id = create_account_and_login(client, admin_headers, role="student")
    _interpose(
        monkeypatch,
        retrieval_service,
        "search_evidence",
        lambda: _commit(test_session_factory, DEACTIVATE, student_id),
    )

    response = client.post("/api/v1/retrieval/search", json={"query": "matricula"}, headers=headers)

    assert response.status_code == 401


class _CallbackGenerator:
    """Gerador falso que corre ``during`` a meio da geração — por exemplo, uma
    desativação da conta ou uma sonda de locks."""

    def __init__(self, during: Callable[[], None] | None = None) -> None:
        self.during = during
        self.calls = 0

    def generate(self, context: AnsweringContext) -> GeneratedAnswer:
        self.calls += 1
        if self.during is not None:
            self.during()
        return GeneratedAnswer(
            answer="Resposta sintética.",
            cited_evidence_ids=(context.evidence[0].evidence_id,),
        )


def _indexed_document(client: TestClient, manager_headers: dict[str, str]) -> tuple[str, str]:
    """Documento oficial com uma versão processada; devolve (documento, versão)."""
    document = client.post(
        "/api/v1/documents",
        json={"title": "Calendário", "language": "pt", "official_source": True},
        headers=manager_headers,
    ).json()
    version = client.post(
        f"/api/v1/documents/{document['id']}/versions",
        files={
            "file": ("c.txt", io.BytesIO("O prazo de matrícula termina em setembro.".encode()),
                     "text/plain")
        },
        headers=manager_headers,
    ).json()
    return document["id"], version["id"]


def test_stateless_answer_is_not_delivered_after_deactivation_during_generation(
    client: TestClient,
    institution,
    test_session_factory: sessionmaker[Session],
) -> None:
    """A geração não corre sob lock; a conta é reconfirmada depois dela."""
    _, admin_headers, _ = institution
    manager_headers, _ = create_account_and_login(
        client, admin_headers, role="knowledge_manager"
    )
    _indexed_document(client, manager_headers)
    headers, student_id = create_account_and_login(client, admin_headers, role="student")
    generator = _CallbackGenerator(lambda: _commit(test_session_factory, DEACTIVATE, student_id))
    app.dependency_overrides[get_answer_generator] = lambda: generator
    try:
        response = client.post(
            "/api/v1/answering/ask", json={"query": "prazo de matrícula"}, headers=headers
        )
    finally:
        app.dependency_overrides.pop(get_answer_generator, None)

    assert generator.calls == 1
    assert response.status_code == 401
    assert "Resposta sintética" not in response.text


# --- Fluxos de turno já protegidos ---------------------------------------------------


@pytest.mark.parametrize("operation", ["message", "ask", "handoff"])
def test_existing_turn_paths_still_refuse_after_deactivation(
    client: TestClient,
    institution,
    monkeypatch: pytest.MonkeyPatch,
    test_session_factory: sessionmaker[Session],
    operation: str,
) -> None:
    """Mensagens, ``/ask`` na conversa e handoff já reliam e bloqueavam
    instituição → utilizador → conversa antes deste incremento. Uma desativação
    gravada depois da autenticação continua a ser recusada, sem nada gravado.
    No ``/ask``, a geração corre antes dos locks (sem eles) e a resposta é
    descartada."""
    _, admin_headers, _ = institution
    manager_headers, _ = create_account_and_login(
        client, admin_headers, role="knowledge_manager"
    )
    _indexed_document(client, manager_headers)
    headers, student_id = create_account_and_login(client, admin_headers, role="student")
    conversation = client.post(
        "/api/v1/conversations", json={"title": "Turnos"}, headers=headers
    ).json()
    url = f"/api/v1/conversations/{conversation['id']}"
    targets = {
        "message": (message_service, "create_message"),
        "ask": (conversation_answering_service, "ask_in_conversation"),
        "handoff": (human_handoff_service, "request_human_handoff"),
    }
    module, name = targets[operation]
    _interpose(
        monkeypatch,
        module,
        name,
        lambda: _commit(test_session_factory, DEACTIVATE, student_id),
    )
    app.dependency_overrides[get_answer_generator] = lambda: _CallbackGenerator()
    try:
        if operation == "message":
            response = client.post(f"{url}/messages", json={"content": "Olá"}, headers=headers)
        elif operation == "ask":
            response = client.post(
                f"{url}/ask", json={"query": "prazo de matrícula"}, headers=headers
            )
        else:
            response = client.post(f"{url}/handoff", headers=headers)
    finally:
        app.dependency_overrides.pop(get_answer_generator, None)

    assert response.status_code == 401
    assert "Resposta sintética" not in response.text
    assert _count(test_session_factory, Message) == 0


_LOCK_NOWAIT = {
    "institutions": "SELECT id FROM institutions WHERE id = :id FOR UPDATE NOWAIT",
    "users": "SELECT id FROM users WHERE id = :id FOR UPDATE NOWAIT",
    "conversations": "SELECT id FROM conversations WHERE id = :id FOR UPDATE NOWAIT",
}


def _lockable_now(factory: sessionmaker[Session], table: str, row_id: str) -> bool:
    """Tenta bloquear a linha noutra sessão, sem esperar."""
    with factory() as db:
        try:
            db.execute(text(_LOCK_NOWAIT[table]), {"id": row_id})
        except OperationalError:
            return False
        finally:
            db.rollback()
    return True


@pytest.mark.parametrize("path", ["stateless", "conversation"])
def test_no_database_lock_is_held_during_generation(
    client: TestClient,
    institution,
    test_session_factory: sessionmaker[Session],
    path: str,
) -> None:
    """A chamada ao modelo — uma futura chamada de rede — não corre sob locks
    da instituição, da conta ou da conversa."""
    institution_id, admin_headers, _ = institution
    manager_headers, _ = create_account_and_login(
        client, admin_headers, role="knowledge_manager"
    )
    _indexed_document(client, manager_headers)
    headers, student_id = create_account_and_login(client, admin_headers, role="student")
    rows = {"institutions": institution_id, "users": student_id}
    url = "/api/v1/answering/ask"
    if path == "conversation":
        conversation = client.post(
            "/api/v1/conversations", json={"title": "Locks"}, headers=headers
        ).json()
        rows["conversations"] = conversation["id"]
        url = f"/api/v1/conversations/{conversation['id']}/ask"
    lockable: dict[str, bool] = {}
    generator = _CallbackGenerator(
        lambda: lockable.update(
            {table: _lockable_now(test_session_factory, table, row) for table, row in rows.items()}
        )
    )
    app.dependency_overrides[get_answer_generator] = lambda: generator
    try:
        response = client.post(url, json={"query": "prazo de matrícula"}, headers=headers)
    finally:
        app.dependency_overrides.pop(get_answer_generator, None)

    assert response.status_code in {200, 201}, response.text
    assert generator.calls == 1
    assert lockable == dict.fromkeys(rows, True)


# --- Ordem e duração dos locks ----------------------------------------------------------

_LOCKING_CLAUSE = re.compile(r"\bFOR (?:UPDATE|NO KEY UPDATE|SHARE|KEY SHARE)\b")
_FIRST_FROM = re.compile(r"\bFROM\s+(\w+)")
_ROW_WRITE = re.compile(r"^\s*(?:UPDATE|DELETE\s+FROM)\s+(\w+)", re.IGNORECASE)
_INSERT = re.compile(r"^\s*INSERT\s+INTO\s+(\w+)", re.IGNORECASE)
# Ordem comum: instituição → utilizador → qualquer recurso.
_LOCK_RANK = {"institutions": 0, "users": 1}


class _LockRecorder:
    """Regista, por transação, as linhas que cada statement bloqueia.

    ``lock`` é um ``SELECT ... FOR ...``, um advisory lock, ou um UPDATE/DELETE
    (que bloqueia as linhas escritas); ``insert`` é uma escrita sem lock de
    linhas existentes. Só grava dentro de ``recording``.
    """

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.by_label: dict[str, list[list[tuple[str, str]]]] = {}
        self._transactions: list[list[tuple[str, str]]] | None = None
        self._open: dict[int, list[tuple[str, str]]] = {}

    def _begin(self, conn) -> None:  # type: ignore[no-untyped-def]
        if self._transactions is not None:
            transaction: list[tuple[str, str]] = []
            self._open[id(conn)] = transaction
            self._transactions.append(transaction)

    def _statement(self, conn, cursor, statement, parameters, context, executemany) -> None:  # type: ignore[no-untyped-def]
        transaction = self._open.get(id(conn))
        if transaction is None or self._transactions is None:
            return
        if "pg_advisory" in statement:
            transaction.append(("lock", "advisory"))
        elif _LOCKING_CLAUSE.search(statement) and (found := _FIRST_FROM.search(statement)):
            transaction.append(("lock", found.group(1)))
        elif found := _ROW_WRITE.match(statement):
            transaction.append(("write", found.group(1)))
        elif found := _INSERT.match(statement):
            transaction.append(("insert", found.group(1)))

    @contextmanager
    def recording(self, label: str) -> Iterator[None]:
        self._transactions, self._open = [], {}
        event.listen(self.engine, "begin", self._begin)
        event.listen(self.engine, "before_cursor_execute", self._statement)
        try:
            yield
        finally:
            event.remove(self.engine, "before_cursor_execute", self._statement)
            event.remove(self.engine, "begin", self._begin)
            self.by_label[label] = self._transactions
            self._transactions = None


def _order_inversions(transaction: list[tuple[str, str]]) -> list[str]:
    """Tabelas bloqueadas pela primeira vez depois de outra de ordem superior."""
    held: set[str] = set()
    highest = -1
    inversions = []
    for kind, table in transaction:
        if kind == "insert" or table in held:
            continue
        rank = _LOCK_RANK.get(table, 2)
        if rank < highest:
            inversions.append(table)
        held.add(table)
        highest = max(highest, rank)
    return inversions


def _locked_before_first_write(transaction: list[tuple[str, str]]) -> set[str]:
    locked: set[str] = set()
    for kind, table in transaction:
        if kind in {"write", "insert"}:
            return locked
        locked.add(table)
    return locked


def _locked_tables(transaction: list[tuple[str, str]]) -> list[str]:
    return [table for kind, table in transaction if kind == "lock"]


# Mutações autorizadas: a transação que escreve tem de bloquear instituição e
# conta antes da primeira escrita, e mantê-las até ao commit.
_MUTATIONS = (
    "document.create",
    "document.update",
    "document.upload",
    "document.reprocess",
    "document.delete",
    "identity.link",
    "identity.unlink",
    "user.update",
    "institution.update",
    "conversation.create",
    "conversation.rename",
    "message.create",
    "conversation.ask",
    "conversation.handoff",
)


def test_every_flow_locks_institution_then_account_then_resources(
    client: TestClient,
    test_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Prova estrutural de que não há inversões de ordem de locks.

    Todos os fluxos com revalidação — os novos e os já existentes — bloqueiam
    pela mesma ordem, instituição → utilizador → recurso, em cada transação. É
    essa ordem comum que exclui deadlocks entre eles e as revogações (que
    seguem o mesmo caminho em ``update_user``). Nas mutações, os locks de
    autorização são adquiridos antes da primeira escrita, na mesma transação,
    e por isso duram até ao commit.
    """
    monkeypatch.setattr(settings, "institutional_data_provider", "mock")
    institution_id, admin_headers = _setup_demo_institution(client)
    manager_headers, _ = create_account_and_login(
        client, admin_headers, role="knowledge_manager"
    )
    student_headers, student_id = create_account_and_login(
        client, admin_headers, role="student"
    )
    _, spare_id = create_account_and_login(client, admin_headers, role="student")
    indexed_id, indexed_version_id = _indexed_document(client, manager_headers)
    recorder = _LockRecorder(test_engine)

    def run(label: str, call: Callable[[], object]) -> dict:
        with recorder.recording(label):
            response = call()
        assert response.status_code < 300, (label, response.status_code, response.text)  # type: ignore[attr-defined]
        return response.json() if response.status_code != 204 else {}  # type: ignore[attr-defined]

    app.dependency_overrides[get_answer_generator] = lambda: _CallbackGenerator()
    try:
        created = run(
            "document.create",
            lambda: client.post(
                "/api/v1/documents", json={"title": "Novo"}, headers=manager_headers
            ),
        )
        document_url = f"/api/v1/documents/{created['id']}"
        run(
            "document.update",
            lambda: client.patch(document_url, json={"title": "Alterado"}, headers=manager_headers),
        )
        run(
            "document.upload",
            lambda: client.post(
                f"{document_url}/versions",
                files={"file": ("n.txt", io.BytesIO(b"outro texto sintetico"), "text/plain")},
                headers=manager_headers,
            ),
        )
        run(
            "document.reprocess",
            lambda: client.post(
                f"/api/v1/documents/{indexed_id}/versions/{indexed_version_id}/reprocess",
                headers=manager_headers,
            ),
        )
        run("document.delete", lambda: client.delete(document_url, headers=manager_headers))
        identity_url = f"/api/v1/users/{student_id}/external-identity"
        run(
            "identity.link",
            lambda: client.put(
                identity_url, json={"external_subject": "SYNTH-STUDENT-0001"}, headers=admin_headers
            ),
        )
        run(
            "academic.access",
            lambda: client.get("/api/v1/academic-requests/access", headers=student_headers),
        )
        run(
            "academic.list",
            lambda: client.get("/api/v1/academic-requests", headers=student_headers),
        )
        conversation = run(
            "conversation.create",
            lambda: client.post(
                "/api/v1/conversations", json={"title": "Ordem"}, headers=student_headers
            ),
        )
        conversation_url = f"/api/v1/conversations/{conversation['id']}"
        run(
            "conversation.rename",
            lambda: client.patch(
                conversation_url, json={"title": "Renomeada"}, headers=student_headers
            ),
        )
        run(
            "message.create",
            lambda: client.post(
                f"{conversation_url}/messages", json={"content": "Olá"}, headers=student_headers
            ),
        )
        run(
            "conversation.ask",
            lambda: client.post(
                f"{conversation_url}/ask",
                json={"query": "prazo de matrícula"},
                headers=student_headers,
            ),
        )
        run(
            "answering.ask",
            lambda: client.post(
                "/api/v1/answering/ask",
                json={"query": "prazo de matrícula"},
                headers=student_headers,
            ),
        )
        run(
            "retrieval.search",
            lambda: client.post(
                "/api/v1/retrieval/search", json={"query": "matricula"}, headers=student_headers
            ),
        )
        run(
            "institution.update",
            lambda: client.patch(
                f"/api/v1/institutions/{institution_id}",
                json={
                    "human_support_name": "Serviços Académicos",
                    "human_support_email": "academicos@example.org",
                },
                headers=admin_headers,
            ),
        )
        run(
            "conversation.handoff",
            lambda: client.post(f"{conversation_url}/handoff", headers=student_headers),
        )
        run(
            "user.update",
            lambda: client.patch(
                f"/api/v1/users/{spare_id}", json={"is_active": False}, headers=admin_headers
            ),
        )
        run("identity.unlink", lambda: client.delete(identity_url, headers=admin_headers))
    finally:
        app.dependency_overrides.pop(get_answer_generator, None)

    for label, transactions in recorder.by_label.items():
        for transaction in transactions:
            assert _order_inversions(transaction) == [], (label, transaction)

    for label in _MUTATIONS:
        writing = [
            transaction
            for transaction in recorder.by_label[label]
            if any(kind in {"write", "insert"} for kind, _ in transaction)
        ]
        assert writing, label
        assert {"institutions", "users"} <= _locked_before_first_write(writing[0]), (
            label,
            writing[0],
        )

    # A consulta académica bloqueia também a associação, depois da conta,
    # antes e depois da fonte, em transações separadas.
    academic = [
        _locked_tables(transaction)[:3] for transaction in recorder.by_label["academic.list"]
    ]
    assert academic.count(["institutions", "users", "user_external_identities"]) == 2
    access = [
        _locked_tables(transaction)[:3] for transaction in recorder.by_label["academic.access"]
    ]
    assert access.count(["institutions", "users", "user_external_identities"]) == 1
