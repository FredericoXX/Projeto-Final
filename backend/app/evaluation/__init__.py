"""Contratos e artefactos da avaliação offline do Momento 5.

Este pacote é lido pelos testes e, na Fase 2, pelo mecanismo de avaliação.
A aplicação em execução nunca o importa: nada no grafo de imports de
`app.main` chega aqui.
"""

from app.evaluation.assets import (
    ALLOWED_URL_HOST,
    CORPUS_PATH,
    CORPUS_SCHEMA_PATH,
    EVALUATION_DIR,
    RUBRIC_PATH,
    RUBRIC_SCHEMA_PATH,
    AssetValidationError,
    ForbiddenDataFinding,
    load_corpus,
    load_rubric,
    scan_forbidden_data,
    validate_corpus_payload,
    validate_rubric_payload,
)
from app.evaluation.contracts import (
    REQUIRED_CRITERION_IDS,
    SCENARIOS,
    Corpus,
    CorpusCase,
    CorpusEvidence,
    ExecutionConfig,
    ExpectedFact,
    ExpectedOutcome,
    ExpectedStatus,
    FactCoverage,
    GeneratorOutput,
    Language,
    ReasonCode,
    Rubric,
    RubricCriterion,
    canonical_schema_json,
    write_versioned_schemas,
)

__all__ = [
    "ALLOWED_URL_HOST",
    "CORPUS_PATH",
    "CORPUS_SCHEMA_PATH",
    "EVALUATION_DIR",
    "REQUIRED_CRITERION_IDS",
    "RUBRIC_PATH",
    "RUBRIC_SCHEMA_PATH",
    "SCENARIOS",
    "AssetValidationError",
    "Corpus",
    "CorpusCase",
    "CorpusEvidence",
    "ExecutionConfig",
    "ExpectedFact",
    "ExpectedOutcome",
    "ExpectedStatus",
    "FactCoverage",
    "ForbiddenDataFinding",
    "GeneratorOutput",
    "Language",
    "ReasonCode",
    "Rubric",
    "RubricCriterion",
    "canonical_schema_json",
    "load_corpus",
    "load_rubric",
    "scan_forbidden_data",
    "validate_corpus_payload",
    "validate_rubric_payload",
    "write_versioned_schemas",
]
