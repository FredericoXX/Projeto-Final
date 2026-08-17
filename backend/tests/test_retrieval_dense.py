"""Retrieval denso experimental sobre pgvector (D4.8).

O modelo de embeddings é um duplo determinístico: nenhum teste faz chamadas de
rede nem exige ``OPENAI_API_KEY``. Os vetores vivem num "espaço de conceitos"
minúsculo — cada eixo é um conceito — para que a proximidade seja escolhida pelo
teste em vez de esperada de um modelo real.

O que se fixa aqui divide-se em quatro grupos:

- **admissibilidade**, que tem de ser exatamente a mesma do retriever lexical:
  isolamento institucional, idioma, documento ativo, validade, ``official_only``
  e versão ``processed`` mais recente. Similaridade vetorial nunca a contorna;
- **as propriedades declaradas da estratégia**: a semântica própria do score,
  a ausência de limiar, o desempate determinístico, e o comportamento — assumido
  e documentado — de devolver ``top_k`` mesmo quando nada é próximo;
- **a identidade do índice**: fornecedor, modelo e ``configuration_version``
  filtrados em conjunto, e um índice misto ou obsoleto recusado antes de
  qualquer medição;
- **a indexação**, que tem de concordar com a recuperação sobre o que é um
  índice íntegro.

Os dois últimos grupos precisam de linhas reais no PostgreSQL, e é por isso que
as guardas do runner são exercitadas aqui e não em
``test_evaluation_dense_baseline.py``, que se mantém sem base de dados de
propósito.
"""

import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.documents.retrievability import RetrievabilityContext, RetrievalEligibility
from app.embeddings.base import EmbeddingIdentity
from app.models.chunk_embedding import EMBEDDING_DIMENSION, ChunkEmbedding
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.document_version import DocumentVersion
from app.retrieval.base import RetrievalContext, ScoreKind
from app.retrieval.dense import (
    DENSE_PIPELINE_VERSION,
    DenseRetrievalTrace,
    PostgresDenseRetriever,
)
from app.retrieval.dependencies import get_retriever
from app.retrieval.lexical import PostgresLexicalRetriever
from scripts.embed_pilot_corpus import content_digest, index_corpus
from scripts.evaluate_dense_baseline import (
    EXIT_INDEX_INCOMPLETE,
    ExperimentError,
    verify_index_identity,
)

BOOTSTRAP_HEADERS = {"X-Bootstrap-Token": settings.bootstrap_token or ""}
_ADMIN_PASSWORD = "supersecret123"

REFERENCE_DATE = date(2026, 8, 16)
YESTERDAY = REFERENCE_DATE - timedelta(days=1)
TOMORROW = REFERENCE_DATE + timedelta(days=1)

FAKE_PROVIDER = "fake"
FAKE_MODEL = "fake-embedding-1"
FAKE_CONFIGURATION = "fake_v1"


# --- Modelo de embeddings determinístico -----------------------------------------


def concept(*weights: float) -> list[float]:
    """Vetor com os pesos dados nos primeiros eixos e zero nos restantes.

    Nunca totalmente nulo: a distância do cosseno a um vetor nulo é indefinida,
    e um teste que a produzisse mediria uma indeterminação em vez de uma
    ordenação.
    """
    if not any(weights):
        msg = "a null vector has no direction and no cosine distance"
        raise ValueError(msg)
    vector = [0.0] * EMBEDDING_DIMENSION
    for index, weight in enumerate(weights):
        vector[index] = weight
    return vector


@dataclass
class FakeEmbeddingModel:
    """Devolve o vetor associado ao texto, ou um eixo neutro se desconhecido."""

    vectors: dict[str, list[float]]
    default: list[float]
    calls: list[list[str]]

    def __init__(
        self, vectors: dict[str, list[float]], default: list[float] | None = None
    ) -> None:
        self.vectors = vectors
        self.default = default if default is not None else concept(0.0, 0.0, 1.0)
        self.calls = []

    @property
    def identity(self) -> EmbeddingIdentity:
        return EmbeddingIdentity(
            provider=FAKE_PROVIDER,
            model=FAKE_MODEL,
            dimension=EMBEDDING_DIMENSION,
            normalization="none",
            similarity_metric="cosine",
            configuration_version=FAKE_CONFIGURATION,
        )

    def embed(self, texts):  # type: ignore[no-untyped-def]
        self.calls.append(list(texts))
        return tuple(tuple(self.vectors.get(text, self.default)) for text in texts)


# --- Construção do corpus ---------------------------------------------------------


@dataclass(frozen=True)
class _Tenant:
    institution_id: uuid.UUID
    user_id: uuid.UUID


def _create_tenant(client: TestClient, *, code_prefix: str) -> _Tenant:
    institution = client.post(
        "/api/v1/institutions",
        json={
            "name": f"Instituição {code_prefix}",
            "code": f"{code_prefix}-{uuid.uuid4().hex[:8].upper()}",
            "default_language": "pt",
            "supported_languages": ["pt", "en"],
        },
        headers=BOOTSTRAP_HEADERS,
    )
    assert institution.status_code == 201, institution.text
    admin = client.post(
        "/api/v1/auth/register-initial-admin",
        json={
            "institution_id": institution.json()["id"],
            "full_name": "Admin Denso",
            "email": f"admin-{uuid.uuid4().hex[:8]}@example.com",
            "password": _ADMIN_PASSWORD,
        },
        headers=BOOTSTRAP_HEADERS,
    )
    assert admin.status_code == 201, admin.text
    return _Tenant(
        institution_id=uuid.UUID(institution.json()["id"]),
        user_id=uuid.UUID(admin.json()["id"]),
    )


def _add_document(
    db: Session,
    tenant: _Tenant,
    *,
    title: str,
    language: str = "pt",
    is_active: bool = True,
    official_source: bool = True,
    valid_from: date | None = None,
    valid_until: date | None = None,
) -> Document:
    document = Document(
        institution_id=tenant.institution_id,
        created_by_user_id=tenant.user_id,
        title=title,
        language=language,
        source_url=None,
        official_source=official_source,
        is_active=is_active,
        valid_from=valid_from,
        valid_until=valid_until,
    )
    db.add(document)
    db.flush()
    return document


def _add_version(
    db: Session,
    tenant: _Tenant,
    document: Document,
    *,
    version_number: int = 1,
    processing_status: str = "processed",
) -> DocumentVersion:
    marker = uuid.uuid4().hex
    version = DocumentVersion(
        document_id=document.id,
        institution_id=tenant.institution_id,
        uploaded_by_user_id=tenant.user_id,
        version_number=version_number,
        original_filename=f"{marker}.txt",
        mime_type="text/plain",
        size_bytes=64,
        checksum_sha256=hashlib.sha256(marker.encode()).hexdigest(),
        storage_path=f"{tenant.institution_id}/{marker}.txt",
        processing_status=processing_status,
        extracted_text="conteudo do corpus denso",
        processed_at=datetime.now(UTC) if processing_status == "processed" else None,
    )
    db.add(version)
    db.flush()
    return version


def _add_chunk(
    db: Session,
    tenant: _Tenant,
    document: Document,
    version: DocumentVersion,
    *,
    content: str,
    chunk_index: int = 0,
    language: str | None = None,
    vector: list[float] | None = None,
) -> DocumentChunk:
    chunk = DocumentChunk(
        institution_id=tenant.institution_id,
        document_id=document.id,
        document_version_id=version.id,
        chunk_index=chunk_index,
        content=content,
        normalized_content=content,
        content_sha256=hashlib.sha256(content.encode()).hexdigest(),
        start_char=0,
        end_char=len(content),
        language=language if language is not None else document.language,
    )
    db.add(chunk)
    db.flush()
    if vector is not None:
        db.add(
            ChunkEmbedding(
                chunk_id=chunk.id,
                provider=FAKE_PROVIDER,
                model=FAKE_MODEL,
                configuration_version=FAKE_CONFIGURATION,
                embedded_content_sha256=chunk.content_sha256,
                embedding=vector,
            )
        )
        db.flush()
    return chunk


def _search(
    db: Session,
    tenant: _Tenant,
    *,
    model: FakeEmbeddingModel,
    query: str = "pergunta",
    top_k: int = 5,
    official_only: bool = True,
    language: str = "pt",
):  # type: ignore[no-untyped-def]
    retriever = PostgresDenseRetriever(model)
    context = RetrievalContext(
        institution_id=tenant.institution_id,
        language=language,
        reference_date=REFERENCE_DATE,
    )
    return retriever.search(db, query, context, top_k, official_only)


def _anchors(result) -> list[tuple[str, int]]:  # type: ignore[no-untyped-def]
    return [(evidence.document_title, evidence.chunk_index) for evidence in result.evidence]


@pytest.fixture
def db(test_session_factory: sessionmaker[Session]):  # type: ignore[no-untyped-def]
    session = test_session_factory()
    try:
        yield session
        session.commit()
    finally:
        session.close()


# --- Ordenação por proximidade ----------------------------------------------------


def test_the_nearest_chunk_comes_first(client: TestClient, db: Session) -> None:
    tenant = _create_tenant(client, code_prefix="DEN")
    document = _add_document(db, tenant, title="Regulamento")
    version = _add_version(db, tenant, document)
    _add_chunk(db, tenant, document, version, content="longe", chunk_index=0,
               vector=concept(0.0, 1.0))
    _add_chunk(db, tenant, document, version, content="perto", chunk_index=1,
               vector=concept(1.0, 0.0))
    db.commit()

    model = FakeEmbeddingModel({"pergunta": concept(1.0, 0.0)})
    result = _search(db, tenant, model=model)

    assert [evidence.chunk_index for evidence in result.evidence] == [1, 0]
    assert result.evidence[0].score > result.evidence[1].score
    # A pergunta é embebida uma vez, e é a pergunta original que chega ao modelo.
    assert model.calls == [["pergunta"]]


def test_ties_are_broken_deterministically_and_not_by_the_database(
    client: TestClient, db: Session
) -> None:
    """Sem desempate estável, duas execuções poderiam trocar as posições.

    Três segmentos exatamente à mesma distância: a ordem tem de vir do critério
    declarado — documento, depois ``chunk_index`` — e não da ordem física das
    linhas.
    """
    tenant = _create_tenant(client, code_prefix="TIE")
    document = _add_document(db, tenant, title="Regulamento")
    version = _add_version(db, tenant, document)
    for index in (2, 0, 1):
        _add_chunk(db, tenant, document, version, content=f"igual {index}",
                   chunk_index=index, vector=concept(1.0, 0.0))
    db.commit()

    model = FakeEmbeddingModel({"pergunta": concept(1.0, 0.0)})
    first = _search(db, tenant, model=model)
    second = _search(db, tenant, model=model)

    assert [evidence.chunk_index for evidence in first.evidence] == [0, 1, 2]
    assert _anchors(first) == _anchors(second)


def test_top_k_truncates_and_the_trace_says_what_survived(
    client: TestClient, db: Session
) -> None:
    tenant = _create_tenant(client, code_prefix="TOP")
    document = _add_document(db, tenant, title="Regulamento")
    version = _add_version(db, tenant, document)
    for index in range(6):
        _add_chunk(db, tenant, document, version, content=f"segmento {index}",
                   chunk_index=index, vector=concept(1.0, index / 10))
    db.commit()

    model = FakeEmbeddingModel({"pergunta": concept(1.0, 0.0)})
    result = _search(db, tenant, model=model, top_k=2)

    assert len(result.evidence) == 2
    trace = result.trace
    assert isinstance(trace, DenseRetrievalTrace)
    # O corte por top_k é apresentação; o trace continua a contar o que existia.
    assert trace.result_count_before_limit == 6
    assert trace.candidates_evaluated == 6


# --- Admissibilidade: a mesma política do lexical ---------------------------------


def test_a_chunk_from_another_institution_is_never_returned(
    client: TestClient, db: Session
) -> None:
    """O isolamento não depende do modelo: está no ``WHERE`` da consulta.

    O segmento da outra instituição é o **mais próximo** da pergunta. Se a
    similaridade pudesse contornar a admissibilidade, seria devolvido em
    primeiro lugar.
    """
    mine = _create_tenant(client, code_prefix="MIN")
    theirs = _create_tenant(client, code_prefix="OUT")

    my_document = _add_document(db, mine, title="Meu")
    my_version = _add_version(db, mine, my_document)
    _add_chunk(db, mine, my_document, my_version, content="meu", vector=concept(0.0, 1.0))

    their_document = _add_document(db, theirs, title="Alheio")
    their_version = _add_version(db, theirs, their_document)
    _add_chunk(db, theirs, their_document, their_version, content="alheio",
               vector=concept(1.0, 0.0))
    db.commit()

    model = FakeEmbeddingModel({"pergunta": concept(1.0, 0.0)})
    result = _search(db, mine, model=model)

    assert [evidence.document_title for evidence in result.evidence] == ["Meu"]


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"is_active": False}, "documento inativo"),
        ({"official_source": False}, "fonte não oficial"),
        ({"language": "en"}, "idioma diferente"),
        ({"valid_from": TOMORROW}, "ainda não vigente"),
        ({"valid_until": YESTERDAY}, "já expirado"),
    ],
)
def test_an_inadmissible_document_is_never_returned_however_close(
    client: TestClient, db: Session, kwargs: dict[str, object], reason: str
) -> None:
    tenant = _create_tenant(client, code_prefix="ADM")
    admissible = _add_document(db, tenant, title="Admissivel")
    admissible_version = _add_version(db, tenant, admissible)
    _add_chunk(db, tenant, admissible, admissible_version, content="admissivel",
               vector=concept(0.0, 1.0))

    excluded = _add_document(db, tenant, title="Excluido", **kwargs)  # type: ignore[arg-type]
    excluded_version = _add_version(db, tenant, excluded)
    _add_chunk(db, tenant, excluded, excluded_version, content="excluido",
               vector=concept(1.0, 0.0))
    db.commit()

    model = FakeEmbeddingModel({"pergunta": concept(1.0, 0.0)})
    result = _search(db, tenant, model=model)

    titles = [evidence.document_title for evidence in result.evidence]
    assert titles == ["Admissivel"], reason


def test_only_the_latest_processed_version_is_visible(
    client: TestClient, db: Session
) -> None:
    """C5, com a versão antiga deliberadamente mais próxima da pergunta."""
    tenant = _create_tenant(client, code_prefix="VER")
    document = _add_document(db, tenant, title="Regulamento")
    old = _add_version(db, tenant, document, version_number=1)
    new = _add_version(db, tenant, document, version_number=2)
    _add_chunk(db, tenant, document, old, content="antigo", chunk_index=0,
               vector=concept(1.0, 0.0))
    _add_chunk(db, tenant, document, new, content="novo", chunk_index=0,
               vector=concept(0.0, 1.0))
    db.commit()

    model = FakeEmbeddingModel({"pergunta": concept(1.0, 0.0)})
    result = _search(db, tenant, model=model)

    assert len(result.evidence) == 1
    assert result.evidence[0].document_version_id == new.id


def test_official_only_disabled_admits_the_unofficial_document(
    client: TestClient, db: Session
) -> None:
    """C11 é condicional ao contexto, e o retriever denso honra as duas formas."""
    tenant = _create_tenant(client, code_prefix="OFF")
    unofficial = _add_document(db, tenant, title="Nao oficial", official_source=False)
    version = _add_version(db, tenant, unofficial)
    _add_chunk(db, tenant, unofficial, version, content="texto", vector=concept(1.0, 0.0))
    db.commit()

    model = FakeEmbeddingModel({"pergunta": concept(1.0, 0.0)})

    assert _search(db, tenant, model=model, official_only=True).evidence == ()
    relaxed = _search(db, tenant, model=model, official_only=False)
    assert [evidence.document_title for evidence in relaxed.evidence] == ["Nao oficial"]


def test_the_dense_visible_set_is_exactly_the_retrieval_eligibility_set(
    client: TestClient, db: Session
) -> None:
    """A prova de que a política é reutilizada, e não reimplementada.

    O conjunto que o retriever consegue devolver — com ``top_k`` grande o
    suficiente para não truncar — tem de coincidir, chunk a chunk, com o que
    ``RetrievalEligibility.select_eligible_chunk_ids`` seleciona. Se alguma
    condição fosse traduzida de outra maneira aqui, os dois conjuntos
    divergiriam.
    """
    tenant = _create_tenant(client, code_prefix="POL")
    other = _create_tenant(client, code_prefix="ALI")

    admissible = _add_document(db, tenant, title="Admissivel")
    admissible_version = _add_version(db, tenant, admissible)
    for index in range(3):
        _add_chunk(db, tenant, admissible, admissible_version, content=f"ok {index}",
                   chunk_index=index, vector=concept(1.0, index / 10))

    inactive = _add_document(db, tenant, title="Inativo", is_active=False)
    inactive_version = _add_version(db, tenant, inactive)
    _add_chunk(db, tenant, inactive, inactive_version, content="inativo",
               vector=concept(1.0, 0.0))

    foreign = _add_document(db, other, title="Alheio")
    foreign_version = _add_version(db, other, foreign)
    _add_chunk(db, other, foreign, foreign_version, content="alheio",
               vector=concept(1.0, 0.0))
    db.commit()

    model = FakeEmbeddingModel({"pergunta": concept(1.0, 0.0)})
    result = _search(db, tenant, model=model, top_k=50)

    policy_ids = set(
        db.scalars(
            RetrievalEligibility.select_eligible_chunk_ids(
                RetrievabilityContext(
                    institution_id=tenant.institution_id,
                    language="pt",
                    reference_date=REFERENCE_DATE,
                    official_only=True,
                )
            )
        ).all()
    )
    assert {evidence.chunk_id for evidence in result.evidence} == policy_ids


# --- Cobertura do índice ----------------------------------------------------------


def test_an_admissible_chunk_without_a_vector_is_invisible_and_counted(
    client: TestClient, db: Session
) -> None:
    """Um segmento por embeber não é uma falha semântica — e o trace di-lo.

    Sem as duas contagens, a ausência de um segmento do resultado seria
    indistinguível de o modelo o ter considerado distante.
    """
    tenant = _create_tenant(client, code_prefix="COV")
    document = _add_document(db, tenant, title="Regulamento")
    version = _add_version(db, tenant, document)
    _add_chunk(db, tenant, document, version, content="com vetor", chunk_index=0,
               vector=concept(1.0, 0.0))
    _add_chunk(db, tenant, document, version, content="sem vetor", chunk_index=1)
    db.commit()

    model = FakeEmbeddingModel({"pergunta": concept(1.0, 0.0)})
    result = _search(db, tenant, model=model)

    assert [evidence.chunk_index for evidence in result.evidence] == [0]
    trace = result.trace
    assert isinstance(trace, DenseRetrievalTrace)
    assert trace.admissible_chunks == 2
    assert trace.embedded_chunks == 1


def test_vectors_of_another_model_are_not_used(client: TestClient, db: Session) -> None:
    """A chave é composta por desenho: dois modelos coexistem sem se misturarem."""
    tenant = _create_tenant(client, code_prefix="MOD")
    document = _add_document(db, tenant, title="Regulamento")
    version = _add_version(db, tenant, document)
    chunk = _add_chunk(db, tenant, document, version, content="texto",
                       vector=concept(1.0, 0.0))
    db.add(
        ChunkEmbedding(
            chunk_id=chunk.id,
            provider=FAKE_PROVIDER,
            model="outro-modelo",
            configuration_version="outro_v1",
            embedded_content_sha256=chunk.content_sha256,
            embedding=concept(0.0, 1.0),
        )
    )
    db.commit()

    model = FakeEmbeddingModel({"pergunta": concept(1.0, 0.0)})
    result = _search(db, tenant, model=model)

    trace = result.trace
    assert isinstance(trace, DenseRetrievalTrace)
    assert trace.embedding_model == FAKE_MODEL
    assert trace.embedded_chunks == 1
    assert len(result.evidence) == 1


def test_vectors_of_another_provider_are_not_used(
    client: TestClient, db: Session
) -> None:
    """O mesmo nome de modelo em dois fornecedores não é o mesmo modelo.

    Sem ``provider`` na chave e no filtro, estes dois vetores seriam
    indistinguíveis e a recuperação misturá-los-ia sem nada falhar.
    """
    tenant = _create_tenant(client, code_prefix="PRV")
    document = _add_document(db, tenant, title="Regulamento")
    version = _add_version(db, tenant, document)
    chunk = _add_chunk(db, tenant, document, version, content="texto",
                       vector=concept(0.0, 1.0))
    db.add(
        ChunkEmbedding(
            chunk_id=chunk.id,
            provider="outro-fornecedor",
            model=FAKE_MODEL,
            configuration_version=FAKE_CONFIGURATION,
            embedded_content_sha256=chunk.content_sha256,
            # Deliberadamente o mais próximo: se fosse usado, viria em primeiro.
            embedding=concept(1.0, 0.0),
        )
    )
    db.commit()

    model = FakeEmbeddingModel({"pergunta": concept(1.0, 0.0)})
    result = _search(db, tenant, model=model)

    assert len(result.evidence) == 1
    # O vetor usado é o da identidade declarada, o distante — não o do outro
    # fornecedor, que estaria colado à pergunta.
    assert result.evidence[0].score < 0.1
    trace = result.trace
    assert isinstance(trace, DenseRetrievalTrace)
    assert trace.embedding_provider == FAKE_PROVIDER


def test_a_vector_of_another_configuration_is_invisible_and_breaks_coverage(
    client: TestClient, db: Session
) -> None:
    """O caso da reindexação interrompida a meio.

    Um segmento com vetor da configuração **anterior** não é recuperável pela
    identidade declarada, e a cobertura tem de o revelar: sem isso, um índice
    meio-antigo passaria por íntegro e o artefacto sairia rotulado com a
    configuração nova.
    """
    tenant = _create_tenant(client, code_prefix="CFG")
    document = _add_document(db, tenant, title="Regulamento")
    version = _add_version(db, tenant, document)
    _add_chunk(db, tenant, document, version, content="atual", chunk_index=0,
               vector=concept(0.0, 1.0))
    old = _add_chunk(db, tenant, document, version, content="antigo", chunk_index=1)
    db.add(
        ChunkEmbedding(
            chunk_id=old.id,
            provider=FAKE_PROVIDER,
            model=FAKE_MODEL,
            configuration_version="fake_v0",
            embedded_content_sha256=old.content_sha256,
            embedding=concept(1.0, 0.0),
        )
    )
    db.commit()

    model = FakeEmbeddingModel({"pergunta": concept(1.0, 0.0)})
    result = _search(db, tenant, model=model)

    assert [evidence.chunk_index for evidence in result.evidence] == [0]
    trace = result.trace
    assert isinstance(trace, DenseRetrievalTrace)
    assert trace.admissible_chunks == 2
    assert trace.embedded_chunks == 1


def test_the_identity_predicate_requires_all_three_fields(
    client: TestClient, db: Session
) -> None:
    """``matches_identity`` é a definição única do filtro, e filtra as três.

    Testada diretamente para que um campo em falta apareça aqui, e não como um
    resultado estranho três camadas acima.
    """
    tenant = _create_tenant(client, code_prefix="IDF")
    document = _add_document(db, tenant, title="Regulamento")
    version = _add_version(db, tenant, document)
    chunk = _add_chunk(db, tenant, document, version, content="texto",
                       vector=concept(1.0, 0.0))
    for divergent in (
        {"provider": "outro"},
        {"model": "outro"},
        {"configuration_version": "outro"},
    ):
        db.add(
            ChunkEmbedding(
                chunk_id=chunk.id,
                provider=divergent.get("provider", FAKE_PROVIDER),
                model=divergent.get("model", "modelo-" + str(len(divergent))),
                configuration_version=divergent.get(
                    "configuration_version", FAKE_CONFIGURATION
                ),
                embedded_content_sha256=chunk.content_sha256,
                embedding=concept(0.0, 1.0),
            )
        )
    db.commit()

    identity = FakeEmbeddingModel({}).identity
    matching = db.scalars(
        select(ChunkEmbedding.chunk_id).where(
            ChunkEmbedding.matches_identity(identity)
        )
    ).all()

    assert list(matching) == [chunk.id]


# --- Integridade do índice: guardas do runner -------------------------------------
#
# Vivem aqui, e não em `test_evaluation_dense_baseline.py`, porque precisam de
# linhas reais no PostgreSQL — e o corpus que as constrói já existe neste
# ficheiro. Manter esse outro módulo sem base de dados é deliberado.


def _retrievability(tenant: _Tenant) -> RetrievabilityContext:
    return RetrievabilityContext(
        institution_id=tenant.institution_id,
        language="pt",
        reference_date=REFERENCE_DATE,
        official_only=True,
    )


def test_a_homogeneous_index_passes_the_identity_guard(
    client: TestClient, db: Session
) -> None:
    tenant = _create_tenant(client, code_prefix="HOM")
    document = _add_document(db, tenant, title="Regulamento")
    version = _add_version(db, tenant, document)
    for index in range(2):
        _add_chunk(db, tenant, document, version, content=f"texto {index}",
                   chunk_index=index, vector=concept(1.0, index / 10))
    db.commit()

    verify_index_identity(
        db,
        context=_retrievability(tenant),
        identity=FakeEmbeddingModel({}).identity,
    )


def test_an_index_with_another_configuration_is_refused_by_name(
    client: TestClient, db: Session
) -> None:
    """Diagnóstico, não deteção: a cobertura também apanharia este caso.

    Como a cobertura filtra pela identidade completa, um índice meio-antigo
    aparece-lhe como cobertura **parcial** — e diria «1 de 2 segmentos
    embebidos», que se lê como *falta indexar*. Esta guarda diz que os vetores
    existem e são de outra configuração, nomeia-a, e corre antes de qualquer
    pesquisa. É o valor que acrescenta aqui; o caso que só ela apanha é o do
    conteúdo obsoleto, abaixo.
    """
    tenant = _create_tenant(client, code_prefix="MIX")
    document = _add_document(db, tenant, title="Regulamento")
    version = _add_version(db, tenant, document)
    _add_chunk(db, tenant, document, version, content="novo", chunk_index=0,
               vector=concept(1.0, 0.0))
    old = _add_chunk(db, tenant, document, version, content="antigo", chunk_index=1)
    db.add(
        ChunkEmbedding(
            chunk_id=old.id,
            provider=FAKE_PROVIDER,
            model=FAKE_MODEL,
            configuration_version="fake_v0",
            embedded_content_sha256=old.content_sha256,
            embedding=concept(0.0, 1.0),
        )
    )
    db.commit()

    with pytest.raises(ExperimentError) as info:
        verify_index_identity(
            db,
            context=_retrievability(tenant),
            identity=FakeEmbeddingModel({}).identity,
        )

    assert info.value.exit_code == EXIT_INDEX_INCOMPLETE
    assert "fake_v0" in str(info.value)


def test_a_vector_of_content_the_chunk_no_longer_has_is_refused(
    client: TestClient, db: Session
) -> None:
    """O vetor descreve texto que já não existe: é obsoleto, não é evidência.

    A cobertura **não** apanha este caso: o vetor satisfaz a identidade e conta
    como coberto. É o que torna esta guarda não-redundante.
    """
    tenant = _create_tenant(client, code_prefix="STL")
    document = _add_document(db, tenant, title="Regulamento")
    version = _add_version(db, tenant, document)
    chunk = _add_chunk(db, tenant, document, version, content="texto",
                       vector=concept(1.0, 0.0))
    db.execute(
        update(ChunkEmbedding)
        .where(ChunkEmbedding.chunk_id == chunk.id)
        .values(embedded_content_sha256="0" * 64)
    )
    db.commit()

    with pytest.raises(ExperimentError) as info:
        verify_index_identity(
            db,
            context=_retrievability(tenant),
            identity=FakeEmbeddingModel({}).identity,
        )

    assert info.value.exit_code == EXIT_INDEX_INCOMPLETE
    assert "no longer has" in str(info.value)


def test_content_that_changed_without_its_hash_being_updated_is_refused(
    client: TestClient, db: Session
) -> None:
    """O caso que dois valores persistidos não conseguem detetar.

    O ``content`` muda e o ``content_sha256`` do chunk fica para trás. Os dois
    valores obsoletos — o do chunk e o do vetor — continuam **iguais entre si**,
    e uma guarda que os comparasse passaria sobre um vetor que descreve texto
    que já não existe. Só recalcular o SHA a partir do ``content`` atual, como a
    indexação faz ao enviá-lo, apanha isto.
    """
    tenant = _create_tenant(client, code_prefix="DRF")
    document = _add_document(db, tenant, title="Regulamento")
    version = _add_version(db, tenant, document)
    chunk = _add_chunk(db, tenant, document, version, content="texto original",
                       vector=concept(1.0, 0.0))
    db.commit()
    # O vetor e o chunk concordam no hash antigo; o conteúdo é que mudou.
    assert chunk.content_sha256 == content_digest("texto original")
    db.execute(
        update(DocumentChunk)
        .where(DocumentChunk.id == chunk.id)
        .values(content="texto completamente diferente")
    )
    db.commit()
    stored = db.execute(
        select(DocumentChunk.content_sha256, ChunkEmbedding.embedded_content_sha256)
        .join(ChunkEmbedding, ChunkEmbedding.chunk_id == DocumentChunk.id)
        .where(DocumentChunk.id == chunk.id)
    ).one()
    assert stored[0] == stored[1], "os dois valores persistidos concordam"

    with pytest.raises(ExperimentError) as info:
        verify_index_identity(
            db,
            context=_retrievability(tenant),
            identity=FakeEmbeddingModel({}).identity,
        )

    assert info.value.exit_code == EXIT_INDEX_INCOMPLETE
    assert "no longer has" in str(info.value)


# --- Indexação: o que conta como "já indexado" ------------------------------------


def _index(
    db: Session, tenant: _Tenant, model: FakeEmbeddingModel, *, reembed: bool = False
) -> dict[str, int]:
    return index_corpus(
        db,
        embedding_model=model,
        context=_retrievability(tenant),
        reembed=reembed,
    )


def test_indexing_writes_the_full_identity(client: TestClient, db: Session) -> None:
    tenant = _create_tenant(client, code_prefix="IDX")
    document = _add_document(db, tenant, title="Regulamento")
    version = _add_version(db, tenant, document)
    _add_chunk(db, tenant, document, version, content="texto")
    db.commit()

    counts = _index(db, tenant, FakeEmbeddingModel({"texto": concept(1.0, 0.0)}))

    assert counts == {
        "admissible": 1,
        "already_indexed": 0,
        "embedded_now": 1,
        "replaced_stale_configuration": 0,
        "replaced_stale_content": 0,
    }
    row = db.scalars(select(ChunkEmbedding)).one()
    assert (row.provider, row.model, row.configuration_version) == (
        FAKE_PROVIDER,
        FAKE_MODEL,
        FAKE_CONFIGURATION,
    )


def test_the_stored_hash_is_recomputed_from_the_text_actually_sent(
    client: TestClient, db: Session
) -> None:
    """Não é copiado de ``DocumentChunk.content_sha256``.

    O chunk leva aqui um ``content_sha256`` deliberadamente errado. Se a
    indexação o copiasse, a coluna descreveria o que se *supõe* ter sido
    enviado; recalculando, descreve o que foi.
    """
    tenant = _create_tenant(client, code_prefix="SHA")
    document = _add_document(db, tenant, title="Regulamento")
    version = _add_version(db, tenant, document)
    chunk = _add_chunk(db, tenant, document, version, content="texto")
    chunk.content_sha256 = "9" * 64
    db.commit()

    _index(db, tenant, FakeEmbeddingModel({"texto": concept(1.0, 0.0)}))

    row = db.scalars(select(ChunkEmbedding)).one()
    assert row.embedded_content_sha256 == content_digest("texto")
    assert row.embedded_content_sha256 != "9" * 64


def test_a_fresh_index_is_not_sent_to_the_provider_again(
    client: TestClient, db: Session
) -> None:
    tenant = _create_tenant(client, code_prefix="FRS")
    document = _add_document(db, tenant, title="Regulamento")
    version = _add_version(db, tenant, document)
    _add_chunk(db, tenant, document, version, content="texto")
    db.commit()
    model = FakeEmbeddingModel({"texto": concept(1.0, 0.0)})
    _index(db, tenant, model)
    calls_after_first = len(model.calls)

    counts = _index(db, tenant, model)

    assert counts["embedded_now"] == 0
    assert counts["already_indexed"] == 1
    assert len(model.calls) == calls_after_first


def test_a_vector_of_another_configuration_is_replaced_and_counted(
    client: TestClient, db: Session
) -> None:
    """Mudar a configuração invalida o vetor anterior; não coexiste com ele."""
    tenant = _create_tenant(client, code_prefix="RPL")
    document = _add_document(db, tenant, title="Regulamento")
    version = _add_version(db, tenant, document)
    chunk = _add_chunk(db, tenant, document, version, content="texto")
    db.add(
        ChunkEmbedding(
            chunk_id=chunk.id,
            provider=FAKE_PROVIDER,
            model=FAKE_MODEL,
            configuration_version="fake_v0",
            embedded_content_sha256=content_digest("texto"),
            embedding=concept(0.0, 1.0),
        )
    )
    db.commit()

    counts = _index(db, tenant, FakeEmbeddingModel({"texto": concept(1.0, 0.0)}))

    assert counts["embedded_now"] == 1
    assert counts["replaced_stale_configuration"] == 1
    assert counts["replaced_stale_content"] == 0
    rows = db.scalars(select(ChunkEmbedding)).all()
    assert len(rows) == 1
    assert rows[0].configuration_version == FAKE_CONFIGURATION


def test_a_vector_whose_content_changed_is_replaced_and_counted(
    client: TestClient, db: Session
) -> None:
    tenant = _create_tenant(client, code_prefix="CHG")
    document = _add_document(db, tenant, title="Regulamento")
    version = _add_version(db, tenant, document)
    chunk = _add_chunk(db, tenant, document, version, content="texto")
    db.add(
        ChunkEmbedding(
            chunk_id=chunk.id,
            provider=FAKE_PROVIDER,
            model=FAKE_MODEL,
            configuration_version=FAKE_CONFIGURATION,
            embedded_content_sha256=content_digest("outro texto qualquer"),
            embedding=concept(0.0, 1.0),
        )
    )
    db.commit()

    counts = _index(db, tenant, FakeEmbeddingModel({"texto": concept(1.0, 0.0)}))

    assert counts["embedded_now"] == 1
    assert counts["replaced_stale_content"] == 1
    assert counts["replaced_stale_configuration"] == 0


def test_the_index_left_by_a_full_run_passes_the_identity_guard(
    client: TestClient, db: Session
) -> None:
    """A indexação e a guarda concordam sobre o que é um índice íntegro.

    Sem isto, as duas poderiam divergir — a indexação a considerar completo o
    que a guarda recusa — e a experiência ficaria impossível de executar sem
    que nenhuma das duas estivesse obviamente errada.
    """
    tenant = _create_tenant(client, code_prefix="AGR")
    document = _add_document(db, tenant, title="Regulamento")
    version = _add_version(db, tenant, document)
    for index in range(3):
        _add_chunk(db, tenant, document, version, content=f"texto {index}",
                   chunk_index=index)
    db.commit()
    model = FakeEmbeddingModel({})

    _index(db, tenant, model)

    verify_index_identity(db, context=_retrievability(tenant), identity=model.identity)
    result = _search(db, tenant, model=model)
    trace = result.trace
    assert isinstance(trace, DenseRetrievalTrace)
    assert trace.admissible_chunks == trace.embedded_chunks == 3


# --- Constraints da tabela ---------------------------------------------------------


@pytest.mark.parametrize("blank", ["", " ", "\t", "\n", " \t\r\n "])
@pytest.mark.parametrize("column", ["provider", "model", "configuration_version"])
def test_whitespace_only_identity_fields_are_rejected_by_the_database(
    client: TestClient, db: Session, column: str, blank: str
) -> None:
    """``btrim(x)`` sem segundo argumento corta só espaços.

    Um identificador composto apenas por tabulações ou mudanças de linha
    passaria por válido e produziria um índice que ninguém consegue voltar a
    selecionar. O conjunto de caracteres é explícito nas constraints por isso.
    """
    tenant = _create_tenant(client, code_prefix="BLK")
    document = _add_document(db, tenant, title="Regulamento")
    version = _add_version(db, tenant, document)
    chunk = _add_chunk(db, tenant, document, version, content="texto")
    db.commit()

    values = {
        "provider": FAKE_PROVIDER,
        "model": FAKE_MODEL,
        "configuration_version": FAKE_CONFIGURATION,
        column: blank,
    }
    db.add(
        ChunkEmbedding(
            chunk_id=chunk.id,
            embedded_content_sha256=chunk.content_sha256,
            embedding=concept(1.0, 0.0),
            **values,
        )
    )
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


# --- Semântica do score -----------------------------------------------------------


def test_the_score_declares_its_own_family_and_the_model_that_produced_it(
    client: TestClient, db: Session
) -> None:
    """Um score denso nunca se apresenta como relevância lexical.

    A ``version`` transporta o modelo porque trocar de modelo produz números
    incomparáveis com os anteriores sem mudar mais nada.
    """
    tenant = _create_tenant(client, code_prefix="SEM")
    document = _add_document(db, tenant, title="Regulamento")
    version = _add_version(db, tenant, document)
    _add_chunk(db, tenant, document, version, content="texto", vector=concept(1.0, 0.0))
    db.commit()

    model = FakeEmbeddingModel({"pergunta": concept(1.0, 0.0)})
    semantics = _search(db, tenant, model=model).score_semantics

    assert semantics.kind is ScoreKind.DENSE_SIMILARITY
    assert semantics.kind is not ScoreKind.LEXICAL_RELEVANCE
    assert DENSE_PIPELINE_VERSION in semantics.version
    assert FAKE_MODEL in semantics.version
    assert semantics.comparable_across_queries is False


def test_the_lexical_relevance_threshold_is_not_applied_to_similarity(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Aplicar o piso lexical à similaridade seria tratar duas escalas como uma.

    Com o limiar a 0.99, o retriever lexical não devolveria nada; o denso
    devolve, porque não usa esse limiar nem nenhum outro.
    """
    tenant = _create_tenant(client, code_prefix="THR")
    document = _add_document(db, tenant, title="Regulamento")
    version = _add_version(db, tenant, document)
    _add_chunk(db, tenant, document, version, content="texto", vector=concept(1.0, 1.0))
    db.commit()

    monkeypatch.setattr(settings, "retrieval_min_relevance_score", 0.99)
    model = FakeEmbeddingModel({"pergunta": concept(1.0, 0.0)})
    result = _search(db, tenant, model=model)

    assert len(result.evidence) == 1
    assert 0.0 < result.evidence[0].score < 0.99


def test_dense_returns_results_even_when_nothing_is_close(
    client: TestClient, db: Session
) -> None:
    """Comportamento **declarado**, não desejável: ver o docstring de ``dense``.

    Sem elegibilidade de conteúdo e sem limiar, uma pergunta sem resposta no
    corpus recebe na mesma ``top_k`` vizinhos. É a diferença comportamental de
    primeira ordem face à baseline lexical, que sabe não devolver nada, e está
    fixada por teste para que não passe a ser esquecida.
    """
    tenant = _create_tenant(client, code_prefix="FAR")
    document = _add_document(db, tenant, title="Regulamento")
    version = _add_version(db, tenant, document)
    for index in range(3):
        _add_chunk(db, tenant, document, version, content=f"nada a ver {index}",
                   chunk_index=index, vector=concept(0.0, 1.0, index / 10))
    db.commit()

    model = FakeEmbeddingModel({"pergunta sem resposta": concept(1.0, 0.0)})
    result = _search(db, tenant, model=model, query="pergunta sem resposta")

    assert len(result.evidence) == 3
    assert all(evidence.score < 0.2 for evidence in result.evidence)


# --- Produção inalterada ----------------------------------------------------------


def test_the_production_factory_still_resolves_the_lexical_retriever() -> None:
    """O D4.8 é uma experiência: nada em produção passa a usar o retriever denso."""
    assert isinstance(get_retriever(), PostgresLexicalRetriever)
