"""Testes diretos ao PostgreSQL das constraints das tabelas documentais
(migration 1482b165c943 / modelos Document e DocumentVersion).

A camada de serviços já garante estas regras em código; estes testes
contornam-na de propósito, construindo linhas diretamente com o ORM,
para confirmar que o PostgreSQL também as impõe — a mesma estratégia de
defesa em profundidade dos testes de integridade multi-institucional.
"""

import uuid
from collections.abc import Iterator
from datetime import date

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.models.document import Document
from app.models.document_version import DocumentVersion
from app.models.institution import Institution
from app.models.user import User


def _make_institution() -> Institution:
    return Institution(
        name="Test Institution",
        code=f"TST-{uuid.uuid4().hex[:8].upper()}",
        default_language="pt",
        supported_languages=["pt", "en"],
    )


def _make_user(institution: Institution) -> User:
    return User(
        institution_id=institution.id,
        full_name="Test User",
        email=f"user-{uuid.uuid4().hex[:8]}@example.com",
        password_hash="not-a-real-hash",
        role="admin",
        is_active=True,
    )


def _make_document(institution: Institution, user: User) -> Document:
    return Document(
        institution_id=institution.id,
        created_by_user_id=user.id,
        title="Integrity Test Document",
        language="pt",
    )


def _make_version(
    document: Document,
    user: User,
    **overrides: object,
) -> DocumentVersion:
    values: dict = {
        "document_id": document.id,
        "institution_id": document.institution_id,
        "uploaded_by_user_id": user.id,
        "version_number": 1,
        "original_filename": "file.txt",
        "mime_type": "text/plain",
        "size_bytes": 10,
        "checksum_sha256": uuid.uuid4().hex + uuid.uuid4().hex,
        "storage_path": f"{document.institution_id}/{document.id}/{uuid.uuid4()}/source.txt",
        "processing_status": "pending",
    }
    values.update(overrides)
    return DocumentVersion(**values)


@pytest.fixture
def db_session(test_session_factory: sessionmaker[Session]) -> Iterator[Session]:
    session = test_session_factory()
    yield session
    session.rollback()
    session.close()


def test_document_rejects_creator_from_another_institution(db_session: Session) -> None:
    institution_a = _make_institution()
    institution_b = _make_institution()
    db_session.add_all([institution_a, institution_b])
    db_session.flush()

    user_b = _make_user(institution_b)
    db_session.add(user_b)
    db_session.flush()

    # user_b pertence à instituição B, mas o documento reclama a A: a FK
    # composta (created_by_user_id, institution_id) tem de rejeitar.
    document = Document(
        institution_id=institution_a.id,
        created_by_user_id=user_b.id,
        title="Cross tenant",
        language="pt",
    )
    db_session.add(document)
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_version_rejects_document_from_another_institution(db_session: Session) -> None:
    institution_a = _make_institution()
    institution_b = _make_institution()
    db_session.add_all([institution_a, institution_b])
    db_session.flush()

    user_a = _make_user(institution_a)
    user_b = _make_user(institution_b)
    db_session.add_all([user_a, user_b])
    db_session.flush()

    document_a = _make_document(institution_a, user_a)
    db_session.add(document_a)
    db_session.flush()

    # O documento pertence à instituição A; a versão reclama a B.
    version = _make_version(document_a, user_b)
    version.institution_id = institution_b.id
    db_session.add(version)
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_version_rejects_uploader_from_another_institution(db_session: Session) -> None:
    institution_a = _make_institution()
    institution_b = _make_institution()
    db_session.add_all([institution_a, institution_b])
    db_session.flush()

    user_a = _make_user(institution_a)
    user_b = _make_user(institution_b)
    db_session.add_all([user_a, user_b])
    db_session.flush()

    document_a = _make_document(institution_a, user_a)
    db_session.add(document_a)
    db_session.flush()

    # Documento e institution_id coerentes (A), mas o uploader é da B.
    version = _make_version(document_a, user_b)
    db_session.add(version)
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_duplicate_checksum_in_same_institution_rejected_by_postgres(
    db_session: Session,
) -> None:
    institution = _make_institution()
    db_session.add(institution)
    db_session.flush()

    user = _make_user(institution)
    db_session.add(user)
    db_session.flush()

    document = _make_document(institution, user)
    db_session.add(document)
    db_session.flush()

    checksum = uuid.uuid4().hex + uuid.uuid4().hex
    first = _make_version(document, user, version_number=1, checksum_sha256=checksum)
    db_session.add(first)
    db_session.flush()

    second = _make_version(document, user, version_number=2, checksum_sha256=checksum)
    db_session.add(second)
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_invalid_processing_status_is_rejected(db_session: Session) -> None:
    institution = _make_institution()
    db_session.add(institution)
    db_session.flush()

    user = _make_user(institution)
    db_session.add(user)
    db_session.flush()

    document = _make_document(institution, user)
    db_session.add(document)
    db_session.flush()

    version = _make_version(document, user, processing_status="done")
    db_session.add(version)
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_non_positive_version_number_is_rejected(db_session: Session) -> None:
    institution = _make_institution()
    db_session.add(institution)
    db_session.flush()

    user = _make_user(institution)
    db_session.add(user)
    db_session.flush()

    document = _make_document(institution, user)
    db_session.add(document)
    db_session.flush()

    version = _make_version(document, user, version_number=0)
    db_session.add(version)
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_non_positive_size_bytes_is_rejected(db_session: Session) -> None:
    institution = _make_institution()
    db_session.add(institution)
    db_session.flush()

    user = _make_user(institution)
    db_session.add(user)
    db_session.flush()

    document = _make_document(institution, user)
    db_session.add(document)
    db_session.flush()

    version = _make_version(document, user, size_bytes=0)
    db_session.add(version)
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_invalid_validity_range_is_rejected(db_session: Session) -> None:
    institution = _make_institution()
    db_session.add(institution)
    db_session.flush()

    user = _make_user(institution)
    db_session.add(user)
    db_session.flush()

    document = _make_document(institution, user)
    document.valid_from = date(2026, 12, 31)
    document.valid_until = date(2026, 1, 1)
    db_session.add(document)
    with pytest.raises(IntegrityError):
        db_session.commit()
