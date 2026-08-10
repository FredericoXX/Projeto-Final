"""Momento 6 — caracterização do fluxo de answering (Fase 1).

Estes testes **fixam o comportamento observável atual** do protótipo no SHA de
base do Momento 6. Não afirmam que esse comportamento é o correto: afirmam
apenas qual é, para que uma alteração arquitetural posterior tenha de declarar
explicitamente se o preserva ou se o muda deliberadamente.

Cobertura já existente e deliberadamente **não** duplicada aqui:

- zero evidências ⇒ ``insufficient_evidence`` sem chamar o gerador —
  ``test_answering_endpoint.py::test_question_without_evidence_returns_insufficient_evidence``,
  ``test_answering_service.py::test_question_without_evidence_returns_fallback_without_calling_generator``
  e o teste ``test_insufficient_evidence_persists_two_messages_without_``
  ``sources_or_provider_call`` de ``test_conversation_answering.py``;
- persistência do turno (``user_message``, ``assistant_message``,
  ``reply_to_message_id``, ``extra_metadata["answer_status"]``,
  transacionalidade) — ``test_conversation_answering.py``;
- fallback persistido sem ``MessageSource`` — idem;
- os cinco reason codes ao nível da função pura de validação —
  ``test_answering_units.py::test_invalid_answers_are_rejected_with_stable_reason_codes``;
- 503 quando a geração é mesmo necessária —
  ``test_answering_endpoint.py::test_unconfigured_provider_returns_503_only_when_generation_is_needed``.

O que este ficheiro acrescenta são as lacunas: a **ordem** das fontes na
superfície pública com mais do que uma citação, o mapeamento dos cinco reason
codes para o comportamento HTTP, e o arranque da aplicação sem credenciais do
fornecedor.
"""

from collections.abc import Callable, Iterator

import pytest
from fastapi.testclient import TestClient

from app.answering.base import AnswerGenerator, GeneratedAnswer
from app.answering.dependencies import get_answer_generator
from app.answering.providers.openai import OpenAIAnswerGenerator
from app.answering.validation import (
    REASON_ANSWER_TOO_LONG,
    REASON_DUPLICATE_EVIDENCE_IDS,
    REASON_EMPTY_ANSWER,
    REASON_MISSING_CITATIONS,
    REASON_UNKNOWN_EVIDENCE_IDS,
)
from app.core.config import settings
from app.main import app
from app.services import answering_service
from tests.moment06_support import (
    RecordingAnswerGenerator,
    ask,
    create_searchable_document,
    setup_institution_with_admin,
)


@pytest.fixture
def override_generator() -> Iterator[Callable[[AnswerGenerator], AnswerGenerator]]:
    def _install(generator: AnswerGenerator) -> AnswerGenerator:
        app.dependency_overrides[get_answer_generator] = lambda: generator
        return generator

    yield _install
    app.dependency_overrides.pop(get_answer_generator, None)


# --- 6.1 Resposta com evidência ------------------------------------------------


def test_sources_follow_generator_citation_order_and_omit_uncited_evidence(
    client: TestClient, override_generator
) -> None:
    """Caracteriza a ordem das ``sources`` na superfície pública.

    Três documentos são recuperados (E1, E2, E3, pela ordem do ranking) e o
    gerador cita deliberadamente ``("E3", "E1")`` — uma ordem que **não** é a
    do ranking. O comportamento atual é: as fontes saem exatamente pela ordem
    das citações do gerador, e a evidência recuperada mas não citada (E2) não
    aparece de todo.
    """
    _, headers, _ = setup_institution_with_admin(client)
    documents = [
        create_searchable_document(
            client,
            headers,
            f"campus matricula prazo regulamento numero {index}",
            title=f"Regulamento {index}",
        )[0]
        for index in range(3)
    ]

    generator = override_generator(
        RecordingAnswerGenerator(
            GeneratedAnswer(
                answer="A matrícula segue os prazos dos regulamentos citados.",
                cited_evidence_ids=("E3", "E1"),
            )
        )
    )
    response = ask(client, headers, "matricula prazo", top_k=3, official_only=True)
    assert response.status_code == 200, response.text

    body = response.json()
    assert body["status"] == "answered"
    assert body["answer"] == "A matrícula segue os prazos dos regulamentos citados."

    # A ordem das fontes é a ordem das citações, não a do ranking.
    assert [source["evidence_id"] for source in body["sources"]] == ["E3", "E1"]

    # O gerador recebeu as três evidências; só duas voltaram como fontes.
    assert len(generator.calls) == 1
    context = generator.calls[0]
    assert [entry.evidence_id for entry in context.evidence] == ["E1", "E2", "E3"]

    by_evidence_id = {entry.evidence_id: entry.evidence for entry in context.evidence}
    for source, evidence_id in zip(body["sources"], ("E3", "E1"), strict=True):
        evidence = by_evidence_id[evidence_id]
        assert source["chunk_id"] == str(evidence.chunk_id)
        assert source["document_id"] == str(evidence.document_id)
        assert source["document_version_id"] == str(evidence.document_version_id)

    # A evidência recuperada e não citada não aparece em sources.
    uncited = by_evidence_id["E2"]
    assert str(uncited.chunk_id) not in response.text
    assert {source["document_id"] for source in body["sources"]} == {
        str(by_evidence_id["E3"].document_id),
        str(by_evidence_id["E1"].document_id),
    }
    assert len(documents) == 3


# --- 6.3 Validação estrutural: os cinco reason codes na superfície HTTP ---------


def _generated_for(reason_code: str) -> GeneratedAnswer:
    """Uma geração que viola exatamente uma das cinco regras estruturais."""
    if reason_code == REASON_EMPTY_ANSWER:
        return GeneratedAnswer(answer="   \n\t ", cited_evidence_ids=("E1",))
    if reason_code == REASON_ANSWER_TOO_LONG:
        return GeneratedAnswer(
            answer="x" * (settings.answering_max_answer_chars + 1),
            cited_evidence_ids=("E1",),
        )
    if reason_code == REASON_MISSING_CITATIONS:
        return GeneratedAnswer(answer="Resposta sem qualquer citação.", cited_evidence_ids=())
    if reason_code == REASON_DUPLICATE_EVIDENCE_IDS:
        return GeneratedAnswer(answer="Resposta duplicada.", cited_evidence_ids=("E1", "E1"))
    return GeneratedAnswer(answer="Resposta inventada.", cited_evidence_ids=("E999",))


@pytest.mark.parametrize(
    ("reason_code", "expected_invalid_count"),
    [
        (REASON_EMPTY_ANSWER, 0),
        (REASON_ANSWER_TOO_LONG, 0),
        (REASON_MISSING_CITATIONS, 0),
        (REASON_DUPLICATE_EVIDENCE_IDS, 0),
        (REASON_UNKNOWN_EVIDENCE_IDS, 1),
    ],
)
def test_each_structural_reason_code_produces_502_upstream_error(
    client: TestClient,
    override_generator,
    monkeypatch: pytest.MonkeyPatch,
    reason_code: str,
    expected_invalid_count: int,
) -> None:
    """Fixa os cinco reason codes atuais e o seu efeito HTTP.

    Os códigos não são reinterpretados nem corrigidos: são registados tal como
    a aplicação os produz hoje. O reason code é confirmado no log (é o único
    sítio onde vive — a resposta HTTP expõe apenas a mensagem segura).
    """
    _, headers, _ = setup_institution_with_admin(client)
    create_searchable_document(client, headers, "campus matricula prazo institucional")
    override_generator(RecordingAnswerGenerator(_generated_for(reason_code)))

    warning_calls: list[tuple[str, tuple[object, ...]]] = []

    def capture_warning(message: str, *args: object) -> None:
        warning_calls.append((message, args))

    # Interceta a emissão no logger do módulo, sem depender da configuração
    # global de logging que outros testes da suite podem alterar.
    monkeypatch.setattr(answering_service.logger, "warning", capture_warning)
    response = ask(client, headers, "matricula prazo")

    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "upstream_error"
    # A mensagem devolvida é sempre a mesma e nunca inclui o reason code nem
    # valores devolvidos pelo fornecedor.
    assert reason_code not in response.text
    assert "E999" not in response.text

    assert len(warning_calls) == 1
    message, arguments = warning_calls[0]
    assert message == (
        "Generated answer rejected: institution=%s reason=%s invalid_count=%d"
    )
    assert arguments[1:] == (reason_code, expected_invalid_count)


# --- 6.6 O fornecedor não pode impedir o arranque -------------------------------


def test_application_starts_and_serves_without_openai_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Caracteriza que a ausência de ``OPENAI_API_KEY`` não impede o arranque.

    Comportamento atual, verificado sem qualquer dependency override: a
    aplicação constrói-se e serve pedidos sem chave nem modelo, e até a
    **resolução** do provider (``get_answer_generator``) tem sucesso. A
    indisponibilidade só se manifesta no ponto em que a geração é realmente
    executada — é aí que ``_build_client`` exige a chave.

    Este momento não altera a resolução atual do provider; apenas a regista.
    """
    monkeypatch.setattr(settings, "openai_api_key", None)
    monkeypatch.setattr(settings, "openai_model", None)

    with TestClient(app) as unauthenticated_client:
        health = unauthenticated_client.get("/api/v1/health")
        assert health.status_code == 200

    # A factory resolve sem erro: nada exige credenciais no arranque.
    generator = get_answer_generator()
    assert isinstance(generator, OpenAIAnswerGenerator)


def test_provider_absence_only_fails_when_generation_is_actually_executed(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Complementa o 503 já coberto: sem evidências nada falha.

    ``test_answering_endpoint.py`` já fixa o par (sem evidências → 200,
    com evidências → 503) para o endpoint independente. O que aqui se
    acrescenta é a leitura pelo lado do provider: com a chave ausente, o
    caminho sem evidências nem sequer constrói o cliente do fornecedor.
    """
    monkeypatch.setattr(settings, "openai_api_key", None)
    monkeypatch.setattr(settings, "openai_model", None)
    _, headers, _ = setup_institution_with_admin(client)
    create_searchable_document(client, headers, "campus matricula prazo institucional")

    def forbidden_client() -> object:
        raise AssertionError("o cliente do fornecedor não pode ser construído aqui")

    monkeypatch.setattr(OpenAIAnswerGenerator, "_build_client", lambda _self: forbidden_client())

    without_evidence = ask(client, headers, "transporte interplanetario inexistente")
    assert without_evidence.status_code == 200
    assert without_evidence.json()["status"] == "insufficient_evidence"
    assert without_evidence.json()["sources"] == []
