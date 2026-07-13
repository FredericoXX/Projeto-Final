"""Testes das versões de documentos: upload em streaming, validação de
formatos, deteção de duplicados, processamento síncrono, conteúdo
paginado, download, reprocessamento e concorrência.

Corre contra a base de dados de teste dedicada (ver conftest.py); a
fixture autouse `_document_storage_tmp` redireciona o armazenamento para
um diretório temporário por teste.
"""

import io
import threading
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.core.exceptions import ConflictError
from app.models.document_version import DocumentVersion
from app.models.user import User
from app.services import document_processing_service, document_version_service
from app.services.document_extraction_service import ExtractionResult
from app.storage import get_document_storage
from tests.pdf_utils import build_pdf

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


def _create_document(client: TestClient, headers: dict[str, str], **overrides: object) -> dict:
    payload: dict = {"title": "Test Document"}
    payload.update(overrides)
    response = client.post("/api/v1/documents", json=payload, headers=headers)
    assert response.status_code == 201
    return response.json()


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


def _setup(client: TestClient) -> tuple[str, dict[str, str], dict]:
    institution_id = _create_institution(client)
    headers = _create_admin_and_login(client, institution_id)
    document = _create_document(client, headers)
    return institution_id, headers, document


# --- Uploads válidos --------------------------------------------------------


def test_upload_txt_is_processed(client: TestClient) -> None:
    _, headers, document = _setup(client)

    response = _upload(client, headers, document["id"], "conteúdo em texto".encode())
    assert response.status_code == 201

    body = response.json()
    assert body["processing_status"] == "processed"
    assert body["version_number"] == 1
    assert body["mime_type"] == "text/plain"
    assert body["page_count"] is None
    assert body["processing_error"] is None
    assert body["processed_at"] is not None
    # storage_path e extracted_text nunca aparecem na resposta.
    assert "storage_path" not in body
    assert "extracted_text" not in body


def test_upload_markdown_is_processed(client: TestClient) -> None:
    _, headers, document = _setup(client)

    response = _upload(
        client,
        headers,
        document["id"],
        b"# Title\n\nBody text.",
        filename="guide.md",
        content_type="text/markdown",
    )
    assert response.status_code == 201

    body = response.json()
    assert body["processing_status"] == "processed"
    assert body["mime_type"] == "text/markdown"
    assert body["page_count"] is None


def test_upload_txt_with_utf8_bom_is_processed(client: TestClient) -> None:
    _, headers, document = _setup(client)

    response = _upload(
        client, headers, document["id"], b"\xef\xbb\xbftexto com BOM"
    )
    assert response.status_code == 201
    assert response.json()["processing_status"] == "processed"


def test_upload_pdf_with_text_is_processed_with_page_count(client: TestClient) -> None:
    _, headers, document = _setup(client)

    pdf = build_pdf(["First page text", "Second page text"])
    response = _upload(
        client,
        headers,
        document["id"],
        pdf,
        filename="report.pdf",
        content_type="application/pdf",
    )
    assert response.status_code == 201

    body = response.json()
    assert body["processing_status"] == "processed"
    assert body["mime_type"] == "application/pdf"
    assert body["page_count"] == 2


def test_second_upload_gets_version_number_two(client: TestClient) -> None:
    _, headers, document = _setup(client)

    first = _upload(client, headers, document["id"], b"first content")
    assert first.status_code == 201
    assert first.json()["version_number"] == 1

    second = _upload(client, headers, document["id"], b"second, different content")
    assert second.status_code == 201
    assert second.json()["version_number"] == 2


# --- Uploads inválidos -------------------------------------------------------


def test_upload_empty_file_returns_422(client: TestClient) -> None:
    _, headers, document = _setup(client)

    response = _upload(client, headers, document["id"], b"")
    assert response.status_code == 422


def test_upload_unsupported_type_returns_415(client: TestClient) -> None:
    _, headers, document = _setup(client)

    response = _upload(
        client,
        headers,
        document["id"],
        b"binary content",
        filename="report.docx",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    assert response.status_code == 415
    assert response.json()["detail"]["code"] == "unsupported_media_type"


def test_upload_pdf_without_signature_returns_415(client: TestClient) -> None:
    _, headers, document = _setup(client)

    response = _upload(
        client,
        headers,
        document["id"],
        b"NOT A PDF AT ALL",
        filename="fake.pdf",
        content_type="application/pdf",
    )
    assert response.status_code == 415


def test_upload_above_size_limit_returns_413(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "document_max_file_size_mb", 1)
    _, headers, document = _setup(client)

    content = b"x" * (1024 * 1024 + 1)
    response = _upload(client, headers, document["id"], content)
    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "payload_too_large"


def test_upload_to_document_of_other_institution_returns_404(client: TestClient) -> None:
    _, headers_a, document = _setup(client)

    institution_b = _create_institution(client)
    headers_b = _create_admin_and_login(client, institution_b)

    response = _upload(client, headers_b, document["id"], b"cross tenant")
    assert response.status_code == 404


# --- Duplicados ---------------------------------------------------------------


def test_duplicate_checksum_in_same_institution_returns_409(client: TestClient) -> None:
    _, headers, document = _setup(client)
    content = b"identical bytes"

    first = _upload(client, headers, document["id"], content)
    assert first.status_code == 201

    second = _upload(client, headers, document["id"], content, filename="other.txt")
    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "resource_conflict"


def test_same_checksum_in_different_institutions_is_allowed(client: TestClient) -> None:
    content = b"same bytes everywhere"

    _, headers_a, document_a = _setup(client)
    first = _upload(client, headers_a, document_a["id"], content)
    assert first.status_code == 201

    institution_b = _create_institution(client)
    headers_b = _create_admin_and_login(client, institution_b)
    document_b = _create_document(client, headers_b)
    second = _upload(client, headers_b, document_b["id"], content)
    assert second.status_code == 201


# --- Path traversal e exposição de caminhos ----------------------------------


def test_path_traversal_filename_is_neutralized(client: TestClient, tmp_path) -> None:
    _, headers, document = _setup(client)

    response = _upload(
        client, headers, document["id"], b"malicious?", filename="../../evil.txt"
    )
    assert response.status_code == 201
    assert response.json()["original_filename"] == "evil.txt"

    # Nada foi escrito fora do root do armazenamento (tmp_path/documents).
    assert not (tmp_path / "evil.txt").exists()
    storage_root = tmp_path / "documents"
    files = [p for p in storage_root.rglob("*") if p.is_file()]
    assert len(files) == 1
    assert files[0].name == "source.txt"


def test_api_never_returns_absolute_paths(client: TestClient, tmp_path) -> None:
    _, headers, document = _setup(client)

    upload = _upload(client, headers, document["id"], b"path check")
    version_id = upload.json()["id"]

    listing = client.get(f"/api/v1/documents/{document['id']}/versions", headers=headers)
    detail = client.get(
        f"/api/v1/documents/{document['id']}/versions/{version_id}", headers=headers
    )
    for response in (upload, listing, detail):
        assert str(tmp_path) not in response.text
        assert "storage_path" not in response.text


# --- Listagem e consulta -------------------------------------------------------


def test_list_versions_ordered_by_version_number_desc(client: TestClient) -> None:
    _, headers, document = _setup(client)
    _upload(client, headers, document["id"], b"v1 content")
    _upload(client, headers, document["id"], b"v2 content")
    _upload(client, headers, document["id"], b"v3 content")

    response = client.get(
        f"/api/v1/documents/{document['id']}/versions", headers=headers
    )
    assert response.status_code == 200

    body = response.json()
    assert body["total"] == 3
    assert [item["version_number"] for item in body["items"]] == [3, 2, 1]


def test_get_version_of_other_institution_returns_404(client: TestClient) -> None:
    _, headers_a, document = _setup(client)
    upload = _upload(client, headers_a, document["id"], b"tenant a content")
    version_id = upload.json()["id"]

    institution_b = _create_institution(client)
    headers_b = _create_admin_and_login(client, institution_b)

    response = client.get(
        f"/api/v1/documents/{document['id']}/versions/{version_id}", headers=headers_b
    )
    assert response.status_code == 404


# --- Processamento e erros -----------------------------------------------------


def test_undecodable_text_file_is_marked_failed_with_safe_error(
    client: TestClient, tmp_path
) -> None:
    _, headers, document = _setup(client)

    # Bytes inválidos em UTF-8: a versão é criada (201) mas a extração falha.
    response = _upload(client, headers, document["id"], b"\xff\xfe\x9c invalid")
    assert response.status_code == 201

    body = response.json()
    assert body["processing_status"] == "failed"
    assert body["processing_error"] == "The file could not be decoded as UTF-8 text."
    assert "Traceback" not in body["processing_error"]
    assert str(tmp_path) not in body["processing_error"]


def test_pdf_without_text_is_marked_failed_with_ocr_message(client: TestClient) -> None:
    _, headers, document = _setup(client)

    pdf = build_pdf([""])
    response = _upload(
        client,
        headers,
        document["id"],
        pdf,
        filename="scanned.pdf",
        content_type="application/pdf",
    )
    assert response.status_code == 201

    body = response.json()
    assert body["processing_status"] == "failed"
    assert "OCR is not available" in body["processing_error"]


# --- Conteúdo paginado -----------------------------------------------------------


def test_content_pagination_works(client: TestClient) -> None:
    _, headers, document = _setup(client)
    text = "abcdefghij" * 10  # 100 caracteres
    upload = _upload(client, headers, document["id"], text.encode())
    version_id = upload.json()["id"]

    url = f"/api/v1/documents/{document['id']}/versions/{version_id}/content"

    full = client.get(url, headers=headers)
    assert full.status_code == 200
    body = full.json()
    assert body["total_characters"] == 100
    assert body["text"] == text
    assert body["offset"] == 0

    sliced = client.get(f"{url}?offset=10&limit=20", headers=headers)
    assert sliced.status_code == 200
    body = sliced.json()
    assert body["text"] == text[10:30]
    assert body["total_characters"] == 100
    assert body["offset"] == 10
    assert body["limit"] == 20


def test_content_limit_above_maximum_returns_422(client: TestClient) -> None:
    _, headers, document = _setup(client)
    upload = _upload(client, headers, document["id"], b"tiny")
    version_id = upload.json()["id"]

    response = client.get(
        f"/api/v1/documents/{document['id']}/versions/{version_id}/content?limit=100001",
        headers=headers,
    )
    assert response.status_code == 422


def test_content_of_unprocessed_version_returns_409(client: TestClient) -> None:
    _, headers, document = _setup(client)

    # A extração falha (bytes inválidos), por isso a versão fica failed.
    upload = _upload(client, headers, document["id"], b"\xff\xfe bad bytes")
    version_id = upload.json()["id"]
    assert upload.json()["processing_status"] == "failed"

    response = client.get(
        f"/api/v1/documents/{document['id']}/versions/{version_id}/content",
        headers=headers,
    )
    assert response.status_code == 409


# --- Download --------------------------------------------------------------------


def test_download_returns_original_file(client: TestClient) -> None:
    _, headers, document = _setup(client)
    content = "conteúdo original para download".encode()
    upload = _upload(client, headers, document["id"], content, filename="manual.txt")
    version_id = upload.json()["id"]

    response = client.get(
        f"/api/v1/documents/{document['id']}/versions/{version_id}/download",
        headers=headers,
    )
    assert response.status_code == 200
    assert response.content == content
    assert response.headers["content-type"].startswith("text/plain")
    assert "manual.txt" in response.headers["content-disposition"]


def test_download_from_other_institution_returns_404(client: TestClient) -> None:
    _, headers_a, document = _setup(client)
    upload = _upload(client, headers_a, document["id"], b"private bytes")
    version_id = upload.json()["id"]

    institution_b = _create_institution(client)
    headers_b = _create_admin_and_login(client, institution_b)

    response = client.get(
        f"/api/v1/documents/{document['id']}/versions/{version_id}/download",
        headers=headers_b,
    )
    assert response.status_code == 404


# --- Reprocessamento ---------------------------------------------------------------


def test_reprocess_processed_version_works(client: TestClient) -> None:
    _, headers, document = _setup(client)
    upload = _upload(client, headers, document["id"], b"reprocess me")
    version_id = upload.json()["id"]

    response = client.post(
        f"/api/v1/documents/{document['id']}/versions/{version_id}/reprocess",
        headers=headers,
    )
    assert response.status_code == 200

    body = response.json()
    assert body["processing_status"] == "processed"
    assert body["version_number"] == 1


def test_reprocess_does_not_create_new_version(client: TestClient) -> None:
    _, headers, document = _setup(client)
    upload = _upload(client, headers, document["id"], b"only one version")
    version_id = upload.json()["id"]

    client.post(
        f"/api/v1/documents/{document['id']}/versions/{version_id}/reprocess",
        headers=headers,
    )

    listing = client.get(f"/api/v1/documents/{document['id']}/versions", headers=headers)
    assert listing.json()["total"] == 1


def test_reprocess_while_processing_returns_409(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> None:
    _, headers, document = _setup(client)
    upload = _upload(client, headers, document["id"], b"lock me")
    version_id = upload.json()["id"]

    # Simula uma extração em curso, marcando o estado diretamente na base.
    session = test_session_factory()
    try:
        version = session.get(DocumentVersion, uuid.UUID(version_id))
        assert version is not None
        version.processing_status = "processing"
        session.commit()
    finally:
        session.close()

    response = client.post(
        f"/api/v1/documents/{document['id']}/versions/{version_id}/reprocess",
        headers=headers,
    )
    assert response.status_code == 409


def test_concurrent_reprocessing_starts_only_one_extraction(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Duas sessões reais disputam a mesma linha de document_versions.

    A primeira grava processing e inicia a extração; a segunda espera pelo
    SELECT ... FOR UPDATE, relê esse estado após o commit e recebe conflito.
    """
    _, headers, document = _setup(client)
    upload = _upload(client, headers, document["id"], b"reprocess concurrently")
    version_id = uuid.UUID(upload.json()["id"])

    barrier = threading.Barrier(2)
    extraction_started = threading.Event()
    conflict_seen = threading.Event()
    release_extraction = threading.Event()
    results: list[str] = []
    errors: list[Exception] = []
    result_lock = threading.Lock()
    extraction_calls = 0

    def blocking_extract(*_args: object) -> ExtractionResult:
        nonlocal extraction_calls
        with result_lock:
            extraction_calls += 1
        extraction_started.set()
        if not release_extraction.wait(timeout=10):
            msg = "timed out waiting to release extraction"
            raise RuntimeError(msg)
        return ExtractionResult(text="reprocessed once", page_count=None)

    monkeypatch.setattr(document_processing_service, "extract_text", blocking_extract)
    storage = get_document_storage()

    def reprocess_worker() -> None:
        session = test_session_factory()
        try:
            version = session.get(DocumentVersion, version_id)
            assert version is not None
            barrier.wait()
            processed = document_processing_service.reprocess_version(
                session, version, storage
            )
            with result_lock:
                results.append(processed.processing_status)
        except ConflictError as exc:
            session.rollback()
            with result_lock:
                errors.append(exc)
            conflict_seen.set()
        except Exception as exc:  # noqa: BLE001 - o teste regista para asserção
            session.rollback()
            with result_lock:
                errors.append(exc)
        finally:
            session.close()

    threads = [threading.Thread(target=reprocess_worker) for _ in range(2)]
    for thread in threads:
        thread.start()

    assert extraction_started.wait(timeout=10)
    assert conflict_seen.wait(timeout=10)
    release_extraction.set()

    for thread in threads:
        thread.join(timeout=15)
        assert not thread.is_alive()

    assert extraction_calls == 1
    assert results == ["processed"]
    assert len(errors) == 1
    assert isinstance(errors[0], ConflictError)


# --- Concorrência -------------------------------------------------------------------


def test_concurrent_uploads_get_distinct_sequential_version_numbers(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> None:
    """Dois uploads concorrentes para o mesmo documento, cada um com a sua
    sessão SQLAlchemy contra o PostgreSQL real. O lock SELECT ... FOR
    UPDATE na linha do documento serializa a atribuição do número de
    versão: os números têm de sair únicos e sequenciais, e nenhum upload
    pode sobrescrever o outro."""
    institution_id, headers, document = _setup(client)

    me = client.get("/api/v1/auth/me", headers=headers)
    admin_id = uuid.UUID(me.json()["id"])
    document_id = uuid.UUID(document["id"])

    results: list[int] = []
    errors: list[Exception] = []
    lock = threading.Lock()
    barrier = threading.Barrier(2)
    storage = get_document_storage()

    def upload_worker(content: bytes) -> None:
        session = test_session_factory()
        try:
            admin = session.get(User, admin_id)
            assert admin is not None
            barrier.wait()
            version = document_version_service.create_version(
                session,
                admin,
                document_id,
                upload_stream=io.BytesIO(content),
                filename="concurrent.txt",
                declared_content_type="text/plain",
                storage=storage,
            )
            with lock:
                results.append(version.version_number)
        except Exception as exc:  # noqa: BLE001 - o teste regista para asserção
            with lock:
                errors.append(exc)
        finally:
            session.close()

    t1 = threading.Thread(target=upload_worker, args=(b"concurrent content one",))
    t2 = threading.Thread(target=upload_worker, args=(b"concurrent content two",))
    t1.start()
    t2.start()
    t1.join(timeout=15)
    t2.join(timeout=15)

    assert errors == []
    assert sorted(results) == [1, 2]

    verify = test_session_factory()
    try:
        versions = verify.scalars(
            select(DocumentVersion).where(DocumentVersion.document_id == document_id)
        ).all()
        assert sorted(v.version_number for v in versions) == [1, 2]
        # Cada versão manteve o seu próprio ficheiro: nenhum upload
        # sobrescreveu o outro.
        paths = {v.storage_path for v in versions}
        assert len(paths) == 2
        for v in versions:
            assert storage.exists(v.storage_path)
    finally:
        verify.close()
