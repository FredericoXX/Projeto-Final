"""Associação de identidade externa e consulta dos próprios pedidos académicos.

O adaptador ativo é escolhido pela configuração real (``mock`` ou
``disabled``) ou por dependency override, nunca por rede. O adaptador simulado
serve apenas as instituições sintéticas ``DEMO-HEI`` e ``DEMO-HEI-B``, por
isso os cenários que o usam criam a instituição com um desses códigos. Nenhum
teste faz chamadas externas, usa credenciais ou exige um modelo de linguagem.
"""

import ast
import inspect
import socket
import uuid
from collections.abc import Callable, Iterator, Mapping
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.answering.dependencies import get_answer_generator
from app.core import config as config_module
from app.core.config import Settings, settings
from app.institutional import dependencies as institutional_dependencies
from app.institutional.contracts import (
    AcademicRequestQuery,
    AcademicRequestQueryKind,
    AcademicRequestRecord,
    AcademicRequestsResult,
    AuthorizedInstitutionalIdentity,
    InstitutionalAccessOutcome,
)
from app.institutional.dependencies import get_institutional_data_provider
from app.institutional.providers.mock import (
    DEMO_INSTITUTION_CODE,
    SECOND_DEMO_INSTITUTION_CODE,
    SNAPSHOT_UPDATED_AT,
    SYNTHETIC_SNAPSHOT,
    InstitutionSnapshot,
    MockInstitutionalDataProvider,
)
from app.main import app
from app.models.chunk_embedding import ChunkEmbedding
from app.models.document_chunk import DocumentChunk
from app.models.message import Message
from app.models.user_external_identity import UserExternalIdentity
from app.retrieval.dependencies import get_retriever
from app.services import academic_request_service
from tests.role_support import create_account_and_login, create_knowledge_manager

BOOTSTRAP_HEADERS = {"X-Bootstrap-Token": settings.bootstrap_token or ""}
ADMIN_PASSWORD = "supersecret123"
BACKEND_DIR = Path(__file__).resolve().parents[1]


class _ExplodingProvider:
    """Adaptador cuja falha técnica tem de virar UNAVAILABLE, sem fuga de dados."""

    simulated = False

    def serves(self, institution_id: uuid.UUID) -> bool:
        return True

    def query_academic_requests(
        self, identity: AuthorizedInstitutionalIdentity, query: AcademicRequestQuery
    ) -> AcademicRequestsResult:
        raise RuntimeError(f"boom for {identity.external_subject}")


class _WrongDetailProvider:
    """Devolve um pedido diferente do indicado — output inconsistente."""

    simulated = False

    def serves(self, institution_id: uuid.UUID) -> bool:
        return True

    def query_academic_requests(
        self, identity: AuthorizedInstitutionalIdentity, query: AcademicRequestQuery
    ) -> AcademicRequestsResult:
        return AcademicRequestsResult(
            outcome=InstitutionalAccessOutcome.SUCCESS,
            records=(
                AcademicRequestRecord(
                    request_id="REQ-OTHER",
                    request_type="Outro",
                    official_status="Submetido",
                    updated_at=datetime(2026, 9, 1, tzinfo=UTC),
                ),
            ),
        )


class _RecordingProvider(MockInstitutionalDataProvider):
    """Adaptador simulado que regista as identidades recebidas.

    ``during_query`` corre dentro da chamada à fonte: é o seam para simular uma
    revogação concorrente enquanto a consulta está em curso.
    """

    def __init__(self, scope: Mapping[uuid.UUID, InstitutionSnapshot]) -> None:
        super().__init__(scope)
        self.identities: list[AuthorizedInstitutionalIdentity] = []
        self.during_query: Callable[[], None] | None = None

    def query_academic_requests(
        self, identity: AuthorizedInstitutionalIdentity, query: AcademicRequestQuery
    ) -> AcademicRequestsResult:
        self.identities.append(identity)
        if self.during_query is not None:
            self.during_query()
        return super().query_academic_requests(identity, query)


@pytest.fixture
def use_provider() -> Iterator:
    def install(provider: object) -> object:
        app.dependency_overrides[get_institutional_data_provider] = lambda: provider
        return provider

    yield install
    app.dependency_overrides.pop(get_institutional_data_provider, None)


@pytest.fixture
def mock_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ativa o modo simulado pela configuração, usando a factory real."""
    monkeypatch.setattr(settings, "institutional_data_provider", "mock")


def _recording(*institutions: tuple[str, str]) -> _RecordingProvider:
    """Adaptador de registo ligado às instituições ``(id, código)`` indicadas."""
    return _RecordingProvider.for_institutions(
        (uuid.UUID(institution_id), code) for institution_id, code in institutions
    )


def _create_institution(client: TestClient, code: str | None = None) -> str:
    response = client.post(
        "/api/v1/institutions",
        json={
            "name": "Academic Requests Institution",
            "code": code or f"ACR-{uuid.uuid4().hex[:8].upper()}",
            "default_language": "pt",
            "supported_languages": ["pt", "en"],
        },
        headers=BOOTSTRAP_HEADERS,
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _create_admin(client: TestClient, institution_id: str) -> dict[str, str]:
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
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _link(client: TestClient, admin_headers: dict[str, str], user_id: str, subject: str):
    return client.put(
        f"/api/v1/users/{user_id}/external-identity",
        json={"external_subject": subject},
        headers=admin_headers,
    )


def _linked_student(
    client: TestClient,
    admin_headers: dict[str, str],
    subject: str = "SYNTH-STUDENT-0001",
    role: str = "student",
) -> tuple[dict[str, str], str]:
    headers, user_id = create_account_and_login(client, admin_headers, role=role)
    assert _link(client, admin_headers, user_id, subject).status_code == 200
    return headers, user_id


def _setup(
    client: TestClient, code: str | None = DEMO_INSTITUTION_CODE
) -> tuple[str, dict[str, str]]:
    """Instituição (por omissão a sintética DEMO-HEI, servida pelo mock) e admin."""
    institution_id = _create_institution(client, code)
    return institution_id, _create_admin(client, institution_id)


_TIMESTAMP_FIELDS = ("attempted_at", "queried_at")


def _without_timestamps(body: dict) -> dict:
    provenance = dict(body["detail"]["provenance"])
    for name in _TIMESTAMP_FIELDS:
        provenance.pop(name)
    return {**body, "detail": {**body["detail"], "provenance": provenance}}


def _commit(factory: sessionmaker[Session], sql: str, **params: object) -> None:
    """Grava uma alteração numa sessão independente, como outra transação."""
    with factory() as db:
        db.execute(text(sql), params)
        db.commit()


# --- Associação de identidade externa ----------------------------------------


def test_admin_links_an_account_and_records_how(client: TestClient) -> None:
    institution_id, admin_headers = _setup(client)
    admin_id = client.get("/api/v1/auth/me", headers=admin_headers).json()["id"]
    _, student_id = create_account_and_login(client, admin_headers, role="student")

    response = _link(client, admin_headers, student_id, "  SYNTH-STUDENT-0001  ")

    assert response.status_code == 200
    body = response.json()
    assert body["external_subject"] == "SYNTH-STUDENT-0001"
    assert body["user_id"] == student_id
    assert body["institution_id"] == institution_id
    assert body["link_method"] == "administrative"
    assert body["linked_by_user_id"] == admin_id
    read = client.get(f"/api/v1/users/{student_id}/external-identity", headers=admin_headers)
    assert read.status_code == 200


def test_linking_the_same_subject_again_is_idempotent(client: TestClient) -> None:
    _, admin_headers = _setup(client)
    _, student_id = create_account_and_login(client, admin_headers, role="student")

    first = _link(client, admin_headers, student_id, "SYNTH-STUDENT-0001")
    second = _link(client, admin_headers, student_id, "SYNTH-STUDENT-0001")
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()


def test_relinking_to_another_subject_requires_explicit_removal(client: TestClient) -> None:
    _, admin_headers = _setup(client)
    _, student_id = create_account_and_login(client, admin_headers, role="student")
    assert _link(client, admin_headers, student_id, "SYNTH-STUDENT-0001").status_code == 200

    assert _link(client, admin_headers, student_id, "SYNTH-STUDENT-0002").status_code == 409

    removed = client.delete(
        f"/api/v1/users/{student_id}/external-identity", headers=admin_headers
    )
    assert removed.status_code == 204
    assert _link(client, admin_headers, student_id, "SYNTH-STUDENT-0002").status_code == 200


def test_a_subject_cannot_be_linked_to_two_accounts(client: TestClient) -> None:
    _, admin_headers = _setup(client)
    _, first_id = create_account_and_login(client, admin_headers, role="student")
    _, second_id = create_account_and_login(client, admin_headers, role="student")

    assert _link(client, admin_headers, first_id, "SYNTH-STUDENT-0001").status_code == 200
    assert _link(client, admin_headers, second_id, "SYNTH-STUDENT-0001").status_code == 409


@pytest.mark.parametrize("role", ["admin", "knowledge_manager", "staff"])
def test_roles_without_individual_records_cannot_be_linked(client: TestClient, role: str) -> None:
    _, admin_headers = _setup(client)
    _, user_id = create_account_and_login(client, admin_headers, role=role)
    assert _link(client, admin_headers, user_id, "SYNTH-STUDENT-0001").status_code == 409


@pytest.mark.parametrize("role", ["student", "user", "knowledge_manager", "staff"])
def test_non_admin_accounts_cannot_link_anyone_including_themselves(
    client: TestClient, role: str
) -> None:
    _, admin_headers = _setup(client)
    headers, user_id = create_account_and_login(client, admin_headers, role=role)

    assert _link(client, headers, user_id, "SYNTH-STUDENT-0001").status_code == 403
    assert (
        client.get(f"/api/v1/users/{user_id}/external-identity", headers=headers).status_code
        == 403
    )
    assert (
        client.delete(f"/api/v1/users/{user_id}/external-identity", headers=headers).status_code
        == 403
    )


def test_admin_of_another_institution_sees_the_account_as_nonexistent(
    client: TestClient,
) -> None:
    _, admin_a = _setup(client)
    _, admin_b = _setup(client, None)
    _, student_a = create_account_and_login(client, admin_a, role="student")

    assert _link(client, admin_b, student_a, "SYNTH-STUDENT-0001").status_code == 404
    assert _link(client, admin_a, student_a, "SYNTH-STUDENT-0001").status_code == 200
    assert (
        client.get(f"/api/v1/users/{student_a}/external-identity", headers=admin_b).status_code
        == 404
    )
    assert (
        client.delete(f"/api/v1/users/{student_a}/external-identity", headers=admin_b).status_code
        == 404
    )


def test_the_same_subject_may_exist_in_two_institutions(client: TestClient) -> None:
    _, admin_a = _setup(client)
    _, admin_b = _setup(client, None)
    _, student_a = create_account_and_login(client, admin_a, role="student")
    _, student_b = create_account_and_login(client, admin_b, role="student")

    assert _link(client, admin_a, student_a, "SYNTH-STUDENT-0001").status_code == 200
    assert _link(client, admin_b, student_b, "SYNTH-STUDENT-0001").status_code == 200


def test_link_payload_rejects_extra_fields_and_blank_subjects(client: TestClient) -> None:
    _, admin_headers = _setup(client)
    _, student_id = create_account_and_login(client, admin_headers, role="student")

    extra = client.put(
        f"/api/v1/users/{student_id}/external-identity",
        json={"external_subject": "SYNTH-STUDENT-0001", "institution_id": str(uuid.uuid4())},
        headers=admin_headers,
    )
    blank = _link(client, admin_headers, student_id, "   ")
    assert extra.status_code == blank.status_code == 422


def test_email_equality_never_creates_a_link(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> None:
    _, admin_headers = _setup(client)
    created = client.post(
        "/api/v1/users",
        json={
            "full_name": "Aluno",
            # O "identificador" no email não tem qualquer efeito.
            "email": "synth-student-0001@example.com",
            "password": "studentsecret1",
            "role": "student",
        },
        headers=admin_headers,
    )
    assert created.status_code == 201
    with test_session_factory() as db:
        assert db.scalar(select(func.count()).select_from(UserExternalIdentity)) == 0


# --- Configuração e integração desativada --------------------------------------


def test_integration_is_disabled_by_default() -> None:
    assert Settings.model_fields["institutional_data_provider"].default == "disabled"


def test_factory_returns_no_provider_when_disabled(
    monkeypatch: pytest.MonkeyPatch, test_session_factory: sessionmaker[Session]
) -> None:
    monkeypatch.setattr(settings, "institutional_data_provider", "disabled")
    with test_session_factory() as db:
        assert institutional_dependencies.get_institutional_data_provider(db) is None


def test_factory_returns_the_simulated_provider_only_when_selected(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    test_session_factory: sessionmaker[Session],
) -> None:
    served = uuid.UUID(_create_institution(client, DEMO_INSTITUTION_CODE))
    other = uuid.UUID(_create_institution(client))
    monkeypatch.setattr(settings, "institutional_data_provider", "mock")
    with test_session_factory() as db:
        provider = institutional_dependencies.get_institutional_data_provider(db)
    assert isinstance(provider, MockInstitutionalDataProvider)
    assert provider.simulated is True
    # Ligado às instituições sintéticas existentes, e só a essas.
    assert provider.serves(served)
    assert not provider.serves(other)


def test_simulated_mode_is_refused_outside_development_and_test(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("INSTITUTIONAL_DATA_PROVIDER", "mock")
    monkeypatch.setenv("ENVIRONMENT", "production")
    with pytest.raises(ValueError, match="only allowed"):
        Settings()  # type: ignore[call-arg]


def test_unknown_provider_is_refused_at_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INSTITUTIONAL_DATA_PROVIDER", "university-api")
    with pytest.raises(ValueError, match="INSTITUTIONAL_DATA_PROVIDER"):
        Settings()  # type: ignore[call-arg]


def test_simulated_mode_is_accepted_in_test_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INSTITUTIONAL_DATA_PROVIDER", "mock")
    monkeypatch.setenv("ENVIRONMENT", "test")
    assert Settings().institutional_data_provider == "mock"  # type: ignore[call-arg]


def test_disabled_integration_shows_no_simulated_data(
    client: TestClient, use_provider
) -> None:
    use_provider(None)
    _, admin_headers = _setup(client)
    headers, _ = _linked_student(client, admin_headers)

    access = client.get("/api/v1/academic-requests/access", headers=headers)
    assert access.json() == {"available": False, "reason": "not_configured", "simulated": False}

    listed = client.get("/api/v1/academic-requests", headers=headers)
    assert listed.status_code == 503
    assert listed.json()["detail"]["code"] == "institutional_integration_not_configured"
    assert "REQ-" not in listed.text
    detail = client.get("/api/v1/academic-requests/REQ-0001-A", headers=headers)
    assert detail.status_code == 503
    assert "Certidão" not in detail.text


def test_application_imports_without_loading_the_simulated_provider() -> None:
    """Resolver o fornecedor desativado não carrega o adaptador simulado."""
    source = inspect.getsource(institutional_dependencies)
    tree = ast.parse(source)
    top_level_imports = [
        node
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module and "providers" in node.module
    ]
    assert top_level_imports == []
    assert config_module.INSTITUTIONAL_PROVIDER_DISABLED == "disabled"


# --- Acesso ---------------------------------------------------------------------


def test_access_reports_why_the_area_is_unavailable(
    client: TestClient, mock_provider
) -> None:
    _, admin_headers = _setup(client)
    unlinked_headers, _ = create_account_and_login(client, admin_headers, role="student")
    linked_headers, _ = _linked_student(client, admin_headers)
    manager_headers = create_knowledge_manager(client, admin_headers)

    def access(headers: dict[str, str]) -> dict:
        response = client.get("/api/v1/academic-requests/access", headers=headers)
        assert response.status_code == 200
        return response.json()

    assert access(linked_headers) == {"available": True, "reason": "available", "simulated": True}
    assert access(unlinked_headers)["reason"] == "not_linked"
    assert access(admin_headers)["reason"] == "not_permitted"
    assert access(manager_headers)["reason"] == "not_permitted"


@pytest.mark.parametrize("role", ["admin", "knowledge_manager", "staff"])
def test_roles_without_permission_get_403(client: TestClient, mock_provider, role: str) -> None:
    _, admin_headers = _setup(client)
    headers = (
        admin_headers
        if role == "admin"
        else create_account_and_login(client, admin_headers, role=role)[0]
    )
    response = client.get("/api/v1/academic-requests", headers=headers)
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "forbidden"


def test_unlinked_student_is_denied_without_reaching_the_provider(
    client: TestClient, use_provider
) -> None:
    institution_id, admin_headers = _setup(client)
    provider = use_provider(_recording((institution_id, DEMO_INSTITUTION_CODE)))
    headers, _ = create_account_and_login(client, admin_headers, role="student")

    response = client.get("/api/v1/academic-requests", headers=headers)

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "institutional_access_denied"
    assert provider.identities == []


def test_requires_authentication(client: TestClient, mock_provider) -> None:
    assert client.get("/api/v1/academic-requests").status_code == 401
    assert client.get("/api/v1/academic-requests/access").status_code == 401


# --- Listagem e detalhe -----------------------------------------------------------


def test_linked_student_lists_only_own_requests_with_provenance(
    client: TestClient, mock_provider
) -> None:
    institution_id, admin_headers = _setup(client)
    headers, _ = _linked_student(client, admin_headers, "SYNTH-STUDENT-0001")

    response = client.get("/api/v1/academic-requests", headers=headers)

    assert response.status_code == 200
    body = response.json()
    assert body["outcome"] == "success"
    assert [item["request_id"] for item in body["items"]] == [
        "REQ-0001-A",
        "REQ-0001-B",
        "REQ-0001-C",
    ]
    assert "REQ-0002-A" not in response.text
    provenance = body["provenance"]
    assert provenance["origin"] == "institutional_api"
    assert provenance["simulated"] is True
    assert provenance["institution_id"] == institution_id
    assert provenance["access_result"] == "success"
    assert provenance["source_updated_at"] == SNAPSHOT_UPDATED_AT.isoformat().replace(
        "+00:00", "Z"
    )
    assert provenance["queried_at"]
    assert provenance["fields_used"] == [
        "request_id",
        "request_type",
        "official_status",
        "updated_at",
        "next_step",
    ]


def test_official_status_is_kept_as_received_and_next_step_only_when_given(
    client: TestClient, mock_provider
) -> None:
    _, admin_headers = _setup(client)
    headers, _ = _linked_student(client, admin_headers, "SYNTH-STUDENT-0001")

    items = {
        item["request_id"]: item
        for item in client.get("/api/v1/academic-requests", headers=headers).json()["items"]
    }
    assert items["REQ-0001-B"]["official_status"] == "Em apreciação"
    assert items["REQ-0001-B"]["next_step"] is None
    assert items["REQ-0001-C"]["next_step"] == "Submeter o comprovativo em falta."
    # Sem campos derivados: nada de "approved", "completed" ou prazos.
    assert set(items["REQ-0001-B"]) == {
        "request_id",
        "request_type",
        "official_status",
        "updated_at",
        "next_step",
    }


def test_student_without_requests_gets_an_explicit_empty_result(
    client: TestClient, mock_provider
) -> None:
    _, admin_headers = _setup(client)
    headers, _ = _linked_student(client, admin_headers, "SYNTH-STUDENT-0003")

    response = client.get("/api/v1/academic-requests", headers=headers)

    assert response.status_code == 200
    assert response.json()["outcome"] == "no_data"
    assert response.json()["items"] == []
    assert response.json()["provenance"]["access_result"] == "no_data"
    assert "next_step" not in response.json()["provenance"]["fields_used"]


def test_user_role_may_also_consult_own_requests(client: TestClient, mock_provider) -> None:
    _, admin_headers = _setup(client)
    headers, _ = _linked_student(client, admin_headers, "SYNTH-STUDENT-0002", role="user")

    response = client.get("/api/v1/academic-requests", headers=headers)
    assert response.status_code == 200
    assert [item["request_id"] for item in response.json()["items"]] == ["REQ-0002-A"]


def test_detail_returns_own_request(client: TestClient, mock_provider) -> None:
    _, admin_headers = _setup(client)
    headers, _ = _linked_student(client, admin_headers, "SYNTH-STUDENT-0001")

    response = client.get("/api/v1/academic-requests/REQ-0001-C", headers=headers)

    assert response.status_code == 200
    assert response.json()["outcome"] == "success"
    assert response.json()["item"]["request_id"] == "REQ-0001-C"
    assert response.json()["provenance"]["origin"] == "institutional_api"


def test_another_students_request_is_indistinguishable_from_a_missing_one(
    client: TestClient, mock_provider
) -> None:
    _, admin_headers = _setup(client)
    headers, _ = _linked_student(client, admin_headers, "SYNTH-STUDENT-0001")

    foreign = client.get("/api/v1/academic-requests/REQ-0002-A", headers=headers)
    missing = client.get("/api/v1/academic-requests/REQ-9999-Z", headers=headers)

    assert foreign.status_code == missing.status_code == 404
    # Idênticas, proveniência incluída, a menos dos instantes da consulta.
    assert _without_timestamps(foreign.json()) == _without_timestamps(missing.json())
    assert foreign.json()["detail"]["provenance"]["access_result"] == "no_data"
    assert foreign.json()["detail"]["provenance"]["fields_used"] == []
    assert "Mudança de turma" not in foreign.text


@pytest.mark.parametrize(
    "request_id",
    ["..%2F..%2Fetc", "REQ 0001", "-REQ", "a" * 65, "REQ;DROP"],
)
def test_malformed_request_identifiers_never_reach_the_provider(
    client: TestClient, use_provider, request_id: str
) -> None:
    institution_id, admin_headers = _setup(client)
    provider = use_provider(_recording((institution_id, DEMO_INSTITUTION_CODE)))
    headers, _ = _linked_student(client, admin_headers)

    response = client.get(f"/api/v1/academic-requests/{request_id}", headers=headers)

    assert response.status_code in {404, 422}
    assert provider.identities == []


def test_query_parameters_cannot_select_another_identity(
    client: TestClient, use_provider
) -> None:
    institution_id, admin_headers = _setup(client)
    provider = use_provider(_recording((institution_id, DEMO_INSTITUTION_CODE)))
    headers, _ = _linked_student(client, admin_headers, "SYNTH-STUDENT-0001")

    response = client.get(
        "/api/v1/academic-requests",
        params={
            "external_subject": "SYNTH-STUDENT-0002",
            "user_id": str(uuid.uuid4()),
            "institution_id": str(uuid.uuid4()),
        },
        headers=headers,
    )

    assert response.status_code == 200
    assert "REQ-0002-A" not in response.text
    assert provider.identities == [
        AuthorizedInstitutionalIdentity(
            institution_id=uuid.UUID(institution_id),
            external_subject="SYNTH-STUDENT-0001",
        )
    ]


def test_students_of_two_institutions_are_isolated(client: TestClient, use_provider) -> None:
    institution_a, admin_a = _setup(client)
    institution_b, admin_b = _setup(client, SECOND_DEMO_INSTITUTION_CODE)
    provider = use_provider(
        _recording(
            (institution_a, DEMO_INSTITUTION_CODE),
            (institution_b, SECOND_DEMO_INSTITUTION_CODE),
        )
    )
    headers_a, _ = _linked_student(client, admin_a, "SYNTH-STUDENT-0001")
    headers_b, _ = _linked_student(client, admin_b, "SYNTH-STUDENT-0002")

    response_a = client.get("/api/v1/academic-requests", headers=headers_a).json()
    response_b = client.get("/api/v1/academic-requests", headers=headers_b).json()

    assert response_a["provenance"]["institution_id"] == institution_a
    assert response_b["provenance"]["institution_id"] == institution_b
    assert {identity.institution_id for identity in provider.identities} == {
        uuid.UUID(institution_a),
        uuid.UUID(institution_b),
    }
    assert "REQ-0001" not in str(response_b)


def test_the_same_external_subject_in_two_institutions_reads_distinct_records(
    client: TestClient, mock_provider
) -> None:
    """F2 da auditoria de 2026-10-09: o identificador externo só tem
    significado dentro da sua instituição. O mesmo SYNTH-STUDENT-0001 em
    DEMO-HEI e em DEMO-HEI-B são dois alunos, com pedidos distintos — antes da
    correção, ambos recebiam os três pedidos de DEMO-HEI."""
    _, admin_a = _setup(client)
    _, admin_b = _setup(client, SECOND_DEMO_INSTITUTION_CODE)
    headers_a, _ = _linked_student(client, admin_a, "SYNTH-STUDENT-0001")
    headers_b, _ = _linked_student(client, admin_b, "SYNTH-STUDENT-0001")

    items_a = client.get("/api/v1/academic-requests", headers=headers_a).json()["items"]
    items_b = client.get("/api/v1/academic-requests", headers=headers_b).json()["items"]

    assert [item["request_id"] for item in items_a] == ["REQ-0001-A", "REQ-0001-B", "REQ-0001-C"]
    assert [item["request_id"] for item in items_b] == ["REQ-B001-A"]
    # Nem por identificador de pedido se atravessa a fronteira institucional.
    foreign = client.get("/api/v1/academic-requests/REQ-0001-A", headers=headers_b)
    missing = client.get("/api/v1/academic-requests/REQ-9999-Z", headers=headers_b)
    assert foreign.status_code == missing.status_code == 404
    assert _without_timestamps(foreign.json()) == _without_timestamps(missing.json())
    assert "Certidão" not in foreign.text
    other_way = client.get("/api/v1/academic-requests/REQ-B001-A", headers=headers_a)
    missing_in_a = client.get("/api/v1/academic-requests/REQ-9999-Z", headers=headers_a)
    assert other_way.status_code == missing_in_a.status_code == 404
    assert _without_timestamps(other_way.json()) == _without_timestamps(missing_in_a.json())
    assert "trabalhador-estudante" not in other_way.text


def test_an_institution_not_served_by_the_adapter_is_not_configured(
    client: TestClient, mock_provider
) -> None:
    """Uma instituição fora do âmbito do adaptador nunca recebe os dados de
    outra: para ela, a integração não está configurada."""
    institution_id, admin_headers = _setup(client, None)
    headers, _ = _linked_student(client, admin_headers, "SYNTH-STUDENT-0001")

    access = client.get("/api/v1/academic-requests/access", headers=headers).json()
    listed = client.get("/api/v1/academic-requests", headers=headers)
    detail = client.get("/api/v1/academic-requests/REQ-0001-A", headers=headers)

    assert access == {"available": False, "reason": "not_configured", "simulated": False}
    # Listagem e detalhe aplicam a mesma delimitação.
    for response in (listed, detail):
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "institutional_integration_not_configured"
        assert response.json()["detail"]["provenance"]["source_consulted"] is False
        assert response.json()["detail"]["provenance"]["institution_id"] == institution_id
        assert "REQ-" not in response.text
        assert "Certidão" not in response.text


# --- Resultados que não são sucesso ------------------------------------------------


def test_source_denial_is_reported_as_access_denied(client: TestClient, mock_provider) -> None:
    _, admin_headers = _setup(client)
    headers, _ = _linked_student(client, admin_headers, "SYNTH-ACCESS-DENIED")

    response = client.get("/api/v1/academic-requests", headers=headers)
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "institutional_access_denied"


def test_source_unavailability_is_a_technical_failure_not_a_decision(
    client: TestClient,
    mock_provider,
    test_session_factory: sessionmaker[Session],
) -> None:
    _, admin_headers = _setup(client)
    headers, _ = _linked_student(client, admin_headers, "SYNTH-UNAVAILABLE")

    response = client.get("/api/v1/academic-requests", headers=headers)

    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "institutional_integration_unavailable"
    # Nem abstenção nem encaminhamento: nenhuma mensagem é criada.
    assert "escalate" not in response.text
    assert "abstain" not in response.text
    with test_session_factory() as db:
        assert db.scalar(select(func.count()).select_from(Message)) == 0


def test_provider_exception_becomes_unavailable_without_leaking_data(
    client: TestClient, use_provider, caplog: pytest.LogCaptureFixture
) -> None:
    use_provider(_ExplodingProvider())
    _, admin_headers = _setup(client)
    headers, _ = _linked_student(client, admin_headers, "SYNTH-STUDENT-0001")

    with caplog.at_level("DEBUG"):
        response = client.get("/api/v1/academic-requests", headers=headers)

    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "institutional_integration_unavailable"
    assert "SYNTH-STUDENT-0001" not in response.text
    assert "boom" not in response.text
    assert "SYNTH-STUDENT-0001" not in caplog.text
    assert "boom" not in caplog.text


def test_inconsistent_detail_from_provider_is_not_shown(
    client: TestClient, use_provider
) -> None:
    use_provider(_WrongDetailProvider())
    _, admin_headers = _setup(client)
    headers, _ = _linked_student(client, admin_headers)

    response = client.get("/api/v1/academic-requests/REQ-0001-A", headers=headers)
    assert response.status_code == 502
    assert "REQ-OTHER" not in response.text


def test_role_change_and_deactivation_revoke_access(client: TestClient, mock_provider) -> None:
    _, admin_headers = _setup(client)
    headers, student_id = _linked_student(client, admin_headers)
    assert client.get("/api/v1/academic-requests", headers=headers).status_code == 200

    client.patch(f"/api/v1/users/{student_id}", json={"role": "staff"}, headers=admin_headers)
    assert client.get("/api/v1/academic-requests", headers=headers).status_code == 403

    client.patch(f"/api/v1/users/{student_id}", json={"role": "student"}, headers=admin_headers)
    assert client.get("/api/v1/academic-requests", headers=headers).status_code == 200

    client.patch(f"/api/v1/users/{student_id}", json={"is_active": False}, headers=admin_headers)
    assert client.get("/api/v1/academic-requests", headers=headers).status_code == 401


def test_removing_the_link_revokes_access(client: TestClient, mock_provider) -> None:
    _, admin_headers = _setup(client)
    headers, student_id = _linked_student(client, admin_headers)

    client.delete(f"/api/v1/users/{student_id}/external-identity", headers=admin_headers)
    response = client.get("/api/v1/academic-requests", headers=headers)
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "institutional_access_denied"


# --- Sem rede, sem LLM, sem persistência -----------------------------------------


def test_simulated_query_makes_no_network_call_and_needs_no_llm(
    client: TestClient,
    mock_provider,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, admin_headers = _setup(client)
    headers, _ = _linked_student(client, admin_headers)

    def _no_network(*args: object, **kwargs: object) -> None:
        raise AssertionError("network access attempted")

    def _no_llm() -> None:
        raise AssertionError("answer generator requested")

    def _no_retriever() -> None:
        raise AssertionError("retriever requested")

    # A ligação à base de dados de teste já existe no pool; qualquer nova
    # ligação de rede a partir daqui falha o teste.
    monkeypatch.setattr(socket, "create_connection", _no_network)
    monkeypatch.setattr(socket.socket, "connect", _no_network)
    app.dependency_overrides[get_answer_generator] = _no_llm
    app.dependency_overrides[get_retriever] = _no_retriever
    try:
        listed = client.get("/api/v1/academic-requests", headers=headers)
        detail = client.get("/api/v1/academic-requests/REQ-0001-A", headers=headers)
    finally:
        app.dependency_overrides.pop(get_answer_generator, None)
        app.dependency_overrides.pop(get_retriever, None)

    assert listed.status_code == detail.status_code == 200


def test_query_persists_nothing_and_touches_no_document_index(
    client: TestClient,
    mock_provider,
    test_session_factory: sessionmaker[Session],
) -> None:
    _, admin_headers = _setup(client)
    headers, _ = _linked_student(client, admin_headers)

    client.get("/api/v1/academic-requests", headers=headers)
    client.get("/api/v1/academic-requests/REQ-0001-A", headers=headers)

    with test_session_factory() as db:
        assert db.scalar(select(func.count()).select_from(Message)) == 0
        assert db.scalar(select(func.count()).select_from(DocumentChunk)) == 0
        assert db.scalar(select(func.count()).select_from(ChunkEmbedding)) == 0


def test_service_is_independent_of_retrieval_and_generation() -> None:
    modules = (
        academic_request_service,
        institutional_dependencies,
    )
    for module in modules:
        tree = ast.parse(inspect.getsource(module))
        imported = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }
        assert not any(
            name.startswith(("app.retrieval", "app.answering", "app.embeddings"))
            for name in imported
        )
    contracts_source = (BACKEND_DIR / "app" / "institutional" / "contracts.py").read_text(
        encoding="utf-8"
    )
    assert "app.retrieval" not in contracts_source.split('"""', 2)[2]
    assert "import openai" not in contracts_source


# --- Contrato do adaptador ----------------------------------------------------------


def _scoped_mock() -> tuple[MockInstitutionalDataProvider, uuid.UUID, uuid.UUID]:
    institution_a, institution_b = uuid.uuid4(), uuid.uuid4()
    provider = MockInstitutionalDataProvider.for_institutions(
        [(institution_a, DEMO_INSTITUTION_CODE), (institution_b, SECOND_DEMO_INSTITUTION_CODE)]
    )
    return provider, institution_a, institution_b


def test_mock_provider_is_deterministic_and_filters_by_identity_first() -> None:
    provider, institution_a, _ = _scoped_mock()
    identity = AuthorizedInstitutionalIdentity(
        institution_id=institution_a, external_subject="SYNTH-STUDENT-0001"
    )
    listed = provider.query_academic_requests(
        identity, AcademicRequestQuery(kind=AcademicRequestQueryKind.LIST)
    )
    again = provider.query_academic_requests(
        identity, AcademicRequestQuery(kind=AcademicRequestQueryKind.LIST)
    )
    foreign = provider.query_academic_requests(
        identity,
        AcademicRequestQuery(kind=AcademicRequestQueryKind.DETAIL, request_id="REQ-0002-A"),
    )

    assert listed == again
    assert listed.outcome is InstitutionalAccessOutcome.SUCCESS
    assert foreign.outcome is InstitutionalAccessOutcome.NO_DATA
    assert foreign.records == ()


def test_mock_provider_selects_by_institution_and_subject() -> None:
    provider, institution_a, institution_b = _scoped_mock()
    query = AcademicRequestQuery(kind=AcademicRequestQueryKind.LIST)

    in_a = provider.query_academic_requests(
        AuthorizedInstitutionalIdentity(institution_a, "SYNTH-STUDENT-0001"), query
    )
    in_b = provider.query_academic_requests(
        AuthorizedInstitutionalIdentity(institution_b, "SYNTH-STUDENT-0001"), query
    )

    assert in_a.records == SYNTHETIC_SNAPSHOT[DEMO_INSTITUTION_CODE]["SYNTH-STUDENT-0001"]
    assert in_b.records == SYNTHETIC_SNAPSHOT[SECOND_DEMO_INSTITUTION_CODE]["SYNTH-STUDENT-0001"]
    assert {record.request_id for record in in_a.records}.isdisjoint(
        {record.request_id for record in in_b.records}
    )


def test_mock_provider_refuses_an_identity_outside_its_scope() -> None:
    provider, _, _ = _scoped_mock()
    outsider = uuid.uuid4()

    assert not provider.serves(outsider)
    for query in (
        AcademicRequestQuery(kind=AcademicRequestQueryKind.LIST),
        AcademicRequestQuery(kind=AcademicRequestQueryKind.DETAIL, request_id="REQ-0001-A"),
    ):
        result = provider.query_academic_requests(
            AuthorizedInstitutionalIdentity(outsider, "SYNTH-STUDENT-0001"), query
        )
        assert result.outcome is InstitutionalAccessOutcome.ACCESS_DENIED
        assert result.records == ()


def test_mock_provider_detail_is_scoped_like_the_listing() -> None:
    """O detalhe de um pedido de outra instituição é NO_DATA, como um inexistente."""
    provider, _, institution_b = _scoped_mock()
    identity_b = AuthorizedInstitutionalIdentity(institution_b, "SYNTH-STUDENT-0001")

    foreign = provider.query_academic_requests(
        identity_b,
        AcademicRequestQuery(kind=AcademicRequestQueryKind.DETAIL, request_id="REQ-0001-A"),
    )
    missing = provider.query_academic_requests(
        identity_b,
        AcademicRequestQuery(kind=AcademicRequestQueryKind.DETAIL, request_id="REQ-9999-Z"),
    )
    own = provider.query_academic_requests(
        identity_b,
        AcademicRequestQuery(kind=AcademicRequestQueryKind.DETAIL, request_id="REQ-B001-A"),
    )

    assert foreign == missing
    assert foreign.outcome is InstitutionalAccessOutcome.NO_DATA
    assert own.outcome is InstitutionalAccessOutcome.SUCCESS
    assert [record.request_id for record in own.records] == ["REQ-B001-A"]


@pytest.mark.parametrize("institution", ["a", "b"])
@pytest.mark.parametrize(
    ("subject", "outcome"),
    [
        ("SYNTH-STUDENT-0001", InstitutionalAccessOutcome.SUCCESS),
        ("SYNTH-STUDENT-0003-UNKNOWN", InstitutionalAccessOutcome.NO_DATA),
        ("SYNTH-ACCESS-DENIED", InstitutionalAccessOutcome.ACCESS_DENIED),
        ("SYNTH-UNAVAILABLE", InstitutionalAccessOutcome.UNAVAILABLE),
    ],
)
def test_mock_provider_scenarios_remain_available_in_each_served_institution(
    institution: str, subject: str, outcome: InstitutionalAccessOutcome
) -> None:
    provider, institution_a, institution_b = _scoped_mock()
    institution_id = institution_a if institution == "a" else institution_b

    result = provider.query_academic_requests(
        AuthorizedInstitutionalIdentity(institution_id, subject),
        AcademicRequestQuery(kind=AcademicRequestQueryKind.LIST),
    )

    assert result.outcome is outcome


def test_unknown_subject_is_no_data() -> None:
    provider, institution_a, _ = _scoped_mock()
    result = provider.query_academic_requests(
        AuthorizedInstitutionalIdentity(institution_id=institution_a, external_subject="SYNTH-X"),
        AcademicRequestQuery(kind=AcademicRequestQueryKind.LIST),
    )
    assert result.outcome is InstitutionalAccessOutcome.NO_DATA


def test_result_contract_rejects_incoherent_combinations() -> None:
    record = AcademicRequestRecord(
        request_id="R",
        request_type="T",
        official_status="S",
        updated_at=datetime(2026, 9, 1, tzinfo=UTC),
    )
    with pytest.raises(ValueError):
        AcademicRequestsResult(outcome=InstitutionalAccessOutcome.SUCCESS)
    with pytest.raises(ValueError):
        AcademicRequestsResult(outcome=InstitutionalAccessOutcome.UNAVAILABLE, records=(record,))
    with pytest.raises(ValueError):
        AcademicRequestQuery(kind=AcademicRequestQueryKind.DETAIL)
    with pytest.raises(ValueError):
        AcademicRequestQuery(kind=AcademicRequestQueryKind.LIST, request_id="R")


def test_outcomes_are_distinct_from_decision_outcomes() -> None:
    from app.decision.contracts import DecisionOutcome

    assert {outcome.value for outcome in InstitutionalAccessOutcome}.isdisjoint(
        {outcome.value for outcome in DecisionOutcome}
    )


# --- Proveniência nos resultados sem sucesso (F3, auditoria de 2026-10-09) ---------


def _provenance(response) -> dict:
    body = response.json()
    return body["provenance"] if "provenance" in body else body["detail"]["provenance"]


def _assert_safe(provenance: dict, institution_id: str) -> None:
    assert provenance["origin"] == "institutional_api"
    assert provenance["institution_id"] == institution_id
    assert provenance["attempted_at"]
    # Nunca o identificador externo, nem pedidos.
    assert "SYNTH-" not in str(provenance)
    assert "REQ-" not in str(provenance)


def test_success_provenance_declares_that_the_source_was_consulted(
    client: TestClient, mock_provider
) -> None:
    institution_id, admin_headers = _setup(client)
    headers, _ = _linked_student(client, admin_headers)

    provenance = _provenance(client.get("/api/v1/academic-requests", headers=headers))

    _assert_safe(provenance, institution_id)
    assert provenance["source_consulted"] is True
    assert provenance["queried_at"] >= provenance["attempted_at"]
    assert provenance["access_result"] == "success"


def test_empty_list_provenance_declares_a_consulted_source_and_no_fields(
    client: TestClient, mock_provider
) -> None:
    institution_id, admin_headers = _setup(client)
    headers, _ = _linked_student(client, admin_headers, "SYNTH-STUDENT-0003")

    provenance = _provenance(client.get("/api/v1/academic-requests", headers=headers))

    _assert_safe(provenance, institution_id)
    assert provenance["access_result"] == "no_data"
    assert provenance["source_consulted"] is True
    assert provenance["source_updated_at"] is not None
    assert provenance["fields_used"] == []


def test_not_configured_carries_provenance_without_consulting_the_source(
    client: TestClient, use_provider
) -> None:
    use_provider(None)
    institution_id, admin_headers = _setup(client)
    headers, _ = _linked_student(client, admin_headers)

    response = client.get("/api/v1/academic-requests", headers=headers)

    assert response.status_code == 503
    provenance = _provenance(response)
    _assert_safe(provenance, institution_id)
    assert provenance == {
        **provenance,
        "simulated": False,
        "source_consulted": False,
        "queried_at": None,
        "source_updated_at": None,
        "access_result": "not_configured",
        "fields_used": [],
    }


def test_unlinked_denial_carries_provenance_without_consulting_the_source(
    client: TestClient, mock_provider
) -> None:
    institution_id, admin_headers = _setup(client)
    headers, _ = create_account_and_login(client, admin_headers, role="student")

    response = client.get("/api/v1/academic-requests", headers=headers)

    assert response.status_code == 403
    provenance = _provenance(response)
    _assert_safe(provenance, institution_id)
    assert provenance["access_result"] == "access_denied"
    assert provenance["source_consulted"] is False
    assert provenance["queried_at"] is None
    assert provenance["simulated"] is True


@pytest.mark.parametrize(
    ("subject", "status", "access_result"),
    [("SYNTH-ACCESS-DENIED", 403, "access_denied"), ("SYNTH-UNAVAILABLE", 502, "unavailable")],
)
def test_source_failures_carry_provenance_of_a_consulted_source(
    client: TestClient, mock_provider, subject: str, status: int, access_result: str
) -> None:
    institution_id, admin_headers = _setup(client)
    headers, _ = _linked_student(client, admin_headers, subject)

    response = client.get("/api/v1/academic-requests", headers=headers)

    assert response.status_code == status
    provenance = _provenance(response)
    _assert_safe(provenance, institution_id)
    assert provenance["access_result"] == access_result
    assert provenance["source_consulted"] is True
    assert provenance["queried_at"] is not None
    assert provenance["fields_used"] == []


def test_provider_exception_carries_provenance(client: TestClient, use_provider) -> None:
    use_provider(_ExplodingProvider())
    institution_id, admin_headers = _setup(client)
    headers, _ = _linked_student(client, admin_headers)

    response = client.get("/api/v1/academic-requests/REQ-0001-A", headers=headers)

    assert response.status_code == 502
    provenance = _provenance(response)
    _assert_safe(provenance, institution_id)
    assert provenance["access_result"] == "unavailable"
    assert provenance["source_consulted"] is True
    assert provenance["simulated"] is False


# --- Revogação concorrente na consulta (F1, auditoria de 2026-10-09) ----------------


def test_deactivation_between_authorization_and_query_returns_no_records(
    client: TestClient,
    mock_provider,
    monkeypatch: pytest.MonkeyPatch,
    test_session_factory: sessionmaker[Session],
) -> None:
    """Reproduz o ensaio da auditoria: a desativação faz commit depois da
    dependência de autorização e antes do service. Antes da correção: 200 com
    três pedidos."""
    _, admin_headers = _setup(client)
    headers, student_id = _linked_student(client, admin_headers)
    original = academic_request_service.list_own_requests

    def revoke_then_continue(*args, **kwargs):  # type: ignore[no-untyped-def]
        _commit(
            test_session_factory,
            "UPDATE users SET is_active = false WHERE id = :id",
            id=student_id,
        )
        return original(*args, **kwargs)

    monkeypatch.setattr(academic_request_service, "list_own_requests", revoke_then_continue)
    response = client.get("/api/v1/academic-requests", headers=headers)

    assert response.status_code == 401
    assert "REQ-" not in response.text


def _student_with_recording_provider(
    client: TestClient, use_provider
) -> tuple[_RecordingProvider, dict[str, str], str]:
    institution_id, admin_headers = _setup(client)
    provider = use_provider(_recording((institution_id, DEMO_INSTITUTION_CODE)))
    headers, student_id = _linked_student(client, admin_headers)
    return provider, headers, student_id


_REVOCATIONS = {
    "deactivated": ("UPDATE users SET is_active = false WHERE id = :id", 401),
    "institution-deactivated": (
        "UPDATE institutions SET is_active = false WHERE id = "
        "(SELECT institution_id FROM users WHERE id = :id)",
        401,
    ),
    "demoted": ("UPDATE users SET role = 'staff' WHERE id = :id", 403),
    "unlinked": ("DELETE FROM user_external_identities WHERE user_id = :id", 403),
    "relinked": (
        "UPDATE user_external_identities SET external_subject = 'SYNTH-STUDENT-0002' "
        "WHERE user_id = :id",
        403,
    ),
}


@pytest.mark.parametrize("path", ["", "/REQ-0001-A"], ids=["list", "detail"])
@pytest.mark.parametrize("revocation", sorted(_REVOCATIONS))
def test_revocation_during_the_source_call_discards_the_records(
    client: TestClient,
    use_provider,
    test_session_factory: sessionmaker[Session],
    revocation: str,
    path: str,
) -> None:
    """A revalidação depois da fonte descarta o que a fonte devolveu quando a
    conta, a instituição, o papel ou a associação mudaram durante a consulta."""
    sql, status = _REVOCATIONS[revocation]
    provider, headers, student_id = _student_with_recording_provider(client, use_provider)
    provider.during_query = lambda: _commit(test_session_factory, sql, id=student_id)

    response = client.get(f"/api/v1/academic-requests{path}", headers=headers)

    assert response.status_code == status
    assert len(provider.identities) == 1
    assert "REQ-" not in response.text
    assert "Certidão" not in response.text
    if status == 403:
        provenance = _provenance(response)
        assert provenance["access_result"] == "access_denied"
        assert provenance["source_consulted"] is True
        assert provenance["fields_used"] == []


def test_no_database_lock_is_held_during_the_source_call(
    client: TestClient,
    use_provider,
    test_session_factory: sessionmaker[Session],
) -> None:
    """Durante a chamada à fonte, uma alteração concorrente da conta ou da
    instituição não espera por esta consulta: com lock_timeout curto, um lock
    retido faria falhar estes UPDATE."""
    provider, headers, student_id = _student_with_recording_provider(client, use_provider)
    observed: list[str] = []

    def update_with_short_lock_timeout() -> None:
        with test_session_factory() as db:
            db.execute(text("SET LOCAL lock_timeout = '500ms'"))
            db.execute(
                text("UPDATE users SET full_name = 'Renomeado' WHERE id = :id"),
                {"id": student_id},
            )
            db.execute(
                text(
                    "UPDATE institutions SET name = name WHERE id = "
                    "(SELECT institution_id FROM users WHERE id = :id)"
                ),
                {"id": student_id},
            )
            db.execute(
                text(
                    "UPDATE user_external_identities SET external_subject = external_subject "
                    "WHERE user_id = :id"
                ),
                {"id": student_id},
            )
            db.commit()
        observed.append("updated")

    provider.during_query = update_with_short_lock_timeout
    response = client.get("/api/v1/academic-requests", headers=headers)

    assert observed == ["updated"]
    assert response.status_code == 200


_LOCK_NOWAIT = {
    "institutions": "SELECT id FROM institutions WHERE id = :id FOR UPDATE NOWAIT",
    "users": "SELECT id FROM users WHERE id = :id FOR UPDATE NOWAIT",
    "user_external_identities": (
        "SELECT id FROM user_external_identities WHERE id = :id FOR UPDATE NOWAIT"
    ),
}


def _lockable_now(factory: sessionmaker[Session], table: str, row_id: object) -> bool:
    """Tenta bloquear a linha noutra sessão, sem esperar."""
    with factory() as db:
        try:
            db.execute(text(_LOCK_NOWAIT[table]), {"id": row_id})
        except OperationalError:
            return False
        finally:
            db.rollback()
    return True


_ACCESS_REVOCATIONS = {
    "deactivated": ("UPDATE users SET is_active = false WHERE id = :id", 401, None),
    "institution-deactivated": (
        "UPDATE institutions SET is_active = false WHERE id = "
        "(SELECT institution_id FROM users WHERE id = :id)",
        401,
        None,
    ),
    "demoted": ("UPDATE users SET role = 'staff' WHERE id = :id", 200, "not_permitted"),
    "unlinked": ("DELETE FROM user_external_identities WHERE user_id = :id", 200, "not_linked"),
}


@pytest.mark.parametrize("revocation", sorted(_ACCESS_REVOCATIONS))
def test_access_check_after_revocation_reflects_the_persisted_state(
    client: TestClient,
    mock_provider,
    monkeypatch: pytest.MonkeyPatch,
    test_session_factory: sessionmaker[Session],
    revocation: str,
) -> None:
    """Revisão final de 2026-10-22: a revogação faz commit depois da
    autenticação e antes do service. Antes da correção, a conta desativada ou
    despromovida ainda recebia ``available: true``, porque a decisão usava o
    papel do objeto da autenticação."""
    sql, status, reason = _ACCESS_REVOCATIONS[revocation]
    _, admin_headers = _setup(client)
    headers, student_id = _linked_student(client, admin_headers)
    original = academic_request_service.get_access

    def revoke_then_continue(*args, **kwargs):  # type: ignore[no-untyped-def]
        _commit(test_session_factory, sql, id=student_id)
        return original(*args, **kwargs)

    monkeypatch.setattr(academic_request_service, "get_access", revoke_then_continue)
    response = client.get("/api/v1/academic-requests/access", headers=headers)

    assert response.status_code == status
    if reason is not None:
        assert response.json() == {"available": False, "reason": reason, "simulated": True}


def test_access_check_keeps_account_institution_and_link_locked_until_delivery(
    client: TestClient,
    mock_provider,
    monkeypatch: pytest.MonkeyPatch,
    test_session_factory: sessionmaker[Session],
) -> None:
    institution_id, admin_headers = _setup(client)
    headers, student_id = _linked_student(client, admin_headers)
    with test_session_factory() as db:
        link_id = db.scalar(
            select(UserExternalIdentity.id).where(
                UserExternalIdentity.user_id == uuid.UUID(student_id)
            )
        )
    rows = {
        "institutions": institution_id,
        "users": student_id,
        "user_external_identities": link_id,
    }
    original = academic_request_service.get_access
    lockable: dict[str, bool] = {}

    def check_then_probe(*args, **kwargs):  # type: ignore[no-untyped-def]
        access = original(*args, **kwargs)
        for table, row in rows.items():
            lockable[table] = _lockable_now(test_session_factory, table, row)
        return access

    monkeypatch.setattr(academic_request_service, "get_access", check_then_probe)
    response = client.get("/api/v1/academic-requests/access", headers=headers)

    assert response.json() == {"available": True, "reason": "available", "simulated": True}
    assert lockable == dict.fromkeys(rows, False)


def test_account_institution_and_link_stay_locked_from_the_final_check_to_delivery(
    client: TestClient,
    mock_provider,
    monkeypatch: pytest.MonkeyPatch,
    test_session_factory: sessionmaker[Session],
) -> None:
    """Depois da reverificação posterior à fonte, a conta, a instituição e a
    associação ficam sob lock até ao fim da transação: uma desativação, uma
    alteração de papel ou uma remoção da associação concorrentes esperam pela
    entrega, em vez de fazerem commit entre a verificação e a resposta."""
    institution_id, admin_headers = _setup(client)
    headers, student_id = _linked_student(client, admin_headers)
    with test_session_factory() as db:
        link_id = db.scalar(
            select(UserExternalIdentity.id).where(
                UserExternalIdentity.user_id == uuid.UUID(student_id)
            )
        )
    rows = {
        "institutions": institution_id,
        "users": student_id,
        "user_external_identities": link_id,
    }
    original = academic_request_service._authorized_identity
    checks: list[AuthorizedInstitutionalIdentity] = []
    lockable: dict[str, bool] = {}

    def check_then_probe(*args, **kwargs):  # type: ignore[no-untyped-def]
        identity = original(*args, **kwargs)
        checks.append(identity)
        if len(checks) == 2:
            for table, row in rows.items():
                lockable[table] = _lockable_now(test_session_factory, table, row)
        return identity

    monkeypatch.setattr(academic_request_service, "_authorized_identity", check_then_probe)
    response = client.get("/api/v1/academic-requests", headers=headers)

    assert response.status_code == 200
    assert len(checks) == 2
    assert lockable == dict.fromkeys(rows, False)
