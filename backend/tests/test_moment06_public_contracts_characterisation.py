"""Momento 6 — caracterização dos contratos HTTP públicos (Fase 3).

Fixa a **forma exata** do payload de retrieval e o conjunto exato de estados
públicos de answering, para que uma alteração posterior aos contratos internos
não consiga mudar a superfície pública em silêncio.

O caso concreto que motiva o teste de forma: ``retrieval_service`` constrói a
resposta com ``RetrievalEvidenceRead(**asdict(item))``. Como o schema Pydantic
ignora campos extra por omissão, acrescentar um campo ao dataclass ``Evidence``
(por exemplo ``score_kind``) **não** provoca erro — passaria despercebido. Por
isso o teste afirma simultaneamente:

1. o conjunto de chaves do JSON devolvido; e
2. que os campos de ``Evidence`` e de ``RetrievalEvidenceRead`` continuam a ser
   o mesmo conjunto — que é a relação de que o ``asdict`` depende.

Cobertura já existente e deliberadamente não duplicada:
``test_retrieval.py::test_existing_term_returns_evidence_without_internal_fields``
afirma a **ausência** de campos internos e os valores de alguns campos; não
afirma o conjunto completo, que é o que falta e o que aqui se acrescenta.
"""

from collections.abc import Callable, Iterator
from dataclasses import fields
from typing import Literal, get_args, get_origin

import pytest
from fastapi.testclient import TestClient

from app.answering.base import AnswerGenerator
from app.answering.dependencies import get_answer_generator
from app.main import app
from app.retrieval.base import Evidence
from app.schemas.answering import AnsweringResponse
from app.schemas.message import ConversationAskResponse
from app.schemas.retrieval import RetrievalEvidenceRead, RetrievalSearchResponse
from tests.moment06_support import (
    RecordingAnswerGenerator,
    ask,
    ask_in_conversation,
    create_conversation,
    create_searchable_document,
    search,
    setup_institution_with_admin,
)


@pytest.fixture
def override_generator() -> Iterator[Callable[[AnswerGenerator], AnswerGenerator]]:
    def _install(generator: AnswerGenerator) -> AnswerGenerator:
        app.dependency_overrides[get_answer_generator] = lambda: generator
        return generator

    yield _install
    app.dependency_overrides.pop(get_answer_generator, None)

# Conjunto de propriedades de cada item de POST /api/v1/retrieval/search neste
# SHA. Derivado do código real (app/schemas/retrieval.py), não de expectativa.
RETRIEVAL_ITEM_FIELDS = frozenset(
    {
        "chunk_id",
        "document_id",
        "document_version_id",
        "document_title",
        "chunk_index",
        "content",
        "score",
        "language",
        "official_source",
        "source_url",
        "valid_from",
        "valid_until",
    }
)

RETRIEVAL_RESPONSE_FIELDS = frozenset({"query", "language", "items"})

# Estados públicos atuais de answering, nos caminhos de sucesso HTTP.
PUBLIC_ANSWER_STATUSES = ("answered", "insufficient_evidence")


# --- 11.1 Forma exata do payload de retrieval -----------------------------------


def test_retrieval_search_item_exposes_exactly_the_current_field_set(
    client: TestClient,
) -> None:
    """A forma do item de retrieval é fixada por inteiro, não por amostragem."""
    _, headers, _ = setup_institution_with_admin(client)
    create_searchable_document(
        client,
        headers,
        "O periodo de matricula no campus decorre entre agosto e setembro.",
        title="Calendário Académico",
    )

    response = search(client, headers, "matricula", top_k=5)
    assert response.status_code == 200, response.text
    body = response.json()

    assert set(body) == RETRIEVAL_RESPONSE_FIELDS
    assert len(body["items"]) == 1
    item = body["items"][0]

    # Conjunto exato: nem a mais (um campo novo teria de ser declarado aqui),
    # nem a menos (remover um campo é uma quebra de contrato).
    assert set(item) == RETRIEVAL_ITEM_FIELDS


def test_retrieval_schema_and_evidence_dataclass_declare_the_same_fields() -> None:
    """Fixa o acoplamento em que ``RetrievalEvidenceRead(**asdict(item))`` assenta.

    Este teste é o que deteta um campo acrescentado ao dataclass ``Evidence``:
    sem ele, um campo novo seria silenciosamente descartado pelo schema e o
    contrato público mudaria — ou não mudaria — sem qualquer sinal.
    """
    evidence_fields = {field.name for field in fields(Evidence)}
    schema_fields = set(RetrievalEvidenceRead.model_fields)

    assert evidence_fields == RETRIEVAL_ITEM_FIELDS
    assert schema_fields == RETRIEVAL_ITEM_FIELDS
    assert evidence_fields == schema_fields
    assert set(RetrievalSearchResponse.model_fields) == RETRIEVAL_RESPONSE_FIELDS


# --- 11.2 / 11.3 Estados públicos de answering ----------------------------------


def _literal_values(annotation: object) -> tuple[str, ...]:
    assert get_origin(annotation) is Literal, annotation
    return get_args(annotation)


def test_both_answering_surfaces_declare_exactly_the_same_two_statuses() -> None:
    """Os dois endpoints declaram hoje exatamente os mesmos dois estados."""
    independent = _literal_values(AnsweringResponse.model_fields["status"].annotation)
    conversational = _literal_values(
        ConversationAskResponse.model_fields["status"].annotation
    )

    assert independent == PUBLIC_ANSWER_STATUSES
    assert conversational == PUBLIC_ANSWER_STATUSES
    assert independent == conversational


def test_answering_ask_returns_only_the_two_declared_statuses(
    client: TestClient, override_generator
) -> None:
    """Observa os dois estados no endpoint independente (200 em ambos)."""
    _, headers, _ = setup_institution_with_admin(client)
    create_searchable_document(client, headers, "campus matricula prazo institucional")
    override_generator(RecordingAnswerGenerator())

    answered = ask(client, headers, "matricula prazo")
    insufficient = ask(client, headers, "transporte interplanetario inexistente")

    assert answered.status_code == insufficient.status_code == 200
    assert answered.json()["status"] == "answered"
    assert insufficient.json()["status"] == "insufficient_evidence"
    observed = {answered.json()["status"], insufficient.json()["status"]}
    assert observed == set(PUBLIC_ANSWER_STATUSES)


def test_conversation_ask_returns_only_the_two_declared_statuses(
    client: TestClient, override_generator
) -> None:
    """Observa os mesmos dois estados no endpoint conversacional (201 em ambos)."""
    _, headers, _ = setup_institution_with_admin(client)
    conversation = create_conversation(client, headers)
    create_searchable_document(client, headers, "campus matricula prazo institucional")
    override_generator(RecordingAnswerGenerator())

    answered = ask_in_conversation(client, headers, conversation["id"], "matricula prazo")
    insufficient = ask_in_conversation(
        client, headers, conversation["id"], "transporte interplanetario inexistente"
    )

    assert answered.status_code == insufficient.status_code == 201
    assert answered.json()["status"] == "answered"
    assert insufficient.json()["status"] == "insufficient_evidence"
    observed = {answered.json()["status"], insufficient.json()["status"]}
    assert observed == set(PUBLIC_ANSWER_STATUSES)
