"""Composição da baseline do Momento 5 (Fase 3).

Esta camada **não avalia**: chama o mecanismo da Fase 2 sem o alterar e
acrescenta o que D9 e D11 exigem de uma baseline e que um relatório de
execução isolado não declara:

- o estatuto de cada população — P1 medida, P2 e P3 **não medidas**;
- cada métrica humana e cada parte humana das métricas híbridas declarada
  como **não medida**, derivada da rubrica aprovada e nunca de uma lista
  escrita à mão;
- a confirmação de R1, que é propriedade da execução e não de um caso;
- a classificação das células `fail`, para que um `fail` esperado não seja
  lido como defeito da aplicação.

Este módulo **não executa e não constrói relatórios**: recebe-os prontos,
já escritos pelo entrypoint da Fase 2. `results` e `result_digest` do
relatório embutido são exatamente os que a Fase 2 produziu, e este módulo
não importa `compute_result_digest`, para que não exista um segundo
caminho de produção capaz de divergir do primeiro.

O JSON é a única fonte primária da baseline. D9 torna o resumo em
Markdown opcional e ele não é produzido: qualquer leitura derivada é
trabalho de quem lê o artefacto.
"""

from collections.abc import Mapping, Sequence
from enum import StrEnum
from typing import Annotated, Any, Final

from pydantic import BaseModel, ConfigDict, Field

from app.evaluation.assets import load_rubric
from app.evaluation.results import SHA_PATTERN, EvaluationReport

BASELINE_SCHEMA_VERSION: Final = "1"
MOMENT: Final = "5"
REPRODUCIBILITY_RUNS: Final = 2

UNEXPLAINED: Final = "unexplained"

# Versão do corpus a que a matriz abaixo corresponde. Se a baseline for
# produzida sobre outra versão, a matriz deixa de se aplicar e **todas**
# as células passam a `unexplained` — fail-closed por omissão.
EXPECTED_FAILURES_CORPUS_VERSION: Final = "1.0.0"

# Matriz explícita e versionada das células `fail` esperadas no corpus
# aprovado na Fase 1. Cada entrada é uma correspondência exata entre caso,
# métrica e motivo aprovado.
#
# Não é derivada por regra genérica: derivá-la exigiria reimplementar a
# lógica de A3 e A5 dentro da Fase 3, e uma regra do género
# "rejected + A7 pass -> expected_rejection" classificaria como esperada
# qualquer falha nova que aparecesse nesse caso, escondendo-a. Qualquer
# célula fora desta matriz é `unexplained` e produz defeito comportamental.
EXPECTED_METRIC_FAILURES: Final[Mapping[tuple[str, str], str]] = {
    # Divergências deliberadas declaradas no rationale dos casos.
    ("C012", "A3"): "declared_source_divergence",
    ("C013", "A3"): "declared_source_divergence",
    # Rejeições: a violação estrutural é o defeito que o caso codifica.
    ("C015", "A5"): "expected_rejection",
    ("C016", "A5"): "expected_rejection",
    ("C017", "A3"): "expected_rejection",
    ("C017", "A5"): "expected_rejection",
    ("C018", "A4"): "expected_rejection",
    ("C019", "A2"): "expected_rejection",
}

CLASSIFICATION_RULE: Final = (
    "Uma célula fail só é considerada esperada quando existe correspondência exata entre caso, "
    "métrica e motivo aprovado na matriz versionada da Fase 3, que corresponde ao corpus "
    f"{EXPECTED_FAILURES_CORPUS_VERSION} aprovado na Fase 1. A classificação é fail-closed: "
    "qualquer outra célula, qualquer célula num caso cujo A7 tenha falhado, e qualquer célula "
    "produzida sobre outra versão do corpus são classificadas como 'unexplained' e entram em "
    "behavioural_defects. Não há regra genérica por desfecho ou por métrica, porque uma regra "
    "dessas classificaria como esperada uma falha nova que surgisse no mesmo caso."
)


class PopulationStatus(StrEnum):
    MEASURED = "measured"
    NOT_MEASURED = "not_measured"


class BaselineModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PopulationRecord(BaselineModel):
    population: str
    status: PopulationStatus
    description: str
    answer_provenance: str | None
    automatic_metrics: list[str]
    note: str


class HumanMetricRecord(BaselineModel):
    """Uma métrica humana, ou a parte humana de uma métrica híbrida."""

    criterion_id: str
    name: str
    metric: str
    assessment: str
    status: PopulationStatus
    required_population: str
    automatic_part_measured: str | None


class ReproducibilityRecord(BaselineModel):
    metric: str
    runs: Annotated[int, Field(ge=2)]
    results_identical: bool
    digest_identical: bool
    result_digest: str


class MetricFailure(BaselineModel):
    case_id: str
    metric: str
    expected_outcome: str
    observed_outcome: str
    outcome_matches_expectation: bool
    classification: str


class FindingsRecord(BaselineModel):
    behavioural_defects: list[str]
    layers_with_defects: list[str]
    metric_failures: list[MetricFailure]
    classification_rule: str
    behavioural_corrections_applied: bool


class BaselineReport(BaselineModel):
    baseline_schema_version: str
    moment: str
    populations: list[PopulationRecord]
    human_metrics: list[HumanMetricRecord]
    reproducibility: ReproducibilityRecord
    findings: FindingsRecord
    limitations: list[str]
    report: EvaluationReport


LIMITATIONS: Final[tuple[str, ...]] = (
    "A baseline mede comportamento sobre material exclusivamente sintético; o comportamento "
    "sobre documentos institucionais reais continua a exigir validação humana.",
    "Avaliar respostas produzidas por um gerador falso mede a camada de answering e o mecanismo "
    "de avaliação — não mede a qualidade do gerador atualmente configurado.",
    "Sem as populações P2 e P3, este momento não produz medição semântica: correção factual, "
    "fidelidade, completude, clareza, concisão e as restantes métricas humanas ficam não medidas.",
    "As métricas automáticas são estruturais e determinísticas; nenhuma delas mede correção "
    "semântica, e nada nesta baseline torna o sistema livre de alucinações.",
    "Não existem pesos nem score agregado: o resultado é um perfil por caso e por cenário, não um "
    "número único comparável.",
    "A baseline fica comparável entre momentos, mas não foi criado gate automático de comparação.",
)


def _population_records() -> list[PopulationRecord]:
    """Estatuto das três populações de D11, sempre as três declaradas."""
    return [
        PopulationRecord(
            population="P1",
            status=PopulationStatus.MEASURED,
            description=(
                "Baseline estrutural offline: a camada de answering executada sobre o "
                "generator_output declarado no corpus."
            ),
            answer_provenance=(
                "gerador falso que devolve o generator_output declarado no corpus sintético"
            ),
            automatic_metrics=["A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "R1"],
            note="População obrigatória; é a baseline reproduzível.",
        ),
        PopulationRecord(
            population="P2",
            status=PopulationStatus.NOT_MEASURED,
            description=(
                "Respostas gravadas e sanitizadas, com proveniência declarada, submetidas a "
                "juízo humano segundo a rubrica aprovada."
            ),
            answer_provenance=None,
            automatic_metrics=[],
            note=(
                "Opcional segundo D11 e não executada nesta fase. As métricas humanas ficam "
                "não medidas — nunca zero e nunca omitidas."
            ),
        ),
        PopulationRecord(
            population="P3",
            status=PopulationStatus.NOT_MEASURED,
            description=(
                "Observação do comportamento do fornecedor atualmente configurado, fora da CI "
                "e não determinística."
            ),
            answer_provenance=None,
            automatic_metrics=[],
            note=(
                "Opcional segundo D5 e D11 e não executada nesta fase. Nenhum resultado obtido "
                "sobre o gerador falso é apresentado como qualidade do gerador real."
            ),
        ),
    ]


def _human_metric_records() -> list[HumanMetricRecord]:
    """Derivado da rubrica aprovada — nunca de uma lista escrita à mão."""
    rubric = load_rubric()
    return [
        HumanMetricRecord(
            criterion_id=criterion.criterion_id,
            name=criterion.name,
            metric=criterion.metric,
            assessment=criterion.assessment.value,
            status=PopulationStatus.NOT_MEASURED,
            required_population="P2",
            automatic_part_measured=criterion.automatic_part,
        )
        for criterion in rubric.criteria
    ]


def classify_metric_failures(results_payload: Mapping[str, Any]) -> list[MetricFailure]:
    """Classifica cada célula `fail` contra a matriz aprovada, fail-closed.

    Só uma correspondência exata (caso, métrica) na matriz da versão do
    corpus avaliada produz uma classificação de célula esperada. Tudo o
    resto é `unexplained`.
    """
    matrix: Mapping[tuple[str, str], str] = (
        EXPECTED_METRIC_FAILURES
        if results_payload.get("corpus_version") == EXPECTED_FAILURES_CORPUS_VERSION
        else {}
    )
    failures: list[MetricFailure] = []
    for case in results_payload["cases"]:
        outcome_matches = case["metrics"]["A7"]["status"] == "pass"
        for metric_id in ("A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8"):
            if case["metrics"][metric_id]["status"] != "fail":
                continue
            if outcome_matches:
                classification = matrix.get((case["case_id"], metric_id), UNEXPLAINED)
            else:
                # O desfecho do caso divergiu: nenhuma célula desse caso
                # pode ser lida como expectativa aprovada.
                classification = UNEXPLAINED
            failures.append(
                MetricFailure(
                    case_id=case["case_id"],
                    metric=metric_id,
                    expected_outcome=case["expected_outcome"],
                    observed_outcome=case["observed_outcome"],
                    outcome_matches_expectation=outcome_matches,
                    classification=classification,
                )
            )
    return failures


def build_findings(results_payload: Mapping[str, Any]) -> FindingsRecord:
    failures = classify_metric_failures(results_payload)
    behavioural = sorted(
        {
            case["case_id"]
            for case in results_payload["cases"]
            if case["metrics"]["A7"]["status"] != "pass"
        }
        | {failure.case_id for failure in failures if failure.classification == UNEXPLAINED}
    )
    return FindingsRecord(
        behavioural_defects=behavioural,
        layers_with_defects=["answering"] if behavioural else [],
        metric_failures=failures,
        classification_rule=CLASSIFICATION_RULE,
        behavioural_corrections_applied=False,
    )


def build_baseline(
    first: EvaluationReport, second: EvaluationReport, *, output_path: str
) -> BaselineReport:
    """Compõe a baseline a partir de dois relatórios já produzidos.

    R1 é propriedade da execução: confirma-se comparando o payload
    canónico `results` e o `result_digest` **tal como a Fase 2 os
    produziu**. O segundo relatório é incorporado sem reconstrução, pelo
    que o `result_digest` da baseline é exatamente o valor da Fase 2.

    O único campo ajustado é `execution_metadata.output_path`: a Fase 2
    grava aí o caminho absoluto do ficheiro que escreveu, e um caminho
    local de máquina não pode entrar num artefacto versionado. É metadado
    volátil, fora do digest e fora da comparação de R1.
    """
    first_results = first.results.model_dump(mode="json")
    second_results = second.results.model_dump(mode="json")
    report = second.model_copy(
        update={
            "execution_metadata": second.execution_metadata.model_copy(
                update={"output_path": output_path}
            )
        }
    )

    return BaselineReport(
        baseline_schema_version=BASELINE_SCHEMA_VERSION,
        moment=MOMENT,
        populations=_population_records(),
        human_metrics=_human_metric_records(),
        reproducibility=ReproducibilityRecord(
            metric="R1",
            runs=REPRODUCIBILITY_RUNS,
            results_identical=first_results == second_results,
            digest_identical=first.result_digest == second.result_digest,
            result_digest=report.result_digest,
        ),
        findings=build_findings(second_results),
        limitations=list(LIMITATIONS),
        report=report,
    )


__all__: Sequence[str] = [
    "BASELINE_SCHEMA_VERSION",
    "CLASSIFICATION_RULE",
    "EXPECTED_FAILURES_CORPUS_VERSION",
    "EXPECTED_METRIC_FAILURES",
    "UNEXPLAINED",
    "BaselineReport",
    "FindingsRecord",
    "HumanMetricRecord",
    "MetricFailure",
    "PopulationRecord",
    "PopulationStatus",
    "ReproducibilityRecord",
    "SHA_PATTERN",
    "build_baseline",
    "build_findings",
    "classify_metric_failures",
]
