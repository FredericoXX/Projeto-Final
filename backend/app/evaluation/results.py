"""Contratos dos resultados da avaliação offline e serialização canónica.

Separação declarada, segundo D9:

- `results` é o **payload canónico e determinístico**. Contém os
  resultados por caso e as propriedades da execução que participam em R1
  — população, versões do corpus e da rubrica, e configuração de
  execução. É a única coisa de que se calcula o `result_digest`.
- `execution_metadata` contém os metadados honestamente voláteis —
  `executed_at`, caminho de saída — e o `commit_sha`. Nada disto entra no
  digest: o digest responde "o comportamento observado mudou?", não "o
  repositório andou?".

Minimização: nenhum modelo aqui tem campo para pergunta, resposta,
mensagem de fallback, título de documento, conteúdo de evidência, prompt,
contexto serializado, UUID técnico, `score` ou `reference_date`. Dos IDs
desconhecidos regista-se apenas a contagem, à semelhança de
`InvalidGeneratedAnswerError.invalid_count` — numa execução com
fornecedor real esses valores seriam conteúdo não confiável.

Este módulo não é reexportado por `app/evaluation/__init__.py`, para que
importar `app.evaluation.assets` continue a não carregar as Settings nem
o SDK do fornecedor (garantia da Fase 1).
"""

import hashlib
import json
import os
import tempfile
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Final

from pydantic import BaseModel, ConfigDict, Field

from app.evaluation.contracts import ExecutionConfig

REPORT_SCHEMA_VERSION: Final = "1"
POPULATION: Final = "P1"
DIGEST_ALGORITHM: Final = "sha256"

SHA_PATTERN: Final = r"^[0-9a-f]{40}$"


class MetricStatus(StrEnum):
    """Escala das métricas automáticas (D1): nunca 0/1/2."""

    PASS = "pass"
    FAIL = "fail"
    NOT_APPLICABLE = "not_applicable"


class ResultModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StatusMetric(ResultModel):
    status: MetricStatus


class UnknownIdsMetric(ResultModel):
    status: MetricStatus
    unknown_count: Annotated[int, Field(ge=0)]


class ExpectedSourcesMetric(ResultModel):
    status: MetricStatus
    matched_count: Annotated[int, Field(ge=0)]
    missing_count: Annotated[int, Field(ge=0)]
    excess_count: Annotated[int, Field(ge=0)]


class DuplicateIdsMetric(ResultModel):
    status: MetricStatus
    duplicate_count: Annotated[int, Field(ge=0)]


class StructuralLimitsMetric(ResultModel):
    """A5 mede três propriedades **em paralelo**.

    Não reproduz a precedência de `validate_generated_answer`, que
    curto-circuita na primeira violação: é essa diferença que dá a A5
    valor diagnóstico num turno rejeitado.
    """

    status: MetricStatus
    answer_non_empty: MetricStatus
    answer_within_limit: MetricStatus
    citations_present: MetricStatus


class ForbiddenClaimsMetric(ResultModel):
    status: MetricStatus
    violation_count: Annotated[int, Field(ge=0)]


class CaseMetrics(ResultModel):
    A1: StatusMetric
    A2: UnknownIdsMetric
    A3: ExpectedSourcesMetric
    A4: DuplicateIdsMetric
    A5: StructuralLimitsMetric
    A6: StatusMetric
    A7: StatusMetric
    A8: ForbiddenClaimsMetric


class CaseResult(ResultModel):
    """Resultado observado de um caso.

    As três listas de citações são deliberadamente distintas:

    - `context_evidence_ids` — IDs conhecidos no contexto real, ou seja o
      que `select_evidence` produziu e o gerador recebeu;
    - `emitted_evidence_ids` — o que o gerador citou;
    - `response_evidence_ids` — o que chegou à resposta pública; vazio
      fora de `answered`.
    """

    case_id: str
    scenario_id: Annotated[int, Field(ge=1, le=12)]
    language: str
    expected_outcome: str
    observed_outcome: str
    observed_status: str | None
    observed_reason_code: str | None
    generator_call_count: Annotated[int, Field(ge=0)]
    context_evidence_ids: list[str]
    emitted_evidence_ids: list[str]
    response_evidence_ids: list[str]
    metrics: CaseMetrics


class EvaluationResults(ResultModel):
    """Payload canónico: é daqui, e só daqui, que sai o `result_digest`."""

    population: str
    corpus_version: str
    rubric_version: str
    execution_config: ExecutionConfig
    case_count: Annotated[int, Field(ge=0)]
    cases: list[CaseResult]


class ExecutionMetadata(ResultModel):
    """Metadados fora do digest. `commit_sha` é obrigatório."""

    executed_at: str
    commit_sha: Annotated[str, Field(pattern=SHA_PATTERN)]
    output_path: str
    digest_algorithm: str = DIGEST_ALGORITHM


class EvaluationReport(ResultModel):
    report_schema_version: str
    results: EvaluationResults
    result_digest: str
    execution_metadata: ExecutionMetadata


def canonical_json(payload: object) -> str:
    """Serialização canónica única do projeto.

    UTF-8, `ensure_ascii=False`, chaves ordenadas, separadores estáveis e
    **sem newline final** — o newline pertence ao ficheiro, não ao
    conteúdo de que se calcula o digest.
    """
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def compute_result_digest(results_payload: object) -> str:
    """SHA-256 da serialização canónica de `results`, e de mais nada."""
    return hashlib.sha256(canonical_json(results_payload).encode("utf-8")).hexdigest()


def report_file_text(report_payload: object) -> str:
    """Texto do ficheiro: legível e diffável, com chaves ordenadas.

    O digest continua a ser verificável a partir do ficheiro, porque se
    recalcula sobre o objeto `results` relido, nunca sobre este texto.
    """
    return json.dumps(report_payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def atomic_write_text(destination: Path, content: str, *, overwrite: bool) -> None:
    """Escrita atómica: temporário na mesma diretoria, flush, fsync e
    publicação numa única operação do sistema de ficheiros.

    A política de sobrescrita é aplicada **na publicação**, não numa
    verificação prévia:

    - `overwrite=True` publica com `os.replace`, que substitui o destino;
    - `overwrite=False` publica com `os.link`, que levanta
      `FileExistsError` se o destino tiver entretanto passado a existir.

    Sem isto haveria uma janela entre verificar e publicar em que outro
    processo poderia criar o destino e vê-lo substituído. O temporário é
    removido em qualquer caminho, incluindo o de falha.
    """
    handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="\n",
        dir=destination.parent,
        prefix=f".{destination.name}.",
        suffix=".tmp",
        delete=False,
    )
    temporary_path = Path(handle.name)
    try:
        with handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        if overwrite:
            os.replace(temporary_path, destination)
        else:
            # Publicação e verificação de existência na mesma operação.
            os.link(temporary_path, destination)
            temporary_path.unlink(missing_ok=True)
    except OSError:
        # Cobre também FileExistsError: o destino existente fica intacto
        # e o temporário nunca sobrevive à falha.
        temporary_path.unlink(missing_ok=True)
        raise
