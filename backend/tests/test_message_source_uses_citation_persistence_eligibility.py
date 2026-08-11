"""Fase 3 da issue #24 — a revalidação de citações consome ``CitationPersistenceEligibility``.

O que já existe cobre o **comportamento**:
``test_moment06_evidence_eligibility_characterisation.py`` prova que uma versão
superada continua a ser aceite (D1 / Decisão 7), que um chunk com idioma
divergente é recusado (C8) e que a proveniência N → N+1 sobrevive ao turno;
``test_conversation_answering.py`` prova o conflito genérico perante metadados,
checksums e conteúdo alterados. Nenhum deles falharia se alguém voltasse a
escrever a admissibilidade documental à mão dentro do service: o comportamento
seria o mesmo e a duplicação regressaria em silêncio, com o import da política
por usar.

É essa a lacuna que este ficheiro fecha. Fixa a **fonte de verdade**, não a
matriz C1–C11 — essa não é repetida aqui — e o risco específico desta migração,
que é o inverso do da Fase 2: aqui o perigo não é perder uma condição, é
**ganhar C5**. A persistência pergunta "esta evidência foi legitimamente usada
para gerar esta resposta", não "é recuperável agora"; resolver a versão efetiva
neste service transformaria uma resposta legítima num conflito sempre que um
carregamento concorrente processasse N+1.

A delegação é fixada **dinamicamente**, em três direções complementares, porque
nenhuma delas basta sozinha:

1. a política é chamada, com o contexto e o sujeito certos — espia;
2. o veredicto **decide**: forçá-lo a negativo recusa uma fonte válida — se
   alguém ignorasse o valor devolvido, isto passaria despercebido;
3. o veredicto é a **única** definição de admissibilidade: forçá-lo a positivo
   aceita uma fonte que a política real recusa. Uma reintrodução inline ao lado
   da chamada continuaria a recusá-la, e este teste falharia.

O que **não** é admissibilidade documental — identificadores, metadados
inalterados, checksums, normalização, coerência com ``extracted_text`` —
continua deste lado, e o ponto 3 confirma-o: com a política forçada a positivo,
essas defesas continuam a recusar o que lhes compete.
"""

import hashlib
import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.answering.dependencies import get_answer_generator
from app.core.exceptions import ConflictError
from app.documents.retrievability import (
    CitationPersistenceEligibility,
    EvidencePolicy,
    RetrievabilityContext,
    RetrievabilitySubject,
    RetrievabilityVerdict,
)
from app.main import app
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.message import Message
from app.schemas.answering import AnswerSourceRead
from app.services import message_source_service
from app.services.message_source_service import (
    SOURCES_CHANGED_MESSAGE,
    revalidate_and_lock_sources,
)
from tests.moment06_support import (
    RecordingAnswerGenerator,
    ask_in_conversation,
    create_conversation,
    create_searchable_document,
    setup_institution_with_admin,
)

# Termo de forma lexical idêntica em 'portuguese' e 'english': ver
# ``moment06_support.CONFIG_INVARIANT_TERMS``.
CONTENT = "erasmus campus provedor alfa institucional"


def _reference_date():
    return datetime.now(UTC).date()


def _first_chunk(db: Session, version_id: uuid.UUID) -> DocumentChunk:
    chunk = db.scalar(
        select(DocumentChunk)
        .where(DocumentChunk.document_version_id == version_id)
        .order_by(DocumentChunk.chunk_index)
        .limit(1)
    )
    assert chunk is not None
    return chunk


def _source_dto(
    db: Session, *, document_id: uuid.UUID, version_id: uuid.UUID
) -> AnswerSourceRead:
    """DTO da fonte citada, tal como ``answering_service`` o constrói."""
    document = db.get(Document, document_id)
    assert document is not None
    chunk = _first_chunk(db, version_id)
    source = AnswerSourceRead(
        evidence_id="E1",
        chunk_id=chunk.id,
        document_id=document.id,
        document_version_id=version_id,
        document_title=document.title,
        chunk_index=chunk.chunk_index,
        source_url=document.source_url,
        official_source=document.official_source,
        language=document.language,
        valid_from=document.valid_from,
        valid_until=document.valid_until,
    )
    source.set_internal_content_sha256(chunk.content_sha256)
    return source


def _force_chunk_language(db: Session, *, version_id: uuid.UUID, language: str) -> None:
    """Coloca o idioma do chunk em divergência com o do documento.

    Contorna deliberadamente a invariante mantida pelos services (o chunk herda
    o idioma do documento na segmentação), escrevendo diretamente na base — é a
    única forma de produzir uma linha que a política real recuse por C8 sem
    tocar em mais nada. Nenhuma constraint é violada. Mesmo desvio, e pela mesma
    razão, que ``test_moment06_evidence_eligibility_characterisation.py``.
    """
    chunk = _first_chunk(db, version_id)
    chunk.language = language
    db.commit()


class _PolicySpy:
    """Delega na política real e regista o que lhe foi pedido.

    Existe porque observar apenas o resultado da revalidação **não distingue**
    "o service pediu o veredicto à política" de "o service voltou a escrever as
    condições à mão e deixou o import por usar": as duas situações aceitam e
    recusam exatamente as mesmas fontes.
    """

    def __init__(self, policy: EvidencePolicy) -> None:
        self._policy = policy
        self.calls: list[tuple[RetrievabilitySubject, RetrievabilityContext]] = []

    def explain(
        self, subject: RetrievabilitySubject, context: RetrievabilityContext
    ) -> RetrievabilityVerdict:
        self.calls.append((subject, context))
        return self._policy.explain(subject, context)


class _ForcedVerdict:
    """Política de teste que responde sempre o mesmo, sem avaliar nada."""

    def __init__(self, eligible: bool) -> None:
        self.eligible = eligible
        self.calls = 0

    def explain(
        self, subject: RetrievabilitySubject, context: RetrievabilityContext
    ) -> RetrievabilityVerdict:
        self.calls += 1
        return RetrievabilityVerdict(
            policy="ForcedForTest", eligible=self.eligible, conditions=()
        )


# --- A fonte de verdade -------------------------------------------------------


def test_the_service_imports_the_persistence_policy_and_not_the_retrieval_one() -> None:
    """C5 não deve ter forma de entrar neste módulo.

    A regressão mais perigosa desta fase não é perder uma condição: é ganhar
    uma. Se o nome da política de recuperação, ou a subquery que materializa
    C5, aparecerem aqui, é porque alguém começou a responder à pergunta errada.
    """
    assert (
        message_source_service.CitationPersistenceEligibility
        is CitationPersistenceEligibility
    )
    assert not hasattr(message_source_service, "RetrievalEligibility")
    assert not hasattr(message_source_service, "latest_processed_version_subquery")


def test_the_policy_used_by_persistence_is_the_one_without_c5() -> None:
    """Persistência pergunta "então"; por isso C5 não pode fazer parte."""
    assert CitationPersistenceEligibility.requires_latest_processed_version is False
    assert (
        "version_is_highest_processed"
        not in CitationPersistenceEligibility.condition_names
    )


def test_the_documental_verdict_is_obtained_from_the_policy(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Uma chamada real a ``explain``, com o contexto e o sujeito das linhas bloqueadas.

    Não se afirma quantas condições a política tem — isso é matéria do teste de
    composição da Fase 1, e depender aqui desse número tornaria este ficheiro
    refém de uma decisão que não lhe pertence. Afirma-se **de onde** vem o
    veredicto, e que o sujeito descreve as entidades que o service bloqueou.
    """
    _, headers, _ = setup_institution_with_admin(client)
    document, version = create_searchable_document(client, headers, CONTENT)
    document_id = uuid.UUID(document["id"])
    version_id = uuid.UUID(version["id"])
    reference_date = _reference_date()

    spy = _PolicySpy(CitationPersistenceEligibility)
    monkeypatch.setattr(
        message_source_service, "CitationPersistenceEligibility", spy
    )

    with test_session_factory() as db:
        institution_id = db.get(Document, document_id).institution_id  # type: ignore[union-attr]
        source = _source_dto(db, document_id=document_id, version_id=version_id)
        snapshots = revalidate_and_lock_sources(
            db,
            institution_id=institution_id,
            cited_sources=[source],
            language="pt",
            reference_date=reference_date,
            official_only=True,
        )
        assert len(snapshots) == 1

        expected_chunk_id = _first_chunk(db, version_id).id
        db.rollback()

    # Uma citação, uma avaliação: a política não é chamada mais do que o
    # necessário nem menos do que uma vez por fonte.
    assert len(spy.calls) == 1
    subject, context = spy.calls[0]

    assert context == RetrievabilityContext(
        institution_id=institution_id,
        language="pt",
        reference_date=reference_date,
        official_only=True,
    )
    # O sujeito descreve as entidades bloqueadas, não o DTO recebido.
    assert subject.chunk_id == expected_chunk_id
    assert subject.document_id == document_id
    assert subject.version_id == version_id
    assert subject.chunk_document_version_id == version_id
    assert subject.chunk_institution_id == institution_id
    assert subject.document_institution_id == institution_id
    assert subject.version_institution_id == institution_id
    assert subject.version_processing_status == "processed"
    # E C5 não é sequer preparada: a versão efetiva fica por resolver.
    assert subject.effective_version_id is None


@pytest.mark.parametrize("official_only", [True, False])
def test_official_only_reaches_the_policy_as_given(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    official_only: bool,
) -> None:
    """O contexto traduz o pedido, sem introduzir configuração nova."""
    _, headers, _ = setup_institution_with_admin(client)
    document, version = create_searchable_document(client, headers, CONTENT)
    document_id = uuid.UUID(document["id"])

    spy = _PolicySpy(CitationPersistenceEligibility)
    monkeypatch.setattr(
        message_source_service, "CitationPersistenceEligibility", spy
    )

    with test_session_factory() as db:
        institution_id = db.get(Document, document_id).institution_id  # type: ignore[union-attr]
        source = _source_dto(
            db, document_id=document_id, version_id=uuid.UUID(version["id"])
        )
        revalidate_and_lock_sources(
            db,
            institution_id=institution_id,
            cited_sources=[source],
            language="pt",
            reference_date=_reference_date(),
            official_only=official_only,
        )
        db.rollback()

    assert [context.official_only for _subject, context in spy.calls] == [official_only]


# --- O veredicto decide, e é a única definição --------------------------------


def test_a_negative_verdict_rejects_an_otherwise_valid_source(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """O valor devolvido é consumido, não apenas pedido.

    A fonte é íntegra em tudo o que o service continua a verificar; a única
    coisa que muda é o veredicto documental. Se alguém chamasse a política e
    ignorasse a resposta, a revalidação teria sucesso e este teste falharia.
    """
    _, headers, _ = setup_institution_with_admin(client)
    document, version = create_searchable_document(client, headers, CONTENT)
    document_id = uuid.UUID(document["id"])

    forced = _ForcedVerdict(eligible=False)
    monkeypatch.setattr(
        message_source_service, "CitationPersistenceEligibility", forced
    )

    with test_session_factory() as db:
        institution_id = db.get(Document, document_id).institution_id  # type: ignore[union-attr]
        source = _source_dto(
            db, document_id=document_id, version_id=uuid.UUID(version["id"])
        )
        with pytest.raises(ConflictError) as raised:
            revalidate_and_lock_sources(
                db,
                institution_id=institution_id,
                cited_sources=[source],
                language="pt",
                reference_date=_reference_date(),
                official_only=True,
            )
        db.rollback()

    assert forced.calls == 1
    # O erro público não revela a condição, o veredicto nem a política.
    assert str(raised.value) == SOURCES_CHANGED_MESSAGE
    assert "ForcedForTest" not in str(raised.value)


def test_no_parallel_definition_of_documental_admissibility_survives(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A política é a **única** fonte de verdade da admissibilidade documental.

    O chunk tem idioma divergente do documento: a política real recusa-o por
    C8, e a primeira metade do teste confirma-o. Com o veredicto forçado a
    positivo, a mesma fonte passa a ser aceite — o que só é possível se
    nenhuma outra definição da admissibilidade documental tiver sobrevivido no
    service. Um bloco ``eligible = (version.processing_status == ... and ...)``
    reintroduzido ao lado da chamada continuaria a recusá-la, e esta segunda
    metade falharia.

    As restantes defesas do service não são afetadas por este cenário e
    continuam ativas: identificadores, metadados (o DTO declara o idioma do
    **documento**, que não mudou), checksums e coerência com ``extracted_text``.
    """
    _, headers, _ = setup_institution_with_admin(client)
    document, version = create_searchable_document(client, headers, CONTENT)
    document_id = uuid.UUID(document["id"])
    version_id = uuid.UUID(version["id"])

    with test_session_factory() as db:
        institution_id = db.get(Document, document_id).institution_id  # type: ignore[union-attr]
        _force_chunk_language(db, version_id=version_id, language="en")
        source = _source_dto(db, document_id=document_id, version_id=version_id)

        # Com a política real, C8 falha e a revalidação recusa.
        with pytest.raises(ConflictError):
            revalidate_and_lock_sources(
                db,
                institution_id=institution_id,
                cited_sources=[source],
                language="pt",
                reference_date=_reference_date(),
                official_only=True,
            )
        db.rollback()

        forced = _ForcedVerdict(eligible=True)
        monkeypatch.setattr(
            message_source_service, "CitationPersistenceEligibility", forced
        )
        snapshots = revalidate_and_lock_sources(
            db,
            institution_id=institution_id,
            cited_sources=[source],
            language="pt",
            reference_date=_reference_date(),
            official_only=True,
        )
        db.rollback()

    assert forced.calls == 1
    assert len(snapshots) == 1
    assert snapshots[0].document_version_id == version_id


def test_snapshot_integrity_stays_in_the_service(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """O que não é admissibilidade documental não migrou para a política.

    Com o veredicto forçado a positivo, um checksum que não corresponde ao
    conteúdo continua a produzir conflito — porque essa verificação é do
    service, e a política nem sequer conhece ``content_sha256``.
    """
    _, headers, _ = setup_institution_with_admin(client)
    document, version = create_searchable_document(client, headers, CONTENT)
    document_id = uuid.UUID(document["id"])

    forced = _ForcedVerdict(eligible=True)
    monkeypatch.setattr(
        message_source_service, "CitationPersistenceEligibility", forced
    )

    with test_session_factory() as db:
        institution_id = db.get(Document, document_id).institution_id  # type: ignore[union-attr]
        source = _source_dto(
            db, document_id=document_id, version_id=uuid.UUID(version["id"])
        )
        source.set_internal_content_sha256(
            hashlib.sha256(b"conteudo que nunca foi citado").hexdigest()
        )
        with pytest.raises(ConflictError):
            revalidate_and_lock_sources(
                db,
                institution_id=institution_id,
                cited_sources=[source],
                language="pt",
                reference_date=_reference_date(),
                official_only=True,
            )
        db.rollback()


# --- O que nunca reavalia política --------------------------------------------


def test_persisted_sources_are_read_back_without_any_policy(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Depois de persistido, um ``MessageSource`` é histórico.

    A leitura devolve o snapshot tal como foi gravado, sem perguntar a nenhuma
    política se a linha continuaria admissível hoje.
    """
    _, headers, _ = setup_institution_with_admin(client)
    conversation = create_conversation(client, headers)
    document, _version = create_searchable_document(client, headers, CONTENT)
    document_id = uuid.UUID(document["id"])

    monkeypatch.setitem(
        app.dependency_overrides,
        get_answer_generator,
        lambda: RecordingAnswerGenerator(),
    )
    response = ask_in_conversation(client, headers, conversation["id"], "erasmus campus")
    assert response.status_code == 201, response.text
    assistant = response.json()["assistant_message"]
    assert assistant["sources"]

    spy = _PolicySpy(CitationPersistenceEligibility)
    monkeypatch.setattr(
        message_source_service, "CitationPersistenceEligibility", spy
    )

    with test_session_factory() as db:
        institution_id = db.get(Document, document_id).institution_id  # type: ignore[union-attr]
        stored = message_source_service.list_message_sources(
            db,
            uuid.UUID(assistant["id"]),
            institution_id=institution_id,
        )

    assert spy.calls == []
    assert [str(row.document_version_id) for row in stored] == [
        source["document_version_id"] for source in assistant["sources"]
    ]
    # A ordem persistida é a das citações, não a dos UUIDs usados no locking.
    assert [row.citation_index for row in stored] == list(range(len(stored)))


def test_creating_the_associations_does_not_evaluate_the_policy_again(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A admissibilidade é avaliada uma vez, na revalidação.

    ``create_message_sources`` recebe snapshots já revalidados; voltar a
    avaliar seria uma segunda oportunidade de recusar uma resposta já gerada.
    """
    institution, headers, _ = setup_institution_with_admin(client)
    conversation = create_conversation(client, headers)
    document, version = create_searchable_document(client, headers, CONTENT)
    document_id = uuid.UUID(document["id"])
    institution_id = uuid.UUID(institution["id"])

    with test_session_factory() as db:
        source = _source_dto(
            db, document_id=document_id, version_id=uuid.UUID(version["id"])
        )
        snapshots = revalidate_and_lock_sources(
            db,
            institution_id=institution_id,
            cited_sources=[source],
            language="pt",
            reference_date=_reference_date(),
            official_only=True,
        )

        assistant_message = Message(
            conversation_id=uuid.UUID(conversation["id"]),
            institution_id=institution_id,
            user_id=None,
            role="assistant",
            content="Resposta fundamentada.",
            language="pt",
        )
        db.add(assistant_message)
        db.flush()

        spy = _PolicySpy(CitationPersistenceEligibility)
        monkeypatch.setattr(
            message_source_service, "CitationPersistenceEligibility", spy
        )
        entities = message_source_service.create_message_sources(
            db,
            assistant_message=assistant_message,
            snapshots=snapshots,
        )
        db.rollback()

    assert spy.calls == []
    assert [entity.citation_index for entity in entities] == [0]
    assert entities[0].document_version_id == uuid.UUID(version["id"])
