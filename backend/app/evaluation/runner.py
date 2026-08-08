"""Execução offline determinística da população P1 e métricas A1–A8.

Percurso de cada caso, sem exceção — incluindo os cinco de rejeição e os
dois de fallback:

    AnsweringRequest → app.services.answering_service.ask → observação

O runner **observa**; não decide. O desfecho `rejected` e o respetivo
`reason_code` vêm de `InvalidGeneratedAnswerError`, levantada pela
implementação real de `validate_generated_answer`: é isso que prova a
precedência que a Fase 1 deliberadamente não reproduziu.

As métricas são funções puras sobre `CaseObservation`, o que permite
demonstrar `pass`, `fail` e `not_applicable` sem corromper os artefactos
aprovados. `CaseObservation` transporta o texto observado apenas em
memória, para A5 e A8; esse texto nunca entra no resultado.

Este módulo não é reexportado por `app/evaluation/__init__.py`, para
preservar a garantia de isolamento da Fase 1.
"""

from dataclasses import dataclass
from typing import cast

from sqlalchemy.orm import Session

from app.answering.base import GeneratedAnswer, InvalidGeneratedAnswerError
from app.evaluation.assets import load_corpus, load_rubric
from app.evaluation.contracts import (
    Corpus,
    CorpusCase,
    ExecutionConfig,
    ExpectedOutcome,
    Rubric,
    normalize_literal_text,
)
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
    POPULATION,
    CaseMetrics,
    CaseResult,
    DuplicateIdsMetric,
    EvaluationResults,
    ExpectedSourcesMetric,
    ForbiddenClaimsMetric,
    MetricStatus,
    StatusMetric,
    StructuralLimitsMetric,
    UnknownIdsMetric,
)
from app.schemas.answering import AnsweringRequest
from app.services import answering_service

OUTCOME_ANSWERED = "answered"
OUTCOME_INSUFFICIENT_EVIDENCE = "insufficient_evidence"
OUTCOME_REJECTED = "rejected"


@dataclass(frozen=True)
class CaseObservation:
    """O que a execução real produziu para um caso.

    `observed_text` existe apenas para A5 e A8 e **nunca** é serializado:
    é a resposta candidata quando houve gerador, ou o fallback público
    quando não houve.
    """

    outcome: str
    status: str | None
    reason_code: str | None
    generator_called: bool
    generator_call_count: int
    context_evidence_ids: tuple[str, ...]
    emitted_evidence_ids: tuple[str, ...]
    response_evidence_ids: tuple[str, ...]
    observed_text: str


def _status(condition: bool) -> MetricStatus:
    return MetricStatus.PASS if condition else MetricStatus.FAIL


def _known_emitted(observation: CaseObservation) -> list[str]:
    """Citações emitidas que existem no contexto real, com repetições.

    Excluir aqui os IDs desconhecidos é o que torna A3 e A4 disjuntas de
    A2: o mesmo defeito nunca é contado duas vezes.
    """
    known = set(observation.context_evidence_ids)
    return [item for item in observation.emitted_evidence_ids if item in known]


def metric_a1(case: CorpusCase, observation: CaseObservation) -> StatusMetric:
    """Estado devolvido vs. `expected_status`; N/A quando há rejeição."""
    if observation.outcome == OUTCOME_REJECTED:
        return StatusMetric(status=MetricStatus.NOT_APPLICABLE)
    expected = case.expected_status.value if case.expected_status is not None else None
    return StatusMetric(status=_status(observation.status == expected))


def metric_a2(case: CorpusCase, observation: CaseObservation) -> UnknownIdsMetric:
    """Única verificação de IDs desconhecidos. Só a contagem é registada."""
    if not observation.generator_called:
        return UnknownIdsMetric(status=MetricStatus.NOT_APPLICABLE, unknown_count=0)
    known = set(observation.context_evidence_ids)
    unknown_count = sum(1 for item in observation.emitted_evidence_ids if item not in known)
    return UnknownIdsMetric(status=_status(unknown_count == 0), unknown_count=unknown_count)


def metric_a3(case: CorpusCase, observation: CaseObservation) -> ExpectedSourcesMetric:
    """Correspondência com `expected_evidence_ids`, sem rácio agregado.

    Opera sobre conjuntos de IDs **conhecidos**: a duplicação é assunto
    exclusivo de A4 e um ID desconhecido nunca conta como excesso.
    """
    if not observation.generator_called:
        return ExpectedSourcesMetric(
            status=MetricStatus.NOT_APPLICABLE,
            matched_count=0,
            missing_count=0,
            excess_count=0,
        )
    cited = set(_known_emitted(observation))
    expected = set(case.expected_evidence_ids)
    matched = len(expected & cited)
    missing = len(expected - cited)
    excess = len(cited - expected)
    return ExpectedSourcesMetric(
        status=_status(missing == 0 and excess == 0),
        matched_count=matched,
        missing_count=missing,
        excess_count=excess,
    )


def metric_a4(case: CorpusCase, observation: CaseObservation) -> DuplicateIdsMetric:
    """Duplicados **entre IDs conhecidos**; disjunta de A2."""
    if not observation.generator_called:
        return DuplicateIdsMetric(status=MetricStatus.NOT_APPLICABLE, duplicate_count=0)
    known_emitted = _known_emitted(observation)
    duplicate_count = len(known_emitted) - len(set(known_emitted))
    return DuplicateIdsMetric(
        status=_status(duplicate_count == 0), duplicate_count=duplicate_count
    )


def metric_a5(
    case: CorpusCase, observation: CaseObservation, *, max_answer_chars: int
) -> StructuralLimitsMetric:
    """Três propriedades estruturais medidas em paralelo.

    Ao contrário de `validate_generated_answer`, que curto-circuita na
    primeira violação, A5 reporta as três independentemente — é assim que
    distingue `empty_answer`, `answer_too_long` e `missing_citations` de
    uma rejeição por duplicação ou por ID desconhecido.
    """
    non_empty = _status(bool(observation.observed_text.strip()))
    within_limit = _status(len(observation.observed_text) <= max_answer_chars)
    if observation.generator_called:
        citations_present = _status(bool(observation.emitted_evidence_ids))
    else:
        # Sem gerador, a ausência de citações é o comportamento correto.
        citations_present = MetricStatus.NOT_APPLICABLE
    applicable = (non_empty, within_limit, citations_present)
    failed = any(item is MetricStatus.FAIL for item in applicable)
    return StructuralLimitsMetric(
        status=MetricStatus.FAIL if failed else MetricStatus.PASS,
        answer_non_empty=non_empty,
        answer_within_limit=within_limit,
        citations_present=citations_present,
    )


def metric_a6(case: CorpusCase, observation: CaseObservation) -> StatusMetric:
    """Chamadas reais ao gerador vs. `expected_generator_called`."""
    if case.expected_generator_called:
        return StatusMetric(status=_status(observation.generator_call_count == 1))
    return StatusMetric(status=_status(observation.generator_call_count == 0))


def metric_a7(case: CorpusCase, observation: CaseObservation) -> StatusMetric:
    """Desfecho observado e, na rejeição, o `reason_code` real."""
    if observation.outcome != case.expected_outcome.value:
        return StatusMetric(status=MetricStatus.FAIL)
    if observation.outcome != OUTCOME_REJECTED:
        return StatusMetric(status=MetricStatus.PASS)
    expected = case.expected_reason_code.value if case.expected_reason_code else None
    return StatusMetric(status=_status(observation.reason_code == expected))


def metric_a8(case: CorpusCase, observation: CaseObservation) -> ForbiddenClaimsMetric:
    """Ausência das `forbidden_claims`, só por correspondência literal."""
    if not observation.generator_called or not case.forbidden_claims:
        return ForbiddenClaimsMetric(status=MetricStatus.NOT_APPLICABLE, violation_count=0)
    text = normalize_literal_text(observation.observed_text)
    violations = sum(1 for claim in case.forbidden_claims if normalize_literal_text(claim) in text)
    return ForbiddenClaimsMetric(status=_status(violations == 0), violation_count=violations)


def evaluate_case(
    case: CorpusCase, observation: CaseObservation, *, max_answer_chars: int
) -> CaseResult:
    """Apura A1–A8 sobre uma observação, sem tocar em textos no resultado."""
    return CaseResult(
        case_id=case.case_id,
        scenario_id=case.scenario_id,
        language=case.language.value,
        expected_outcome=case.expected_outcome.value,
        observed_outcome=observation.outcome,
        observed_status=observation.status,
        observed_reason_code=observation.reason_code,
        generator_call_count=observation.generator_call_count,
        context_evidence_ids=list(observation.context_evidence_ids),
        emitted_evidence_ids=list(observation.emitted_evidence_ids),
        response_evidence_ids=list(observation.response_evidence_ids),
        metrics=CaseMetrics(
            A1=metric_a1(case, observation),
            A2=metric_a2(case, observation),
            A3=metric_a3(case, observation),
            A4=metric_a4(case, observation),
            A5=metric_a5(case, observation, max_answer_chars=max_answer_chars),
            A6=metric_a6(case, observation),
            A7=metric_a7(case, observation),
            A8=metric_a8(case, observation),
        ),
    )


def observe_case(case: CorpusCase, config: ExecutionConfig) -> CaseObservation:
    """Executa um caso na camada real e devolve o que foi observado.

    Pressupõe `answering_limits` já ativo — os limites têm de ser os do
    corpus antes de `ask` os ler.
    """
    institution = synthetic_institution(config.institution_name)
    session = SentinelSession(institution=institution)
    retriever = FakeRetriever(evidence=build_evidence(case))
    generated = (
        GeneratedAnswer(
            answer=case.generator_output.answer,
            cited_evidence_ids=tuple(case.generator_output.cited_evidence_ids),
        )
        if case.generator_output is not None
        # Nunca usado: nos casos de fallback o serviço devolve antes de
        # chegar ao gerador, e A6 confirma que não houve chamada.
        else GeneratedAnswer(answer="", cited_evidence_ids=())
    )
    generator = FakeAnswerGenerator(generated=generated)
    request = AnsweringRequest(
        query=case.question,
        language=case.language.value,
        top_k=HARNESS_TOP_K,
        official_only=True,
    )

    fallback_text = ""
    response_ids: tuple[str, ...] = ()
    try:
        response = answering_service.ask(
            cast(Session, session),
            synthetic_user(),
            request,
            retriever,
            generator,
        )
    except InvalidGeneratedAnswerError as exc:
        outcome = OUTCOME_REJECTED
        status: str | None = None
        reason_code: str | None = exc.reason_code
    else:
        outcome = response.status
        status = response.status
        reason_code = None
        response_ids = tuple(source.evidence_id for source in response.sources)
        fallback_text = response.answer

    _assert_single_institution_lookup(case, session)

    generator_called = generator.call_count > 0
    context_ids: tuple[str, ...] = ()
    emitted_ids: tuple[str, ...] = ()
    if generator_called:
        context = generator.contexts[0]
        context_ids = tuple(entry.evidence_id for entry in context.evidence)
        emitted_ids = tuple(generated.cited_evidence_ids)

    return CaseObservation(
        outcome=outcome,
        status=status,
        reason_code=reason_code,
        generator_called=generator_called,
        generator_call_count=generator.call_count,
        context_evidence_ids=context_ids,
        emitted_evidence_ids=emitted_ids,
        response_evidence_ids=response_ids,
        # Com gerador, o texto observado é o candidato — o único que
        # existe num turno rejeitado. Sem gerador, é o fallback público.
        observed_text=generated.answer if generator_called else fallback_text,
    )


def _assert_single_institution_lookup(case: CorpusCase, session: SentinelSession) -> None:
    expected = [("Institution", str(SYNTHETIC_INSTITUTION_ID))]
    if session.accesses != expected:
        msg = f"{case.case_id}: acessos à base de dados inesperados durante a avaliação"
        raise UnexpectedDatabaseAccess(msg)


def run_offline_evaluation(
    corpus: Corpus | None = None, rubric: Rubric | None = None
) -> EvaluationResults:
    """Executa os casos do corpus aprovado e devolve o payload canónico.

    A rubrica é carregada e validada, mas não é aplicada: P1 apura apenas
    métricas automáticas. Regista-se a `rubric_version` para que o
    resultado seja rastreável até à versão aprovada (D9).
    """
    active_corpus = corpus if corpus is not None else load_corpus()
    active_rubric = rubric if rubric is not None else load_rubric()
    config = active_corpus.execution_config

    results: list[CaseResult] = []
    with answering_limits(config):
        for case in active_corpus.cases:
            observation = observe_case(case, config)
            results.append(
                evaluate_case(case, observation, max_answer_chars=config.max_answer_chars)
            )

    return EvaluationResults(
        population=POPULATION,
        corpus_version=active_corpus.corpus_version,
        rubric_version=active_rubric.rubric_version,
        execution_config=config,
        case_count=len(results),
        cases=results,
    )


__all__ = [
    "OUTCOME_ANSWERED",
    "OUTCOME_INSUFFICIENT_EVIDENCE",
    "OUTCOME_REJECTED",
    "CaseObservation",
    "ExpectedOutcome",
    "evaluate_case",
    "metric_a1",
    "metric_a2",
    "metric_a3",
    "metric_a4",
    "metric_a5",
    "metric_a6",
    "metric_a7",
    "metric_a8",
    "observe_case",
    "run_offline_evaluation",
]
