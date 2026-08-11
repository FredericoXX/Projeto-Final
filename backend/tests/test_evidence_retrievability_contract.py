"""Fase 1 da issue #24 — contrato entre os adaptadores SQL e Python.

Sobre o **mesmo** corpus de linhas reais no PostgreSQL da suite, executa as
duas formas da política e afirma que selecionam exatamente o mesmo conjunto de
chunks. É este teste que torna a duplicação impossível de manter em silêncio: se
uma condição for acrescentada, removida ou traduzida de forma diferente num só
adaptador, os conjuntos deixam de coincidir.

Cobre obrigatoriamente cada linha da tabela de não-equivalências da Decisão 5
da issue #24: C5 sobre versões intercaladas, a lógica ternária de C9/C10 com
``NULL`` e limites exatos, a omissão condicional de C11, ``IS TRUE`` em C6, a
comparação de idioma sob a collation do PostgreSQL em C7/C8, e o isolamento
institucional em C1–C3.

O corpus é construído diretamente com o ORM, e não pela API, porque precisa de
estados que os services impedem deliberadamente — versões ``failed``
intercaladas, idioma de chunk divergente do documento e etiquetas de idioma que
diferem apenas em maiúsculas. É esse o ponto: o contrato tem de valer também
para linhas que a aplicação não produz hoje.
"""

import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.documents.retrievability import (
    CitationPersistenceEligibility,
    EvidencePolicy,
    RetrievabilityContext,
    RetrievabilitySubject,
    RetrievalEligibility,
    latest_processed_version_subquery,
)
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.document_version import DocumentVersion

BOOTSTRAP_HEADERS = {"X-Bootstrap-Token": settings.bootstrap_token or ""}
_ADMIN_PASSWORD = "supersecret123"

REFERENCE_DATE = date(2026, 8, 11)
YESTERDAY = REFERENCE_DATE - timedelta(days=1)
TOMORROW = REFERENCE_DATE + timedelta(days=1)


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
    email = f"admin-{uuid.uuid4().hex[:8]}@example.com"
    admin = client.post(
        "/api/v1/auth/register-initial-admin",
        json={
            "institution_id": institution.json()["id"],
            "full_name": "Admin Contrato",
            "email": email,
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
    version_number: int,
    processing_status: str,
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
        extracted_text="conteudo do corpus de contrato",
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
    language: str | None = None,
    chunk_index: int = 0,
) -> DocumentChunk:
    content = "conteudo do corpus de contrato"
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
    return chunk


# --- Os dois adaptadores, sobre as mesmas linhas ------------------------------------


def _sql_selection(
    db: Session, policy: EvidencePolicy, context: RetrievabilityContext
) -> set[uuid.UUID]:
    return set(db.scalars(policy.select_eligible_chunk_ids(context)).all())


def _python_selection(
    db: Session, policy: EvidencePolicy, context: RetrievabilityContext
) -> set[uuid.UUID]:
    """Veredicto Python sobre **todos** os chunks da base, sem pré-filtro.

    Não se filtra por instituição antes de avaliar: se o fizesse, C1–C3
    deixariam de ser exercitadas e o contrato deixaria de cobrir o isolamento
    institucional. O universo avaliado é o mesmo que o join SQL percorre.
    """
    # Versão efetiva por documento, resolvida a partir da mesma definição
    # canónica que o adaptador SQL usa para C5.
    latest = latest_processed_version_subquery(context)
    effective_by_document = {
        row.document_id: row.version_id
        for row in db.execute(select(latest).where(latest.c.rn == 1))
    }

    rows = db.execute(
        select(DocumentChunk, Document, DocumentVersion)
        .join(Document, Document.id == DocumentChunk.document_id)
        .join(DocumentVersion, DocumentVersion.id == DocumentChunk.document_version_id)
    ).all()

    selected: set[uuid.UUID] = set()
    for chunk, document, version in rows:
        subject = RetrievabilitySubject.from_entities(
            chunk=chunk,
            document=document,
            version=version,
            effective_version_id=effective_by_document.get(document.id),
        )
        if policy.explain(subject, context).eligible:
            selected.add(chunk.id)
    return selected


def _assert_adapters_agree(
    db: Session, policy: EvidencePolicy, context: RetrievabilityContext
) -> set[uuid.UUID]:
    sql_selected = _sql_selection(db, policy, context)
    python_selected = _python_selection(db, policy, context)
    assert sql_selected == python_selected, (
        f"{policy.name}: só em SQL={sql_selected - python_selected} "
        f"só em Python={python_selected - sql_selected}"
    )
    return sql_selected


def _context(tenant: _Tenant, **overrides: object) -> RetrievabilityContext:
    values: dict = {
        "institution_id": tenant.institution_id,
        "language": "pt",
        "reference_date": REFERENCE_DATE,
        "official_only": True,
    }
    values.update(overrides)
    return RetrievabilityContext(**values)


# --- Corpus completo, cobrindo a matriz da Decisão 5 ---------------------------------


@dataclass(frozen=True)
class _Corpus:
    tenant: _Tenant
    other_tenant: _Tenant
    chunks: dict[str, uuid.UUID]


@pytest.fixture
def corpus(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> _Corpus:
    tenant = _create_tenant(client, code_prefix="CTR")
    other = _create_tenant(client, code_prefix="OTH")
    chunks: dict[str, uuid.UUID] = {}

    with test_session_factory() as db:
        # Documento simples e admissível: a referência de controlo.
        plain = _add_document(db, tenant, title="Documento simples")
        plain_v1 = _add_version(db, tenant, plain, version_number=1, processing_status="processed")
        chunks["plain"] = _add_chunk(db, tenant, plain, plain_v1).id

        # C5 — versões processed e failed intercaladas. A versão efetiva é a
        # processed de maior version_number (3), não a mais recente (4, failed).
        layered = _add_document(db, tenant, title="Documento com camadas")
        layered_v1 = _add_version(
            db, tenant, layered, version_number=1, processing_status="processed"
        )
        layered_v2 = _add_version(
            db, tenant, layered, version_number=2, processing_status="failed"
        )
        layered_v3 = _add_version(
            db, tenant, layered, version_number=3, processing_status="processed"
        )
        layered_v4 = _add_version(
            db, tenant, layered, version_number=4, processing_status="failed"
        )
        chunks["layered_v1_superseded"] = _add_chunk(db, tenant, layered, layered_v1).id
        chunks["layered_v2_failed"] = _add_chunk(db, tenant, layered, layered_v2).id
        chunks["layered_v3_effective"] = _add_chunk(db, tenant, layered, layered_v3).id
        chunks["layered_v4_failed"] = _add_chunk(db, tenant, layered, layered_v4).id

        # C12 na prática — documento sem qualquer versão processed.
        unprocessed = _add_document(db, tenant, title="Documento sem processed")
        unprocessed_v1 = _add_version(
            db, tenant, unprocessed, version_number=1, processing_status="pending"
        )
        chunks["unprocessed"] = _add_chunk(db, tenant, unprocessed, unprocessed_v1).id

        # C6 — documento inativo.
        inactive = _add_document(db, tenant, title="Documento inativo", is_active=False)
        inactive_v1 = _add_version(
            db, tenant, inactive, version_number=1, processing_status="processed"
        )
        chunks["inactive"] = _add_chunk(db, tenant, inactive, inactive_v1).id

        # C11 — documento não oficial.
        unofficial = _add_document(
            db, tenant, title="Documento não oficial", official_source=False
        )
        unofficial_v1 = _add_version(
            db, tenant, unofficial, version_number=1, processing_status="processed"
        )
        chunks["unofficial"] = _add_chunk(db, tenant, unofficial, unofficial_v1).id

        # C9/C10 — a matriz da validade, incluindo limites exatos.
        validity_cases = {
            "validity_both_null": (None, None),
            "validity_from_null_until_today": (None, REFERENCE_DATE),
            "validity_from_today_until_null": (REFERENCE_DATE, None),
            "validity_both_today": (REFERENCE_DATE, REFERENCE_DATE),
            "validity_future_from": (TOMORROW, None),
            "validity_expired_until": (None, YESTERDAY),
        }
        for index, (key, (valid_from, valid_until)) in enumerate(validity_cases.items()):
            document = _add_document(
                db,
                tenant,
                title=f"Validade {index}",
                valid_from=valid_from,
                valid_until=valid_until,
            )
            version = _add_version(
                db, tenant, document, version_number=1, processing_status="processed"
            )
            chunks[key] = _add_chunk(db, tenant, document, version).id

        # C7 — idioma do documento diferente do contexto.
        english = _add_document(db, tenant, title="English document", language="en")
        english_v1 = _add_version(
            db, tenant, english, version_number=1, processing_status="processed"
        )
        chunks["english_document"] = _add_chunk(db, tenant, english, english_v1).id

        # C8 — idioma do chunk divergente do documento (invariante contornada
        # de propósito: é a linha que a Decisão 5 manda cobrir).
        divergent = _add_document(db, tenant, title="Documento com chunk divergente")
        divergent_v1 = _add_version(
            db, tenant, divergent, version_number=1, processing_status="processed"
        )
        chunks["divergent_chunk_language"] = _add_chunk(
            db, tenant, divergent, divergent_v1, language="en"
        ).id

        # C7/C8 — etiquetas que diferem apenas em maiúsculas, dos dois lados.
        upper_document = _add_document(db, tenant, title="Documento PT", language="PT")
        upper_document_v1 = _add_version(
            db, tenant, upper_document, version_number=1, processing_status="processed"
        )
        chunks["uppercase_document_language"] = _add_chunk(
            db, tenant, upper_document, upper_document_v1
        ).id

        upper_chunk_document = _add_document(db, tenant, title="Documento chunk PT")
        upper_chunk_version = _add_version(
            db, tenant, upper_chunk_document, version_number=1, processing_status="processed"
        )
        chunks["uppercase_chunk_language"] = _add_chunk(
            db, tenant, upper_chunk_document, upper_chunk_version, language="PT"
        ).id

        # C1–C3 — corpus equivalente noutra instituição.
        foreign = _add_document(db, other, title="Documento de outra instituição")
        foreign_v1 = _add_version(
            db, other, foreign, version_number=1, processing_status="processed"
        )
        chunks["foreign_institution"] = _add_chunk(db, other, foreign, foreign_v1).id

        db.commit()

    return _Corpus(tenant=tenant, other_tenant=other, chunks=chunks)


# --- O contrato -----------------------------------------------------------------------


@pytest.mark.parametrize("official_only", [True, False])
@pytest.mark.parametrize("language", ["pt", "en", "PT"])
def test_adapters_agree_for_both_policies_across_contexts(
    corpus: _Corpus,
    test_session_factory: sessionmaker[Session],
    official_only: bool,
    language: str,
) -> None:
    """SQL e Python selecionam o mesmo conjunto, em todos os contextos."""
    context = _context(corpus.tenant, language=language, official_only=official_only)
    with test_session_factory() as db:
        for policy in (CitationPersistenceEligibility, RetrievalEligibility):
            _assert_adapters_agree(db, policy, context)


@pytest.mark.parametrize(
    "reference_date",
    [REFERENCE_DATE, YESTERDAY, TOMORROW, date(2026, 1, 1), date(2027, 1, 1)],
)
def test_adapters_agree_across_reference_dates(
    corpus: _Corpus,
    test_session_factory: sessionmaker[Session],
    reference_date: date,
) -> None:
    """A lógica ternária de C9/C10 concorda em ambos os lados, em cada data."""
    context = _context(corpus.tenant, reference_date=reference_date)
    with test_session_factory() as db:
        for policy in (CitationPersistenceEligibility, RetrievalEligibility):
            _assert_adapters_agree(db, policy, context)


def test_retrieval_selection_is_exactly_the_expected_corpus_subset(
    corpus: _Corpus, test_session_factory: sessionmaker[Session]
) -> None:
    """Ancora o contrato num conjunto conhecido, não apenas na coincidência.

    Dois adaptadores podem concordar por estarem ambos errados. Este teste
    fixa **quais** chunks a política de recuperação admite no corpus.
    """
    context = _context(corpus.tenant)
    with test_session_factory() as db:
        selected = _assert_adapters_agree(db, RetrievalEligibility, context)

    # Ficam de fora, cada um pela sua condição: a versão 1 superada (C5), as
    # versões failed (C4), o documento sem processed (C4), o inativo (C6), o
    # não oficial (C11), a validade futura e a expirada (C9/C10), o documento
    # em inglês (C7), o chunk divergente e o chunk em 'PT' (C8), o documento em
    # 'PT' (C7) e o corpus da outra instituição (C1–C3).
    expected_keys = {
        "plain",
        "layered_v3_effective",
        "validity_both_null",
        "validity_from_null_until_today",
        "validity_from_today_until_null",
        "validity_both_today",
    }
    assert selected == {corpus.chunks[key] for key in expected_keys}


def test_c5_is_the_only_difference_between_the_two_policies_on_real_rows(
    corpus: _Corpus, test_session_factory: sessionmaker[Session]
) -> None:
    """A composição, verificada sobre linhas reais e não só sobre a lista.

    A persistência de citações admite exatamente os chunks da recuperação mais
    os das versões ``processed`` superadas. É a proveniência histórica da
    Decisão 7, observada no adaptador SQL.
    """
    context = _context(corpus.tenant)
    with test_session_factory() as db:
        retrieval = _assert_adapters_agree(db, RetrievalEligibility, context)
        citation = _assert_adapters_agree(db, CitationPersistenceEligibility, context)

    assert retrieval < citation
    # A única diferença é a versão 1, processed mas já superada pela versão 3.
    assert citation - retrieval == {corpus.chunks["layered_v1_superseded"]}
    # As versões failed nunca entram em nenhuma das políticas (C4).
    assert corpus.chunks["layered_v2_failed"] not in citation
    assert corpus.chunks["layered_v4_failed"] not in citation


def test_institution_isolation_holds_in_the_sql_adapter(
    corpus: _Corpus, test_session_factory: sessionmaker[Session]
) -> None:
    """C1–C3 são filtros no PostgreSQL, não apenas verificações em Python."""
    context = _context(corpus.tenant)
    other_context = _context(corpus.other_tenant)

    with test_session_factory() as db:
        own = _sql_selection(db, RetrievalEligibility, context)
        foreign = _sql_selection(db, RetrievalEligibility, other_context)

        # O SQL compilado menciona as três colunas institution_id.
        compiled = str(
            RetrievalEligibility.select_eligible_chunk_ids(context).compile(
                db.get_bind(), compile_kwargs={"literal_binds": True}
            )
        )

    assert corpus.chunks["foreign_institution"] not in own
    assert foreign == {corpus.chunks["foreign_institution"]}
    assert own.isdisjoint(foreign)
    for table in ("document_chunks.institution_id", "documents.institution_id",
                  "document_versions.institution_id"):
        assert table in compiled


def test_official_only_removes_the_condition_instead_of_negating_it(
    corpus: _Corpus, test_session_factory: sessionmaker[Session]
) -> None:
    """C11: ``sql`` devolve ``None`` quando o contexto não a exige."""
    restricted = _context(corpus.tenant, official_only=True)
    permissive = _context(corpus.tenant, official_only=False)

    with test_session_factory() as db:
        restricted_selected = _assert_adapters_agree(db, RetrievalEligibility, restricted)
        permissive_selected = _assert_adapters_agree(db, RetrievalEligibility, permissive)
        restricted_sql = str(
            RetrievalEligibility.select_eligible_chunk_ids(restricted).compile(
                db.get_bind(), compile_kwargs={"literal_binds": True}
            )
        )
        permissive_sql = str(
            RetrievalEligibility.select_eligible_chunk_ids(permissive).compile(
                db.get_bind(), compile_kwargs={"literal_binds": True}
            )
        )

    assert corpus.chunks["unofficial"] not in restricted_selected
    assert corpus.chunks["unofficial"] in permissive_selected
    assert restricted_selected < permissive_selected

    # A condição desaparece do WHERE, em vez de virar uma tautologia.
    assert "official_source IS true" in restricted_sql
    assert "official_source" not in permissive_sql


def test_document_active_uses_is_true_rather_than_column_truthiness(
    corpus: _Corpus, test_session_factory: sessionmaker[Session]
) -> None:
    """C6 mantém ``IS TRUE`` explícito, como a Decisão 5 exige."""
    context = _context(corpus.tenant)
    with test_session_factory() as db:
        selected = _assert_adapters_agree(db, RetrievalEligibility, context)
        compiled = str(
            RetrievalEligibility.select_eligible_chunk_ids(context).compile(
                db.get_bind(), compile_kwargs={"literal_binds": True}
            )
        )

    assert corpus.chunks["inactive"] not in selected
    assert "is_active IS true" in compiled


def test_language_comparison_agrees_between_postgresql_and_python(
    corpus: _Corpus, test_session_factory: sessionmaker[Session]
) -> None:
    """C7/C8 sob a collation real: etiquetas que diferem só no case.

    Se a base passar a usar uma collation **não determinística**, a igualdade
    do PostgreSQL deixaria de coincidir com a comparação por code point do
    Python e este teste falha — que é exatamente o sinal que a Decisão 5 pede,
    em vez de uma divergência silenciosa.
    """
    lowercase = _context(corpus.tenant, language="pt")
    uppercase = _context(corpus.tenant, language="PT")

    with test_session_factory() as db:
        selected_lower = _assert_adapters_agree(db, RetrievalEligibility, lowercase)
        selected_upper = _assert_adapters_agree(db, RetrievalEligibility, uppercase)

    # Nem o documento em 'PT' nem o chunk em 'PT' satisfazem um contexto 'pt'.
    assert corpus.chunks["uppercase_document_language"] not in selected_lower
    assert corpus.chunks["uppercase_chunk_language"] not in selected_lower
    # E o documento em 'PT' é admitido quando o contexto também é 'PT'.
    assert corpus.chunks["uppercase_document_language"] in selected_upper
    assert corpus.chunks["plain"] not in selected_upper


def test_chunk_language_is_evaluated_independently_of_document_language(
    corpus: _Corpus, test_session_factory: sessionmaker[Session]
) -> None:
    """C8 exclui a linha com idioma divergente, nos dois adaptadores."""
    context = _context(corpus.tenant)
    with test_session_factory() as db:
        selected = _assert_adapters_agree(db, RetrievalEligibility, context)

    assert corpus.chunks["divergent_chunk_language"] not in selected
    assert corpus.chunks["english_document"] not in selected


def test_document_without_processed_version_is_never_selected(
    corpus: _Corpus, test_session_factory: sessionmaker[Session]
) -> None:
    """C4 exclui a linha em ambas as políticas; C12 é o conjunto vazio."""
    context = _context(corpus.tenant)
    with test_session_factory() as db:
        retrieval = _assert_adapters_agree(db, RetrievalEligibility, context)
        citation = _assert_adapters_agree(db, CitationPersistenceEligibility, context)

    assert corpus.chunks["unprocessed"] not in retrieval
    assert corpus.chunks["unprocessed"] not in citation
