"""Momento 6 — caracterização da elegibilidade documental (Fase 0 da issue #24).

Fixa o comportamento atual das condições C1–C12 da issue #24 **segundo a
semântica real de cada condição**. Nem todas são condições de linha isoláveis:
C5 é uma condição sobre o conjunto de versões do documento, C12 é a ausência de
linhas, e C1–C3 são sustentadas por foreign keys compostas do PostgreSQL. Onde
uma condição é estruturalmente garantida pela base, o teste demonstra a
constraint e o comportamento observável, em vez de fabricar um estado
impossível só para marcar uma caixa.

**Não** se implementa aqui nada da issue #24: nem ``RetrievalEligibility``, nem
``CitationPersistenceEligibility``, nem ``DiagnosticEligibility``, nem
``app.documents.retrievability``. Caracteriza-se apenas o comportamento que
essas peças terão de preservar.

Cobertura já existente e deliberadamente **não** duplicada (registada na matriz
do relatório do Momento 6):

- C1–C3, forma estrutural — os testes
  ``test_cross_institution_chunk_is_rejected_by_postgres`` e
  ``test_chunk_with_wrong_document_is_rejected_by_postgres`` de
  ``test_document_chunks.py``;
  ``test_document_integrity.py::test_version_rejects_document_from_another_institution``;
- C1–C3, forma observável — o teste
  ``test_institution_isolation_applies_to_regular_user_and_admin`` de
  ``test_retrieval.py``;
- C4 — ``test_retrieval.py::test_nonprocessed_latest_version_does_not_hide_previous_processed``;
- C5 — ``test_retrieval.py::test_latest_processed_version_replaces_older_in_search``
  e ``::test_historical_chunks_remain_stored_but_are_not_searched``;
- C6, C9, C10 — ``test_retrieval.py::test_inactive_future_and_expired_documents_are_excluded``;
- C7 — ``test_retrieval.py::test_portuguese_and_english_searches_work``;
- C11 — ``test_retrieval.py::test_official_only_defaults_true_and_false_allows_both``;
- C12 — ``test_retrieval.py::test_document_without_processed_version_is_not_searched``.

As lacunas que este ficheiro fecha são **C8** (idioma do chunk, que nenhum teste
isolava de C7) e a **ausência de C5 na persistência de citações** (D1 /
Decisão 7), além da divergência **D2** no diagnóstico.

Nota sobre D2: o teste que a caracterizava foi atualizado na Fase 4 da issue
#24, que a resolveu ao fazer o diagnóstico delegar em ``RetrievalEligibility``.
O cenário permanece; passou a provar a coincidência entre diagnóstico e
política, em vez da divergência. As restantes caracterizações deste ficheiro
descrevem comportamento que se mantém.
"""

import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session, sessionmaker

from app.answering.base import AnsweringContext
from app.answering.dependencies import get_answer_generator
from app.core.exceptions import ConflictError
from app.diagnostics.document_pipeline import (
    evaluate_eligibility,
    load_version_chunks,
    select_by_document_id,
)
from app.main import app
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.message_source import MessageSource
from app.schemas.answering import AnswerSourceRead
from app.services import message_source_service
from tests.moment06_support import (
    RecordingAnswerGenerator,
    ask_in_conversation,
    create_conversation,
    create_searchable_document,
    search,
    setup_institution_with_admin,
    upload_version,
)

# Nomes das condições que o diagnóstico expõe. Reproduzidos aqui a partir do
# código real (app/diagnostics/document_pipeline.py) para que uma alteração ao
# relatório tenha de passar por este teste.
#
# ``chunk_language_compatible`` entrou na Fase 4 da issue #24, quando o
# diagnóstico passou a delegar em ``RetrievalEligibility``: é a condição C8,
# cuja ausência era a divergência D2 caracterizada neste ficheiro. As restantes
# mantêm o nome histórico — a política adotou-os deliberadamente na Fase 1.
DIAGNOSTIC_CONDITION_NAMES = (
    "version_processed",
    "version_is_highest_processed",
    "document_active",
    "language_compatible",
    "chunk_language_compatible",
    "valid_from_compatible",
    "valid_until_compatible",
    "official_source_compatible",
)

# Termo cuja forma lexical é idêntica nas configurações FTS 'portuguese' e
# 'english': sem isto, um chunk com idioma divergente deixaria de ser
# encontrado por causa do *stemming* e o teste de C8 passaria por engano.
INVARIANT_TERM = "erasmus"
DIVERGENT_CONTENT = "erasmus campus alfa provedor institucional"


def _first_chunk(db: Session, version_id: uuid.UUID) -> DocumentChunk:
    chunk = db.scalar(
        select(DocumentChunk)
        .where(DocumentChunk.document_version_id == version_id)
        .order_by(DocumentChunk.chunk_index)
        .limit(1)
    )
    assert chunk is not None
    return chunk


def _force_chunk_language(
    db: Session, *, version_id: uuid.UUID, language: str
) -> DocumentChunk:
    """Coloca o idioma do chunk em divergência com o do documento.

    A invariante que hoje mascara D2 é mantida pelos services (o chunk herda o
    idioma do documento na segmentação, ``update_document`` recusa alterar o
    idioma de um documento com versões, e ``rebuild_document_chunks`` volta a
    derivá-lo). Este helper contorna deliberadamente **apenas** essa operação
    normal, escrevendo diretamente na base — é a única forma de observar o
    código atual perante uma linha que viole a invariante, como a Decisão 5 da
    issue #24 prevê. Nenhuma constraint é violada: ``language`` é uma coluna
    livre, e o ``search_vector`` é recalculado pelo PostgreSQL.
    """
    chunk = _first_chunk(db, version_id)
    chunk.language = language
    db.commit()
    db.refresh(chunk)
    return chunk


def _search_vector_still_matches(db: Session, chunk_id: uuid.UUID, term: str) -> bool:
    """Confirma que o índice FTS continua a casar o termo na config portuguesa.

    Sem esta verificação, um resultado vazio poderia dever-se ao *stemming* e
    não a C8 — o teste passaria pela razão errada.
    """
    return bool(
        db.scalar(
            text(
                "SELECT search_vector @@ websearch_to_tsquery('portuguese', :term) "
                "FROM document_chunks WHERE id = :chunk_id"
            ),
            {"term": term, "chunk_id": chunk_id},
        )
    )


def _source_dto(
    db: Session,
    *,
    document_id: uuid.UUID,
    version_id: uuid.UUID,
    language: str | None = None,
) -> AnswerSourceRead:
    """DTO da fonte citada, construído como ``answering_service`` o constrói."""
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
        language=language if language is not None else document.language,
        valid_from=document.valid_from,
        valid_until=document.valid_until,
    )
    source.set_internal_content_sha256(chunk.content_sha256)
    return source


# --- C8: idioma do chunk, isolado de C7 -----------------------------------------


def test_c8_chunk_language_divergent_from_document_is_excluded_from_retrieval(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> None:
    """C8 exclui o chunk mesmo quando C7 (idioma do documento) é satisfeita.

    O documento continua em ``pt`` e a pergunta é feita em ``pt``: a única
    condição violada é a do idioma do **chunk**.
    """
    _, headers, _ = setup_institution_with_admin(client)
    _, version = create_searchable_document(client, headers, DIVERGENT_CONTENT)

    before = search(client, headers, INVARIANT_TERM)
    assert before.status_code == 200
    assert len(before.json()["items"]) == 1

    with test_session_factory() as db:
        chunk = _force_chunk_language(
            db, version_id=uuid.UUID(version["id"]), language="en"
        )
        document = db.get(Document, chunk.document_id)
        assert document is not None
        # C7 continua satisfeita; só C8 passa a falhar.
        assert document.language == "pt"
        assert chunk.language == "en"
        # E o índice FTS continua a casar o termo sob a configuração
        # portuguesa: a exclusão que se segue é de política, não de stemming.
        assert _search_vector_still_matches(db, chunk.id, INVARIANT_TERM)

    after = search(client, headers, INVARIANT_TERM)
    assert after.status_code == 200
    assert after.json()["items"] == []


def test_c8_chunk_language_divergent_is_rejected_by_citation_revalidation(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> None:
    """A revalidação de fontes citadas também avalia C8, ao contrário do diagnóstico.

    O DTO declara o idioma do **documento** (``pt``), pelo que a comparação de
    metadados continua coerente: a única condição que falha é o idioma do
    chunk.
    """
    _, headers, _ = setup_institution_with_admin(client)
    document, version = create_searchable_document(client, headers, DIVERGENT_CONTENT)
    document_id = uuid.UUID(document["id"])
    version_id = uuid.UUID(version["id"])

    with test_session_factory() as db:
        institution_id = db.get(Document, document_id).institution_id  # type: ignore[union-attr]
        source = _source_dto(db, document_id=document_id, version_id=version_id)
        # Antes da divergência, a revalidação aceita a mesma fonte.
        accepted = message_source_service.revalidate_and_lock_sources(
            db,
            institution_id=institution_id,
            cited_sources=[source],
            language="pt",
            reference_date=datetime.now(UTC).date(),
            official_only=True,
        )
        assert len(accepted) == 1
        db.rollback()

        _force_chunk_language(db, version_id=version_id, language="en")
        source_after = _source_dto(
            db, document_id=document_id, version_id=version_id, language="pt"
        )
        with pytest.raises(ConflictError):
            message_source_service.revalidate_and_lock_sources(
                db,
                institution_id=institution_id,
                cited_sources=[source_after],
                language="pt",
                reference_date=datetime.now(UTC).date(),
                official_only=True,
            )


def test_d2_diagnostic_now_evaluates_chunk_language_like_retrieval(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> None:
    """D2 — divergência **resolvida** na Fase 4 da issue #24.

    O Momento 6 caracterizou aqui o comportamento histórico: perante a mesma
    linha que o retrieval e a revalidação de fontes recusavam, o diagnóstico
    declarava a versão elegível, porque a sua lista de condições nomeadas não
    incluía nenhuma sobre o idioma do chunk. Esse comportamento foi registado
    como divergência conhecida, nunca como requisito — e a Fase 4 da issue #24
    é exatamente a fase que o corrige, ao fazer o diagnóstico delegar em
    ``RetrievalEligibility`` em vez de manter uma lista própria.

    O cenário mantém-se intacto; o que muda é a expectativa. O teste passa a
    provar a tese da Fase 4: perante a mesma linha, o diagnóstico e a política
    dizem agora o mesmo, e C8 aparece com nome próprio no relatório.
    """
    _, headers, _ = setup_institution_with_admin(client)
    document, version = create_searchable_document(client, headers, DIVERGENT_CONTENT)
    document_id = uuid.UUID(document["id"])
    version_id = uuid.UUID(version["id"])

    with test_session_factory() as db:
        institution_id = db.get(Document, document_id).institution_id  # type: ignore[union-attr]
        _force_chunk_language(db, version_id=version_id, language="en")

        selection = select_by_document_id(
            db, institution_id=institution_id, document_id=document_id
        )
        effective = selection.effective_retrieval_version
        assert effective is not None
        eligibility = evaluate_eligibility(
            selection,
            effective,
            question_language="pt",
            reference_date=datetime.now(UTC).date(),
            official_only=True,
            chunks=load_version_chunks(db, effective),
        )

    names = tuple(condition.name for condition in eligibility.conditions)
    assert names == DIAGNOSTIC_CONDITION_NAMES
    # C8 passou a ter nome próprio no relatório, e é a única que falha: o
    # documento continua em 'pt', logo C7 mantém-se satisfeita.
    assert "chunk_language_compatible" in names
    failed = tuple(
        condition.name for condition in eligibility.conditions if not condition.satisfied
    )
    assert failed == ("chunk_language_compatible",)
    # E o veredicto deixou de divergir do retrieval.
    assert eligibility.eligible is False
    # O relatório declara qual política produziu este veredicto.
    assert eligibility.policy == "RetrievalEligibility"

    after = search(client, headers, INVARIANT_TERM)
    assert after.json()["items"] == []


# --- C12 no diagnóstico: ausência de linhas, não condição de linha ---------------


def test_c12_absence_of_processed_version_is_reported_as_its_own_condition(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> None:
    """C12 não é uma condição de linha: manifesta-se como conjunto vazio.

    No retrieval isso já é observável como ausência de resultados
    (``test_retrieval.py::test_document_without_processed_version_is_not_searched``).
    No diagnóstico tem forma própria — uma condição única, ``processed_version_exists``,
    e nenhuma das outras é sequer avaliada.
    """
    _, headers, _ = setup_institution_with_admin(client)
    document = create_searchable_document(client, headers, "campus provedor alfa")[0]
    document_id = uuid.UUID(document["id"])

    with test_session_factory() as db:
        institution_id = db.get(Document, document_id).institution_id  # type: ignore[union-attr]
        selection = select_by_document_id(
            db, institution_id=institution_id, document_id=document_id
        )
        # ``version=None`` é exatamente o que a camada de seleção entrega
        # quando não existe versão processed.
        eligibility = evaluate_eligibility(
            selection,
            None,
            question_language="pt",
            reference_date=datetime.now(UTC).date(),
            official_only=True,
            chunks=(),
        )

    assert [condition.name for condition in eligibility.conditions] == [
        "processed_version_exists"
    ]
    assert eligibility.eligible is False
    assert eligibility.version_id is None
    assert eligibility.version_number is None
    assert eligibility.processing_status is None


# --- D1 / Decisão 7: C5 não pertence à persistência de citações ------------------


def test_c5_is_absent_from_citation_revalidation_which_accepts_a_superseded_version(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> None:
    """Fase 0 da issue #24 — a revalidação aceita uma versão já superada.

    Esta é a diferença D1, e é **intencional** (Decisão 7): a persistência da
    citação pergunta "o que foi usado então", não "o que é recuperável agora".
    O teste fixa que C5 não é aplicada aqui — se alguém fundir as duas
    políticas, este teste falha.
    """
    _, headers, _ = setup_institution_with_admin(client)
    document, version_1 = create_searchable_document(
        client, headers, "campus provedor alfa versao antiga"
    )
    document_id = uuid.UUID(document["id"])
    version_1_id = uuid.UUID(version_1["id"])

    with test_session_factory() as db:
        institution_id = db.get(Document, document_id).institution_id  # type: ignore[union-attr]
        source = _source_dto(db, document_id=document_id, version_id=version_1_id)

    version_2 = upload_version(
        client, headers, document["id"], "campus provedor alfa versao nova"
    )
    assert version_2["version_number"] == 2

    # A versão 1 deixou de ser recuperável: C5 aplica-se ao retrieval.
    superseded = search(client, headers, "antiga")
    assert superseded.json()["items"] == []
    current = search(client, headers, "nova")
    assert current.json()["items"][0]["document_version_id"] == version_2["id"]

    # Mas a persistência da citação sobre a versão 1 continua a ser aceite.
    with test_session_factory() as db:
        snapshots = message_source_service.revalidate_and_lock_sources(
            db,
            institution_id=institution_id,
            cited_sources=[source],
            language="pt",
            reference_date=datetime.now(UTC).date(),
            official_only=True,
        )
        assert len(snapshots) == 1
        assert snapshots[0].document_version_id == version_1_id
        assert snapshots[0].document_id == document_id
        db.rollback()


def test_phase_zero_issue_24_preserves_historical_provenance_when_n_plus_one_is_processed(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fase 0 da issue #24 — proveniência histórica N → N+1.

    A resposta é gerada a partir da versão N. Enquanto o gerador está em
    execução, o callback já existente na suite cria e processa N+1. O turno
    tem de persistir a fonte realmente usada (N), embora uma pesquisa nova já
    só possa devolver N+1. Depois de persistida, a fonte histórica continua
    legível sem reavaliar a elegibilidade atual.
    """
    institution, headers, _ = setup_institution_with_admin(client)
    conversation = create_conversation(client, headers)
    document, version_n = create_searchable_document(
        client,
        headers,
        "erasmus campus proveniencia historica versao inicial",
        title="Regulamento de mobilidade",
    )

    before = search(client, headers, "erasmus campus")
    assert before.status_code == 200, before.text
    assert {item["document_version_id"] for item in before.json()["items"]} == {
        version_n["id"]
    }

    created_versions: list[dict] = []

    def process_n_plus_one(context: AnsweringContext) -> None:
        assert {str(item.evidence.document_version_id) for item in context.evidence} == {
            version_n["id"]
        }
        created_versions.append(
            upload_version(
                client,
                headers,
                document["id"],
                "erasmus campus proveniencia historica versao atualizada",
            )
        )

    generator = RecordingAnswerGenerator(callback=process_n_plus_one)
    monkeypatch.setitem(
        app.dependency_overrides,
        get_answer_generator,
        lambda: generator,
    )

    response = ask_in_conversation(
        client,
        headers,
        conversation["id"],
        "erasmus campus",
    )
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "answered"
    assert len(generator.calls) == 1
    assert len(created_versions) == 1
    version_n_plus_one = created_versions[0]
    assert version_n_plus_one["version_number"] == version_n["version_number"] + 1
    assert version_n_plus_one["processing_status"] == "processed"

    current = search(client, headers, "erasmus campus")
    assert current.status_code == 200, current.text
    current_version_ids = {
        item["document_version_id"] for item in current.json()["items"]
    }
    assert current_version_ids == {version_n_plus_one["id"]}
    assert version_n["id"] not in current_version_ids

    assistant = response.json()["assistant_message"]
    assert [source["document_version_id"] for source in assistant["sources"]] == [
        version_n["id"]
    ]

    with test_session_factory() as db:
        persisted = db.scalar(
            select(MessageSource).where(
                MessageSource.message_id == uuid.UUID(assistant["id"])
            )
        )
        assert persisted is not None
        assert persisted.institution_id == uuid.UUID(institution["id"])
        assert persisted.document_id == uuid.UUID(document["id"])
        assert persisted.document_version_id == uuid.UUID(version_n["id"])
        assert db.get(DocumentChunk, persisted.chunk_id) is not None

    history = client.get(
        f"/api/v1/conversations/{conversation['id']}/messages",
        headers=headers,
    )
    assert history.status_code == 200, history.text
    historical_assistant = next(
        item for item in history.json()["items"] if item["id"] == assistant["id"]
    )
    assert historical_assistant["sources"] == assistant["sources"]
    assert historical_assistant["sources"][0]["document_version_id"] == version_n["id"]
