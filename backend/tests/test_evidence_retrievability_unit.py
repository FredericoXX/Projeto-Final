"""Fase 1 da issue #24 — veredicto Python e composição das políticas.

Testes puros, sem PostgreSQL: exercitam o adaptador Python de
:mod:`app.documents.retrievability` sobre sujeitos construídos à mão. O estilo
segue o prior art de ``test_lexical_eligibility.py``, que já testa uma função
pura sobre sinais.

Estes testes conhecem **nomes de condições e comportamento**, nunca a ordem
nem a quantidade de condições da lista interna. A exceção deliberada é o teste
de composição: aí o conjunto de condições *é* o comportamento em causa.
"""

from datetime import date
from uuid import UUID

import pytest

from app.documents.retrievability import (
    BASE_CONDITIONS,
    LATEST_PROCESSED_VERSION,
    CitationPersistenceEligibility,
    RetrievabilityContext,
    RetrievabilitySubject,
    RetrievalEligibility,
)

INSTITUTION_ID = UUID("11111111-1111-4111-8111-111111111111")
OTHER_INSTITUTION_ID = UUID("22222222-2222-4222-8222-222222222222")
DOCUMENT_ID = UUID("33333333-3333-4333-8333-333333333333")
VERSION_ID = UUID("44444444-4444-4444-8444-444444444444")
CHUNK_ID = UUID("55555555-5555-4555-8555-555555555555")
NEWER_VERSION_ID = UUID("66666666-6666-4666-8666-666666666666")

REFERENCE_DATE = date(2026, 8, 11)


def _context(**overrides: object) -> RetrievabilityContext:
    values: dict = {
        "institution_id": INSTITUTION_ID,
        "language": "pt",
        "reference_date": REFERENCE_DATE,
        "official_only": True,
    }
    values.update(overrides)
    return RetrievabilityContext(**values)


def _subject(**overrides: object) -> RetrievabilitySubject:
    """Sujeito que satisfaz **todas** as condições; cada teste viola uma."""
    values: dict = {
        "chunk_id": CHUNK_ID,
        "chunk_institution_id": INSTITUTION_ID,
        "chunk_document_id": DOCUMENT_ID,
        "chunk_document_version_id": VERSION_ID,
        "chunk_language": "pt",
        "document_id": DOCUMENT_ID,
        "document_institution_id": INSTITUTION_ID,
        "document_is_active": True,
        "document_language": "pt",
        "document_official_source": True,
        "document_valid_from": None,
        "document_valid_until": None,
        "version_id": VERSION_ID,
        "version_institution_id": INSTITUTION_ID,
        "version_document_id": DOCUMENT_ID,
        "version_processing_status": "processed",
        "effective_version_id": VERSION_ID,
    }
    values.update(overrides)
    return RetrievabilitySubject(**values)


# --- Caso positivo -------------------------------------------------------------


def test_compliant_subject_satisfies_both_policies() -> None:
    subject, context = _subject(), _context()

    for policy in (RetrievalEligibility, CitationPersistenceEligibility):
        verdict = policy.explain(subject, context)
        assert verdict.eligible is True, policy.name
        assert verdict.failed_condition_names == (), policy.name
        assert verdict.policy == policy.name
        # Cada condição da política aparece no veredicto, com detalhe legível.
        assert len(verdict.conditions) == len(policy.conditions)
        assert all(outcome.detail for outcome in verdict.conditions)


# --- Uma violação isolada por condição da política base -------------------------


@pytest.mark.parametrize(
    ("overrides", "expected_failure"),
    [
        # C1 — o chunk pertence a outra instituição.
        ({"chunk_institution_id": OTHER_INSTITUTION_ID}, "chunk_belongs_to_institution"),
        # C2 — o documento pertence a outra instituição.
        (
            {"document_institution_id": OTHER_INSTITUTION_ID},
            "document_belongs_to_institution",
        ),
        # C3 — a versão pertence a outra instituição.
        (
            {"version_institution_id": OTHER_INSTITUTION_ID},
            "version_belongs_to_institution",
        ),
        # C4 — a versão não está processed.
        ({"version_processing_status": "failed"}, "version_processed"),
        ({"version_processing_status": "pending"}, "version_processed"),
        ({"version_processing_status": "processing"}, "version_processed"),
        # C6 — o documento está inativo.
        ({"document_is_active": False}, "document_active"),
        # C7 — o idioma do documento difere do contexto.
        ({"document_language": "en"}, "language_compatible"),
        # C8 — o idioma do chunk difere do contexto, com C7 satisfeita.
        ({"chunk_language": "en"}, "chunk_language_compatible"),
        # C9 — valid_from ainda no futuro.
        ({"document_valid_from": date(2026, 8, 12)}, "valid_from_compatible"),
        # C10 — valid_until já expirado.
        ({"document_valid_until": date(2026, 8, 10)}, "valid_until_compatible"),
        # C11 — documento não oficial, com official_only ativo.
        ({"document_official_source": False}, "official_source_compatible"),
    ],
)
def test_each_base_condition_can_fail_in_isolation(
    overrides: dict, expected_failure: str
) -> None:
    """Cada condição da base falha sozinha e é nomeada no veredicto.

    A asserção é sobre o **nome estável** da condição, não sobre a sua posição
    na lista: um administrador tem de conseguir citá-la sem ambiguidade.
    """
    verdict = CitationPersistenceEligibility.explain(_subject(**overrides), _context())

    assert verdict.eligible is False
    assert verdict.failed_condition_names == (expected_failure,)

    # A mesma violação reprova igualmente na política de recuperação: as
    # condições da base são comuns às duas.
    retrieval_verdict = RetrievalEligibility.explain(_subject(**overrides), _context())
    assert retrieval_verdict.eligible is False
    assert expected_failure in retrieval_verdict.failed_condition_names


# --- C5, exclusiva de RetrievalEligibility --------------------------------------


@pytest.mark.parametrize(
    "effective_version_id",
    [NEWER_VERSION_ID, None],
    ids=["versão superada por outra processed", "nenhuma versão processed"],
)
def test_c5_fails_only_for_retrieval_and_never_for_citation_persistence(
    effective_version_id: UUID | None,
) -> None:
    """A diferença de proveniência histórica, no adaptador Python.

    O mesmo sujeito é inadmissível para recuperação e admissível para
    persistência de citação. Não é um defeito: é a Decisão 7 da issue #24.
    """
    subject = _subject(effective_version_id=effective_version_id)
    context = _context()

    retrieval = RetrievalEligibility.explain(subject, context)
    assert retrieval.eligible is False
    assert retrieval.failed_condition_names == ("version_is_highest_processed",)

    citation = CitationPersistenceEligibility.explain(subject, context)
    assert citation.eligible is True
    assert citation.failed_condition_names == ()
    # C5 nem sequer é avaliada nesta política.
    assert "version_is_highest_processed" not in {
        outcome.name for outcome in citation.conditions
    }


# --- Casos-limite de C9/C10 (Decisão 5) -----------------------------------------


@pytest.mark.parametrize(
    ("valid_from", "valid_until"),
    [
        (None, None),
        (None, REFERENCE_DATE),
        (REFERENCE_DATE, None),
        (REFERENCE_DATE, REFERENCE_DATE),
        (date(2026, 1, 1), date(2026, 12, 31)),
    ],
    ids=[
        "ambos NULL",
        "valid_from NULL, valid_until no limite exato",
        "valid_from no limite exato, valid_until NULL",
        "ambos exatamente na data de referência",
        "intervalo aberto em redor da data",
    ],
)
def test_validity_boundaries_are_inclusive_and_null_is_permissive(
    valid_from: date | None, valid_until: date | None
) -> None:
    """``NULL`` é permissivo e os limites são inclusivos, nos dois campos."""
    subject = _subject(
        document_valid_from=valid_from, document_valid_until=valid_until
    )
    verdict = RetrievalEligibility.explain(subject, _context())
    assert verdict.eligible is True, verdict.failed_condition_names


def test_validity_is_rejected_one_day_outside_each_boundary() -> None:
    just_after = _subject(document_valid_from=date(2026, 8, 12))
    just_before = _subject(document_valid_until=date(2026, 8, 10))

    assert RetrievalEligibility.explain(just_after, _context()).failed_condition_names == (
        "valid_from_compatible",
    )
    assert RetrievalEligibility.explain(just_before, _context()).failed_condition_names == (
        "valid_until_compatible",
    )


# --- C11 nos dois estados do flag ------------------------------------------------


@pytest.mark.parametrize("official_source", [True, False])
def test_official_only_disabled_admits_both_kinds_of_source(official_source: bool) -> None:
    """Com ``official_only`` desligado, C11 satisfaz-se sempre."""
    subject = _subject(document_official_source=official_source)
    verdict = RetrievalEligibility.explain(subject, _context(official_only=False))
    assert verdict.eligible is True, verdict.failed_condition_names


def test_official_only_enabled_rejects_only_the_unofficial_source() -> None:
    context = _context(official_only=True)
    assert RetrievalEligibility.explain(_subject(), context).eligible is True
    rejected = RetrievalEligibility.explain(
        _subject(document_official_source=False), context
    )
    assert rejected.failed_condition_names == ("official_source_compatible",)


# --- C7/C8: etiquetas que diferem apenas em maiúsculas ---------------------------


@pytest.mark.parametrize(
    ("field", "expected_failure"),
    [
        ("document_language", "language_compatible"),
        ("chunk_language", "chunk_language_compatible"),
    ],
)
def test_language_comparison_is_case_sensitive(field: str, expected_failure: str) -> None:
    """Comparação por code point: ``'PT'`` não satisfaz um contexto ``'pt'``.

    O teste de contrato confirma que o PostgreSQL concorda, sob a collation
    determinística em uso.
    """
    verdict = RetrievalEligibility.explain(_subject(**{field: "PT"}), _context())
    assert verdict.eligible is False
    assert verdict.failed_condition_names == (expected_failure,)


# --- Várias violações simultâneas -------------------------------------------------


def test_all_failed_conditions_are_reported_not_only_the_first() -> None:
    """O veredicto explica tudo o que falhou, para orientar a correção."""
    subject = _subject(
        document_is_active=False,
        document_language="en",
        document_official_source=False,
    )
    verdict = CitationPersistenceEligibility.explain(subject, _context())

    assert verdict.eligible is False
    assert set(verdict.failed_condition_names) == {
        "document_active",
        "language_compatible",
        "official_source_compatible",
    }


# --- Teste de composição ----------------------------------------------------------


def test_citation_persistence_is_exactly_the_base_policy() -> None:
    assert CitationPersistenceEligibility.conditions == BASE_CONDITIONS


def test_retrieval_is_the_base_policy_plus_the_latest_processed_version() -> None:
    assert RetrievalEligibility.conditions == (*BASE_CONDITIONS, LATEST_PROCESSED_VERSION)


def test_the_only_difference_between_the_two_policies_is_c5() -> None:
    """O teste que impede a fusão acidental das duas políticas.

    Compara **conjuntos de nomes**, não contagens nem ocorrências textuais no
    código. Falha se alguém acrescentar C5 à persistência de citações — o que
    destruiria a proveniência histórica — ou se acrescentar uma condição a uma
    política sem decidir se pertence à base.
    """
    retrieval = set(RetrievalEligibility.condition_names)
    citation = set(CitationPersistenceEligibility.condition_names)

    assert retrieval - citation == {"version_is_highest_processed"}
    assert citation - retrieval == set()
    assert citation == set(condition.name for condition in BASE_CONDITIONS)

    # E a mesma verdade pelo lado do adaptador SQL.
    assert RetrievalEligibility.requires_latest_processed_version is True
    assert CitationPersistenceEligibility.requires_latest_processed_version is False


def test_condition_names_are_unique_and_stable() -> None:
    """Nomes duplicados tornariam o veredicto ambíguo para quem o lê."""
    for policy in (RetrievalEligibility, CitationPersistenceEligibility):
        names = policy.condition_names
        assert len(set(names)) == len(names), policy.name

    # Os nomes que o diagnóstico já usa são preservados exatamente, para que a
    # Fase 4 seja delegação e não renomeação.
    assert {
        "version_processed",
        "version_is_highest_processed",
        "document_active",
        "language_compatible",
        "valid_from_compatible",
        "valid_until_compatible",
        "official_source_compatible",
    } <= set(RetrievalEligibility.condition_names)
