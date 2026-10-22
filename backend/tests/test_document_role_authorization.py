"""Autorização documental por papel (C13, política v1.7).

Mecanismo separado do isolamento institucional: decide que papéis podem ser
fundamentados por um documento, dentro da mesma instituição. Documentos e
papéis são sintéticos.
"""

import io
import uuid
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.documents.retrievability import (
    DOCUMENT_ROLE_AUTHORIZED,
    RELAXABLE_CONDITIONS,
    RetrievabilityContext,
    RetrievalEligibility,
)
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from tests.role_support import create_account_and_login
from tests.test_evidence_retrievability_unit import _context, _subject
from tests.test_role_separation import _create_admin, _create_institution


@pytest.mark.parametrize(
    ("access_roles", "requester_role", "authorized"),
    [
        ((), "student", True),
        ((), None, True),
        (("staff",), "student", False),
        (("staff",), "staff", True),
        (("staff", "student"), "student", True),
        (("staff",), None, False),
    ],
)
def test_role_verdict(
    access_roles: tuple[str, ...], requester_role: str | None, authorized: bool
) -> None:
    verdict = RetrievalEligibility.explain(
        _subject(document_access_roles=access_roles),
        _context(requester_role=requester_role),
    )
    assert verdict.eligible is authorized
    if not authorized:
        assert verdict.failed_condition_names == ("document_role_authorized",)


def test_absence_of_role_never_widens_access() -> None:
    """Consumidores offline sem papel só veem documentos sem restrição."""
    assert DOCUMENT_ROLE_AUTHORIZED.holds(
        _subject(document_access_roles=()), _context(requester_role=None)
    )
    assert not DOCUMENT_ROLE_AUTHORIZED.holds(
        _subject(document_access_roles=("admin",)), _context(requester_role=None)
    )


@pytest.mark.parametrize(
    "condition",
    ["chunk_belongs_to_institution", "document_role_authorized", "version_processed"],
)
def test_only_validity_can_be_relaxed(condition: str) -> None:
    """Ablações e diagnóstico nunca desligam isolamento nem autorização."""
    with pytest.raises(ValueError, match="only validity"):
        RetrievabilityContext(
            institution_id=uuid.uuid4(),
            language="pt",
            reference_date=date(2026, 10, 1),
            official_only=True,
            relaxed_conditions=frozenset({condition}),
        )


def test_relaxed_validity_admits_an_expired_document_and_nothing_else() -> None:
    expired = _subject(document_valid_until=date(2020, 1, 1))
    restricted_expired = _subject(
        document_valid_until=date(2020, 1, 1), document_access_roles=("staff",)
    )
    relaxed = _context(requester_role="student", relaxed_conditions=RELAXABLE_CONDITIONS)

    assert not RetrievalEligibility.explain(expired, _context()).eligible
    assert RetrievalEligibility.explain(expired, relaxed).eligible
    assert not RetrievalEligibility.explain(restricted_expired, relaxed).eligible


# --- Base de dados ----------------------------------------------------------------------


def _world(client: TestClient) -> tuple[dict[str, str], dict[str, str]]:
    institution_id = _create_institution(client)
    admin, _ = _create_admin(client, institution_id)
    manager, _ = create_account_and_login(client, admin, role="knowledge_manager")
    return admin, manager


def _document(client: TestClient, manager: dict[str, str], title: str, roles: list[str]) -> dict:
    created = client.post(
        "/api/v1/documents",
        json={"title": title, "language": "pt", "official_source": True, "access_roles": roles},
        headers=manager,
    )
    assert created.status_code == 201, created.text
    version = client.post(
        f"/api/v1/documents/{created.json()['id']}/versions",
        files={
            "file": (
                f"{uuid.uuid4().hex}.txt",
                io.BytesIO(f"O prazo de matrícula termina a 30 de setembro ({title}).".encode()),
                "text/plain",
            )
        },
        headers=manager,
    )
    assert version.status_code == 201, version.text
    return created.json()


def test_documents_default_to_unrestricted_and_reject_unknown_roles(
    client: TestClient,
) -> None:
    _, manager = _world(client)
    default = client.post("/api/v1/documents", json={"title": "Sem papéis"}, headers=manager)
    unknown = client.post(
        "/api/v1/documents",
        json={"title": "Papel inválido", "access_roles": ["superuser"]},
        headers=manager,
    )
    null_update = client.patch(
        f"/api/v1/documents/{default.json()['id']}", json={"access_roles": None}, headers=manager
    )

    assert default.json()["access_roles"] == []
    assert unknown.status_code == 422
    assert null_update.status_code == 422


def test_sql_and_python_adapters_agree_for_every_role(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> None:
    admin, manager = _world(client)
    _document(client, manager, "Público", [])
    _document(client, manager, "Só staff", ["staff"])
    _document(client, manager, "Staff e alunos", ["staff", "student"])
    institution_id = client.get("/api/v1/auth/me", headers=admin).json()["institution_id"]

    for role in ("student", "staff", "user", None):
        context = RetrievabilityContext(
            institution_id=uuid.UUID(institution_id),
            language="pt",
            reference_date=date.today(),
            official_only=True,
            requester_role=role,
        )
        with test_session_factory() as db:
            sql_ids = set(db.scalars(RetrievalEligibility.select_eligible_chunk_ids(context)))
            rows = db.execute(
                select(DocumentChunk, Document).join(
                    Document, Document.id == DocumentChunk.document_id
                )
            ).all()
            python_ids = {
                chunk.id
                for chunk, document in rows
                if (not document.access_roles) or (role in document.access_roles)
            }
        assert sql_ids == python_ids, role


def test_b0_answering_respects_role_authorization(client: TestClient) -> None:
    admin, manager = _world(client)
    _document(client, manager, "Só staff", ["staff"])
    student, _ = create_account_and_login(client, admin, role="student")
    staff, _ = create_account_and_login(client, admin, role="staff")

    def search(headers: dict[str, str]) -> list[str]:
        response = client.post(
            "/api/v1/retrieval/search", json={"query": "prazo de matrícula"}, headers=headers
        )
        assert response.status_code == 200, response.text
        return [item["document_title"] for item in response.json()["items"]]

    assert search(student) == []
    assert search(staff) == ["Só staff"]


def test_document_management_is_not_restricted_by_access_roles(client: TestClient) -> None:
    """documents.manage governa a gestão, não a fundamentação."""
    _, manager = _world(client)
    document = _document(client, manager, "Só alunos", ["student"])

    read = client.get(f"/api/v1/documents/{document['id']}", headers=manager)

    assert read.status_code == 200
    assert read.json()["access_roles"] == ["student"]
