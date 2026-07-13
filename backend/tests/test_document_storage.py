"""Testes do armazenamento local de documentos.

Duas frentes: testes unitários do LocalDocumentStorage (caminhos,
temporários, proteção contra path traversal) e testes de ausência de
ficheiros órfãos nos cenários de erro do upload — incluindo a falha de
commit depois de o ficheiro final já ter sido movido, forçada aqui ao
desativar a verificação prévia de checksum para deixar a UNIQUE
constraint disparar no commit.
"""

import io
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.services import document_version_service
from app.storage.local import LocalDocumentStorage, StoragePathError

BOOTSTRAP_HEADERS = {"X-Bootstrap-Token": settings.bootstrap_token or ""}

_ADMIN_PASSWORD = "supersecret123"


# --- LocalDocumentStorage (unitários) ---------------------------------------


def test_save_temp_writes_chunks_inside_root(tmp_path: Path) -> None:
    storage = LocalDocumentStorage(tmp_path)

    relative = storage.save_temp([b"abc", b"def"])
    resolved = storage.resolve_path(relative)

    assert resolved.is_relative_to(tmp_path)
    assert resolved.read_bytes() == b"abcdef"


def test_save_temp_removes_partial_file_when_producer_fails(tmp_path: Path) -> None:
    storage = LocalDocumentStorage(tmp_path)

    def failing_chunks():
        yield b"partial data"
        msg = "stream interrupted"
        raise RuntimeError(msg)

    with pytest.raises(RuntimeError):
        storage.save_temp(failing_chunks())

    leftovers = [p for p in tmp_path.rglob("*") if p.is_file()]
    assert leftovers == []


def test_move_to_final_moves_atomically(tmp_path: Path) -> None:
    storage = LocalDocumentStorage(tmp_path)
    temp = storage.save_temp([b"payload"])

    storage.move_to_final(temp, "inst/doc/ver/source.txt")

    assert not storage.exists(temp)
    assert storage.exists("inst/doc/ver/source.txt")
    with storage.open("inst/doc/ver/source.txt") as handle:
        assert handle.read() == b"payload"


def test_resolve_path_rejects_escape_attempts(tmp_path: Path) -> None:
    storage = LocalDocumentStorage(tmp_path)

    with pytest.raises(StoragePathError):
        storage.resolve_path("../outside.txt")
    with pytest.raises(StoragePathError):
        storage.resolve_path("a/../../outside.txt")


def test_delete_is_idempotent(tmp_path: Path) -> None:
    storage = LocalDocumentStorage(tmp_path)
    temp = storage.save_temp([b"to delete"])

    storage.delete(temp)
    assert not storage.exists(temp)
    # Segunda remoção não levanta erro.
    storage.delete(temp)


# --- Ausência de órfãos nos cenários de erro do upload ------------------------


def _create_institution(client: TestClient) -> str:
    response = client.post(
        "/api/v1/institutions",
        json={
            "name": "Test Institution",
            "code": f"TST-{uuid.uuid4().hex[:8].upper()}",
            "default_language": "pt",
            "supported_languages": ["pt", "en"],
        },
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


def _create_document(client: TestClient, headers: dict[str, str]) -> str:
    response = client.post(
        "/api/v1/documents", json={"title": "Storage Test"}, headers=headers
    )
    assert response.status_code == 201
    return response.json()["id"]


def _upload(
    client: TestClient,
    headers: dict[str, str],
    document_id: str,
    content: bytes,
    filename: str = "notes.txt",
    content_type: str = "text/plain",
):
    return client.post(
        f"/api/v1/documents/{document_id}/versions",
        files={"file": (filename, io.BytesIO(content), content_type)},
        headers=headers,
    )


def _stored_files(tmp_path: Path) -> list[Path]:
    root = tmp_path / "documents"
    if not root.exists():
        return []
    return [p for p in root.rglob("*") if p.is_file()]


def test_temp_file_removed_after_unsupported_type(client: TestClient, tmp_path: Path) -> None:
    institution_id = _create_institution(client)
    headers = _create_admin_and_login(client, institution_id)
    document_id = _create_document(client, headers)

    response = _upload(
        client,
        headers,
        document_id,
        b"whatever bytes",
        filename="evil.exe",
        content_type="application/octet-stream",
    )
    assert response.status_code == 415
    assert _stored_files(tmp_path) == []


def test_temp_file_removed_after_duplicate_checksum(
    client: TestClient, tmp_path: Path
) -> None:
    institution_id = _create_institution(client)
    headers = _create_admin_and_login(client, institution_id)
    document_id = _create_document(client, headers)
    content = b"duplicated bytes"

    first = _upload(client, headers, document_id, content)
    assert first.status_code == 201

    second = _upload(client, headers, document_id, content, filename="copy.txt")
    assert second.status_code == 409

    # Só o ficheiro da primeira versão pode existir; nem temporários nem
    # finais órfãos do segundo upload.
    files = _stored_files(tmp_path)
    assert len(files) == 1
    assert files[0].name == "source.txt"


def test_temp_file_removed_after_size_limit_exceeded(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "document_max_file_size_mb", 1)
    institution_id = _create_institution(client)
    headers = _create_admin_and_login(client, institution_id)
    document_id = _create_document(client, headers)

    response = _upload(client, headers, document_id, b"x" * (1024 * 1024 + 1))
    assert response.status_code == 413
    assert _stored_files(tmp_path) == []


def test_final_file_removed_when_commit_fails(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Simula a corrida entre a verificação prévia de checksum e o commit:
    com a verificação desativada, o segundo upload do mesmo conteúdo só
    falha na UNIQUE constraint, já depois de o ficheiro final ter sido
    movido — o service tem de o remover e devolver 409, sem órfãos."""
    monkeypatch.setattr(
        document_version_service, "_ensure_checksum_unique", lambda *args: None
    )
    institution_id = _create_institution(client)
    headers = _create_admin_and_login(client, institution_id)
    document_id = _create_document(client, headers)
    content = b"raced content"

    first = _upload(client, headers, document_id, content)
    assert first.status_code == 201

    second = _upload(client, headers, document_id, content, filename="race.txt")
    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "resource_conflict"

    files = _stored_files(tmp_path)
    assert len(files) == 1
    assert files[0].name == "source.txt"
