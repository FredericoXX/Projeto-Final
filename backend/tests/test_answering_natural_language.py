"""Perguntas naturais no answering e no fluxo conversacional.

O retriever é o PostgresLexicalRetriever real (com pesquisa progressiva)
sobre documentos realmente processados; apenas o AnswerGenerator é
substituído por dependency override. Sem rede e sem credenciais.
"""

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.models.message import Message
from app.models.message_source import MessageSource
from tests.test_answering_endpoint import (
    FakeAnswerGenerator,
    _ask,
    _create_searchable_document,
    _setup,
    override_generator,  # noqa: F401 - fixture reexportada para este módulo
)
from tests.test_conversation_answering import (
    _create_conversation,
    _row_counts,
)

# A pergunta natural partilha dois termos informativos com o conteúdo
# ("aulas", "setembro") e um que só existe na pergunta ("começam"): a
# variante exact falha, a evidência chega pela disjuntiva reduzida e a
# cobertura (2/3) é suficiente para ser evidência.
NATURAL_QUESTION = "Quando começam as aulas de setembro?"
CLASSES_CONTENT = "As aulas do primeiro semestre iniciam-se em 21 de setembro de 2026."


# --- POST /api/v1/answering/ask ------------------------------------------------


def test_natural_question_reaches_generator_and_answers(
    client: TestClient, override_generator  # noqa: F811 - fixture
) -> None:
    _, headers, _ = _setup(client)
    document = _create_searchable_document(
        client, headers, CLASSES_CONTENT, title="Calendário Letivo"
    )
    generator = override_generator(FakeAnswerGenerator())

    response = _ask(client, headers, query=NATURAL_QUESTION)
    assert response.status_code == 200

    body = response.json()
    assert body["status"] == "answered"
    # A pergunta original é preservada na resposta pública.
    assert body["query"] == NATURAL_QUESTION
    # O gerador foi chamado exatamente uma vez, com a evidência correta
    # no contexto (a recuperada pela estratégia progressiva).
    assert len(generator.calls) == 1
    context = generator.calls[0]
    assert len(context.evidence) == 1
    assert "21 de setembro de 2026" in context.evidence[0].evidence.content
    # A fonte citada é devolvida e pertence ao documento certo.
    assert len(body["sources"]) == 1
    assert body["sources"][0]["document_id"] == document["id"]
    assert body["sources"][0]["document_title"] == "Calendário Letivo"


def test_natural_question_without_evidence_keeps_fallback(
    client: TestClient, override_generator  # noqa: F811 - fixture
) -> None:
    _, headers, _ = _setup(client)
    _create_searchable_document(client, headers, CLASSES_CONTENT)
    generator = override_generator(FakeAnswerGenerator())

    response = _ask(client, headers, query="Qual é o preço do transporte urbano?")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "insufficient_evidence"
    assert body["sources"] == []
    # Zero evidências continua a nunca chamar o gerador.
    assert generator.calls == []


def test_keyword_query_still_reaches_generator(
    client: TestClient, override_generator  # noqa: F811 - fixture
) -> None:
    _, headers, _ = _setup(client)
    _create_searchable_document(client, headers, CLASSES_CONTENT)
    generator = override_generator(FakeAnswerGenerator())

    response = _ask(client, headers, query="aulas")
    assert response.status_code == 200
    assert response.json()["status"] == "answered"
    assert len(generator.calls) == 1


def test_functional_only_question_never_reaches_generator(
    client: TestClient, override_generator  # noqa: F811 - fixture
) -> None:
    """Reprodução do achado da auditoria no answering: o documento contém
    literalmente "O que é", mas uma pergunta composta apenas por termos
    funcionais não pesquisa, devolve insufficient_evidence e nunca chega
    ao gerador."""
    _, headers, _ = _setup(client)
    _create_searchable_document(
        client,
        headers,
        "O que é a matrícula? A matrícula é o registo anual do estudante.",
        title="FAQ Matrícula",
    )
    generator = override_generator(FakeAnswerGenerator())

    response = _ask(client, headers, query="O que é?")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "insufficient_evidence"
    assert body["sources"] == []
    assert generator.calls == []


# --- POST /api/v1/conversations/{id}/ask -----------------------------------------


def _ask_in_conversation(
    client: TestClient, conversation_id: str, headers: dict[str, str], query: str
):
    return client.post(
        f"/api/v1/conversations/{conversation_id}/ask",
        json={"query": query},
        headers=headers,
    )


def test_natural_question_turn_persists_answer_and_sources(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
    override_generator,  # noqa: F811 - fixture
) -> None:
    _, headers, _ = _setup(client)
    document = _create_searchable_document(
        client, headers, CLASSES_CONTENT, title="Calendário Letivo"
    )
    conversation = _create_conversation(client, headers)
    generator = override_generator(FakeAnswerGenerator())

    response = _ask_in_conversation(client, conversation["id"], headers, NATURAL_QUESTION)
    assert response.status_code == 201

    body = response.json()
    assert body["status"] == "answered"
    assert body["user_message"]["content"] == NATURAL_QUESTION
    assert body["assistant_message"]["reply_to_message_id"] == body["user_message"]["id"]
    assert len(generator.calls) == 1

    # Exatamente duas mensagens e uma fonte persistidas (sem duplicados).
    assert _row_counts(test_session_factory) == (2, 1)
    with test_session_factory() as db:
        source = db.scalar(select(MessageSource))
        assert source is not None
        assert str(source.document_id) == document["id"]
        assert source.message_id == uuid.UUID(body["assistant_message"]["id"])

    # O histórico devolve o turno persistido, pela ordem, sem duplicados.
    history = client.get(
        f"/api/v1/conversations/{conversation['id']}/messages", headers=headers
    )
    assert history.status_code == 200
    items = history.json()["items"]
    assert [item["id"] for item in items] == [
        body["user_message"]["id"],
        body["assistant_message"]["id"],
    ]
    assert len(items[1]["sources"]) == 1


def test_natural_question_without_evidence_persists_fallback_without_sources(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
    override_generator,  # noqa: F811 - fixture
) -> None:
    _, headers, _ = _setup(client)
    _create_searchable_document(client, headers, CLASSES_CONTENT)
    conversation = _create_conversation(client, headers)
    generator = override_generator(FakeAnswerGenerator())

    response = _ask_in_conversation(
        client, conversation["id"], headers, "Qual é o preço do transporte urbano?"
    )
    assert response.status_code == 201
    assert response.json()["status"] == "insufficient_evidence"
    assert generator.calls == []

    # Duas mensagens persistidas, nenhuma MessageSource.
    assert _row_counts(test_session_factory) == (2, 0)
    with test_session_factory() as db:
        assert db.scalars(select(Message)).all() is not None


def test_natural_question_conversation_is_isolated_between_institutions(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
    override_generator,  # noqa: F811 - fixture
) -> None:
    """A mesma pergunta natural em duas instituições: cada turno cita
    exclusivamente o documento da própria instituição — o fallback nunca
    atravessa o isolamento institucional."""
    _, headers_a, _ = _setup(client)
    document_a = _create_searchable_document(
        client, headers_a, "As aulas da instituição A decorrem em setembro.", title="Doc A"
    )
    _, headers_b, _ = _setup(client)
    document_b = _create_searchable_document(
        client, headers_b, "As aulas da instituição B decorrem em setembro.", title="Doc B"
    )
    override_generator(FakeAnswerGenerator())

    conversation_a = _create_conversation(client, headers_a)
    conversation_b = _create_conversation(client, headers_b)

    response_a = _ask_in_conversation(
        client, conversation_a["id"], headers_a, NATURAL_QUESTION
    )
    response_b = _ask_in_conversation(
        client, conversation_b["id"], headers_b, NATURAL_QUESTION
    )
    assert response_a.status_code == 201
    assert response_b.status_code == 201
    assert response_a.json()["status"] == "answered"
    assert response_b.json()["status"] == "answered"

    sources_a = response_a.json()["assistant_message"]["sources"]
    sources_b = response_b.json()["assistant_message"]["sources"]
    assert [source["document_id"] for source in sources_a] == [document_a["id"]]
    assert [source["document_id"] for source in sources_b] == [document_b["id"]]

    # As MessageSource persistidas também nunca cruzam instituições.
    with test_session_factory() as db:
        stored = db.scalars(select(MessageSource)).all()
        assert {str(source.document_id) for source in stored} == {
            document_a["id"],
            document_b["id"],
        }
        for source in stored:
            message = db.get(Message, source.message_id)
            assert message is not None
            assert message.institution_id == source.institution_id
