"""Integração do OCR com o processamento, a base de dados e a API.

Usa a base de dados de teste dedicada e documentos sintéticos gerados em
runtime; o motor OCR real nunca é executado — o TesseractOcrEngine é
substituído por fakes através de monkeypatch no módulo de extração.
"""

import io
import uuid

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
from sqlalchemy import func, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.models.conversation import Conversation
from app.models.document_chunk import DocumentChunk
from app.models.document_version import DocumentVersion
from app.models.message import Message
from app.models.message_source import MessageSource
from app.services import document_extraction_service, document_processing_service
from app.services.document_extraction_service import (
    LOW_QUALITY_WARNING,
    OCR_UNAVAILABLE_MESSAGE,
)
from app.services.ocr_engine import OcrPageResult, OcrWord, build_page_result
from app.storage import get_document_storage
from tests.pdf_utils import build_pdf

BOOTSTRAP_HEADERS = {"X-Bootstrap-Token": settings.bootstrap_token or ""}
_ADMIN_PASSWORD = "supersecret123"

NATIVE_TEXT = "Regulamento sintetico com texto nativo suficiente para nao precisar de OCR."


def _word(text: str, left: int, *, confidence: float = 95.0) -> OcrWord:
    return OcrWord(
        text=text,
        confidence=confidence,
        block=1,
        paragraph=1,
        line=1,
        left=left,
        top=0,
        width=10 * len(text),
        height=20,
    )


class FakeOcrEngine:
    def __init__(self, *, available: bool = True, confidence: float = 95.0) -> None:
        self.available = available
        self.confidence = confidence

    def is_available(self) -> bool:
        return self.available

    def recognize(self, image: object, language: str) -> OcrPageResult:
        return build_page_result(
            (
                _word("Inicio", 0, confidence=self.confidence),
                _word("das", 80, confidence=self.confidence),
                _word("aulas", 130, confidence=self.confidence),
                _word("05", 700, confidence=self.confidence),
                _word("de", 740, confidence=self.confidence),
                _word("outubro", 780, confidence=self.confidence),
                _word("de", 870, confidence=self.confidence),
                _word("2030", 910, confidence=self.confidence),
            )
        )


def _install_fake_engine(monkeypatch: pytest.MonkeyPatch, engine: FakeOcrEngine) -> None:
    monkeypatch.setattr(
        document_extraction_service, "TesseractOcrEngine", lambda **_kwargs: engine
    )


def _scanned_pdf_bytes() -> bytes:
    image = Image.new("RGB", (200, 100), "white")
    ImageDraw.Draw(image).rectangle((20, 20, 180, 80), fill="black")
    buffer = io.BytesIO()
    image.save(buffer, format="PDF")
    image.close()
    return buffer.getvalue()


def _mixed_pdf_bytes() -> bytes:
    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter()
    writer.add_page(PdfReader(io.BytesIO(build_pdf([NATIVE_TEXT]))).pages[0])
    writer.add_page(PdfReader(io.BytesIO(_scanned_pdf_bytes())).pages[0])
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def _create_institution(client: TestClient) -> str:
    response = client.post(
        "/api/v1/institutions",
        json={
            "name": "OCR Institution",
            "code": f"OCR-{uuid.uuid4().hex[:8].upper()}",
            "default_language": "pt",
            "supported_languages": ["pt", "en"],
        },
        headers=BOOTSTRAP_HEADERS,
    )
    assert response.status_code == 201
    return response.json()["id"]


def _create_admin_and_login(client: TestClient, institution_id: str) -> dict[str, str]:
    email = f"admin-{uuid.uuid4().hex[:8]}@example.com"
    response = client.post(
        "/api/v1/auth/register-initial-admin",
        json={
            "institution_id": institution_id,
            "full_name": "Admin OCR",
            "email": email,
            "password": _ADMIN_PASSWORD,
        },
        headers=BOOTSTRAP_HEADERS,
    )
    assert response.status_code == 201
    login = client.post(
        "/api/v1/auth/login", json={"email": email, "password": _ADMIN_PASSWORD}
    )
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _create_document(client: TestClient, headers: dict[str, str]) -> dict:
    response = client.post(
        "/api/v1/documents", json={"title": "Documento OCR"}, headers=headers
    )
    assert response.status_code == 201
    return response.json()


def _setup(client: TestClient) -> tuple[str, dict[str, str], dict]:
    institution_id = _create_institution(client)
    headers = _create_admin_and_login(client, institution_id)
    document = _create_document(client, headers)
    return institution_id, headers, document


def _upload(
    client: TestClient,
    headers: dict[str, str],
    document_id: str,
    content: bytes,
    filename: str = "scanned.pdf",
    content_type: str = "application/pdf",
    extra_data: dict[str, str] | None = None,
):
    return client.post(
        f"/api/v1/documents/{document_id}/versions",
        files={"file": (filename, io.BytesIO(content), content_type)},
        data=extra_data or {},
        headers=headers,
    )


def _count_chunks(session: Session, version_id: str) -> int:
    return int(
        session.scalar(
            select(func.count())
            .select_from(DocumentChunk)
            .where(DocumentChunk.document_version_id == uuid.UUID(version_id))
        )
        or 0
    )


# --- Processamento e persistência ---------------------------------------------


def test_scanned_pdf_ends_processed_with_ocr_metadata(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_engine(monkeypatch, FakeOcrEngine(confidence=95.0))
    _, headers, document = _setup(client)

    response = _upload(client, headers, document["id"], _scanned_pdf_bytes())
    assert response.status_code == 201
    body = response.json()
    assert body["processing_status"] == "processed"
    assert body["processing_error"] is None
    assert body["page_count"] == 1
    assert body["extraction_method"] == "ocr"
    assert body["extraction_quality"] == "high"
    assert body["extraction_warning"] is None
    assert isinstance(body["extraction_details"], list)
    assert body["extraction_details"][0]["method"] == "ocr"
    assert body["extraction_details"][0]["ocr_confidence"] == pytest.approx(95.0)

    session = test_session_factory()
    try:
        version = session.get(DocumentVersion, uuid.UUID(body["id"]))
        assert version is not None
        assert version.extracted_text is not None
        # Evento e data sintéticos na mesma linha, com separador de coluna.
        assert "Inicio das aulas | 05 de outubro de 2030" in version.extracted_text
        assert _count_chunks(session, body["id"]) >= 1
    finally:
        session.close()


def test_mixed_pdf_ends_processed_with_method_mixed(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_fake_engine(monkeypatch, FakeOcrEngine())
    _, headers, document = _setup(client)

    response = _upload(client, headers, document["id"], _mixed_pdf_bytes(), "mixed.pdf")
    assert response.status_code == 201
    body = response.json()
    assert body["processing_status"] == "processed"
    assert body["extraction_method"] == "mixed"
    assert body["page_count"] == 2
    methods = [detail["method"] for detail in body["extraction_details"]]
    assert methods == ["native", "ocr"]


def test_native_pdf_upload_keeps_native_metadata(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Nenhum fake instalado: um PDF nativo nunca chega a construir o motor.
    _, headers, document = _setup(client)
    response = _upload(client, headers, document["id"], build_pdf([NATIVE_TEXT]), "native.pdf")
    assert response.status_code == 201
    body = response.json()
    assert body["processing_status"] == "processed"
    assert body["extraction_method"] == "native"
    assert body["extraction_quality"] == "high"
    assert body["extraction_details"][0]["ocr_confidence"] is None


def test_txt_and_markdown_uploads_remain_functional(client: TestClient) -> None:
    _, headers, document = _setup(client)
    txt = _upload(client, headers, document["id"], b"conteudo texto", "a.txt", "text/plain")
    assert txt.status_code == 201
    assert txt.json()["processing_status"] == "processed"
    assert txt.json()["extraction_method"] == "native"
    assert txt.json()["extraction_details"] is None  # sem conceito de página

    other = _create_document(client, headers)
    md = _upload(client, headers, other["id"], b"# Titulo\n\ncorpo", "b.md", "text/markdown")
    assert md.status_code == 201
    assert md.json()["processing_status"] == "processed"


def test_low_confidence_ends_processed_with_warning_not_failed(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_fake_engine(monkeypatch, FakeOcrEngine(confidence=30.0))
    _, headers, document = _setup(client)

    response = _upload(client, headers, document["id"], _scanned_pdf_bytes())
    assert response.status_code == 201
    body = response.json()
    # Qualidade baixa nunca transforma um processamento bem-sucedido em failed.
    assert body["processing_status"] == "processed"
    assert body["processing_error"] is None
    assert body["extraction_quality"] == "low"
    assert body["extraction_warning"] == LOW_QUALITY_WARNING


def test_unavailable_ocr_ends_failed_with_safe_error_and_no_partial_state(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_engine(monkeypatch, FakeOcrEngine(available=False))
    _, headers, document = _setup(client)

    response = _upload(client, headers, document["id"], _scanned_pdf_bytes())
    assert response.status_code == 201
    body = response.json()
    assert body["processing_status"] == "failed"
    assert body["processing_error"] == OCR_UNAVAILABLE_MESSAGE
    # Falha nunca mantém metadados de sucesso nem texto parcial.
    assert body["extraction_method"] is None
    assert body["extraction_quality"] is None
    assert body["extraction_warning"] is None
    assert body["extraction_details"] is None

    session = test_session_factory()
    try:
        version = session.get(DocumentVersion, uuid.UUID(body["id"]))
        assert version is not None
        assert version.extracted_text is None
        assert _count_chunks(session, body["id"]) == 0
    finally:
        session.close()


def test_reprocess_failed_version_can_end_processed_and_clears_previous_state(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = FakeOcrEngine(available=False)
    _install_fake_engine(monkeypatch, engine)
    _, headers, document = _setup(client)
    body = _upload(client, headers, document["id"], _scanned_pdf_bytes()).json()
    assert body["processing_status"] == "failed"

    # Runtime "instalado": o reprocessamento da versão failed conclui.
    engine.available = True
    response = client.post(
        f"/api/v1/documents/{document['id']}/versions/{body['id']}/reprocess",
        headers=headers,
    )
    assert response.status_code == 200
    reprocessed = response.json()
    assert reprocessed["processing_status"] == "processed"
    assert reprocessed["processing_error"] is None
    assert reprocessed["extraction_method"] == "ocr"


def test_reprocess_failure_clears_success_metadata(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = FakeOcrEngine()
    _install_fake_engine(monkeypatch, engine)
    _, headers, document = _setup(client)
    body = _upload(client, headers, document["id"], _scanned_pdf_bytes()).json()
    assert body["extraction_method"] == "ocr"

    engine.available = False
    response = client.post(
        f"/api/v1/documents/{document['id']}/versions/{body['id']}/reprocess",
        headers=headers,
    )
    assert response.status_code == 200
    failed = response.json()
    assert failed["processing_status"] == "failed"
    assert failed["extraction_method"] is None
    assert failed["extraction_quality"] is None
    assert failed["extraction_warning"] is None
    assert failed["extraction_details"] is None


def test_commit_failure_leaves_no_partial_state(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_engine(monkeypatch, FakeOcrEngine())
    _, headers, document = _setup(client)
    body = _upload(client, headers, document["id"], _scanned_pdf_bytes()).json()
    assert body["processing_status"] == "processed"

    session = test_session_factory()
    try:
        version = session.get(DocumentVersion, uuid.UUID(body["id"]))
        assert version is not None
        storage = get_document_storage()
        real_commit = session.commit
        calls = {"count": 0}

        def failing_final_commit() -> None:
            calls["count"] += 1
            if calls["count"] == 2:  # o commit final (o 1.º grava "processing";
                # o 3.º é o _finalize_failure e tem de funcionar)
                raise RuntimeError("simulated commit failure")
            real_commit()

        monkeypatch.setattr(session, "commit", failing_final_commit)
        result = document_processing_service.reprocess_version(session, version, storage)
        monkeypatch.setattr(session, "commit", real_commit)
        # A falha de commit final termina failed, sem estado parcial.
        assert result.processing_status == "failed"
        assert result.extracted_text is None
        assert result.extraction_method is None
        assert _count_chunks(session, body["id"]) == 0
    finally:
        session.close()


def test_processing_does_not_touch_conversations_or_sources(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_engine(monkeypatch, FakeOcrEngine())
    _, headers, document = _setup(client)

    def _snapshot(session: Session) -> tuple[int, int, int]:
        return (
            int(session.scalar(select(func.count()).select_from(Conversation)) or 0),
            int(session.scalar(select(func.count()).select_from(Message)) or 0),
            int(session.scalar(select(func.count()).select_from(MessageSource)) or 0),
        )

    session = test_session_factory()
    try:
        before = _snapshot(session)
    finally:
        session.close()

    _upload(client, headers, document["id"], _scanned_pdf_bytes())

    session = test_session_factory()
    try:
        assert _snapshot(session) == before
    finally:
        session.close()


# --- Isolamento institucional ---------------------------------------------------


def test_version_of_other_institution_remains_404(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_fake_engine(monkeypatch, FakeOcrEngine())
    _, headers_a, document_a = _setup(client)
    body = _upload(client, headers_a, document_a["id"], _scanned_pdf_bytes()).json()

    institution_b = _create_institution(client)
    headers_b = _create_admin_and_login(client, institution_b)
    response = client.get(
        f"/api/v1/documents/{document_a['id']}/versions/{body['id']}",
        headers=headers_b,
    )
    assert response.status_code == 404


# --- API: schemas de leitura ------------------------------------------------------


def test_version_read_exposes_typed_metadata_and_hides_internals(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_fake_engine(monkeypatch, FakeOcrEngine())
    _, headers, document = _setup(client)
    body = _upload(client, headers, document["id"], _scanned_pdf_bytes()).json()

    response = client.get(
        f"/api/v1/documents/{document['id']}/versions/{body['id']}", headers=headers
    )
    assert response.status_code == 200
    version = response.json()
    assert version["extraction_method"] == "ocr"
    assert version["extraction_quality"] in {"high", "medium", "low"}
    detail = version["extraction_details"][0]
    assert set(detail) == {
        "page_number",
        "method",
        "native_characters",
        "extracted_characters",
        "ocr_confidence",
        "quality",
        "warning",
    }
    # Campos internos continuam ausentes do endpoint de metadados.
    assert "storage_path" not in version
    assert "extracted_text" not in version


def test_historical_versions_return_null_metadata(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> None:
    _, headers, document = _setup(client)
    body = _upload(client, headers, document["id"], b"texto antigo", "a.txt", "text/plain").json()

    # Simula uma versão histórica anterior ao OCR: campos a NULL.
    session = test_session_factory()
    try:
        version = session.get(DocumentVersion, uuid.UUID(body["id"]))
        assert version is not None
        version.extraction_method = None
        version.extraction_quality = None
        version.extraction_warning = None
        version.extraction_details = None
        session.commit()
    finally:
        session.close()

    response = client.get(
        f"/api/v1/documents/{document['id']}/versions/{body['id']}", headers=headers
    )
    assert response.status_code == 200
    version_body = response.json()
    assert version_body["extraction_method"] is None
    assert version_body["extraction_quality"] is None
    assert version_body["extraction_warning"] is None
    assert version_body["extraction_details"] is None


@pytest.mark.parametrize(
    "field",
    [
        "extraction_method",
        "extraction_quality",
        "extraction_warning",
        "extraction_details",
        "force_ocr",
    ],
)
def test_client_cannot_send_calculated_extraction_fields(
    client: TestClient, field: str
) -> None:
    """Campos calculados pelo servidor (e force_ocr) são rejeitados com
    422 — nunca aceites nem silenciosamente ignorados."""
    _, headers, document = _setup(client)
    response = _upload(
        client,
        headers,
        document["id"],
        build_pdf([NATIVE_TEXT]),
        "native.pdf",
        extra_data={field: "ocr"},
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert field in str(detail)

    # Nenhuma versão foi criada pelo pedido rejeitado.
    listing = client.get(
        f"/api/v1/documents/{document['id']}/versions", headers=headers
    )
    assert listing.status_code == 200
    assert listing.json()["total"] == 0


def test_upload_without_forbidden_fields_still_works(client: TestClient) -> None:
    _, headers, document = _setup(client)
    response = _upload(client, headers, document["id"], build_pdf([NATIVE_TEXT]), "ok.pdf")
    assert response.status_code == 201
    assert response.json()["extraction_method"] == "native"


def test_no_public_ocr_endpoint_exists(client: TestClient) -> None:
    from app.main import app

    paths = [getattr(route, "path", "") for route in app.routes]
    assert not any("ocr" in path.lower() for path in paths)


# --- Constraints da base de dados --------------------------------------------------


def test_constraints_reject_invalid_extraction_values(
    client: TestClient,
    test_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_engine(monkeypatch, FakeOcrEngine())
    _, headers, document = _setup(client)
    body = _upload(client, headers, document["id"], _scanned_pdf_bytes()).json()

    from sqlalchemy.exc import DBAPIError

    for column, value in (("extraction_method", "bogus"), ("extraction_quality", "great")):
        with pytest.raises(DBAPIError):
            with test_engine.begin() as connection:
                connection.execute(
                    text(
                        f"UPDATE document_versions SET {column} = :value WHERE id = :id"
                    ),
                    {"value": value, "id": body["id"]},
                )
