"""Testes do mecanismo de avaliação offline (Momento 5, Fase 2).

Não usam base de dados, storage, rede nem fornecedor. As fixtures autouse
do conftest que preparam a base de dados são anuladas neste módulo.

Limitação declarada, igual à da Fase 1: o pytest importa
`tests/conftest.py` ao coletar, e esse ficheiro importa a aplicação e as
Settings. A garantia forte sobre credenciais vive no teste em subprocesso
de `test_evaluation_cli.py`, que é o caminho real de execução.
"""

import re
import socket
from typing import Any

import pytest
from pydantic import ValidationError

from app.answering.base import GeneratedAnswer, InvalidGeneratedAnswerError
from app.answering.fallback import get_fallback_message
from app.answering.validation import validate_generated_answer
from app.core.config import settings
from app.evaluation.assets import load_corpus
from app.evaluation.contracts import Corpus, CorpusCase, normalize_literal_text
from app.evaluation.harness import (
    HARNESS_TOP_K,
    SYNTHETIC_INSTITUTION_ID,
    FakeAnswerGenerator,
    FakeRetriever,
    SentinelSession,
    UnexpectedDatabaseAccess,
    answering_limits,
    build_evidence,
    synthetic_institution,
    synthetic_user,
)
from app.evaluation.results import (
    MetricStatus,
    canonical_json,
    compute_result_digest,
)
from app.evaluation.runner import (
    CaseObservation,
    evaluate_case,
    metric_a1,
    metric_a2,
    metric_a3,
    metric_a4,
    metric_a5,
    metric_a6,
    metric_a7,
    metric_a8,
    observe_case,
    run_offline_evaluation,
)
from app.models.document import Document
from app.models.institution import Institution
from app.schemas.answering import AnsweringRequest
from app.services import answering_service

PASS = MetricStatus.PASS
FAIL = MetricStatus.FAIL
NA = MetricStatus.NOT_APPLICABLE

UUID_PATTERN = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)


# --- Anulação das fixtures de base de dados do conftest ------------------------


@pytest.fixture(scope="session", autouse=True)
def _override_get_db() -> None:
    """Anula a fixture homónima do conftest: aqui não há dependência de DB."""


@pytest.fixture(autouse=True)
def _clean_tables() -> None:
    """Anula a fixture homónima do conftest: aqui não há tabelas a truncar."""


# --- Auxiliares ---------------------------------------------------------------


@pytest.fixture(scope="module")
def corpus() -> Corpus:
    return load_corpus()


@pytest.fixture(scope="module")
def evaluation(corpus: Corpus) -> Any:
    return run_offline_evaluation()


def _case(corpus: Corpus, case_id: str) -> CorpusCase:
    for case in corpus.cases:
        if case.case_id == case_id:
            return case
    msg = f"caso {case_id} ausente do corpus"
    raise AssertionError(msg)


def _result(evaluation: Any, case_id: str) -> Any:
    for result in evaluation.cases:
        if result.case_id == case_id:
            return result
    msg = f"resultado {case_id} ausente"
    raise AssertionError(msg)


def _observation(**overrides: Any) -> CaseObservation:
    values: dict[str, Any] = {
        "outcome": "answered",
        "status": "answered",
        "reason_code": None,
        "generator_called": True,
        "generator_call_count": 1,
        "context_evidence_ids": ("E1",),
        "emitted_evidence_ids": ("E1",),
        "response_evidence_ids": ("E1",),
        "observed_text": "Resposta sintética.",
    }
    values.update(overrides)
    return CaseObservation(**values)


# --- Execução dos 19 casos -----------------------------------------------------


def test_all_nineteen_cases_are_executed(evaluation: Any) -> None:
    assert evaluation.case_count == 19
    assert len(evaluation.cases) == 19
    assert [result.case_id for result in evaluation.cases] == [
        f"C{index:03d}" for index in range(1, 20)
    ]


def test_results_envelope_records_population_and_versions(evaluation: Any) -> None:
    assert evaluation.population == "P1"
    assert evaluation.corpus_version == "1.0.0"
    assert evaluation.rubric_version == "1.0.0"
    assert evaluation.execution_config.max_answer_chars == 4000
    assert evaluation.execution_config.max_context_chars == 12000


def test_every_case_reaches_its_expected_outcome(evaluation: Any) -> None:
    for result in evaluation.cases:
        assert result.observed_outcome == result.expected_outcome, result.case_id
        assert result.metrics.A7.status is PASS, result.case_id


def test_the_five_real_reason_codes_are_observed(evaluation: Any) -> None:
    observed = {
        result.observed_reason_code
        for result in evaluation.cases
        if result.observed_outcome == "rejected"
    }
    assert observed == {
        "empty_answer",
        "answer_too_long",
        "missing_citations",
        "duplicate_evidence_ids",
        "unknown_evidence_ids",
    }


def test_rejections_pass_through_the_real_validation(
    corpus: Corpus, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Prova que o runner não reimplementa a validação.

    Substituir `validate_generated_answer` no serviço faz o caso rejeitado
    falhar de outra maneira; se o runner tivesse lógica própria, o
    resultado não mudaria.
    """
    sentinel = RuntimeError("validação real substituída")

    def _explode(*args: Any, **kwargs: Any) -> Any:
        raise sentinel

    monkeypatch.setattr(answering_service, "validate_generated_answer", _explode)
    case = _case(corpus, "C015")
    with answering_limits(corpus.execution_config), pytest.raises(RuntimeError) as excinfo:
        observe_case(case, corpus.execution_config)
    assert excinfo.value is sentinel


def test_real_validation_raises_the_typed_error() -> None:
    """O `reason_code` que o runner observa vem desta exceção, não dele."""
    with pytest.raises(InvalidGeneratedAnswerError) as excinfo:
        validate_generated_answer(
            GeneratedAnswer(answer="", cited_evidence_ids=("E1",)), {"E1"}, 4000
        )
    assert excinfo.value.reason_code == "empty_answer"


# --- Harness -------------------------------------------------------------------


def test_requests_use_top_k_one_and_the_retriever_records_it(corpus: Corpus) -> None:
    case = _case(corpus, "C001")
    retriever = FakeRetriever(evidence=build_evidence(case))
    institution = synthetic_institution(corpus.execution_config.institution_name)
    session = SentinelSession(institution=institution)
    generator = FakeAnswerGenerator(
        generated=GeneratedAnswer(answer="Resposta.", cited_evidence_ids=("E1",))
    )
    request = AnsweringRequest(
        query=case.question, language="pt", top_k=HARNESS_TOP_K, official_only=True
    )
    with answering_limits(corpus.execution_config):
        answering_service.ask(
            session,  # type: ignore[arg-type]
            synthetic_user(),
            request,
            retriever,
            generator,
        )
    assert retriever.calls == [{"top_k": 1, "official_only": True}]
    assert HARNESS_TOP_K == 1


def test_answering_limits_are_restored_after_the_run(corpus: Corpus) -> None:
    original_answer = settings.answering_max_answer_chars
    original_context = settings.answering_max_context_chars
    run_offline_evaluation()
    assert settings.answering_max_answer_chars == original_answer
    assert settings.answering_max_context_chars == original_context


def test_answering_limits_are_restored_when_a_case_raises(corpus: Corpus) -> None:
    original_answer = settings.answering_max_answer_chars
    original_context = settings.answering_max_context_chars
    with pytest.raises(RuntimeError), answering_limits(corpus.execution_config):
        assert settings.answering_max_answer_chars == corpus.execution_config.max_answer_chars
        msg = "falha simulada a meio da avaliação"
        raise RuntimeError(msg)
    assert settings.answering_max_answer_chars == original_answer
    assert settings.answering_max_context_chars == original_context


def test_sentinel_session_serves_only_the_synthetic_institution() -> None:
    institution = synthetic_institution("Instituição Sintética de Avaliação")
    session = SentinelSession(institution=institution)
    assert session.get(Institution, SYNTHETIC_INSTITUTION_ID) is institution
    assert session.accesses == [("Institution", str(SYNTHETIC_INSTITUTION_ID))]


def test_sentinel_session_rejects_another_entity_or_id() -> None:
    institution = synthetic_institution("Instituição Sintética de Avaliação")
    session = SentinelSession(institution=institution)
    with pytest.raises(UnexpectedDatabaseAccess):
        session.get(Document, SYNTHETIC_INSTITUTION_ID)
    with pytest.raises(UnexpectedDatabaseAccess):
        session.get(Institution, "outro-id")


@pytest.mark.parametrize("attribute", ["execute", "query", "add", "commit", "flush", "scalars"])
def test_sentinel_session_rejects_any_other_access(attribute: str) -> None:
    session = SentinelSession(institution=synthetic_institution("Sintética"))
    with pytest.raises(UnexpectedDatabaseAccess):
        getattr(session, attribute)


def test_evidence_derivation_is_deterministic_and_groups_by_document(corpus: Corpus) -> None:
    case = _case(corpus, "C002")
    first = build_evidence(case)
    second = build_evidence(case)
    assert [item.chunk_id for item in first] == [item.chunk_id for item in second]
    # C002 tem duas evidências do mesmo document_ref (D1).
    assert first[0].document_id == first[1].document_id
    assert first[0].document_version_id == first[1].document_version_id
    assert first[0].chunk_id != first[1].chunk_id
    assert [item.chunk_index for item in first] == [0, 1]
    assert all(item.score == 1.0 for item in first)


# --- A1 ------------------------------------------------------------------------


def test_metric_a1(corpus: Corpus) -> None:
    case = _case(corpus, "C001")
    assert metric_a1(case, _observation()).status is PASS
    assert metric_a1(case, _observation(status="insufficient_evidence")).status is FAIL
    assert metric_a1(case, _observation(outcome="rejected", status=None)).status is NA


# --- A2 ------------------------------------------------------------------------


def test_metric_a2(corpus: Corpus) -> None:
    case = _case(corpus, "C001")
    assert metric_a2(case, _observation()).status is PASS
    failing = metric_a2(case, _observation(emitted_evidence_ids=("E1", "E9")))
    assert failing.status is FAIL
    assert failing.unknown_count == 1
    absent = metric_a2(case, _observation(generator_called=False, generator_call_count=0))
    assert absent.status is NA


def test_metric_a2_records_only_the_count_not_the_ids(corpus: Corpus) -> None:
    case = _case(corpus, "C001")
    result = metric_a2(case, _observation(emitted_evidence_ids=("E1", "E9", "E42")))
    assert result.unknown_count == 2
    assert "E42" not in canonical_json(result.model_dump(mode="json"))


# --- A3 ------------------------------------------------------------------------


def test_metric_a3_counts_matched_missing_and_known_excess(corpus: Corpus) -> None:
    case = _case(corpus, "C013")  # expected_evidence_ids == ["E1", "E2"]
    matched_only = metric_a3(
        case, _observation(context_evidence_ids=("E1", "E2"), emitted_evidence_ids=("E1",))
    )
    assert (matched_only.matched_count, matched_only.missing_count) == (1, 1)
    assert matched_only.excess_count == 0
    assert matched_only.status is FAIL

    complete = metric_a3(
        case,
        _observation(context_evidence_ids=("E1", "E2"), emitted_evidence_ids=("E1", "E2")),
    )
    assert (complete.matched_count, complete.missing_count, complete.excess_count) == (2, 0, 0)
    assert complete.status is PASS


def test_metric_a3_never_counts_an_unknown_id_as_excess(corpus: Corpus) -> None:
    case = _case(corpus, "C001")  # expected_evidence_ids == ["E1"]
    result = metric_a3(case, _observation(emitted_evidence_ids=("E1", "E9")))
    assert result.excess_count == 0
    assert result.status is PASS


def test_metric_a3_counts_known_excess(corpus: Corpus) -> None:
    case = _case(corpus, "C012")  # expected_evidence_ids == ["E1"]
    result = metric_a3(
        case,
        _observation(context_evidence_ids=("E1", "E2"), emitted_evidence_ids=("E1", "E2")),
    )
    assert (result.matched_count, result.missing_count, result.excess_count) == (1, 0, 1)
    assert result.status is FAIL


# --- A4 ------------------------------------------------------------------------


def test_metric_a4_detects_duplicates_among_known_ids(corpus: Corpus) -> None:
    case = _case(corpus, "C018")
    result = metric_a4(
        case,
        _observation(context_evidence_ids=("E1", "E2"), emitted_evidence_ids=("E1", "E1")),
    )
    assert result.status is FAIL
    assert result.duplicate_count == 1


def test_a2_and_a4_are_disjoint(corpus: Corpus) -> None:
    """Um ID desconhecido duplicado é um defeito só, contado uma vez."""
    case = _case(corpus, "C019")
    observation = _observation(context_evidence_ids=("E1", "E2"), emitted_evidence_ids=("E9", "E9"))
    assert metric_a2(case, observation).status is FAIL
    assert metric_a4(case, observation).status is PASS
    assert metric_a4(case, observation).duplicate_count == 0


# --- A5 ------------------------------------------------------------------------


def test_metric_a5_measures_the_three_properties_in_parallel(corpus: Corpus) -> None:
    case = _case(corpus, "C001")
    empty = metric_a5(case, _observation(observed_text="   "), max_answer_chars=4000)
    assert empty.answer_non_empty is FAIL
    assert empty.answer_within_limit is PASS
    assert empty.citations_present is PASS
    assert empty.status is FAIL

    too_long = metric_a5(case, _observation(observed_text="x" * 4001), max_answer_chars=4000)
    assert too_long.answer_within_limit is FAIL
    assert too_long.answer_non_empty is PASS

    no_citations = metric_a5(case, _observation(emitted_evidence_ids=()), max_answer_chars=4000)
    assert no_citations.citations_present is FAIL
    assert no_citations.answer_non_empty is PASS


def test_metric_a5_marks_citations_not_applicable_without_generator(corpus: Corpus) -> None:
    case = _case(corpus, "C004")
    fallback = metric_a5(
        case,
        _observation(
            outcome="insufficient_evidence",
            status="insufficient_evidence",
            generator_called=False,
            generator_call_count=0,
            emitted_evidence_ids=(),
            response_evidence_ids=(),
            observed_text=get_fallback_message("pt"),
        ),
        max_answer_chars=4000,
    )
    assert fallback.citations_present is NA
    assert fallback.status is PASS


def test_a5_discriminates_the_five_rejections(evaluation: Any) -> None:
    empty = _result(evaluation, "C015").metrics.A5
    assert (empty.answer_non_empty, empty.answer_within_limit) == (FAIL, PASS)

    too_long = _result(evaluation, "C016").metrics.A5
    assert (too_long.answer_non_empty, too_long.answer_within_limit) == (PASS, FAIL)

    missing = _result(evaluation, "C017").metrics.A5
    assert missing.citations_present is FAIL
    assert (missing.answer_non_empty, missing.answer_within_limit) == (PASS, PASS)

    for case_id in ("C018", "C019"):
        structural = _result(evaluation, case_id).metrics.A5
        assert structural.status is PASS, case_id
        assert structural.citations_present is PASS, case_id


# --- A6 ------------------------------------------------------------------------


def test_metric_a6_compares_real_call_counts(corpus: Corpus) -> None:
    answered = _case(corpus, "C001")
    assert metric_a6(answered, _observation()).status is PASS
    assert metric_a6(answered, _observation(generator_call_count=0)).status is FAIL

    fallback = _case(corpus, "C004")
    assert metric_a6(fallback, _observation(generator_call_count=0)).status is PASS
    assert metric_a6(fallback, _observation(generator_call_count=1)).status is FAIL


# --- A7 ------------------------------------------------------------------------


def test_metric_a7_detects_wrong_outcome_and_wrong_reason_code(corpus: Corpus) -> None:
    answered = _case(corpus, "C001")
    assert metric_a7(answered, _observation()).status is PASS
    assert metric_a7(answered, _observation(outcome="rejected")).status is FAIL

    rejected = _case(corpus, "C015")  # espera empty_answer
    good = _observation(outcome="rejected", status=None, reason_code="empty_answer")
    assert metric_a7(rejected, good).status is PASS
    bad = _observation(outcome="rejected", status=None, reason_code="answer_too_long")
    assert metric_a7(rejected, bad).status is FAIL


# --- A8 ------------------------------------------------------------------------


def test_metric_a8_detects_a_forbidden_literal(corpus: Corpus) -> None:
    case = _case(corpus, "C009")
    claim = case.forbidden_claims[0]
    clean = metric_a8(case, _observation(observed_text="Resposta prudente."))
    assert clean.status is PASS
    violating = metric_a8(case, _observation(observed_text=f"Ora, {claim.upper()}   sem dúvida."))
    assert violating.status is FAIL
    assert violating.violation_count == 1


def test_metric_a8_is_not_applicable_without_claims_or_generator(corpus: Corpus) -> None:
    assert metric_a8(_case(corpus, "C001"), _observation()).status is NA
    without_generator = _observation(generator_called=False, generator_call_count=0)
    assert metric_a8(_case(corpus, "C009"), without_generator).status is NA


def test_a8_violation_cannot_be_expressed_by_a_valid_corpus(corpus: Corpus) -> None:
    """A deteção testa-se por observação mutada, não por corpus mutado.

    A regra cruzada da Fase 1 rejeita qualquer corpus cuja resposta
    declarada contenha uma `forbidden_claim` — a impossibilidade é ela
    própria a garantia, e fica aqui documentada.
    """
    payload = corpus.model_dump(mode="json")
    for case in payload["cases"]:
        if case["case_id"] == "C009":
            case["generator_output"]["answer"] += " " + case["forbidden_claims"][0]
    with pytest.raises(ValidationError):
        Corpus.model_validate(payload)


def test_normalization_is_shared_with_phase_one() -> None:
    assert normalize_literal_text("  O   ÚNICO  prazo ") == "o único prazo"


# --- R1 ------------------------------------------------------------------------


def test_r1_same_input_produces_same_results_and_digest() -> None:
    first = run_offline_evaluation().model_dump(mode="json")
    second = run_offline_evaluation().model_dump(mode="json")
    assert first == second
    assert compute_result_digest(first) == compute_result_digest(second)


def test_volatile_metadata_does_not_change_the_digest(evaluation: Any) -> None:
    payload = evaluation.model_dump(mode="json")
    digest = compute_result_digest(payload)
    report = {
        "report_schema_version": "1",
        "results": payload,
        "result_digest": digest,
        "execution_metadata": {
            "executed_at": "2026-08-07T10:00:00+00:00",
            "commit_sha": "0" * 40,
            "output_path": "a/primeiro.json",
            "digest_algorithm": "sha256",
        },
    }
    other = dict(report)
    other["execution_metadata"] = {
        **report["execution_metadata"],  # type: ignore[dict-item]
        "executed_at": "2030-01-01T23:59:59+00:00",
        "output_path": "b/segundo.json",
    }
    assert compute_result_digest(report["results"]) == compute_result_digest(other["results"])
    assert digest == compute_result_digest(other["results"])


def test_changing_a_result_changes_the_digest(evaluation: Any) -> None:
    payload = evaluation.model_dump(mode="json")
    digest = compute_result_digest(payload)
    payload["cases"][0]["metrics"]["A1"]["status"] = "fail"
    assert compute_result_digest(payload) != digest


def test_canonical_json_is_stable_and_sorted() -> None:
    assert canonical_json({"b": 1, "a": [2, 1]}) == '{"a":[2,1],"b":1}'
    assert not canonical_json({"a": 1}).endswith("\n")


# --- Minimização ---------------------------------------------------------------


def test_report_contains_no_technical_uuid(evaluation: Any) -> None:
    serialized = canonical_json(evaluation.model_dump(mode="json"))
    assert not UUID_PATTERN.search(serialized)


def test_report_contains_no_corpus_text(evaluation: Any, corpus: Corpus) -> None:
    serialized = canonical_json(evaluation.model_dump(mode="json"))
    forbidden_texts: list[str] = [get_fallback_message("pt"), get_fallback_message("en")]
    for case in corpus.cases:
        forbidden_texts.extend([case.question, case.rationale])
        forbidden_texts.extend(case.forbidden_claims)
        for item in case.evidence:
            forbidden_texts.extend([item.content, item.document_title])
            if item.source_url:
                forbidden_texts.append(item.source_url)
        for fact in case.expected_facts:
            forbidden_texts.append(fact.statement)
        if case.generator_output is not None:
            forbidden_texts.append(case.generator_output.answer)
    # A resposta declarada de C015 é vazia por construção; uma string
    # vazia está contida em qualquer texto e não prova nada.
    for text in forbidden_texts:
        if text.strip():
            assert text not in serialized


def test_report_has_no_score_or_reference_date_keys(evaluation: Any) -> None:
    serialized = canonical_json(evaluation.model_dump(mode="json"))
    for forbidden_key in ('"score"', '"reference_date"', '"prompt"', '"answer"', '"question"'):
        assert forbidden_key not in serialized


def test_case_result_keeps_the_three_citation_views_separate(evaluation: Any) -> None:
    excess = _result(evaluation, "C012")
    assert excess.context_evidence_ids == ["E1", "E2"]
    assert excess.emitted_evidence_ids == ["E1", "E2"]
    assert excess.response_evidence_ids == ["E1", "E2"]

    unknown = _result(evaluation, "C019")
    assert unknown.context_evidence_ids == ["E1", "E2"]
    assert unknown.emitted_evidence_ids == ["E1", "E9"]
    # Turno rejeitado: nada chega à resposta pública.
    assert unknown.response_evidence_ids == []

    fallback = _result(evaluation, "C004")
    assert fallback.context_evidence_ids == []
    assert fallback.emitted_evidence_ids == []
    assert fallback.response_evidence_ids == []


# --- Isolamento ----------------------------------------------------------------


def test_real_provider_is_never_instantiated(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.answering import dependencies
    from app.answering.providers import openai as openai_provider

    def _forbidden(*args: Any, **kwargs: Any) -> Any:
        msg = "o gerador real não pode ser instanciado na avaliação offline"
        raise AssertionError(msg)

    monkeypatch.setattr(openai_provider.OpenAIAnswerGenerator, "__init__", _forbidden)
    monkeypatch.setattr(dependencies, "get_answer_generator", _forbidden)
    assert run_offline_evaluation().case_count == 19


def test_no_network_is_used_during_the_evaluation(monkeypatch: pytest.MonkeyPatch) -> None:
    class BlockedSocket(socket.socket):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            msg = "a avaliação offline não pode abrir sockets"
            raise AssertionError(msg)

    def _blocked(*args: Any, **kwargs: Any) -> Any:
        msg = "a avaliação offline não pode ligar-se à rede"
        raise AssertionError(msg)

    monkeypatch.setattr(socket, "socket", BlockedSocket)
    monkeypatch.setattr(socket, "create_connection", _blocked)
    assert run_offline_evaluation().case_count == 19


def test_evaluate_case_is_pure_over_the_observation(corpus: Corpus) -> None:
    case = _case(corpus, "C001")
    observation = _observation()
    first = evaluate_case(case, observation, max_answer_chars=4000)
    second = evaluate_case(case, observation, max_answer_chars=4000)
    assert first.model_dump(mode="json") == second.model_dump(mode="json")
