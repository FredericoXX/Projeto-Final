"""Eliminação segura de documentos: regras, storage e concorrência.

PostgreSQL real; o AnswerGenerator é substituído por dependency override
quando é preciso citar um documento — sem rede e sem credenciais.
"""

import threading
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.models.conversation import Conversation
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.document_version import DocumentVersion
from app.models.message import Message
from app.models.message_source import MessageSource
from app.models.user import User
from app.services import document_service, message_source_service
from app.services.document_service import (
    DOCUMENT_PROCESSING_MESSAGE,
    DOCUMENT_REFERENCED_MESSAGE,
)
from app.storage import get_document_storage
from tests.test_conversation_answering import (
    FakeAnswerGenerator,
    _ask,
    _create_admin,
    _create_conversation,
    _create_institution,
    _create_searchable_document,
    _create_user,
    override_generator,  # noqa: F401 - fixture reexportada para este módulo
)

BOOTSTRAP_HEADERS = {"X-Bootstrap-Token": settings.bootstrap_token or ""}


def _delete(client: TestClient, document_id: str, headers: dict[str, str]):
    return client.delete(f"/api/v1/documents/{document_id}", headers=headers)


def _count(session: Session, model, document_id: str) -> int:
    return (
        session.scalar(
            select(func.count())
            .select_from(model)
            .where(model.document_id == uuid.UUID(document_id))
        )
        or 0
    )


def _setup(client: TestClient) -> tuple[dict, dict[str, str]]:
    institution = _create_institution(client)
    headers, _ = _create_admin(client, institution["id"])
    return institution, headers


def _cite_document(
    client: TestClient,
    headers: dict[str, str],
    override,  # fixture installer
    # Dois termos informativos partilhados com o conteúdo de teste
    # ("aulas", "setembro"): o suficiente para ser evidência (2 de 3).
    query: str = "Quando começam as aulas de setembro?",
) -> None:
    """Faz uma pergunta que cita o documento, persistindo MessageSource."""
    conversation = _create_conversation(client, headers)
    override(FakeAnswerGenerator())
    response = _ask(client, conversation["id"], headers, query=query)
    assert response.status_code == 201
    assert response.json()["status"] == "answered"


# --- Autorização e isolamento -------------------------------------------------


def test_delete_requires_authentication_and_admin(client: TestClient) -> None:
    institution, admin_headers = _setup(client)
    document, _ = _create_searchable_document(
        client,
        admin_headers,
        "conteudo qualquer",
        title="Doc",
        source_url="https://example.edu/doc",
    )

    assert _delete(client, document["id"], {}).status_code == 401

    user_headers, _ = _create_user(client, admin_headers)
    assert _delete(client, document["id"], user_headers).status_code == 403
    assert institution["id"]


def test_delete_document_of_other_institution_returns_404(client: TestClient) -> None:
    _, headers_a = _setup(client)
    document, _ = _create_searchable_document(
        client, headers_a, "conteudo alfa", title="Doc A", source_url="https://example.edu/a"
    )

    _, headers_b = _setup(client)
    assert _delete(client, document["id"], headers_b).status_code == 404
    # O documento continua intacto para a instituição dona.
    assert (
        client.get(f"/api/v1/documents/{document['id']}", headers=headers_a).status_code
        == 200
    )


# --- Eliminação permitida --------------------------------------------------------


def test_delete_document_without_versions(client: TestClient) -> None:
    _, headers = _setup(client)
    response = client.post(
        "/api/v1/documents",
        json={"title": "Sem versões", "language": "pt"},
        headers=headers,
    )
    document_id = response.json()["id"]

    assert _delete(client, document_id, headers).status_code == 204
    assert client.get(f"/api/v1/documents/{document_id}", headers=headers).status_code == 404


def test_delete_removes_versions_chunks_files_and_frees_checksum(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> None:
    _, headers = _setup(client)
    content = "As aulas do primeiro semestre iniciam-se em 21 de setembro de 2026."
    document, version = _create_searchable_document(
        client, headers, content, title="Doc Completo", source_url="https://example.edu/doc"
    )
    storage = get_document_storage()
    with test_session_factory() as db:
        stored_version = db.get(DocumentVersion, uuid.UUID(version["id"]))
        assert stored_version is not None
        storage_path = stored_version.storage_path
    assert storage.exists(storage_path)

    assert _delete(client, document["id"], headers).status_code == 204

    with test_session_factory() as db:
        assert _count(db, DocumentVersion, document["id"]) == 0
        assert _count(db, DocumentChunk, document["id"]) == 0
        assert db.get(Document, uuid.UUID(document["id"])) is None
    # Ficheiro removido do storage.
    assert not storage.exists(storage_path)
    # Listagem e detalhe deixam de o devolver.
    listing = client.get("/api/v1/documents", headers=headers).json()
    assert all(item["id"] != document["id"] for item in listing["items"])
    assert client.get(f"/api/v1/documents/{document['id']}", headers=headers).status_code == 404

    # O retrieval deixa de encontrar o conteúdo.
    search = client.post(
        "/api/v1/retrieval/search",
        json={"query": "aulas"},
        headers=headers,
    )
    assert search.status_code == 200
    assert search.json()["items"] == []

    # O checksum fica livre: o mesmo ficheiro pode voltar a ser carregado.
    replacement, _ = _create_searchable_document(
        client, headers, content, title="Doc Recarregado", source_url="https://example.edu/doc"
    )
    assert replacement["id"] != document["id"]


def test_delete_document_with_failed_version(client: TestClient) -> None:
    _, headers = _setup(client)
    response = client.post(
        "/api/v1/documents",
        json={"title": "Com versão failed", "language": "pt"},
        headers=headers,
    )
    document_id = response.json()["id"]
    upload = client.post(
        f"/api/v1/documents/{document_id}/versions",
        files={"file": ("bad.txt", b"\xff\xfe invalid", "text/plain")},
        headers=headers,
    )
    assert upload.json()["processing_status"] == "failed"

    assert _delete(client, document_id, headers).status_code == 204


def test_delete_inactive_uncited_document(client: TestClient) -> None:
    _, headers = _setup(client)
    document, _ = _create_searchable_document(
        client, headers, "conteudo inativo", title="Inativo", source_url="https://example.edu/i"
    )
    client.patch(
        f"/api/v1/documents/{document['id']}", json={"is_active": False}, headers=headers
    )
    assert _delete(client, document["id"], headers).status_code == 204


def test_missing_storage_file_does_not_block_deletion(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> None:
    _, headers = _setup(client)
    document, version = _create_searchable_document(
        client, headers, "conteudo sem ficheiro", title="Sem Ficheiro",
        source_url="https://example.edu/s",
    )
    storage = get_document_storage()
    with test_session_factory() as db:
        stored_version = db.get(DocumentVersion, uuid.UUID(version["id"]))
        assert stored_version is not None
        storage.delete(stored_version.storage_path)

    assert _delete(client, document["id"], headers).status_code == 204


# --- Eliminação bloqueada ----------------------------------------------------------


def test_cited_document_returns_409_and_history_remains(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
    override_generator,  # noqa: F811 - fixture
) -> None:
    _, headers = _setup(client)
    document, _ = _create_searchable_document(
        client,
        headers,
        "As aulas do primeiro semestre iniciam-se em 21 de setembro de 2026.",
        title="Citado",
        source_url="https://example.edu/c",
    )
    _cite_document(client, headers, override_generator)

    response = _delete(client, document["id"], headers)
    assert response.status_code == 409
    body = response.json()
    assert body["detail"]["code"] == "resource_conflict"
    assert body["detail"]["message"] == DOCUMENT_REFERENCED_MESSAGE
    # Nenhum caminho interno na resposta.
    assert "storage" not in response.text

    with test_session_factory() as db:
        assert (db.scalar(select(func.count()).select_from(MessageSource)) or 0) == 1
        assert (db.scalar(select(func.count()).select_from(Message)) or 0) == 2
        assert (db.scalar(select(func.count()).select_from(Conversation)) or 0) == 1
        assert _count(db, DocumentVersion, document["id"]) == 1
        assert _count(db, DocumentChunk, document["id"]) == 1

    # A alternativa continua disponível: desativar o documento citado.
    deactivate = client.patch(
        f"/api/v1/documents/{document['id']}", json={"is_active": False}, headers=headers
    )
    assert deactivate.status_code == 200
    assert deactivate.json()["is_active"] is False
    # Desativado, deixa de ser recuperável em novas pesquisas.
    search = client.post(
        "/api/v1/retrieval/search", json={"query": "aulas"}, headers=headers
    )
    assert search.json()["items"] == []
    # Mas as fontes históricas permanecem.
    with test_session_factory() as db:
        assert (db.scalar(select(func.count()).select_from(MessageSource)) or 0) == 1


def test_processing_version_returns_409(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> None:
    _, headers = _setup(client)
    document, version = _create_searchable_document(
        client, headers, "conteudo em processamento", title="Processing",
        source_url="https://example.edu/p",
    )
    with test_session_factory() as db:
        stored = db.get(DocumentVersion, uuid.UUID(version["id"]))
        assert stored is not None
        stored.processing_status = "processing"
        db.commit()

    response = _delete(client, document["id"], headers)
    assert response.status_code == 409
    assert response.json()["detail"]["message"] == DOCUMENT_PROCESSING_MESSAGE


def test_failed_deletion_leaves_no_partial_state(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Uma falha a meio da transação (simulada no commit) faz rollback
    integral: chunks, versões e documento permanecem."""
    _, headers = _setup(client)
    document, _ = _create_searchable_document(
        client, headers, "conteudo estavel", title="Rollback",
        source_url="https://example.edu/r",
    )

    original_commit = Session.commit

    def failing_commit(session: Session) -> None:
        raise RuntimeError("simulated commit failure")

    with test_session_factory() as db:
        admin = db.scalar(select(User).where(User.role == "admin"))
        assert admin is not None
        storage = get_document_storage()
        monkeypatch.setattr(Session, "commit", failing_commit)
        try:
            with pytest.raises(RuntimeError):
                document_service.delete_document(
                    db, admin, uuid.UUID(document["id"]), storage=storage
                )
        finally:
            monkeypatch.setattr(Session, "commit", original_commit)

    with test_session_factory() as db:
        assert db.get(Document, uuid.UUID(document["id"])) is not None
        assert _count(db, DocumentVersion, document["id"]) == 1
        assert _count(db, DocumentChunk, document["id"]) == 1


def test_storage_failure_after_commit_is_best_effort(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    test_session_factory: sessionmaker[Session],
) -> None:
    """Falha na limpeza do storage depois do commit: a eliminação da base
    mantém-se (204) e o resíduo fica apenas registado."""
    from app.storage.local import LocalDocumentStorage

    _, headers = _setup(client)
    document, _ = _create_searchable_document(
        client, headers, "conteudo com residuo", title="Resíduo",
        source_url="https://example.edu/res",
    )

    def failing_delete(self: LocalDocumentStorage, path: str) -> None:
        raise OSError("simulated storage failure")

    monkeypatch.setattr(LocalDocumentStorage, "delete", failing_delete)
    response = _delete(client, document["id"], headers)
    assert response.status_code == 204

    with test_session_factory() as db:
        assert db.get(Document, uuid.UUID(document["id"])) is None


# --- Concorrência -------------------------------------------------------------------


def test_concurrent_answering_first_makes_delete_409(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
    override_generator,  # noqa: F811 - fixture
) -> None:
    """O answering persiste a fonte primeiro: o DELETE espera pelos locks,
    deteta a referência e devolve 409; resposta e fonte ficam intactas."""
    _, headers = _setup(client)
    document, version = _create_searchable_document(
        client,
        headers,
        "As aulas do primeiro semestre iniciam-se em 21 de setembro de 2026.",
        title="Corrida A",
        source_url="https://example.edu/ca",
    )
    conversation = _create_conversation(client, headers)

    source_locked = threading.Event()
    release_answer = threading.Event()
    results: dict[str, object] = {}

    def blocking_callback(_context: object) -> None:
        # Geração "lenta": deixa o DELETE arrancar antes da persistência.
        source_locked.set()
        assert release_answer.wait(timeout=15)

    override_generator(FakeAnswerGenerator(callback=blocking_callback))

    def ask_worker() -> None:
        results["ask"] = _ask(
            client, conversation["id"], headers, query="Quando começam as aulas de setembro?"
        ).status_code

    def delete_worker() -> None:
        assert source_locked.wait(timeout=15)
        # Espera que o answering entre na fase de locks e persista.
        release_answer.set()
        results["delete"] = _delete(client, document["id"], headers).status_code

    threads = [threading.Thread(target=ask_worker), threading.Thread(target=delete_worker)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
        assert not thread.is_alive()

    assert results["ask"] == 201
    assert results["delete"] == 409
    with test_session_factory() as db:
        assert (db.scalar(select(func.count()).select_from(MessageSource)) or 0) == 1
        assert _count(db, DocumentVersion, document["id"]) == 1
    assert version["id"]


def test_concurrent_delete_first_leaves_no_partial_turn(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
    override_generator,  # noqa: F811 - fixture
) -> None:
    """O DELETE ganha a corrida durante a geração: a revalidação do
    answering deixa de encontrar as versões, falha com 409 e nenhum turno
    parcial é persistido."""
    _, headers = _setup(client)
    document, _ = _create_searchable_document(
        client,
        headers,
        "As aulas do segundo semestre iniciam-se em setembro de 2027.",
        title="Corrida B",
        source_url="https://example.edu/cb",
    )
    conversation = _create_conversation(client, headers)

    generation_started = threading.Event()
    deletion_finished = threading.Event()
    results: dict[str, object] = {}

    def deleting_callback(_context: object) -> None:
        # Durante a geração (sem locks abertos), o DELETE corre e comita.
        generation_started.set()
        assert deletion_finished.wait(timeout=15)

    override_generator(FakeAnswerGenerator(callback=deleting_callback))

    def ask_worker() -> None:
        results["ask"] = _ask(
            client, conversation["id"], headers, query="Quando começam as aulas de setembro?"
        ).status_code

    def delete_worker() -> None:
        assert generation_started.wait(timeout=15)
        results["delete"] = _delete(client, document["id"], headers).status_code
        deletion_finished.set()

    threads = [threading.Thread(target=ask_worker), threading.Thread(target=delete_worker)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
        assert not thread.is_alive()

    assert results["delete"] == 204
    assert results["ask"] == 409
    with test_session_factory() as db:
        assert (db.scalar(select(func.count()).select_from(MessageSource)) or 0) == 0
        assert (db.scalar(select(func.count()).select_from(Message)) or 0) == 0
        assert db.get(Document, uuid.UUID(document["id"])) is None


def test_document_level_reference_helper(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
    override_generator,  # noqa: F811 - fixture
) -> None:
    institution, headers = _setup(client)
    document, _ = _create_searchable_document(
        client,
        headers,
        "As aulas do primeiro semestre iniciam-se em 21 de setembro de 2026.",
        title="Helper",
        source_url="https://example.edu/h",
    )
    with test_session_factory() as db:
        assert not message_source_service.is_document_referenced(
            db,
            document_id=uuid.UUID(document["id"]),
            institution_id=uuid.UUID(institution["id"]),
        )
    _cite_document(client, headers, override_generator)
    with test_session_factory() as db:
        assert message_source_service.is_document_referenced(
            db,
            document_id=uuid.UUID(document["id"]),
            institution_id=uuid.UUID(institution["id"]),
        )


def test_delete_error_responses_never_expose_internals(
    client: TestClient, override_generator  # noqa: F811 - fixture
) -> None:
    _, headers = _setup(client)
    _create_searchable_document(
        client,
        headers,
        "As aulas do primeiro semestre iniciam-se em 21 de setembro de 2026.",
        title="Sem Fugas",
        source_url="https://example.edu/f",
    )
    _cite_document(client, headers, override_generator)
    document_id = client.get("/api/v1/documents", headers=headers).json()["items"][0]["id"]

    response = _delete(client, document_id, headers)
    assert response.status_code == 409
    for forbidden in ("storage", "Traceback", "IntegrityError", "SELECT", "\\\\"):
        assert forbidden not in response.text


# --- Corrida upload vs eliminação (A4) --------------------------------------------


def test_concurrent_upload_then_delete_leaves_no_orphan_file(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> None:
    """O upload adquire primeiro o advisory lock documental e fica retido
    antes do commit; a eliminação espera, e o snapshot dela inclui a nova
    versão — o ficheiro acabado de carregar também é removido."""
    import io as io_module

    from app.services import document_version_service
    from app.storage.local import LocalDocumentStorage

    _, headers = _setup(client)
    response = client.post(
        "/api/v1/documents",
        json={"title": "Corrida Upload", "language": "pt"},
        headers=headers,
    )
    document_id = response.json()["id"]

    storage = get_document_storage()
    upload_moved = threading.Event()
    release_upload = threading.Event()
    results: dict[str, object] = {}
    original_move = LocalDocumentStorage.move_to_final

    def blocking_move(self: LocalDocumentStorage, temp_path: str, final_path: str) -> None:
        # Neste ponto o upload já detém o advisory lock e o lock da linha
        # do documento; reter aqui deixa a eliminação à espera.
        original_move(self, temp_path, final_path)
        upload_moved.set()
        assert release_upload.wait(timeout=15)

    def upload_worker() -> None:
        db = test_session_factory()
        try:
            admin = db.scalar(select(User).where(User.role == "admin"))
            assert admin is not None
            version = document_version_service.create_version(
                db,
                admin,
                uuid.UUID(document_id),
                upload_stream=io_module.BytesIO(b"conteudo da corrida"),
                filename="corrida.txt",
                declared_content_type="text/plain",
                storage=storage,
            )
            results["upload_path"] = version.storage_path
            results["upload"] = "created"
        except Exception as exc:  # noqa: BLE001 - recolhido para asserção
            results["upload"] = type(exc).__name__
        finally:
            db.close()

    def delete_worker() -> None:
        assert upload_moved.wait(timeout=15)
        release_upload.set()
        results["delete"] = _delete(client, document_id, headers).status_code

    import unittest.mock

    with unittest.mock.patch.object(LocalDocumentStorage, "move_to_final", blocking_move):
        threads = [threading.Thread(target=upload_worker), threading.Thread(target=delete_worker)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
            assert not thread.is_alive()

    assert results["upload"] == "created"
    assert results["delete"] == 204
    # A versão criada pelo upload foi incluída no snapshot da eliminação:
    # nem registo nem ficheiro sobram.
    assert not storage.exists(str(results["upload_path"]))
    with test_session_factory() as db:
        assert db.get(Document, uuid.UUID(document_id)) is None
        assert _count(db, DocumentVersion, document_id) == 0


def test_concurrent_delete_then_upload_fails_clean_without_orphan(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> None:
    """A eliminação vence: o upload que chega depois encontra o documento
    removido, falha com NotFound e não deixa ficheiro nenhum."""
    import io as io_module

    from app.core.exceptions import NotFoundError
    from app.services import document_version_service

    _, headers = _setup(client)
    document, _ = _create_searchable_document(
        client, headers, "conteudo inicial", title="Corrida Delete",
        source_url="https://example.edu/cd",
    )
    storage = get_document_storage()

    with test_session_factory() as db:
        admin = db.scalar(select(User).where(User.role == "admin"))
        assert admin is not None
        # Eliminação completa primeiro.
        assert _delete(client, document["id"], headers).status_code == 204
        # Upload posterior: 404 limpo, sem resíduos.
        with pytest.raises(NotFoundError):
            document_version_service.create_version(
                db,
                admin,
                uuid.UUID(document["id"]),
                upload_stream=io_module.BytesIO(b"conteudo tardio"),
                filename="tardio.txt",
                declared_content_type="text/plain",
                storage=storage,
            )
        db.rollback()

    root = storage.resolve_path(".")
    leftover = [
        p
        for p in root.rglob("*")
        if p.is_file() and document["id"] in str(p)
    ]
    assert leftover == []


# --- Journal durável de limpeza (A5) ------------------------------------------------


def test_storage_failure_leaves_durable_task_and_reconciles(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    test_session_factory: sessionmaker[Session],
) -> None:
    """Falha de storage após o commit: a tarefa de limpeza (registada na
    mesma transação da eliminação) permanece na base; a reconciliação
    posterior remove o ficheiro e conclui a tarefa."""
    from app.models.storage_cleanup_task import StorageCleanupTask
    from app.services.document_service import reconcile_pending_deletions
    from app.storage.local import LocalDocumentStorage

    _, headers = _setup(client)
    document, version = _create_searchable_document(
        client, headers, "conteudo tarefa", title="Tarefa",
        source_url="https://example.edu/j",
    )
    storage = get_document_storage()
    with test_session_factory() as db:
        stored_version = db.get(DocumentVersion, uuid.UUID(version["id"]))
        assert stored_version is not None
        storage_path = stored_version.storage_path

    original_delete = LocalDocumentStorage.delete

    def failing_delete(self: LocalDocumentStorage, path: str) -> None:
        raise OSError("simulated storage failure")

    monkeypatch.setattr(LocalDocumentStorage, "delete", failing_delete)
    assert _delete(client, document["id"], headers).status_code == 204

    # A tarefa ficou persistida de forma durável; o ficheiro é resíduo.
    with test_session_factory() as db:
        tasks = db.scalars(select(StorageCleanupTask)).all()
        assert [task.storage_path for task in tasks] == [storage_path]
        assert str(tasks[0].document_id) == document["id"]
    assert storage.exists(storage_path)

    # Reconciliação com o storage recuperado: resíduo e tarefa concluídos.
    monkeypatch.setattr(LocalDocumentStorage, "delete", original_delete)
    with test_session_factory() as db:
        assert reconcile_pending_deletions(db, storage) == 1
    assert not storage.exists(storage_path)
    with test_session_factory() as db:
        assert db.scalars(select(StorageCleanupTask)).all() == []


def test_next_deletion_drains_pending_tasks(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> None:
    """A reconciliação corre no fim de cada eliminação, drenando também
    tarefas residuais de eliminações anteriores."""
    from app.models.storage_cleanup_task import StorageCleanupTask

    _, headers = _setup(client)
    storage = get_document_storage()
    document, version = _create_searchable_document(
        client, headers, "residuo anterior", title="Resíduo Antigo",
        source_url="https://example.edu/ra",
    )
    with test_session_factory() as db:
        stored_version = db.get(DocumentVersion, uuid.UUID(version["id"]))
        assert stored_version is not None
        residual_path = stored_version.storage_path
        # Tarefa residual artificial apontando para um ficheiro real.
        db.add(
            StorageCleanupTask(
                document_id=uuid.UUID(document["id"]), storage_path=residual_path
            )
        )
        db.commit()
    # Elimina o documento dono do resíduo (o registo na base desaparece).
    assert _delete(client, document["id"], headers).status_code == 204

    # A reconciliação da própria eliminação drenou tudo.
    with test_session_factory() as db:
        assert db.scalars(select(StorageCleanupTask)).all() == []
    assert not storage.exists(residual_path)


def test_cleanup_enqueue_failure_rolls_back_whole_deletion(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    test_session_factory: sessionmaker[Session],
) -> None:
    """Falha ao registar as tarefas de limpeza: nunca é silenciosa — a
    eliminação inteira faz rollback e nada (registos ou ficheiros) se
    perde."""
    from app.services import document_service as service_module

    _, headers = _setup(client)
    document, version = _create_searchable_document(
        client, headers, "conteudo protegido", title="Enqueue Falha",
        source_url="https://example.edu/ef",
    )
    storage = get_document_storage()
    with test_session_factory() as db:
        stored_version = db.get(DocumentVersion, uuid.UUID(version["id"]))
        assert stored_version is not None
        storage_path = stored_version.storage_path

    def failing_enqueue(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("simulated cleanup enqueue failure")

    monkeypatch.setattr(service_module, "_enqueue_cleanup_tasks", failing_enqueue)
    # O TestClient relança exceções de servidor: a falha nunca é um 204
    # silencioso — propaga como erro e nada é eliminado.
    with pytest.raises(RuntimeError, match="simulated cleanup enqueue failure"):
        _delete(client, document["id"], headers)

    with test_session_factory() as db:
        assert db.get(Document, uuid.UUID(document["id"])) is not None
        assert _count(db, DocumentVersion, document["id"]) == 1
        assert _count(db, DocumentChunk, document["id"]) == 1
    assert storage.exists(storage_path)


def test_concurrent_reconciliations_do_not_lose_or_duplicate_tasks(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> None:
    """Duas reconciliações simultâneas: SKIP LOCKED particiona as tarefas
    sem bloquear, sem perder entradas e sem processar em duplicado."""
    from app.models.storage_cleanup_task import StorageCleanupTask
    from app.services.document_service import reconcile_pending_deletions

    _, headers = _setup(client)
    storage = get_document_storage()
    paths: list[str] = []
    for index in range(2):
        _, version = _create_searchable_document(
            client,
            headers,
            f"conteudo concorrente {index}",
            title=f"Concorrente {index}",
            source_url=f"https://example.edu/cc{index}",
        )
        with test_session_factory() as db:
            stored_version = db.get(DocumentVersion, uuid.UUID(version["id"]))
            assert stored_version is not None
            paths.append(stored_version.storage_path)
            db.add(
                StorageCleanupTask(
                    document_id=stored_version.document_id,
                    storage_path=stored_version.storage_path,
                )
            )
            db.commit()

    removed_counts: list[int] = []
    errors: list[Exception] = []
    lock = threading.Lock()
    barrier = threading.Barrier(2)

    def reconcile_worker() -> None:
        db = test_session_factory()
        try:
            barrier.wait()
            removed = reconcile_pending_deletions(db, storage)
            with lock:
                removed_counts.append(removed)
        except Exception as exc:  # noqa: BLE001 - recolhido para asserção
            with lock:
                errors.append(exc)
        finally:
            db.close()

    threads = [threading.Thread(target=reconcile_worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
        assert not thread.is_alive()

    assert errors == []
    # As duas reconciliações repartiram as tarefas: total exato, sem
    # duplicados nem perdas.
    assert sum(removed_counts) == 2
    with test_session_factory() as db:
        assert db.scalars(select(StorageCleanupTask)).all() == []
    for path in paths:
        assert not storage.exists(path)
