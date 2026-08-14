"""Configuração do destino humano default de uma instituição (A2.3a).

A invariante em teste é a da secção 9 do enunciado: a configuração está **ou**
totalmente ausente, **ou** completa (nome com pelo menos uma via de contacto).
Não há estado intermédio válido.

Os testes exercitam a superfície administrativa real — criação por bootstrap e
``PATCH`` por admin autenticado —, não apenas os schemas, porque é aí que a
regra tem de valer: o serviço avalia o **estado final** de um PATCH parcial, o
que nenhum schema consegue fazer sozinho.
"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

BOOTSTRAP_HEADERS = {"X-Bootstrap-Token": settings.bootstrap_token or ""}
_ADMIN_PASSWORD = "supersecret123"


def _institution_payload(**overrides: object) -> dict:
    payload: dict = {
        "name": "Support Institution",
        "code": f"SUP-{uuid.uuid4().hex[:8].upper()}",
        "default_language": "pt",
        "supported_languages": ["pt", "en"],
    }
    payload.update(overrides)
    return payload


def _create_institution(client: TestClient, **overrides: object):
    return client.post(
        "/api/v1/institutions",
        json=_institution_payload(**overrides),
        headers=BOOTSTRAP_HEADERS,
    )


def _create_admin(client: TestClient, institution_id: str) -> dict[str, str]:
    email = f"admin-{uuid.uuid4().hex[:8]}@example.com"
    response = client.post(
        "/api/v1/auth/register-initial-admin",
        json={
            "institution_id": institution_id,
            "full_name": "Admin Support",
            "email": email,
            "password": _ADMIN_PASSWORD,
        },
        headers=BOOTSTRAP_HEADERS,
    )
    assert response.status_code == 201
    login = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": _ADMIN_PASSWORD},
    )
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


# --- Estados válidos ------------------------------------------------------


def test_institution_without_human_support_remains_valid(client: TestClient) -> None:
    """O campo é opcional: nenhuma instituição existente passa a ser inválida."""
    response = _create_institution(client)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["human_support_name"] is None
    assert body["human_support_email"] is None
    assert body["human_support_url"] is None


def test_institution_with_name_and_email_is_valid(client: TestClient) -> None:
    response = _create_institution(
        client,
        human_support_name="Academic Services",
        human_support_email="support@example.invalid",
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["human_support_name"] == "Academic Services"
    assert body["human_support_email"] == "support@example.invalid"
    assert body["human_support_url"] is None


def test_institution_with_name_and_url_is_valid(client: TestClient) -> None:
    response = _create_institution(
        client,
        human_support_name="Academic Services",
        human_support_url="https://example.invalid/apoio",
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["human_support_url"] == "https://example.invalid/apoio"
    assert body["human_support_email"] is None


def test_institution_with_name_email_and_url_is_valid(client: TestClient) -> None:
    response = _create_institution(
        client,
        human_support_name="Academic Services",
        human_support_email="support@example.invalid",
        human_support_url="https://example.invalid/apoio",
    )

    assert response.status_code == 201, response.text


# --- Estados inválidos ----------------------------------------------------


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"human_support_email": "support@example.invalid"}, id="email-sem-nome"),
        pytest.param({"human_support_url": "https://example.invalid"}, id="url-sem-nome"),
        pytest.param(
            {
                "human_support_email": "support@example.invalid",
                "human_support_url": "https://example.invalid",
            },
            id="contactos-sem-nome",
        ),
        pytest.param({"human_support_name": "Academic Services"}, id="nome-sem-contacto"),
    ],
)
def test_partial_human_support_configuration_is_rejected(
    client: TestClient, overrides: dict
) -> None:
    """Um nome sem contacto não encaminha ninguém; um contacto sem nome não
    identifica o serviço. Nenhum dos dois é apresentável ao utilizador."""
    response = _create_institution(client, **overrides)

    assert response.status_code == 422, response.text


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        "file:///etc/passwd",
        "ftp://example.invalid",
        "example.invalid",
    ],
)
def test_dangerous_or_invalid_support_url_is_rejected(client: TestClient, url: str) -> None:
    response = _create_institution(
        client,
        human_support_name="Academic Services",
        human_support_url=url,
    )

    assert response.status_code == 422, response.text


@pytest.mark.parametrize(
    "email",
    ["support", "support@", "@example.invalid", "support@localhost", "sup port@example.invalid"],
)
def test_invalid_support_email_is_rejected(client: TestClient, email: str) -> None:
    response = _create_institution(
        client,
        human_support_name="Academic Services",
        human_support_email=email,
    )

    assert response.status_code == 422, response.text


@pytest.mark.parametrize("scheme", ["http://example.invalid", "https://example.invalid"])
def test_http_and_https_support_urls_are_accepted(client: TestClient, scheme: str) -> None:
    response = _create_institution(
        client,
        human_support_name="Academic Services",
        human_support_url=scheme,
    )

    assert response.status_code == 201, response.text


# --- PATCH: a invariante vale sobre o estado final ------------------------


def test_admin_can_configure_human_support_through_patch(client: TestClient) -> None:
    institution = _create_institution(client).json()
    headers = _create_admin(client, institution["id"])

    response = client.patch(
        f"/api/v1/institutions/{institution['id']}",
        json={
            "human_support_name": "Academic Services",
            "human_support_email": "support@example.invalid",
        },
        headers=headers,
    )

    assert response.status_code == 200, response.text
    assert response.json()["human_support_email"] == "support@example.invalid"


def test_patch_cannot_leave_a_name_without_any_contact(client: TestClient) -> None:
    """Limpar o único contacto deixaria um nome sozinho — estado intermédio."""
    institution = _create_institution(
        client,
        human_support_name="Academic Services",
        human_support_email="support@example.invalid",
    ).json()
    headers = _create_admin(client, institution["id"])

    response = client.patch(
        f"/api/v1/institutions/{institution['id']}",
        json={"human_support_email": None},
        headers=headers,
    )

    assert response.status_code == 422, response.text
    unchanged = client.get(f"/api/v1/institutions/{institution['id']}", headers=headers)
    assert unchanged.json()["human_support_email"] == "support@example.invalid"


def test_patch_cannot_add_a_contact_without_a_name(client: TestClient) -> None:
    institution = _create_institution(client).json()
    headers = _create_admin(client, institution["id"])

    response = client.patch(
        f"/api/v1/institutions/{institution['id']}",
        json={"human_support_email": "support@example.invalid"},
        headers=headers,
    )

    assert response.status_code == 422, response.text


def test_patch_can_clear_the_whole_configuration(client: TestClient) -> None:
    """Voltar ao estado "não configurada" é uma transição legítima."""
    institution = _create_institution(
        client,
        human_support_name="Academic Services",
        human_support_email="support@example.invalid",
    ).json()
    headers = _create_admin(client, institution["id"])

    response = client.patch(
        f"/api/v1/institutions/{institution['id']}",
        json={
            "human_support_name": None,
            "human_support_email": None,
            "human_support_url": None,
        },
        headers=headers,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["human_support_name"] is None
    assert body["human_support_email"] is None


def test_patch_swapping_email_for_url_keeps_the_configuration_valid(client: TestClient) -> None:
    institution = _create_institution(
        client,
        human_support_name="Academic Services",
        human_support_email="support@example.invalid",
    ).json()
    headers = _create_admin(client, institution["id"])

    response = client.patch(
        f"/api/v1/institutions/{institution['id']}",
        json={
            "human_support_email": None,
            "human_support_url": "https://example.invalid/apoio",
        },
        headers=headers,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["human_support_email"] is None
    assert body["human_support_url"] == "https://example.invalid/apoio"


# --- Superfície e proteções preservadas -----------------------------------


def test_patch_still_forbids_unknown_fields(client: TestClient) -> None:
    """extra="forbid" continua em vigor depois dos campos novos."""
    institution = _create_institution(client).json()
    headers = _create_admin(client, institution["id"])

    response = client.patch(
        f"/api/v1/institutions/{institution['id']}",
        json={"human_support_phone": "+238 000 0000"},
        headers=headers,
    )

    assert response.status_code == 422, response.text


def test_reading_human_support_still_requires_an_authenticated_admin(client: TestClient) -> None:
    institution = _create_institution(
        client,
        human_support_name="Academic Services",
        human_support_email="support@example.invalid",
    ).json()

    response = client.get(f"/api/v1/institutions/{institution['id']}")

    assert response.status_code == 401, response.text


def test_admin_cannot_configure_another_institution(client: TestClient) -> None:
    """Isolamento inalterado: outra instituição continua a responder 404."""
    own = _create_institution(client).json()
    other = _create_institution(client).json()
    headers = _create_admin(client, own["id"])

    response = client.patch(
        f"/api/v1/institutions/{other['id']}",
        json={
            "human_support_name": "Academic Services",
            "human_support_email": "support@example.invalid",
        },
        headers=headers,
    )

    assert response.status_code == 404, response.text


# --- Defesa em profundidade na base de dados ------------------------------


def _insert_institution_directly(
    db: Session,
    *,
    name: str | None,
    email: str | None,
    url: str | None,
) -> None:
    """INSERT que contorna schemas e serviços, como faria SQL manual."""
    db.execute(
        text(
            "INSERT INTO institutions "
            "(id, name, code, default_language, supported_languages, is_active,"
            " human_support_name, human_support_email, human_support_url) "
            "VALUES (gen_random_uuid(), 'Direct', :code, 'pt', ARRAY['pt'], true,"
            " :name, :email, :url)"
        ),
        {
            "code": f"DIR-{uuid.uuid4().hex[:8].upper()}",
            "name": name,
            "email": email,
            "url": url,
        },
    )
    db.flush()


def test_database_check_constraint_rejects_a_partial_configuration(
    test_session_factory: sessionmaker[Session],
) -> None:
    """A invariante não depende apenas da aplicação: um INSERT direto — script,
    serviço futuro, SQL manual — é recusado pelo PostgreSQL."""
    with test_session_factory() as db:
        with pytest.raises(IntegrityError) as exc_info:
            _insert_institution_directly(db, name="Academic Services", email=None, url=None)
        assert "ck_institutions_human_support_configuration" in str(exc_info.value)
        db.rollback()


@pytest.mark.parametrize("blank", ["", " ", "   ", "\t", "\n"])
def test_database_check_constraint_rejects_blank_strings(
    test_session_factory: sessionmaker[Session],
    blank: str,
) -> None:
    """Um valor só com espaços não é uma configuração.

    ``IS NOT NULL`` sozinho aceitaria ``"   "`` como nome e contacto, deixando
    passar uma configuração formalmente completa que o handoff apresentaria
    como um destino em branco. A constraint usa ``btrim(...) <> ''``, o mesmo
    padrão já aplicado a ``document_chunks``.
    """
    with test_session_factory() as db:
        with pytest.raises(IntegrityError) as exc_info:
            _insert_institution_directly(db, name=blank, email=blank, url=None)
        assert "ck_institutions_human_support_configuration" in str(exc_info.value)
        db.rollback()


def test_database_check_constraint_rejects_a_blank_field_beside_a_valid_one(
    test_session_factory: sessionmaker[Session],
) -> None:
    """Cada campo presente é validado por si, não apenas o conjunto.

    Aqui o URL válido já satisfaria a exigência de "pelo menos um contacto";
    o email em branco tem de ser recusado na mesma, porque um campo presente
    e vazio é dado corrompido.
    """
    with test_session_factory() as db:
        with pytest.raises(IntegrityError) as exc_info:
            _insert_institution_directly(
                db,
                name="Academic Services",
                email="   ",
                url="https://example.invalid/apoio",
            )
        assert "ck_institutions_human_support_configuration" in str(exc_info.value)
        db.rollback()


def test_database_check_constraint_accepts_the_two_valid_states(
    test_session_factory: sessionmaker[Session],
) -> None:
    """Contraponto: a constraint não é apenas restritiva por acidente."""
    with test_session_factory() as db:
        _insert_institution_directly(db, name=None, email=None, url=None)
        _insert_institution_directly(
            db, name="Academic Services", email="support@example.invalid", url=None
        )
        _insert_institution_directly(
            db, name="Academic Services", email=None, url="https://example.invalid"
        )
        db.rollback()


@pytest.mark.parametrize("blank", ["", "   "])
def test_api_also_rejects_blank_human_support_values(client: TestClient, blank: str) -> None:
    """A camada de aplicação recusa antes de chegar à base (422, não 500)."""
    response = _create_institution(
        client,
        human_support_name=blank,
        human_support_email="support@example.invalid",
    )

    assert response.status_code == 422, response.text
