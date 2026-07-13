"""Testes unitários do adapter OpenAI com cliente simulado.

Nenhum teste faz chamadas reais: o cliente é sempre um fake injetado no
construtor, e os casos "não configurado" nem chegam a precisar de cliente.
"""

import json
import logging
import uuid
from types import SimpleNamespace
from typing import Any

import httpx
import openai
import pytest

from app.answering.base import (
    AnswerGenerationError,
    AnswerGeneratorUnavailableError,
    AnsweringContext,
    ContextEvidence,
)
from app.answering.providers.openai import OpenAIAnswerGenerator
from app.core.config import settings
from app.retrieval.base import Evidence


def _context() -> AnsweringContext:
    evidence = Evidence(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        document_version_id=uuid.uuid4(),
        document_title="Calendário Académico",
        chunk_index=0,
        content="O prazo de matrícula decorre em setembro.",
        score=0.7,
        language="pt",
        official_source=True,
        source_url=None,
        valid_from=None,
        valid_until=None,
    )
    return AnsweringContext(
        query="prazo de matrícula",
        language="pt",
        institution_name="Universidade de Teste",
        evidence=(ContextEvidence(evidence_id="E1", evidence=evidence),),
        max_context_chars=12000,
    )


def _completion(content: Any) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )


class _FakeCompletions:
    def __init__(self, response: Any = None, exception: Exception | None = None) -> None:
        self.response = response
        self.exception = exception
        self.calls: list[dict] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self.exception is not None:
            raise self.exception
        return self.response


class _FakeClient:
    def __init__(self, response: Any = None, exception: Exception | None = None) -> None:
        self.completions = _FakeCompletions(response, exception)
        self.chat = SimpleNamespace(completions=self.completions)


@pytest.fixture(autouse=True)
def _configured_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "openai_model", "test-model")


def test_valid_configuration_and_structured_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _FakeClient(
        response=_completion(
            json.dumps({"answer": "Setembro.", "cited_evidence_ids": ["E1"]})
        )
    )
    generated = OpenAIAnswerGenerator(client=client).generate(_context())

    assert generated.answer == "Setembro."
    assert generated.cited_evidence_ids == ("E1",)
    assert len(client.completions.calls) == 1
    call = client.completions.calls[0]
    assert call["model"] == "test-model"
    roles = [message["role"] for message in call["messages"]]
    assert roles == ["system", "user"]
    assert call["response_format"]["type"] == "json_schema"


def test_missing_api_key_raises_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "openai_api_key", None)
    # Sem cliente injetado e sem chave: falha antes de qualquer chamada.
    with pytest.raises(AnswerGeneratorUnavailableError):
        OpenAIAnswerGenerator().generate(_context())


def test_missing_model_raises_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "openai_model", None)
    client = _FakeClient(response=_completion("{}"))
    with pytest.raises(AnswerGeneratorUnavailableError):
        OpenAIAnswerGenerator(client=client).generate(_context())
    # O fornecedor nunca chega a ser contactado.
    assert client.completions.calls == []


def test_timeout_is_converted_to_safe_error() -> None:
    timeout = openai.APITimeoutError(request=httpx.Request("POST", "https://api.test"))
    client = _FakeClient(exception=timeout)
    with pytest.raises(AnswerGenerationError):
        OpenAIAnswerGenerator(client=client).generate(_context())


def test_provider_error_is_converted_and_never_leaks_secret(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    sentinels = (
        "sk-log-sentinel-secret",
        "sensitive-question-log-sentinel",
        "sensitive-document-log-sentinel",
        "Authorization: Bearer sensitive-token-sentinel",
        "sensitive-provider-response-sentinel",
    )
    monkeypatch.setattr(settings, "openai_api_key", sentinels[0])
    client = _FakeClient(exception=openai.OpenAIError("\n".join(sentinels)))

    with caplog.at_level(logging.ERROR, logger="app.answering.providers.openai"):
        with pytest.raises(AnswerGenerationError) as excinfo:
            OpenAIAnswerGenerator(client=client).generate(_context())

    assert excinfo.value.__cause__ is None
    assert "Answer provider request failed" in caplog.text
    assert "error_type=OpenAIError" in caplog.text
    assert "Traceback" not in caplog.text
    assert "exc_info" not in caplog.text
    for sentinel in sentinels:
        assert sentinel not in caplog.text
        assert sentinel not in str(excinfo.value)
        assert sentinel not in repr(excinfo.value)


def test_openai_client_disables_sdk_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    fake_client = _FakeClient(
        response=_completion(
            json.dumps({"answer": "Setembro.", "cited_evidence_ids": ["E1"]})
        )
    )

    def build_fake_client(**kwargs: Any) -> _FakeClient:
        captured.update(kwargs)
        return fake_client

    monkeypatch.setattr(settings, "openai_api_key", "test-only-key")
    monkeypatch.setattr(openai, "OpenAI", build_fake_client)
    OpenAIAnswerGenerator().generate(_context())

    assert captured["timeout"] == settings.openai_timeout_seconds
    assert captured["max_retries"] == 0


def test_unexpected_error_is_converted_to_safe_error() -> None:
    client = _FakeClient(exception=RuntimeError("boom"))
    with pytest.raises(AnswerGenerationError) as excinfo:
        OpenAIAnswerGenerator(client=client).generate(_context())
    assert "boom" not in str(excinfo.value)


@pytest.mark.parametrize(
    "content",
    [
        None,
        "",
        "not json at all",
        json.dumps({"answer": "ok"}),  # falta cited_evidence_ids
        json.dumps({"cited_evidence_ids": ["E1"]}),  # falta answer
        json.dumps({"answer": 42, "cited_evidence_ids": ["E1"]}),
        json.dumps({"answer": "ok", "cited_evidence_ids": "E1"}),
        json.dumps({"answer": "ok", "cited_evidence_ids": [1, 2]}),
        json.dumps(["answer", "lista em vez de objeto"]),
    ],
)
def test_unusable_provider_responses_are_rejected(content: Any) -> None:
    client = _FakeClient(response=_completion(content))
    with pytest.raises(AnswerGenerationError):
        OpenAIAnswerGenerator(client=client).generate(_context())


def test_empty_choices_is_rejected() -> None:
    client = _FakeClient(response=SimpleNamespace(choices=[]))
    with pytest.raises(AnswerGenerationError):
        OpenAIAnswerGenerator(client=client).generate(_context())


def test_nonexistent_citations_pass_through_for_downstream_validation() -> None:
    # A existência dos IDs é validada em validation.py (no service), não
    # no adapter: aqui só se garante o parsing estrutural.
    client = _FakeClient(
        response=_completion(
            json.dumps({"answer": "Resposta.", "cited_evidence_ids": ["E9"]})
        )
    )
    generated = OpenAIAnswerGenerator(client=client).generate(_context())
    assert generated.cited_evidence_ids == ("E9",)
