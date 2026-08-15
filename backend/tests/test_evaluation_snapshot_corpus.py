"""Identidade do corpus construída sobre PostgreSQL real.

Aqui prova-se o que os testes puros não podem provar: que o corpus do snapshot
é **exatamente** o que ``RetrievalEligibility`` considera admissível, e que a
elegibilidade não foi reimplementada por baixo. Nenhum destes testes recodifica
C1–C11 — cada caso monta um estado documental e observa se a versão entra ou
não no corpus, comparando sempre contra a política como fonte de verdade.

As entidades são criadas diretamente por ORM em vez de pela API de upload: os
casos temporais exigem controlar ``valid_from``/``valid_until``,
``processing_status`` e ``official_source`` com precisão, e o pipeline de
extração não é o sujeito destes testes.
"""

import hashlib
import uuid
from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.documents.retrievability import RetrievabilityContext, RetrievalEligibility
from app.evaluation.snapshot import ChunkIdentity, EvaluationSnapshot, compute_chunk_digest
from app.evaluation.snapshot_builder import (
    build_evaluation_snapshot,
    collect_corpus_entries,
    describe_retrieval_configuration,
)
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.document_version import DocumentVersion
from app.models.institution import Institution
from app.models.user import User

TODAY = date(2026, 8, 13)


def _institution(db: Session, *, code: str) -> Institution:
    institution = Institution(
        name=f"Institution {code}",
        code=code,
        default_language="pt",
        supported_languages=["pt", "en"],
    )
    db.add(institution)
    db.flush()
    return institution


def _user(db: Session, institution: Institution) -> User:
    user = User(
        institution_id=institution.id,
        full_name="Corpus Owner",
        email=f"owner-{uuid.uuid4().hex[:8]}@example.com",
        password_hash="unused",
        role="admin",
    )
    db.add(user)
    db.flush()
    return user


def _document(
    db: Session,
    institution: Institution,
    user: User,
    *,
    title: str = "Regulamento Académico",
    language: str = "pt",
    official_source: bool = True,
    is_active: bool = True,
    valid_from: date | None = None,
    valid_until: date | None = None,
    description: str | None = None,
    source_url: str | None = None,
) -> Document:
    document = Document(
        institution_id=institution.id,
        created_by_user_id=user.id,
        title=title,
        description=description,
        language=language,
        source_url=source_url,
        official_source=official_source,
        is_active=is_active,
        valid_from=valid_from,
        valid_until=valid_until,
    )
    db.add(document)
    db.flush()
    return document


def _version(
    db: Session,
    document: Document,
    user: User,
    *,
    version_number: int = 1,
    processing_status: str = "processed",
    content: str = "prazo de matricula no campus",
) -> DocumentVersion:
    checksum = hashlib.sha256(f"{document.id}:{version_number}".encode()).hexdigest()
    version = DocumentVersion(
        document_id=document.id,
        institution_id=document.institution_id,
        uploaded_by_user_id=user.id,
        version_number=version_number,
        original_filename=f"v{version_number}.txt",
        mime_type="text/plain",
        size_bytes=len(content),
        checksum_sha256=checksum,
        storage_path=f"documents/{document.id}/v{version_number}.txt",
        processing_status=processing_status,
        extracted_text=content,
    )
    db.add(version)
    db.flush()
    if processing_status == "processed":
        _chunk(db, document, version, content=content)
    return version


def _chunk(
    db: Session,
    document: Document,
    version: DocumentVersion,
    *,
    chunk_index: int = 0,
    content: str = "prazo de matricula no campus",
    language: str | None = None,
) -> DocumentChunk:
    chunk = DocumentChunk(
        institution_id=document.institution_id,
        document_id=document.id,
        document_version_id=version.id,
        chunk_index=chunk_index,
        content=content,
        normalized_content=content.lower(),
        content_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        start_char=0,
        end_char=len(content),
        language=language if language is not None else document.language,
        section_title="Matrículas",
        structure_type="paragraph",
        page_number=1,
    )
    db.add(chunk)
    db.flush()
    return chunk


def _context(
    institution: Institution,
    *,
    language: str = "pt",
    reference_date: date = TODAY,
    official_only: bool = True,
) -> RetrievabilityContext:
    return RetrievabilityContext(
        institution_id=institution.id,
        language=language,
        reference_date=reference_date,
        official_only=official_only,
    )


def _snapshot(
    db: Session,
    institution: Institution,
    *,
    language: str = "pt",
    reference_date: date = TODAY,
    top_k: int = 5,
    official_only: bool = True,
) -> EvaluationSnapshot:
    return build_evaluation_snapshot(
        db,
        institution_id=institution.id,
        language=language,
        reference_date=reference_date,
        top_k=top_k,
        official_only=official_only,
    )


@pytest.fixture
def db(test_session_factory: sessionmaker[Session]):
    session = test_session_factory()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def _version_ids(entries) -> set:
    return {entry.document_version_id for entry in entries}


# --- T13 · a política existente é a fonte de verdade ----------------------


def test_corpus_matches_the_eligibility_policy_exactly(db: Session) -> None:
    """O corpus é o conjunto elegível, não uma segunda definição paralela.

    A comparação é feita sobre a **identidade exata dos segmentos**, não sobre
    conjuntos de versões nem sobre contagens: o digest esperado é reconstruído
    a partir das linhas que a própria política devolve. Comparar versões
    deixaria passar a perda de um segmento numa versão presente; comparar
    contagens deixaria passar dois conjuntos do mesmo tamanho com conteúdos
    diferentes. Ambas são divergências silenciosas que este teste existe para
    apanhar.
    """
    institution = _institution(db, code=f"POL-{uuid.uuid4().hex[:6].upper()}")
    user = _user(db, institution)
    eligible = _document(db, institution, user, title="Elegível")
    version = _version(db, eligible, user)
    _chunk(db, eligible, version, chunk_index=1, content="segundo segmento")
    _chunk(db, eligible, version, chunk_index=2, content="terceiro segmento")
    second = _document(db, institution, user, title="Outro elegível")
    _version(db, second, user, content="outro conteudo")
    inactive = _document(db, institution, user, title="Inativo", is_active=False)
    _version(db, inactive, user)

    context = _context(institution)
    entries = collect_corpus_entries(db, context)

    policy_chunk_ids = set(
        db.scalars(RetrievalEligibility.select_eligible_chunk_ids(context)).all()
    )

    # Reconstrói, a partir das linhas que a **política** devolve, o digest que
    # cada versão devia ter. Comparar contagens não chegava: dois conjuntos com
    # o mesmo número de segmentos mas conteúdos diferentes passariam.
    policy_rows = db.execute(
        select(
            DocumentChunk.document_version_id,
            DocumentChunk.chunk_index,
            DocumentChunk.content,
            DocumentChunk.normalized_content,
            DocumentChunk.section_title,
            DocumentChunk.structure_type,
        ).where(DocumentChunk.id.in_(policy_chunk_ids))
    ).all()

    grouped: dict[uuid.UUID, list[ChunkIdentity]] = {}
    for version_id, index, content, normalized, section, structure in policy_rows:
        grouped.setdefault(version_id, []).append(
            ChunkIdentity(
                chunk_index=index,
                content_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
                normalized_content_sha256=hashlib.sha256(
                    normalized.encode("utf-8")
                ).hexdigest(),
                section_title=section,
                structure_type=structure,
            )
        )

    expected = {
        version_id: (len(chunks), compute_chunk_digest(tuple(chunks)))
        for version_id, chunks in grouped.items()
    }
    observed = {
        entry.document_version_id: (entry.chunk_count, entry.chunk_digest)
        for entry in entries
    }

    assert observed == expected
    assert sum(count for count, _digest in observed.values()) == len(policy_chunk_ids)


def test_losing_one_eligible_chunk_changes_the_identity(db: Session) -> None:
    """Contraexemplo de M2: a versão continua presente, o corpus não é o mesmo.

    Uma comparação apenas ao nível das versões não distinguiria estes dois
    estados; a identidade tem de os separar.
    """
    institution = _institution(db, code=f"LOS-{uuid.uuid4().hex[:6].upper()}")
    user = _user(db, institution)
    document = _document(db, institution, user)
    version = _version(db, document, user)
    extra = _chunk(db, document, version, chunk_index=1, content="segmento a remover")
    before = _snapshot(db, institution)

    db.delete(extra)
    db.flush()
    after = _snapshot(db, institution)

    assert _version_ids(after.corpus) == _version_ids(before.corpus)
    assert after.corpus_digest != before.corpus_digest
    assert before.corpus[0].chunk_count == 2
    assert after.corpus[0].chunk_count == 1


# --- Casos temporais A–C · vigência --------------------------------------


@pytest.mark.parametrize(
    ("valid_from", "valid_until", "expected", "label"),
    [
        pytest.param(date(2026, 12, 1), None, False, "ainda-nao-vigente", id="A-nao-vigente"),
        pytest.param(date(2026, 1, 1), date(2026, 12, 31), True, "vigente", id="B-vigente"),
        pytest.param(None, date(2026, 1, 31), False, "expirado", id="C-expirado"),
        pytest.param(None, None, True, "sem-limites", id="B-sem-limites"),
        pytest.param(TODAY, TODAY, True, "fronteira-inclusiva", id="B-fronteiras"),
    ],
)
def test_document_validity_window_decides_membership(
    db: Session, valid_from, valid_until, expected: bool, label: str
) -> None:
    institution = _institution(db, code=f"VAL-{uuid.uuid4().hex[:6].upper()}")
    user = _user(db, institution)
    document = _document(
        db, institution, user, valid_from=valid_from, valid_until=valid_until
    )
    _version(db, document, user)

    entries = collect_corpus_entries(db, _context(institution))

    assert (document.id in {entry.document_id for entry in entries}) is expected, label


# --- Casos temporais D/E · versão efetiva --------------------------------


def test_only_the_latest_processed_version_enters_the_corpus(db: Session) -> None:
    """D e E: a versão nova substitui a anterior; a histórica sai do corpus."""
    institution = _institution(db, code=f"VER-{uuid.uuid4().hex[:6].upper()}")
    user = _user(db, institution)
    document = _document(db, institution, user)
    first = _version(db, document, user, version_number=1, content="primeira versao")

    before = collect_corpus_entries(db, _context(institution))
    assert _version_ids(before) == {first.id}

    second = _version(db, document, user, version_number=2, content="segunda versao")

    after = collect_corpus_entries(db, _context(institution))
    assert _version_ids(after) == {second.id}
    assert first.id not in _version_ids(after)


def test_a_new_version_changes_both_identities(db: Session) -> None:
    """T3: substituir a versão material altera corpus e snapshot."""
    institution = _institution(db, code=f"NEW-{uuid.uuid4().hex[:6].upper()}")
    user = _user(db, institution)
    document = _document(db, institution, user)
    _version(db, document, user, version_number=1, content="primeira versao")
    before = _snapshot(db, institution)

    _version(db, document, user, version_number=2, content="segunda versao")
    after = _snapshot(db, institution)

    assert after.corpus_digest != before.corpus_digest
    assert after.snapshot_id != before.snapshot_id


def test_unprocessed_version_does_not_become_the_effective_one(db: Session) -> None:
    """Uma versão `pending` não substitui a `processed` mais recente."""
    institution = _institution(db, code=f"PEN-{uuid.uuid4().hex[:6].upper()}")
    user = _user(db, institution)
    document = _document(db, institution, user)
    processed = _version(db, document, user, version_number=1)
    _version(db, document, user, version_number=2, processing_status="pending")

    entries = collect_corpus_entries(db, _context(institution))

    assert _version_ids(entries) == {processed.id}


# --- Casos F–H · estado, oficialidade e idioma ---------------------------


def test_inactive_document_is_excluded(db: Session) -> None:
    institution = _institution(db, code=f"INA-{uuid.uuid4().hex[:6].upper()}")
    user = _user(db, institution)
    document = _document(db, institution, user, is_active=False)
    _version(db, document, user)

    assert collect_corpus_entries(db, _context(institution)) == ()


def test_unofficial_document_is_excluded_only_when_official_only_is_set(db: Session) -> None:
    institution = _institution(db, code=f"OFF-{uuid.uuid4().hex[:6].upper()}")
    user = _user(db, institution)
    document = _document(db, institution, user, official_source=False)
    _version(db, document, user)

    restricted = collect_corpus_entries(db, _context(institution, official_only=True))
    permissive = collect_corpus_entries(db, _context(institution, official_only=False))

    assert restricted == ()
    assert _version_ids(permissive) != set()


def test_official_only_changes_the_corpus_and_the_snapshot(db: Session) -> None:
    institution = _institution(db, code=f"OF2-{uuid.uuid4().hex[:6].upper()}")
    user = _user(db, institution)
    official = _document(db, institution, user, title="Oficial", official_source=True)
    _version(db, official, user)
    unofficial = _document(db, institution, user, title="Não oficial", official_source=False)
    _version(db, unofficial, user)

    restricted = _snapshot(db, institution, official_only=True)
    permissive = _snapshot(db, institution, official_only=False)

    assert restricted.corpus_digest != permissive.corpus_digest
    assert restricted.snapshot_id != permissive.snapshot_id
    assert len(restricted.corpus) == 1
    assert len(permissive.corpus) == 2


def test_incompatible_language_is_excluded(db: Session) -> None:
    institution = _institution(db, code=f"LNG-{uuid.uuid4().hex[:6].upper()}")
    user = _user(db, institution)
    portuguese = _document(db, institution, user, title="PT", language="pt")
    _version(db, portuguese, user)
    english = _document(db, institution, user, title="EN", language="en")
    _version(db, english, user)

    in_portuguese = collect_corpus_entries(db, _context(institution, language="pt"))
    in_english = collect_corpus_entries(db, _context(institution, language="en"))

    assert {entry.document_id for entry in in_portuguese} == {portuguese.id}
    assert {entry.document_id for entry in in_english} == {english.id}


def test_chunk_language_divergent_from_the_document_is_excluded(db: Session) -> None:
    """C8 existe por si: um chunk histórico pode divergir do documento."""
    institution = _institution(db, code=f"CHL-{uuid.uuid4().hex[:6].upper()}")
    user = _user(db, institution)
    document = _document(db, institution, user, language="pt")
    version = _version(db, document, user)
    db.query(DocumentChunk).filter(DocumentChunk.document_version_id == version.id).update(
        {"language": "en"}
    )
    db.flush()

    assert collect_corpus_entries(db, _context(institution, language="pt")) == ()


# --- T5/T6/T9 · o que altera e o que não altera a identidade -------------


def test_ineligible_document_does_not_change_the_corpus_identity(db: Session) -> None:
    """T5: acrescentar documentos inelegíveis não move a identidade."""
    institution = _institution(db, code=f"IGN-{uuid.uuid4().hex[:6].upper()}")
    user = _user(db, institution)
    eligible = _document(db, institution, user, title="Elegível")
    _version(db, eligible, user)
    before = _snapshot(db, institution)

    inactive = _document(db, institution, user, title="Inativo", is_active=False)
    _version(db, inactive, user)
    expired = _document(db, institution, user, title="Expirado", valid_until=date(2020, 1, 1))
    _version(db, expired, user)
    unofficial = _document(db, institution, user, title="Oficioso", official_source=False)
    _version(db, unofficial, user)
    other_language = _document(db, institution, user, title="Inglês", language="en")
    _version(db, other_language, user)

    after = _snapshot(db, institution)

    assert after.corpus_digest == before.corpus_digest
    assert after.snapshot_id == before.snapshot_id


def test_irrelevant_document_metadata_does_not_change_the_identity(db: Session) -> None:
    """T9: a descrição não participa na recuperação, no ranking nem no contexto.

    A lista é curta de propósito. ``source_url`` **não** está aqui: é enviado
    ao gerador dentro do payload de evidência, pelo que é material — ver o
    teste seguinte.
    """
    institution = _institution(db, code=f"MET-{uuid.uuid4().hex[:6].upper()}")
    user = _user(db, institution)
    document = _document(db, institution, user, description="antes")
    _version(db, document, user)
    before = _snapshot(db, institution)

    document.description = "depois"
    db.flush()
    after = _snapshot(db, institution)

    assert after.corpus_digest == before.corpus_digest
    assert after.snapshot_id == before.snapshot_id


def test_source_url_changes_the_identity(db: Session) -> None:
    """H3: ``source_url`` chega ao gerador e é contexto experimental.

    ``app.answering.context.evidence_payload`` envia-o em cada evidência. Dois
    corpora que diferissem apenas no URL apresentariam ao modelo um contexto
    diferente; igualá-los afirmaria uma comparabilidade que não existe.
    """
    institution = _institution(db, code=f"URL-{uuid.uuid4().hex[:6].upper()}")
    user = _user(db, institution)
    document = _document(db, institution, user, source_url=None)
    _version(db, document, user)
    absent = _snapshot(db, institution)

    document.source_url = "https://example.invalid/documento"
    db.flush()
    present = _snapshot(db, institution)

    document.source_url = "https://example.invalid/outro"
    db.flush()
    changed = _snapshot(db, institution)

    assert absent.corpus[0].source_url is None
    assert absent.corpus_digest != present.corpus_digest
    assert present.corpus_digest != changed.corpus_digest


def test_renormalising_a_chunk_changes_the_identity(db: Session) -> None:
    """H1: ``normalized_content`` é o texto efetivamente pesquisado.

    É dele que a coluna gerada ``search_vector`` deriva. Alterá-lo sem tocar no
    conteúdo original muda o que a recuperação encontra — e tem de mudar a
    identidade.
    """
    institution = _institution(db, code=f"NRM-{uuid.uuid4().hex[:6].upper()}")
    user = _user(db, institution)
    document = _document(db, institution, user)
    version = _version(db, document, user)
    before = _snapshot(db, institution)

    db.query(DocumentChunk).filter(DocumentChunk.document_version_id == version.id).update(
        {"normalized_content": "texto normalizado de outra forma"}
    )
    db.flush()
    after = _snapshot(db, institution)

    assert after.corpus_digest != before.corpus_digest
    assert after.snapshot_id != before.snapshot_id


def test_content_hashes_are_recomputed_and_not_trusted_from_the_column(db: Session) -> None:
    """H1: a identidade deriva do conteúdo real, não do hash persistido.

    ``document_chunks.content_sha256`` é uma afirmação sobre o conteúdo. Se o
    conteúdo mudar e o hash persistido ficar desatualizado, uma identidade que
    confiasse na coluna declararia o corpus inalterado.
    """
    institution = _institution(db, code=f"RCP-{uuid.uuid4().hex[:6].upper()}")
    user = _user(db, institution)
    document = _document(db, institution, user)
    version = _version(db, document, user)
    before = _snapshot(db, institution)

    # Conteúdo alterado deixando o hash persistido intacto (estado que a
    # aplicação não produz, mas que SQL direto produziria).
    db.query(DocumentChunk).filter(DocumentChunk.document_version_id == version.id).update(
        {"content": "conteudo substituido sem atualizar o hash"}
    )
    db.flush()
    after = _snapshot(db, institution)

    assert after.corpus_digest != before.corpus_digest


def test_sql_computed_digest_matches_python_hashlib(db: Session) -> None:
    """O SHA-256 do PostgreSQL e o do ``hashlib`` têm de coincidir.

    O builder calcula os hashes de conteúdo na base para não trazer texto
    documental para memória; essa escolha só é legítima se o valor for o mesmo
    que a canonicalização em Python produziria.
    """
    institution = _institution(db, code=f"SHA-{uuid.uuid4().hex[:6].upper()}")
    user = _user(db, institution)
    document = _document(db, institution, user)
    content = "prazo de matricula no campus"
    _version(db, document, user, content=content)

    entries = collect_corpus_entries(db, _context(institution))
    stored = db.scalar(
        select(DocumentChunk.content_sha256).where(
            DocumentChunk.document_id == document.id
        )
    )

    expected = hashlib.sha256(content.encode("utf-8")).hexdigest()
    assert stored == expected
    assert entries[0].chunk_count == 1
    # O digest do chunk deriva do hash recalculado; recompor com o valor
    # esperado tem de reproduzir exatamente o mesmo valor.
    assert entries[0].chunk_digest == compute_chunk_digest(
        (
            ChunkIdentity(
                chunk_index=0,
                content_sha256=expected,
                normalized_content_sha256=hashlib.sha256(
                    content.lower().encode("utf-8")
                ).hexdigest(),
                section_title="Matrículas",
                structure_type="paragraph",
            ),
        )
    )


def test_document_title_changes_the_identity(db: Session) -> None:
    """O título entra no ranking (sobreposição com o título do documento)."""
    institution = _institution(db, code=f"TIT-{uuid.uuid4().hex[:6].upper()}")
    user = _user(db, institution)
    document = _document(db, institution, user, title="Antes")
    _version(db, document, user)
    before = _snapshot(db, institution)

    document.title = "Depois"
    db.flush()
    after = _snapshot(db, institution)

    assert after.corpus_digest != before.corpus_digest


def test_reference_date_that_changes_eligibility_changes_the_corpus(db: Session) -> None:
    """T6: a mesma base, lida em datas diferentes, é outro corpus."""
    institution = _institution(db, code=f"REF-{uuid.uuid4().hex[:6].upper()}")
    user = _user(db, institution)
    document = _document(db, institution, user, valid_from=date(2026, 6, 1))
    _version(db, document, user)

    before_validity = _snapshot(db, institution, reference_date=date(2026, 1, 1))
    during_validity = _snapshot(db, institution, reference_date=date(2026, 8, 13))

    assert before_validity.corpus == ()
    assert len(during_validity.corpus) == 1
    assert before_validity.corpus_digest != during_validity.corpus_digest
    assert before_validity.snapshot_id != during_validity.snapshot_id


def test_reference_date_is_explicit_and_never_defaults_to_today(db: Session) -> None:
    """A data é sempre recebida; nada aqui chama ``date.today()``."""
    institution = _institution(db, code=f"EXP-{uuid.uuid4().hex[:6].upper()}")
    user = _user(db, institution)
    _version(db, _document(db, institution, user), user)

    snapshot = _snapshot(db, institution, reference_date=date(2030, 5, 4))

    assert snapshot.reference_date == date(2030, 5, 4)
    assert snapshot.as_payload()["reference_date"] == "2030-05-04"


# --- T1/T2 sobre a base ---------------------------------------------------


def test_repeated_builds_over_unchanged_data_are_identical(db: Session) -> None:
    institution = _institution(db, code=f"REP-{uuid.uuid4().hex[:6].upper()}")
    user = _user(db, institution)
    for index in range(4):
        document = _document(db, institution, user, title=f"Documento {index}")
        _version(db, document, user, content=f"conteudo {index}")

    first = _snapshot(db, institution)
    second = _snapshot(db, institution)

    assert first.snapshot_id == second.snapshot_id
    assert first.corpus_digest == second.corpus_digest
    assert first.as_payload() == second.as_payload()


def test_rechunking_a_version_changes_the_identity(db: Session) -> None:
    """Resegmentar altera o que a recuperação devolve, sem trocar a versão."""
    institution = _institution(db, code=f"RCH-{uuid.uuid4().hex[:6].upper()}")
    user = _user(db, institution)
    document = _document(db, institution, user)
    version = _version(db, document, user)
    before = _snapshot(db, institution)

    _chunk(db, document, version, chunk_index=1, content="segmento adicional")
    after = _snapshot(db, institution)

    assert after.corpus_digest != before.corpus_digest
    assert after.corpus[0].chunk_count == 2
    assert before.corpus[0].chunk_count == 1


# --- T21 · isolamento institucional --------------------------------------


def test_snapshot_never_incorporates_another_institutions_documents(db: Session) -> None:
    """Corpora estruturalmente idênticos em dois locatários não colidem.

    Os documentos são construídos com o mesmo título, idioma, oficialidade e
    conteúdo; só os identificadores e a instituição diferem. Se o filtro
    institucional falhasse, os digests coincidiriam — ou pior, cada snapshot
    incluiria as versões do outro.
    """
    first = _institution(db, code=f"TNA-{uuid.uuid4().hex[:6].upper()}")
    second = _institution(db, code=f"TNB-{uuid.uuid4().hex[:6].upper()}")
    first_user = _user(db, first)
    second_user = _user(db, second)

    first_document = _document(db, first, first_user, title="Regulamento")
    first_version = _version(db, first_document, first_user, content="mesmo conteudo")
    second_document = _document(db, second, second_user, title="Regulamento")
    second_version = _version(db, second_document, second_user, content="mesmo conteudo")

    first_snapshot = _snapshot(db, first)
    second_snapshot = _snapshot(db, second)

    assert _version_ids(first_snapshot.corpus) == {first_version.id}
    assert _version_ids(second_snapshot.corpus) == {second_version.id}
    assert second_version.id not in _version_ids(first_snapshot.corpus)
    assert first_version.id not in _version_ids(second_snapshot.corpus)
    assert first_snapshot.corpus_digest != second_snapshot.corpus_digest
    assert first_snapshot.snapshot_id != second_snapshot.snapshot_id

    serialized = str(first_snapshot.as_payload())
    assert str(second.id) not in serialized
    assert str(second_document.id) not in serialized
    assert str(second_version.id) not in serialized


def test_empty_institution_produces_an_empty_but_valid_snapshot(db: Session) -> None:
    institution = _institution(db, code=f"EMP-{uuid.uuid4().hex[:6].upper()}")

    snapshot = _snapshot(db, institution)

    assert snapshot.corpus == ()
    assert len(snapshot.snapshot_id) == 64


# --- Configuração de recuperação lida do código --------------------------


def test_retrieval_configuration_is_read_from_the_implementation() -> None:
    """Os valores vêm do código real, não de constantes escritas à mão.

    Se o scoring subir de versão, se o limiar mudar ou se o orçamento de
    candidatos for recalculado, o snapshot acompanha sem ninguém editar isto.
    """
    from app.core.config import settings
    from app.retrieval.lexical import LEXICAL_SCORE_SEMANTICS, global_candidate_limit

    config = describe_retrieval_configuration(language="pt", top_k=5, official_only=True)

    from app.retrieval.lexical import LEXICAL_PIPELINE_VERSION

    assert config.strategy == "lexical"
    assert config.pipeline_version == LEXICAL_PIPELINE_VERSION
    assert config.scoring_version == LEXICAL_SCORE_SEMANTICS.version
    assert config.score_kind == "lexical_relevance"
    assert config.comparable_across_queries is False
    assert config.fts_config == "portuguese"
    assert config.min_relevance_score == settings.retrieval_min_relevance_score
    assert config.candidate_limit == global_candidate_limit(5)


def test_score_semantics_are_recorded_as_relevance_not_confidence() -> None:
    """O score lexical continua declarado como relevância.

    Um snapshot que o rotulasse como confiança convidaria a leitura errada na
    fase de medição, que é precisamente o que este campo existe para impedir.
    """
    config = describe_retrieval_configuration(language="pt", top_k=5, official_only=True)

    assert config.score_kind == "lexical_relevance"
    assert "confidence" not in config.canonical()
    assert config.comparable_across_queries is False


def test_language_changes_the_resolved_fts_configuration() -> None:
    portuguese = describe_retrieval_configuration(language="pt", top_k=5, official_only=True)
    english = describe_retrieval_configuration(language="en", top_k=5, official_only=True)
    other = describe_retrieval_configuration(language="fr", top_k=5, official_only=True)

    assert portuguese.fts_config == "portuguese"
    assert english.fts_config == "english"
    assert other.fts_config == "simple"
