"""Fase 4 da issue #24 — o diagnóstico consome ``RetrievalEligibility``.

Último consumidor a migrar, e o único cuja migração **muda um veredicto**: ao
delegar na política, o diagnóstico passa a avaliar C8 (idioma do chunk), que a
sua lista própria não incluía. Essa é a divergência D2 do Momento 6, e a sua
resolução está provada em
``test_moment06_evidence_eligibility_characterisation.py``, onde o cenário
histórico foi mantido e a expectativa atualizada.

O que este ficheiro fecha é outra coisa: a **fonte de verdade**. Comparar
resultados não bastaria — uma lista de condições reescrita à mão dentro do
diagnóstico produziria hoje exatamente os mesmos veredictos, com o import da
política por usar, e nada falharia. A lição das Fases 2 e 3 é que isso tem de
ser provado dinamicamente.

São três direções, e nenhuma basta sozinha:

1. a política é chamada, com o contexto, o sujeito e o ``effective_version_id``
   certos — espia;
2. o veredicto **decide** o campo ``eligible``: forçá-lo a negativo torna
   inelegível uma versão sã;
3. o veredicto **decide as condições relatadas**: uma condição forçada a
   negativa aparece negativa no relatório, mesmo quando a linha real a
   satisfaz. É esta que apanha a reintrodução de
   ``EligibilityCondition("document_active", document.is_active, ...)`` ao lado
   da chamada.

A matriz C1–C11 não é repetida aqui: pertence aos testes de composição e de
contrato da Fase 1.
"""

import uuid
from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.diagnostics import document_pipeline
from app.diagnostics.document_pipeline import (
    REPORTED_CONDITION_NAMES,
    SelectionContext,
    evaluate_eligibility,
    load_version_chunks,
    select_by_document_id,
)
from app.documents.retrievability import (
    ConditionOutcome,
    EvidencePolicy,
    RetrievabilityContext,
    RetrievabilitySubject,
    RetrievabilityVerdict,
    RetrievalEligibility,
)
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.document_version import DocumentVersion
from tests.moment06_support import (
    create_searchable_document,
    setup_institution_with_admin,
    upload_version,
)

CONTENT = "erasmus campus provedor alfa institucional"


class _PolicySpy:
    """Delega na política real e regista o que lhe foi pedido."""

    def __init__(self, policy: EvidencePolicy) -> None:
        self._policy = policy
        self.name = policy.name
        self.calls: list[tuple[RetrievabilitySubject, RetrievabilityContext]] = []

    def explain(
        self, subject: RetrievabilitySubject, context: RetrievabilityContext
    ) -> RetrievabilityVerdict:
        self.calls.append((subject, context))
        return self._policy.explain(subject, context)


class _ForcedVerdict:
    """Política de teste que responde sempre o mesmo, sem avaliar nada.

    ``failing`` nomeia as condições a devolver como não satisfeitas; todas as
    outras condições relatáveis vêm satisfeitas. O nome de cada uma é o nome
    canónico da política, para que a projeção do relatório as reconheça.
    """

    def __init__(self, *, failing: frozenset[str] = frozenset()) -> None:
        self.name = "ForcedForTest"
        self.failing = failing
        self.calls = 0

    def explain(
        self, subject: RetrievabilitySubject, context: RetrievabilityContext
    ) -> RetrievabilityVerdict:
        self.calls += 1
        outcomes = tuple(
            ConditionOutcome(
                name=name,
                satisfied=name not in self.failing,
                detail=f"forced outcome for {name}",
            )
            for name in REPORTED_CONDITION_NAMES
        )
        return RetrievabilityVerdict(
            policy=self.name,
            eligible=all(outcome.satisfied for outcome in outcomes),
            conditions=outcomes,
        )


def _healthy_selection(
    client: TestClient, db: Session
) -> tuple[SelectionContext, list[DocumentChunk], uuid.UUID, uuid.UUID]:
    """Documento real, processado e admissível, com os chunks da versão efetiva."""
    _, headers, _ = setup_institution_with_admin(client)
    document, _version = create_searchable_document(client, headers, CONTENT)
    document_id = uuid.UUID(document["id"])
    institution_id = db.get(Document, document_id).institution_id  # type: ignore[union-attr]
    selection = select_by_document_id(
        db, institution_id=institution_id, document_id=document_id
    )
    effective = selection.effective_retrieval_version
    assert effective is not None
    return selection, load_version_chunks(db, effective), institution_id, effective.id


# --- A fonte de verdade -------------------------------------------------------


def test_the_diagnostic_no_longer_defines_documental_admissibility_itself() -> None:
    """Importa a política de recuperação, e só essa."""
    assert document_pipeline.RetrievalEligibility is RetrievalEligibility
    # A política de persistência responde a outra pergunta — "podia ter sido
    # citada então" — e não pertence a um diagnóstico de recuperabilidade.
    assert not hasattr(document_pipeline, "CitationPersistenceEligibility")


def test_the_policy_used_by_the_diagnostic_is_the_one_that_includes_c5() -> None:
    """O diagnóstico pergunta "agora"; por isso C5 tem de fazer parte."""
    assert RetrievalEligibility.requires_latest_processed_version is True
    assert "version_is_highest_processed" in RetrievalEligibility.condition_names


def test_c1_to_c3_are_evaluated_by_the_policy_but_not_exposed(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> None:
    """O isolamento institucional continua no SQL, não na superfície do relatório.

    A política avalia C1–C3; o relatório nunca as mostrou, porque as consultas
    do diagnóstico já restringem ``institution_id``. Expô-las agora alargaria a
    superfície sem acrescentar informação.
    """
    institutional = (
        "chunk_belongs_to_institution",
        "document_belongs_to_institution",
        "version_belongs_to_institution",
    )
    for name in institutional:
        assert name in RetrievalEligibility.condition_names
        assert name not in REPORTED_CONDITION_NAMES

    with test_session_factory() as db:
        selection, chunks, _institution_id, _effective_id = _healthy_selection(client, db)
        eligibility = evaluate_eligibility(
            selection,
            selection.effective_retrieval_version,
            question_language="pt",
            reference_date=datetime.now(UTC).date(),
            official_only=True,
            chunks=chunks,
        )

    reported = tuple(condition.name for condition in eligibility.conditions)
    assert reported == REPORTED_CONDITION_NAMES
    for name in institutional:
        assert name not in reported


def test_the_verdict_is_obtained_from_the_policy(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Uma chamada real a ``explain``, com o contexto e o sujeito da linha.

    Não se afirma quantas condições a política tem — isso é matéria do teste de
    composição da Fase 1. Afirma-se **de onde** vem o veredicto.
    """
    reference_date = date(2031, 3, 1)
    spy = _PolicySpy(RetrievalEligibility)
    monkeypatch.setattr(document_pipeline, "RetrievalEligibility", spy)

    with test_session_factory() as db:
        selection, chunks, institution_id, effective_id = _healthy_selection(client, db)
        eligibility = evaluate_eligibility(
            selection,
            selection.effective_retrieval_version,
            question_language="pt",
            reference_date=reference_date,
            official_only=True,
            chunks=chunks,
        )

    # Uma avaliação por chunk: a política avalia candidatos, não versões.
    assert len(spy.calls) == len(chunks)
    assert spy.calls

    expected_context = RetrievabilityContext(
        institution_id=institution_id,
        language="pt",
        reference_date=reference_date,
        official_only=True,
    )
    assert [context for _subject, context in spy.calls] == [expected_context] * len(chunks)

    subjects = [subject for subject, _context in spy.calls]
    assert {subject.chunk_id for subject in subjects} == {chunk.id for chunk in chunks}
    for subject in subjects:
        assert subject.version_id == effective_id
        assert subject.chunk_document_version_id == effective_id
        # C5 é resolvida pela mesma versão efetiva que a seleção já determinou.
        assert subject.effective_version_id == effective_id

    assert eligibility.eligible is True
    assert eligibility.policy == RetrievalEligibility.name


def test_c5_is_evaluated_against_the_effective_version(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> None:
    """Uma versão superada falha C5 — e o diagnóstico obtém-na da política.

    A versão 1 continua ``processed`` e o documento continua admissível: a
    única condição que falha é a de ser a ``processed`` mais recente.
    """
    _, headers, _ = setup_institution_with_admin(client)
    document, first = create_searchable_document(client, headers, CONTENT)
    second = upload_version(client, headers, document["id"], f"{CONTENT} atualizado")
    document_id = uuid.UUID(document["id"])
    first_id = uuid.UUID(first["id"])

    with test_session_factory() as db:
        institution_id = db.get(Document, document_id).institution_id  # type: ignore[union-attr]
        selection = select_by_document_id(
            db, institution_id=institution_id, document_id=document_id
        )
        superseded = db.get(DocumentVersion, first_id)
        assert superseded is not None
        eligibility = evaluate_eligibility(
            selection,
            superseded,
            question_language="pt",
            reference_date=datetime.now(UTC).date(),
            official_only=True,
            chunks=load_version_chunks(db, superseded),
        )

    assert selection.effective_retrieval_version is not None
    assert str(selection.effective_retrieval_version.id) == second["id"]
    failed = tuple(
        condition.name for condition in eligibility.conditions if not condition.satisfied
    )
    assert failed == ("version_is_highest_processed",)
    assert eligibility.eligible is False


# --- O veredicto decide, e é a única definição --------------------------------


def test_a_negative_verdict_makes_a_healthy_version_ineligible(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """O valor devolvido é consumido, não apenas pedido."""
    forced = _ForcedVerdict(failing=frozenset({"document_active"}))
    monkeypatch.setattr(document_pipeline, "RetrievalEligibility", forced)

    with test_session_factory() as db:
        selection, chunks, _institution_id, _effective_id = _healthy_selection(client, db)
        eligibility = evaluate_eligibility(
            selection,
            selection.effective_retrieval_version,
            question_language="pt",
            reference_date=datetime.now(UTC).date(),
            official_only=True,
            chunks=chunks,
        )
        # A linha real está sã: é o veredicto que decide, não a coluna.
        assert selection.document.is_active is True

    assert forced.calls == len(chunks)
    assert eligibility.eligible is False


def test_the_reported_conditions_come_from_the_verdict(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Nenhuma condição do relatório é recalculada ao lado da política.

    Cada condição relatável é forçada a negativa, uma de cada vez, sobre um
    documento real que as satisfaz todas. Se alguma continuasse a ser decidida
    por ``document.is_active``, ``version.processing_status`` ou equivalente, a
    condição correspondente apareceria satisfeita e este teste falharia nela.
    """
    with test_session_factory() as db:
        selection, chunks, _institution_id, _effective_id = _healthy_selection(client, db)

        for name in REPORTED_CONDITION_NAMES:
            forced = _ForcedVerdict(failing=frozenset({name}))
            monkeypatch.setattr(document_pipeline, "RetrievalEligibility", forced)
            eligibility = evaluate_eligibility(
                selection,
                selection.effective_retrieval_version,
                question_language="pt",
                reference_date=datetime.now(UTC).date(),
                official_only=True,
                chunks=chunks,
            )
            failed = tuple(
                condition.name
                for condition in eligibility.conditions
                if not condition.satisfied
            )
            assert failed == (name,), f"{name} não veio do veredicto: {failed}"
            assert eligibility.eligible is False


def test_a_positive_verdict_accepts_what_the_real_policy_would_reject(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A política é a **única** definição da admissibilidade documental.

    A versão 1 é superada pela 2, pelo que a política real a recusa por C5. Com
    o veredicto forçado a positivo, o diagnóstico aceita-a — o que só é
    possível se nenhuma comparação paralela entre a versão selecionada e a
    versão efetiva tiver sobrevivido dentro de ``evaluate_eligibility``.
    """
    _, headers, _ = setup_institution_with_admin(client)
    document, first = create_searchable_document(client, headers, CONTENT)
    upload_version(client, headers, document["id"], f"{CONTENT} atualizado")
    document_id = uuid.UUID(document["id"])

    with test_session_factory() as db:
        institution_id = db.get(Document, document_id).institution_id  # type: ignore[union-attr]
        selection = select_by_document_id(
            db, institution_id=institution_id, document_id=document_id
        )
        superseded = db.get(DocumentVersion, uuid.UUID(first["id"]))
        assert superseded is not None
        chunks = load_version_chunks(db, superseded)

        forced = _ForcedVerdict()
        monkeypatch.setattr(document_pipeline, "RetrievalEligibility", forced)
        eligibility = evaluate_eligibility(
            selection,
            superseded,
            question_language="pt",
            reference_date=datetime.now(UTC).date(),
            official_only=True,
            chunks=chunks,
        )

    assert forced.calls == len(chunks)
    assert eligibility.eligible is True
    assert all(condition.satisfied for condition in eligibility.conditions)


# --- O que continua a pertencer ao diagnóstico --------------------------------


def test_c12_stays_outside_the_policy(
    client: TestClient,
    test_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """"Existe alguma versão processed?" não é condição sobre uma linha.

    Sem versão efetiva não há sujeito para avaliar: a política não chega a ser
    chamada, e o relatório mantém a sua condição própria.
    """
    spy = _PolicySpy(RetrievalEligibility)
    monkeypatch.setattr(document_pipeline, "RetrievalEligibility", spy)

    _, headers, _ = setup_institution_with_admin(client)
    document, _version = create_searchable_document(client, headers, CONTENT)
    document_id = uuid.UUID(document["id"])

    with test_session_factory() as db:
        institution_id = db.get(Document, document_id).institution_id  # type: ignore[union-attr]
        selection = select_by_document_id(
            db, institution_id=institution_id, document_id=document_id
        )
        eligibility = evaluate_eligibility(
            selection,
            None,
            question_language="pt",
            reference_date=datetime.now(UTC).date(),
            official_only=True,
            chunks=(),
        )

    assert spy.calls == []
    assert [condition.name for condition in eligibility.conditions] == [
        "processed_version_exists"
    ]
    assert "processed_version_exists" not in RetrievalEligibility.condition_names
    assert eligibility.eligible is False
    # Mesmo sem política avaliada, o relatório diz a que pergunta responde.
    assert eligibility.policy == RetrievalEligibility.name


def test_the_report_declares_the_policy_it_evaluated(
    client: TestClient, test_session_factory: sessionmaker[Session]
) -> None:
    """O relatório distingue recuperabilidade atual de proveniência histórica.

    Sem esta identificação, "não elegível" podia ser lido como um juízo sobre
    citações já persistidas — que nenhuma política reavalia.
    """
    from app.retrieval.lexical import PostgresLexicalRetriever

    _, headers, _ = setup_institution_with_admin(client)
    document, _version = create_searchable_document(client, headers, CONTENT)

    question = document_pipeline.parse_questions_payload(
        [
            {
                "id": "q1",
                "question": "Onde fica o campus?",
                "language": "pt",
                "expected_answer": "campus",
                "expected_facts": [{"name": "campus", "alternatives": ["campus"]}],
            }
        ]
    )
    document_id = uuid.UUID(document["id"])
    with test_session_factory() as db:
        institution_id = db.get(Document, document_id).institution_id  # type: ignore[union-attr]
        report = document_pipeline.run_diagnostic(
            db,
            PostgresLexicalRetriever(),
            institution_id=institution_id,
            questions=question,
            document_id=document_id,
        )

    eligibility = report.questions[0].effective_version_eligibility
    assert eligibility.policy == "RetrievalEligibility"

    rendered = document_pipeline.render_markdown(report)
    assert "- Política avaliada: RetrievalEligibility (recuperabilidade atual)" in rendered

    payload = document_pipeline.render_json(report)
    assert '"policy": "RetrievalEligibility"' in payload
    # O relatório continua a ser sobre recuperabilidade, não sobre citações.
    assert "CitationPersistenceEligibility" not in payload
