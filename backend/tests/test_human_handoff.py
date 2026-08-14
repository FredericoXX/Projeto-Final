"""Encaminhamento humano E1 solicitado pelo utilizador (A2.3a).

O que estes testes fixam é a **capacidade** de escalar, não uma política que
decida quando escalar: a única origem é o pedido explícito do utilizador. Não
há aqui nenhum caso em que o sistema infira que deve escalar, e a ausência
dessa inferência é deliberada — a policy pertence a uma fase posterior.

Três propriedades são o núcleo:

1. o handoff é **determinístico** — nem retriever nem gerador são tocados;
2. o destino é um **snapshot histórico** — alterar a instituição depois não
   reescreve a mensagem;
3. nada é persistido quando a operação é recusada.
"""

import ast
import inspect
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.answering.base import AnsweringContext, GeneratedAnswer
from app.answering.dependencies import get_answer_generator
from app.api.routes import conversations as conversations_routes
from app.core.config import settings
from app.core.exceptions import AuthenticationError, NotFoundError
from app.core.handoff_message import HANDOFF_MESSAGE_VERSION
from app.decision.contracts import DecisionOutcome
from app.main import app
from app.models.message import Message
from app.models.message_source import MessageSource
from app.models.user import User
from app.retrieval.base import RetrievalContext, RetrievalResult
from app.retrieval.dependencies import get_retriever
from app.schemas.handoff import HANDOFF_OUTCOME
from app.services import human_handoff_service

BOOTSTRAP_HEADERS = {"X-Bootstrap-Token": settings.bootstrap_token or ""}
_ADMIN_PASSWORD = "supersecret123"
_USER_PASSWORD = "anothersecret123"

_DESTINATION_NAME = "Academic Services"
_DESTINATION_EMAIL = "support@example.invalid"
_DESTINATION_URL = "https://example.invalid/apoio"


# --- Espiões que falham se forem usados -----------------------------------


class ExplodingRetriever:
    """Falha imediatamente se o handoff tocar no retrieval."""

    def search(
        self,
        db: Session,
        query: str,
        context: RetrievalContext,
        top_k: int,
        official_only: bool,
    ) -> RetrievalResult:
        raise AssertionError("O handoff E1 não pode chamar o retriever.")


class ExplodingAnswerGenerator:
    """Falha imediatamente se o handoff tocar na geração."""

    def generate(self, context: AnsweringContext) -> GeneratedAnswer:
        raise AssertionError("O handoff E1 não pode chamar o gerador.")


# --- Helpers --------------------------------------------------------------


def _create_institution(
    client: TestClient,
    *,
    name: str = "Handoff Institution",
    support: dict[str, Any] | None = None,
    default_language: str = "pt",
) -> dict:
    payload: dict[str, Any] = {
        "name": name,
        "code": f"HDF-{uuid.uuid4().hex[:8].upper()}",
        "default_language": default_language,
        "supported_languages": ["pt", "en"],
    }
    if support is not None:
        payload.update(support)
    response = client.post("/api/v1/institutions", json=payload, headers=BOOTSTRAP_HEADERS)
    assert response.status_code == 201, response.text
    return response.json()


def _configured_support() -> dict[str, Any]:
    return {
        "human_support_name": _DESTINATION_NAME,
        "human_support_email": _DESTINATION_EMAIL,
        "human_support_url": _DESTINATION_URL,
    }


def _create_admin(client: TestClient, institution_id: str) -> dict[str, str]:
    email = f"admin-{uuid.uuid4().hex[:8]}@example.com"
    response = client.post(
        "/api/v1/auth/register-initial-admin",
        json={
            "institution_id": institution_id,
            "full_name": "Admin Handoff",
            "email": email,
            "password": _ADMIN_PASSWORD,
        },
        headers=BOOTSTRAP_HEADERS,
    )
    assert response.status_code == 201, response.text
    login = client.post("/api/v1/auth/login", json={"email": email, "password": _ADMIN_PASSWORD})
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _create_user(client: TestClient, admin_headers: dict[str, str]) -> dict[str, str]:
    email = f"user-{uuid.uuid4().hex[:8]}@example.com"
    response = client.post(
        "/api/v1/users",
        json={
            "full_name": "Handoff User",
            "email": email,
            "password": _USER_PASSWORD,
            "role": "student",
        },
        headers=admin_headers,
    )
    assert response.status_code == 201, response.text
    login = client.post("/api/v1/auth/login", json={"email": email, "password": _USER_PASSWORD})
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _create_conversation(
    client: TestClient, headers: dict[str, str], *, language: str = "pt"
) -> dict:
    response = client.post(
        "/api/v1/conversations",
        json={"title": "Assuntos académicos", "language": language},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def _handoff(client: TestClient, headers: dict[str, str], conversation_id: str):
    return client.post(f"/api/v1/conversations/{conversation_id}/handoff", headers=headers)


def _setup(
    client: TestClient,
    *,
    support: dict[str, Any] | None = None,
    language: str = "pt",
) -> tuple[dict, dict[str, str], dict]:
    institution = _create_institution(client, support=support, default_language=language)
    headers = _create_admin(client, institution["id"])
    conversation = _create_conversation(client, headers, language=language)
    return institution, headers, conversation


def _message_count(test_session_factory: sessionmaker[Session]) -> int:
    with test_session_factory() as db:
        return db.scalar(select(func.count()).select_from(Message)) or 0


@pytest.fixture
def no_llm_dependencies():
    """Instala espiões que falham se o endpoint resolver retriever/gerador."""
    app.dependency_overrides[get_retriever] = lambda: ExplodingRetriever()
    app.dependency_overrides[get_answer_generator] = lambda: ExplodingAnswerGenerator()
    yield
    app.dependency_overrides.pop(get_retriever, None)
    app.dependency_overrides.pop(get_answer_generator, None)


# --- Caminho feliz --------------------------------------------------------


def test_user_requested_handoff_persists_an_auditable_assistant_message(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
) -> None:
    institution, headers, conversation = _setup(client, support=_configured_support())
    before = client.get(f"/api/v1/conversations/{conversation['id']}", headers=headers).json()

    response = _handoff(client, headers, conversation["id"])

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["outcome"] == "escalate"
    assert body["conversation_id"] == conversation["id"]
    assert body["destination"] == {
        "name": _DESTINATION_NAME,
        "email": _DESTINATION_EMAIL,
        "url": _DESTINATION_URL,
    }

    message = body["assistant_message"]
    assert message["role"] == "assistant"
    assert message["user_id"] is None
    assert message["conversation_id"] == conversation["id"]
    assert message["institution_id"] == institution["id"]
    assert message["language"] == "pt"
    assert message["reply_to_message_id"] is None
    assert message["sources"] == []
    assert message["extra_metadata"] == {
        "turn_type": "human_handoff",
        "decision_outcome": "escalate",
        "handoff_mode": "e1",
        "handoff_trigger": "user_requested",
        "message_version": HANDOFF_MESSAGE_VERSION,
        "handoff_destination": {
            "name": _DESTINATION_NAME,
            "email": _DESTINATION_EMAIL,
            "url": _DESTINATION_URL,
        },
    }

    # O destino aparece no texto apresentado, não só no metadata.
    assert _DESTINATION_NAME in message["content"]
    assert _DESTINATION_EMAIL in message["content"]
    assert _DESTINATION_URL in message["content"]

    assert _message_count(test_session_factory) == 1

    after = client.get(f"/api/v1/conversations/{conversation['id']}", headers=headers).json()
    assert after["updated_at"] > before["updated_at"]


def test_handoff_message_appears_in_the_persisted_history(client: TestClient) -> None:
    """A mensagem sobrevive ao pedido: recarregar a conversa continua a mostrá-la."""
    _, headers, conversation = _setup(client, support=_configured_support())
    created = _handoff(client, headers, conversation["id"]).json()["assistant_message"]

    listing = client.get(
        f"/api/v1/conversations/{conversation['id']}/messages", headers=headers
    )

    assert listing.status_code == 200
    items = listing.json()["items"]
    assert [item["id"] for item in items] == [created["id"]]
    assert items[0]["extra_metadata"]["turn_type"] == "human_handoff"


def test_handoff_creates_no_message_sources(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
) -> None:
    """E1 não cita documentos: não há evidência, logo não há fonte a registar."""
    _, headers, conversation = _setup(client, support=_configured_support())

    response = _handoff(client, headers, conversation["id"])

    assert response.status_code == 201
    assert response.json()["assistant_message"]["sources"] == []
    with test_session_factory() as db:
        assert db.scalar(select(func.count()).select_from(MessageSource)) == 0


def test_handoff_works_with_only_an_email_configured(client: TestClient) -> None:
    _, headers, conversation = _setup(
        client,
        support={
            "human_support_name": _DESTINATION_NAME,
            "human_support_email": _DESTINATION_EMAIL,
        },
    )

    body = _handoff(client, headers, conversation["id"]).json()

    assert body["destination"] == {
        "name": _DESTINATION_NAME,
        "email": _DESTINATION_EMAIL,
        "url": None,
    }
    assert "None" not in body["assistant_message"]["content"]


def test_handoff_works_with_only_a_url_configured(client: TestClient) -> None:
    _, headers, conversation = _setup(
        client,
        support={
            "human_support_name": _DESTINATION_NAME,
            "human_support_url": _DESTINATION_URL,
        },
    )

    body = _handoff(client, headers, conversation["id"]).json()

    assert body["destination"]["email"] is None
    assert body["destination"]["url"] == _DESTINATION_URL
    assert "None" not in body["assistant_message"]["content"]


def test_regular_user_can_request_handoff_in_their_own_conversation(client: TestClient) -> None:
    institution = _create_institution(client, support=_configured_support())
    admin_headers = _create_admin(client, institution["id"])
    user_headers = _create_user(client, admin_headers)
    conversation = _create_conversation(client, user_headers)

    response = _handoff(client, user_headers, conversation["id"])

    assert response.status_code == 201, response.text


# --- Determinismo: sem LLM, sem retrieval ---------------------------------


def test_handoff_never_touches_retriever_or_generator(
    client: TestClient,
    no_llm_dependencies: None,
) -> None:
    """Se o endpoint resolvesse qualquer das duas dependências, os espiões
    levantariam AssertionError e o pedido não devolveria 201."""
    _, headers, conversation = _setup(client, support=_configured_support())

    response = _handoff(client, headers, conversation["id"])

    assert response.status_code == 201, response.text


def test_handoff_service_does_not_import_retrieval_or_answering() -> None:
    """Barreira estrutural: o determinismo de E1 não depende de disciplina.

    Um import de ``app.retrieval`` ou ``app.answering`` neste módulo seria o
    primeiro passo para o handoff voltar a depender de um fornecedor.
    """
    tree = ast.parse(inspect.getsource(human_handoff_service))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.module is not None
            imported.add(node.module)

    forbidden = {name for name in imported if name.startswith(("app.retrieval", "app.answering"))}
    assert forbidden == set()


def test_handoff_endpoint_declares_no_generator_or_retriever_dependency() -> None:
    """A rota não pede retriever nem generator — nada há para resolver.

    O contraste com ``ask_in_conversation`` é parte da asserção: mostra que os
    nomes procurados são os corretos e que o teste falharia se o handoff
    passasse a declarar as mesmas dependências.
    """
    handoff_parameters = set(inspect.signature(conversations_routes.request_handoff).parameters)
    ask_parameters = set(inspect.signature(conversations_routes.ask_in_conversation).parameters)

    assert {"retriever", "generator"} <= ask_parameters
    assert "retriever" not in handoff_parameters
    assert "generator" not in handoff_parameters


# --- Snapshot histórico ---------------------------------------------------


def test_destination_snapshot_is_not_reevaluated_after_the_institution_changes(
    client: TestClient,
) -> None:
    """T0: destino antigo → handoff. T1: admin muda. O histórico não muda."""
    institution, headers, conversation = _setup(
        client,
        support={
            "human_support_name": _DESTINATION_NAME,
            "human_support_email": "old@example.invalid",
        },
    )
    first = _handoff(client, headers, conversation["id"]).json()
    assert first["destination"]["email"] == "old@example.invalid"

    changed = client.patch(
        f"/api/v1/institutions/{institution['id']}",
        json={
            "human_support_name": "Student Desk",
            "human_support_email": "new@example.invalid",
        },
        headers=headers,
    )
    assert changed.status_code == 200, changed.text

    history = client.get(
        f"/api/v1/conversations/{conversation['id']}/messages", headers=headers
    ).json()["items"]

    historic = history[0]
    assert historic["extra_metadata"]["handoff_destination"] == {
        "name": _DESTINATION_NAME,
        "email": "old@example.invalid",
        "url": None,
    }
    assert "old@example.invalid" in historic["content"]
    assert "new@example.invalid" not in historic["content"]
    assert "Student Desk" not in historic["content"]


def test_a_later_handoff_records_the_new_destination(client: TestClient) -> None:
    """O snapshot é do momento: o encaminhamento seguinte regista o destino novo."""
    institution, headers, conversation = _setup(
        client,
        support={
            "human_support_name": _DESTINATION_NAME,
            "human_support_email": "old@example.invalid",
        },
    )
    _handoff(client, headers, conversation["id"])
    client.patch(
        f"/api/v1/institutions/{institution['id']}",
        json={"human_support_name": "Student Desk", "human_support_email": "new@example.invalid"},
        headers=headers,
    )

    second = _handoff(client, headers, conversation["id"]).json()

    assert second["destination"] == {
        "name": "Student Desk",
        "email": "new@example.invalid",
        "url": None,
    }


# --- Destino não configurado ----------------------------------------------


def test_handoff_without_configured_support_is_rejected_without_persisting(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
) -> None:
    _, headers, conversation = _setup(client)
    before = client.get(f"/api/v1/conversations/{conversation['id']}", headers=headers).json()

    response = _handoff(client, headers, conversation["id"])

    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "resource_conflict"
    assert _message_count(test_session_factory) == 0

    after = client.get(f"/api/v1/conversations/{conversation['id']}", headers=headers).json()
    assert after["updated_at"] == before["updated_at"]


def test_unconfigured_support_error_reveals_nothing_beyond_the_configuration(
    client: TestClient,
) -> None:
    _, headers, conversation = _setup(client)

    message = _handoff(client, headers, conversation["id"]).json()["detail"]["message"]

    assert message == "Human support is not configured for this institution."


# --- Conversa não ativa ---------------------------------------------------


@pytest.mark.parametrize("status", ["closed", "archived"])
def test_inactive_conversation_rejects_handoff_without_creating_messages(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
    status: str,
) -> None:
    _, headers, conversation = _setup(client, support=_configured_support())
    closed = client.patch(
        f"/api/v1/conversations/{conversation['id']}",
        json={"status": status},
        headers=headers,
    )
    assert closed.status_code == 200, closed.text

    response = _handoff(client, headers, conversation["id"])

    assert response.status_code == 409, response.text
    assert _message_count(test_session_factory) == 0


def test_active_conversation_accepts_handoff(client: TestClient) -> None:
    """Contraponto explícito dos dois casos acima."""
    _, headers, conversation = _setup(client, support=_configured_support())
    assert conversation["status"] == "active"

    assert _handoff(client, headers, conversation["id"]).status_code == 201


# --- Isolamento institucional e autenticação ------------------------------


def test_conversation_from_another_institution_reports_as_missing(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
) -> None:
    """Instituição A não pode encaminhar — nem descobrir — uma conversa de B."""
    institution_b = _create_institution(
        client, name="Institution B", support=_configured_support()
    )
    headers_b = _create_admin(client, institution_b["id"])
    conversation_b = _create_conversation(client, headers_b)

    institution_a = _create_institution(
        client, name="Institution A", support=_configured_support()
    )
    headers_a = _create_admin(client, institution_a["id"])

    response = _handoff(client, headers_a, conversation_b["id"])

    assert response.status_code == 404, response.text
    assert response.json()["detail"]["code"] == "resource_not_found"
    # Nada de B é revelado: nem o destino, nem o título, nem a existência.
    body = response.text
    assert institution_b["id"] not in body
    assert conversation_b.get("title", "") not in body or "Assuntos" not in body
    assert _message_count(test_session_factory) == 0


def test_unconfigured_tenant_cannot_probe_another_institution_conversation(
    client: TestClient,
) -> None:
    """404 precede a validação do destino: a resposta não muda consoante a
    instituição do atacante ter ou não atendimento configurado."""
    institution_b = _create_institution(
        client, name="Institution B", support=_configured_support()
    )
    headers_b = _create_admin(client, institution_b["id"])
    conversation_b = _create_conversation(client, headers_b)

    institution_a = _create_institution(client, name="Institution A")
    headers_a = _create_admin(client, institution_a["id"])

    response = _handoff(client, headers_a, conversation_b["id"])

    assert response.status_code == 404, response.text


def test_regular_user_cannot_hand_off_another_users_conversation(client: TestClient) -> None:
    institution = _create_institution(client, support=_configured_support())
    admin_headers = _create_admin(client, institution["id"])
    owner_headers = _create_user(client, admin_headers)
    other_headers = _create_user(client, admin_headers)
    conversation = _create_conversation(client, owner_headers)

    response = _handoff(client, other_headers, conversation["id"])

    assert response.status_code == 404, response.text


def test_handoff_requires_authentication(client: TestClient) -> None:
    _, headers, conversation = _setup(client, support=_configured_support())

    response = client.post(f"/api/v1/conversations/{conversation['id']}/handoff")

    assert response.status_code == 401, response.text


def test_unknown_conversation_is_not_found(client: TestClient) -> None:
    _, headers, _ = _setup(client, support=_configured_support())

    response = _handoff(client, headers, str(uuid.uuid4()))

    assert response.status_code == 404, response.text


# --- Payload: o cliente não escolhe nada ----------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        {"decision_outcome": "escalate", "handoff_trigger": "system_decision"},
        {"handoff_trigger": "system_decision"},
        {"destination": {"name": "Attacker", "email": "attacker@example.invalid"}},
        {"institution_id": str(uuid.uuid4())},
    ],
)
def test_client_supplied_body_never_changes_the_outcome(
    client: TestClient, payload: dict
) -> None:
    """O trigger e o destino são determinados pelo backend.

    O endpoint não declara schema de pedido, portanto o corpo é ignorado por
    inteiro — o que se fixa aqui é que nenhum valor enviado atravessa para a
    resposta nem para o snapshot.
    """
    _, headers, conversation = _setup(client, support=_configured_support())

    response = client.post(
        f"/api/v1/conversations/{conversation['id']}/handoff",
        json=payload,
        headers=headers,
    )

    assert response.status_code == 201, response.text
    metadata = response.json()["assistant_message"]["extra_metadata"]
    assert metadata["handoff_trigger"] == "user_requested"
    assert metadata["handoff_destination"]["name"] == _DESTINATION_NAME
    assert response.json()["destination"]["name"] == _DESTINATION_NAME


def test_handoff_metadata_carries_no_question_or_document_content(client: TestClient) -> None:
    """O metadata é operacional: sem pergunta, sem prompt, sem dados pessoais."""
    institution = _create_institution(client, support=_configured_support())
    admin_headers = _create_admin(client, institution["id"])
    user_headers = _create_user(client, admin_headers)
    conversation = _create_conversation(client, user_headers)

    metadata = _handoff(client, user_headers, conversation["id"]).json()["assistant_message"][
        "extra_metadata"
    ]

    assert set(metadata) == {
        "turn_type",
        "decision_outcome",
        "handoff_mode",
        "handoff_trigger",
        "message_version",
        "handoff_destination",
    }
    assert set(metadata["handoff_destination"]) == {"name", "email", "url"}


# --- Idioma ---------------------------------------------------------------


def test_message_uses_the_conversation_language(client: TestClient) -> None:
    _, headers, conversation = _setup(client, support=_configured_support(), language="pt")
    pt_content = _handoff(client, headers, conversation["id"]).json()["assistant_message"][
        "content"
    ]

    english = _create_conversation(client, headers, language="en")
    en_content = _handoff(client, headers, english["id"]).json()["assistant_message"]["content"]

    assert pt_content.startswith("Este pedido")
    assert en_content.startswith("This request")
    assert "Serviço:" in pt_content
    assert "Service:" in en_content


def test_message_never_promises_a_ticket_an_operator_or_a_deadline(client: TestClient) -> None:
    """E1 apenas direciona. Prometer receção seria factualmente falso."""
    _, headers, conversation = _setup(client, support=_configured_support())
    pt_content = _handoff(client, headers, conversation["id"]).json()["assistant_message"][
        "content"
    ]
    english = _create_conversation(client, headers, language="en")
    en_content = _handoff(client, headers, english["id"]).json()["assistant_message"]["content"]

    forbidden = (
        "ticket",
        "pedido registado",
        "foi registado",
        "entrará em contacto",
        "will contact you",
        "has been assigned",
        "prazo de resposta",
        "within",
        "24",
        "48",
    )
    for content in (pt_content, en_content):
        lowered = content.lower()
        for claim in forbidden:
            assert claim not in lowered, claim


# --- Segundo handoff ------------------------------------------------------


def test_two_explicit_requests_create_two_messages(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
) -> None:
    """Comportamento decidido e documentado: **sem** idempotência no backend.

    Duas solicitações explícitas são dois pedidos do utilizador e produzem dois
    registos. Introduzir deduplicação exigiria uma chave de idempotência que
    não existe, e uma janela temporal arbitrária esconderia um pedido real. É o
    frontend que impede o duplo clique acidental, através do estado pending.
    """
    _, headers, conversation = _setup(client, support=_configured_support())

    first = _handoff(client, headers, conversation["id"])
    second = _handoff(client, headers, conversation["id"])

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["assistant_message"]["id"] != second.json()["assistant_message"]["id"]
    assert _message_count(test_session_factory) == 2


# --- Identidade revalidada antes da persistência --------------------------
#
# Estes testes chamam o service diretamente com um ``current_user`` que já não
# corresponde à linha persistida. É essa a propriedade em causa: o service
# **não confia** no objeto que recebe da autenticação, relê-o e bloqueia-o. Um
# teste via HTTP não conseguiria observá-lo, porque `get_current_user`
# rejeitaria o pedido antes de o service correr — a janela real é a que existe
# entre esse SELECT e o commit.


def _stale_user(institution_id: str, user_id: str, *, role: str) -> User:
    """Objeto de identidade não ligado à sessão, como o que a autenticação
    produziu antes de a linha mudar."""
    return User(
        id=uuid.UUID(user_id),
        institution_id=uuid.UUID(institution_id),
        role=role,
        is_active=True,
        full_name="Stale Identity",
        email=f"stale-{uuid.uuid4().hex[:8]}@example.com",
        password_hash="unused",
    )


def test_deactivated_user_cannot_complete_a_handoff(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
) -> None:
    """Desativação concorrente não atravessa a janela de autorização."""
    institution = _create_institution(client, support=_configured_support())
    admin_headers = _create_admin(client, institution["id"])
    user_headers = _create_user(client, admin_headers)
    conversation = _create_conversation(client, user_headers)
    me = client.get("/api/v1/auth/me", headers=user_headers).json()

    with test_session_factory() as db:
        db.execute(
            text("UPDATE users SET is_active = false WHERE id = :id"),
            {"id": me["id"]},
        )
        db.commit()

    with test_session_factory() as db:
        stale = _stale_user(institution["id"], me["id"], role="student")
        with pytest.raises(AuthenticationError):
            human_handoff_service.request_human_handoff(
                db, stale, uuid.UUID(conversation["id"])
            )

    assert _message_count(test_session_factory) == 0


def test_demoted_admin_cannot_hand_off_another_users_conversation(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
) -> None:
    """O papel usado é o persistido, não o que veio do token.

    Um admin despromovido concorrentemente deixa de alcançar conversas de
    outros utilizadores: o acesso volta a ser avaliado como utilizador comum e
    a conversa alheia responde como inexistente.
    """
    institution = _create_institution(client, support=_configured_support())
    admin_headers = _create_admin(client, institution["id"])
    owner_headers = _create_user(client, admin_headers)
    conversation = _create_conversation(client, owner_headers)
    demoted_headers = _create_user(client, admin_headers)
    demoted = client.get("/api/v1/auth/me", headers=demoted_headers).json()

    with test_session_factory() as db:
        # A linha diz "student"; o objeto de identidade ainda diz "admin".
        stale = _stale_user(institution["id"], demoted["id"], role="admin")
        with pytest.raises(NotFoundError):
            human_handoff_service.request_human_handoff(
                db, stale, uuid.UUID(conversation["id"])
            )

    assert _message_count(test_session_factory) == 0


def test_persisted_admin_role_still_reaches_another_users_conversation(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
) -> None:
    """Contraponto do teste anterior: a regra existente de admin não foi
    endurecida por acidente — só deixou de aceitar um papel obsoleto."""
    institution = _create_institution(client, support=_configured_support())
    admin_headers = _create_admin(client, institution["id"])
    admin = client.get("/api/v1/auth/me", headers=admin_headers).json()
    owner_headers = _create_user(client, admin_headers)
    conversation = _create_conversation(client, owner_headers)

    with test_session_factory() as db:
        identity = _stale_user(institution["id"], admin["id"], role="admin")
        response = human_handoff_service.request_human_handoff(
            db, identity, uuid.UUID(conversation["id"])
        )

    assert response.outcome == "escalate"
    assert _message_count(test_session_factory) == 1


def test_handoff_locks_institution_user_and_conversation_in_the_documented_order() -> None:
    """A ordem instituição → utilizador → conversa é a mesma de
    ``ask_in_conversation``; ordens divergentes entre fluxos que bloqueiam as
    mesmas linhas são a receita conhecida para deadlock."""
    source = inspect.getsource(human_handoff_service.request_human_handoff)
    institution_at = source.index("select(Institution)")
    user_at = source.index("select(User)")
    conversation_at = source.index("get_accessible_conversation_by_identity")

    assert institution_at < user_at < conversation_at


# --- Coerência com os contratos de decisão --------------------------------


def test_public_outcome_matches_the_decision_contract() -> None:
    """Impede que o valor público e o enum divirjam sem nada falhar."""
    assert HANDOFF_OUTCOME == DecisionOutcome.ESCALATE.value
    assert HANDOFF_OUTCOME == "escalate"


def test_handoff_does_not_introduce_a_decision_policy() -> None:
    """A2.3a implementa a capacidade de escalar, não a política que decide."""
    from app.decision import contracts

    assert not hasattr(contracts, "DecisionPolicy")
    assert not hasattr(contracts, "RequestSpecificity")
    assert not hasattr(contracts, "AnswerabilityEvaluator")
