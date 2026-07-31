"""Testes do answering_service com fakes de Retriever e AnswerGenerator.

Sem rede e sem credenciais: nenhum teste toca no SDK do fornecedor.
"""

import hashlib
import logging
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.answering.base import (
    AnswerGenerationError,
    AnswerGeneratorUnavailableError,
    AnsweringContext,
    GeneratedAnswer,
    InvalidGeneratedAnswerError,
)
from app.core.config import settings
from app.core.exceptions import ValidationError
from app.models.user import User
from app.retrieval.base import Evidence, RetrievalContext
from app.schemas.answering import AnsweringRequest
from app.services import answering_service

BOOTSTRAP_HEADERS = {"X-Bootstrap-Token": settings.bootstrap_token or ""}
_ADMIN_PASSWORD = "supersecret123"


class FakeRetriever:
    """Retriever de teste: devolve evidências fixas e regista as chamadas."""

    def __init__(self, evidence: list[Evidence] | None = None) -> None:
        self.evidence = evidence or []
        self.calls: list[dict] = []

    def search(
        self,
        db: Session,
        query: str,
        context: RetrievalContext,
        top_k: int,
        official_only: bool,
    ) -> list[Evidence]:
        self.calls.append(
            {
                "query": query,
                "context": context,
                "top_k": top_k,
                "official_only": official_only,
            }
        )
        return list(self.evidence)


class FakeAnswerGenerator:
    """Gerador de teste configurável; nunca toca na rede."""

    def __init__(
        self,
        result: GeneratedAnswer | None = None,
        exception: Exception | None = None,
    ) -> None:
        self.result = result
        self.exception = exception
        self.calls: list[AnsweringContext] = []

    def generate(self, context: AnsweringContext) -> GeneratedAnswer:
        self.calls.append(context)
        if self.exception is not None:
            raise self.exception
        if self.result is not None:
            return self.result
        # Resposta válida por omissão: cita a primeira evidência.
        return GeneratedAnswer(
            answer="Resposta fundamentada.",
            cited_evidence_ids=(context.evidence[0].evidence_id,),
        )


def _evidence(content: str = "O prazo de matrícula é em setembro.") -> Evidence:
    return Evidence(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        document_version_id=uuid.uuid4(),
        document_title="Calendário Académico",
        chunk_index=0,
        content=content,
        score=0.7,
        language="pt",
        official_source=True,
        source_url="https://example.edu/doc",
        valid_from=None,
        valid_until=None,
    )


def _create_institution_and_admin(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
    *,
    default_language: str = "pt",
    supported_languages: list[str] | None = None,
) -> tuple[Session, User]:
    institution = client.post(
        "/api/v1/institutions",
        json={
            "name": "Answering Institution",
            "code": f"ANS-{uuid.uuid4().hex[:8].upper()}",
            "default_language": default_language,
            "supported_languages": supported_languages or ["pt", "en"],
        },
        headers=BOOTSTRAP_HEADERS,
    )
    assert institution.status_code == 201
    admin = client.post(
        "/api/v1/auth/register-initial-admin",
        json={
            "institution_id": institution.json()["id"],
            "full_name": "Admin Answering",
            "email": f"admin-{uuid.uuid4().hex[:8]}@example.com",
            "password": _ADMIN_PASSWORD,
        },
        headers=BOOTSTRAP_HEADERS,
    )
    assert admin.status_code == 201

    session = test_session_factory()
    user = session.get(User, uuid.UUID(admin.json()["id"]))
    assert user is not None
    return session, user


def _admin_headers(client: TestClient, user: User) -> dict[str, str]:
    login = client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": _ADMIN_PASSWORD}
    )
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _request(**overrides: object) -> AnsweringRequest:
    payload: dict = {"query": "Qual é o prazo de matrícula?"}
    payload.update(overrides)
    return AnsweringRequest(**payload)


def test_question_with_evidence_calls_generator_and_answers(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> None:
    session, user = _create_institution_and_admin(client, test_session_factory)
    try:
        retriever = FakeRetriever([_evidence()])
        generator = FakeAnswerGenerator()
        response = answering_service.ask(session, user, _request(), retriever, generator)

        assert response.status == "answered"
        assert response.answer == "Resposta fundamentada."
        assert len(generator.calls) == 1
        assert generator.calls[0].institution_name == "Answering Institution"
        assert len(response.sources) == 1
        assert response.sources[0].evidence_id == "E1"
        expected_checksum = hashlib.sha256(
            generator.calls[0].evidence[0].evidence.content.encode("utf-8")
        ).hexdigest()
        assert response.sources[0].internal_content_sha256 == expected_checksum
        assert "content_sha256" not in response.model_dump_json()
    finally:
        session.close()


def test_question_without_evidence_returns_fallback_without_calling_generator(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> None:
    session, user = _create_institution_and_admin(client, test_session_factory)
    try:
        generator = FakeAnswerGenerator()
        response = answering_service.ask(
            session, user, _request(), FakeRetriever([]), generator
        )

        assert response.status == "insufficient_evidence"
        assert generator.calls == []
        assert response.sources == []
        # Fallback português (idioma padrão da instituição).
        assert response.answer.startswith("Não encontrei informação institucional")
    finally:
        session.close()


def test_fallback_uses_english_when_language_is_english(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> None:
    session, user = _create_institution_and_admin(client, test_session_factory)
    try:
        response = answering_service.ask(
            session,
            user,
            _request(language="en"),
            FakeRetriever([]),
            FakeAnswerGenerator(),
        )
        assert response.language == "en"
        assert response.answer.startswith("I could not find sufficient")
    finally:
        session.close()


def test_real_retriever_rejects_partial_match_without_calling_generator(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> None:
    """Serviço com o retriever **real** sobre um documento sintético cujo
    único candidato cobre 1 dos 3 termos: o retrieval devolve vazio, o
    answering devolve insufficient_evidence e o gerador não é chamado."""
    import io

    from app.retrieval.lexical import PostgresLexicalRetriever

    session, user = _create_institution_and_admin(client, test_session_factory)
    try:
        headers = _admin_headers(client, user)
        document = client.post(
            "/api/v1/documents",
            json={
                "title": "Política Interna",
                "language": "pt",
                "official_source": True,
                "source_url": "https://example.edu/politica",
            },
            headers=headers,
        )
        assert document.status_code == 201
        upload = client.post(
            f"/api/v1/documents/{document.json()['id']}/versions",
            files={
                "file": (
                    "politica.txt",
                    io.BytesIO(b"Regime institucional geral."),
                    "text/plain",
                )
            },
            headers=headers,
        )
        assert upload.status_code == 201
        assert upload.json()["processing_status"] == "processed"

        generator = FakeAnswerGenerator()
        response = answering_service.ask(
            session,
            user,
            _request(query="regime avaliacao exames"),
            PostgresLexicalRetriever(),
            generator,
        )
        assert response.status == "insufficient_evidence"
        assert response.sources == []
        assert generator.calls == []
    finally:
        session.close()


def test_omitted_language_uses_institution_default(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> None:
    session, user = _create_institution_and_admin(client, test_session_factory)
    try:
        retriever = FakeRetriever([_evidence()])
        response = answering_service.ask(
            session, user, _request(), retriever, FakeAnswerGenerator()
        )
        assert response.language == "pt"
        assert retriever.calls[0]["context"].language == "pt"
    finally:
        session.close()


def test_omitted_language_accepts_conversation_fallback(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> None:
    session, user = _create_institution_and_admin(client, test_session_factory)
    try:
        retriever = FakeRetriever([_evidence()])
        response = answering_service.ask(
            session,
            user,
            _request(),
            retriever,
            FakeAnswerGenerator(),
            fallback_language="en",
        )
        assert response.language == "en"
        assert retriever.calls[0]["context"].language == "en"
    finally:
        session.close()


def test_unsupported_language_raises_validation_error(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> None:
    session, user = _create_institution_and_admin(client, test_session_factory)
    try:
        with pytest.raises(ValidationError):
            answering_service.ask(
                session,
                user,
                _request(language="fr"),
                FakeRetriever([_evidence()]),
                FakeAnswerGenerator(),
            )
    finally:
        session.close()


def test_default_top_k_is_applied(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> None:
    session, user = _create_institution_and_admin(client, test_session_factory)
    try:
        retriever = FakeRetriever([_evidence()])
        answering_service.ask(session, user, _request(), retriever, FakeAnswerGenerator())
        assert retriever.calls[0]["top_k"] == settings.answering_default_top_k
    finally:
        session.close()


def test_top_k_above_configured_maximum_is_rejected(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> None:
    session, user = _create_institution_and_admin(client, test_session_factory)
    try:
        retriever = FakeRetriever([_evidence()])
        with pytest.raises(ValidationError, match="top_k"):
            answering_service.ask(
                session,
                user,
                _request(top_k=settings.answering_max_top_k + 1),
                retriever,
                FakeAnswerGenerator(),
            )
        assert retriever.calls == []
    finally:
        session.close()


def test_official_only_is_forwarded_to_retriever(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> None:
    session, user = _create_institution_and_admin(client, test_session_factory)
    try:
        retriever = FakeRetriever([_evidence()])
        answering_service.ask(
            session, user, _request(official_only=False), retriever, FakeAnswerGenerator()
        )
        assert retriever.calls[0]["official_only"] is False
    finally:
        session.close()


def test_only_cited_evidence_appears_in_sources(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> None:
    session, user = _create_institution_and_admin(client, test_session_factory)
    try:
        first = _evidence(content="primeira evidência")
        second = _evidence(content="segunda evidência")
        generator = FakeAnswerGenerator(
            result=GeneratedAnswer(answer="Só a segunda.", cited_evidence_ids=("E2",))
        )
        response = answering_service.ask(
            session, user, _request(), FakeRetriever([first, second]), generator
        )
        assert [source.evidence_id for source in response.sources] == ["E2"]
        assert response.sources[0].chunk_id == second.chunk_id
    finally:
        session.close()


def test_invented_evidence_id_fails_safely(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> None:
    session, user = _create_institution_and_admin(client, test_session_factory)
    try:
        generator = FakeAnswerGenerator(
            result=GeneratedAnswer(answer="Resposta.", cited_evidence_ids=("E9",))
        )
        with pytest.raises(InvalidGeneratedAnswerError) as excinfo:
            answering_service.ask(
                session, user, _request(), FakeRetriever([_evidence()]), generator
            )
        assert "E9" not in str(excinfo.value)
    finally:
        session.close()


def test_untrusted_citation_ids_never_enter_logs(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
    caplog: pytest.LogCaptureFixture,
) -> None:
    session, user = _create_institution_and_admin(client, test_session_factory)
    untrusted_ids = (
        "sensitive-question-sentinel\nWARNING forged-log-entry",
        "sensitive-document-id-sentinel\rforged-carriage-return",
        "sk-invalid-id-secret",
        "unicode-学生-🎓-" + "x" * 5000,
    )
    generator = FakeAnswerGenerator(
        result=GeneratedAnswer(
            answer="Resposta.",
            cited_evidence_ids=("E1", *untrusted_ids),
        )
    )
    try:
        with caplog.at_level(logging.WARNING, logger="app.services.answering_service"):
            with pytest.raises(InvalidGeneratedAnswerError):
                answering_service.ask(
                    session,
                    user,
                    _request(),
                    FakeRetriever([_evidence()]),
                    generator,
                )

        assert "reason=unknown_evidence_ids" in caplog.text
        assert "invalid_count=4" in caplog.text
        for untrusted_id in untrusted_ids:
            assert untrusted_id not in caplog.text
        assert "forged-log-entry" not in caplog.text
        assert "forged-carriage-return" not in caplog.text
    finally:
        session.close()


def test_unavailable_provider_propagates_service_unavailable(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> None:
    session, user = _create_institution_and_admin(client, test_session_factory)
    try:
        generator = FakeAnswerGenerator(
            exception=AnswerGeneratorUnavailableError("not configured")
        )
        with pytest.raises(AnswerGeneratorUnavailableError):
            answering_service.ask(
                session, user, _request(), FakeRetriever([_evidence()]), generator
            )
    finally:
        session.close()


def test_provider_failure_does_not_expose_internal_details(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> None:
    session, user = _create_institution_and_admin(client, test_session_factory)
    try:
        generator = FakeAnswerGenerator(
            exception=AnswerGenerationError(
                "The answer generator failed to produce a usable response."
            )
        )
        with pytest.raises(AnswerGenerationError) as excinfo:
            answering_service.ask(
                session, user, _request(), FakeRetriever([_evidence()]), generator
            )
        assert "Traceback" not in str(excinfo.value)
        assert "sk-" not in str(excinfo.value)
    finally:
        session.close()


def test_query_normalizing_to_empty_raises_validation_error(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> None:
    session, user = _create_institution_and_admin(client, test_session_factory)
    try:
        retriever = FakeRetriever([_evidence()])
        with pytest.raises(ValidationError):
            answering_service.ask(
                session, user, _request(query="´´"), retriever, FakeAnswerGenerator()
            )
        assert retriever.calls == []
    finally:
        session.close()
