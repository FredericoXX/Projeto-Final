"""Validação dos artefactos de avaliação do Momento 5 (Fase 1).

Estes testes não usam base de dados, storage, rede nem fornecedor. As
duas fixtures autouse do conftest que preparam a base de dados são
anuladas neste módulo, porque nada aqui a utiliza.

Limitação declarada: o pytest importa `tests/conftest.py` ao coletar
qualquer teste desta diretoria, e esse ficheiro importa a aplicação
FastAPI e as Settings. Este módulo não as importa. A propriedade forte —
validar os artefactos sem `.env`, sem base de dados, sem rede e sem
storage — é verificada em subprocesso por
`test_evaluation_package_validates_assets_in_isolation`.
"""

import ast
import json
import os
import subprocess
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from app.evaluation.assets import (
    CORPUS_PATH,
    CORPUS_SCHEMA_PATH,
    RUBRIC_PATH,
    RUBRIC_SCHEMA_PATH,
    AssetValidationError,
    scan_forbidden_data,
    validate_corpus_payload,
    validate_rubric_payload,
)
from app.evaluation.contracts import (
    REQUIRED_CRITERION_IDS,
    SCALE_VALUES,
    SCENARIOS,
    Corpus,
    ExpectedOutcome,
    FactCoverage,
    Language,
    ReasonCode,
    Rubric,
    canonical_schema_json,
)

BACKEND_DIR = Path(__file__).resolve().parents[1]
VALIDATION_MODULE = BACKEND_DIR / "app" / "answering" / "validation.py"

# Composição exata da versão 1.0.0 do corpus. É propriedade **deste
# artefacto**, e não uma invariante permanente do modelo: um corpus futuro
# pode ter outra dimensão. Fica no teste para que remover um caso aprovado
# não passe despercebido.
EXPECTED_CASE_IDS: tuple[str, ...] = tuple(f"C{index:03d}" for index in range(1, 20))

Payload = dict[str, Any]
Mutation = Callable[[Payload], None]


# --- Anulação das fixtures de base de dados do conftest ------------------------
# Estes testes não tocam na base de dados; sem estas anulações, a fixture
# de sessão do conftest criaria a base de testes só para os coletar.


@pytest.fixture(scope="session", autouse=True)
def _override_get_db() -> None:
    """Anula a fixture homónima do conftest: aqui não há dependência de DB."""


@pytest.fixture(autouse=True)
def _clean_tables() -> None:
    """Anula a fixture homónima do conftest: aqui não há tabelas a truncar."""


# --- Auxiliares ---------------------------------------------------------------


def _corpus_payload() -> Payload:
    payload = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _rubric_payload() -> Payload:
    payload = json.loads(RUBRIC_PATH.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _case(payload: Payload, case_id: str) -> Payload:
    for case in payload["cases"]:
        if case["case_id"] == case_id:
            return case
    msg = f"caso {case_id} ausente do corpus"
    raise AssertionError(msg)


def _iter_keys(value: object) -> Iterator[str]:
    if isinstance(value, dict):
        for key, item in value.items():
            yield str(key)
            yield from _iter_keys(item)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_keys(item)


# --- Carregamento e conformidade dos schemas ----------------------------------


def test_corpus_loads_and_validates() -> None:
    corpus = validate_corpus_payload(_corpus_payload(), source=CORPUS_PATH.name)
    assert corpus.schema_version == "1"
    assert corpus.corpus_version == "1.0.0"
    assert corpus.execution_config.max_answer_chars == 4000
    assert corpus.execution_config.max_context_chars == 12000
    assert len(corpus.cases) >= 1


def test_versioned_corpus_contains_exactly_the_approved_cases() -> None:
    corpus = validate_corpus_payload(_corpus_payload())
    assert tuple(case.case_id for case in corpus.cases) == EXPECTED_CASE_IDS


def test_rubric_loads_and_validates() -> None:
    rubric = validate_rubric_payload(_rubric_payload(), source=RUBRIC_PATH.name)
    assert rubric.schema_version == "1"
    assert rubric.rubric_version == "1.0.0"


def test_corpus_schema_file_matches_the_model() -> None:
    assert CORPUS_SCHEMA_PATH.read_text(encoding="utf-8") == canonical_schema_json(Corpus)


def test_rubric_schema_file_matches_the_model() -> None:
    assert RUBRIC_SCHEMA_PATH.read_text(encoding="utf-8") == canonical_schema_json(Rubric)


def test_generated_schemas_forbid_unknown_fields() -> None:
    # O schema versionado valida estrutura; as regras cruzadas vivem nos
    # modelos Pydantic e não são exprimíveis em JSON Schema.
    for path in (CORPUS_SCHEMA_PATH, RUBRIC_SCHEMA_PATH):
        schema = json.loads(path.read_text(encoding="utf-8"))
        assert schema["additionalProperties"] is False
        objects = [
            definition
            for definition in schema["$defs"].values()
            if definition.get("type") == "object"
        ]
        assert objects
        for definition in objects:
            assert definition.get("additionalProperties") is False


# --- Cobertura exigida pela Fase 1 --------------------------------------------


def test_all_twelve_scenarios_are_covered() -> None:
    corpus = validate_corpus_payload(_corpus_payload())
    covered = {case.scenario_id for case in corpus.cases}
    assert covered == set(SCENARIOS)


def test_scenario_names_match_the_catalogue() -> None:
    corpus = validate_corpus_payload(_corpus_payload())
    for case in corpus.cases:
        assert case.scenario == SCENARIOS[case.scenario_id]


def test_all_five_reason_codes_are_covered() -> None:
    corpus = validate_corpus_payload(_corpus_payload())
    codes = {case.expected_reason_code for case in corpus.cases if case.expected_reason_code}
    assert codes == set(ReasonCode)


def test_both_languages_are_present() -> None:
    corpus = validate_corpus_payload(_corpus_payload())
    assert {case.language for case in corpus.cases} == set(Language)


def test_all_fact_coverage_values_are_exercised() -> None:
    corpus = validate_corpus_payload(_corpus_payload())
    coverages = {fact.expected_coverage for case in corpus.cases for fact in case.expected_facts}
    assert coverages == set(FactCoverage)


def test_required_observations_are_present() -> None:
    corpus = validate_corpus_payload(_corpus_payload())
    missing_sources = [
        case
        for case in corpus.cases
        if case.generator_output is not None
        and set(case.expected_evidence_ids) - set(case.generator_output.cited_evidence_ids)
    ]
    excess_sources = [
        case
        for case in corpus.cases
        if case.generator_output is not None
        and set(case.generator_output.cited_evidence_ids) - set(case.expected_evidence_ids)
    ]
    injection_cases = [case for case in corpus.cases if case.scenario_id == 8]
    fallback_cases = [
        case
        for case in corpus.cases
        if case.expected_outcome is ExpectedOutcome.INSUFFICIENT_EVIDENCE
    ]

    assert missing_sources, "falta um caso com fontes esperadas em falta"
    assert excess_sources, "falta um caso com fonte conhecida mas excessiva"
    assert injection_cases, "falta um caso de prompt injection"
    assert any(case.forbidden_claims for case in corpus.cases), "falta um caso com forbidden_claims"
    assert fallback_cases, "falta um caso de fallback"
    for case in fallback_cases:
        assert not case.expected_generator_called
        assert case.generator_output is None


def _approved_case(case_id: str) -> Any:
    corpus = validate_corpus_payload(_corpus_payload())
    for case in corpus.cases:
        if case.case_id == case_id:
            return case
    msg = f"caso {case_id} ausente do corpus"
    raise AssertionError(msg)


def test_c012_keeps_the_known_but_excessive_citation() -> None:
    case = _approved_case("C012")
    assert case.expected_outcome is ExpectedOutcome.ANSWERED
    assert [item.evidence_id for item in case.evidence] == ["E1", "E2"]
    assert case.expected_evidence_ids == ["E1"]

    cited = case.generator_output.cited_evidence_ids
    assert "E1" in cited
    # E2 existe no contexto: é uma citação conhecida, e por isso excessiva
    # em vez de desconhecida — a distinção que separa A3 de A2.
    assert "E2" in cited
    assert set(cited) - set(case.expected_evidence_ids) == {"E2"}

    assert "deliberada" in case.rationale
    assert "excesso" in case.rationale


def test_c013_keeps_the_materially_asserted_fact_without_its_citation() -> None:
    case = _approved_case("C013")
    assert case.expected_outcome is ExpectedOutcome.ANSWERED
    assert {"E1", "E2"} <= set(case.expected_evidence_ids)
    assert case.generator_output.cited_evidence_ids == ["E1"]

    supported_by_e2 = [
        fact
        for fact in case.expected_facts
        if "E2" in fact.supported_by and fact.expected_coverage is FactCoverage.COVERED
    ]
    assert supported_by_e2, "C013 tem de declarar um facto coberto sustentado por E2"

    # Correspondência literal, não semântica: o caso está escrito para que
    # a afirmação apareça na resposta exatamente como o facto a enuncia.
    answer = case.generator_output.answer
    assert any(fact.statement in answer for fact in supported_by_e2)

    assert "deliberada" in case.rationale
    assert "falta" in case.rationale


def test_c014_keeps_the_contradicted_fact_and_the_declared_divergence() -> None:
    case = _approved_case("C014")
    assert case.expected_outcome is ExpectedOutcome.ANSWERED

    contradicted = [
        fact
        for fact in case.expected_facts
        if fact.expected_coverage is FactCoverage.CONTRADICTED
    ]
    assert contradicted, "C014 tem de declarar um facto contradito"
    assert all("E1" in fact.supported_by for fact in contradicted)

    # A resposta continua estruturalmente válida: a divergência é de
    # linguagem, não de validação determinística.
    assert case.generator_output.answer.strip()
    assert case.generator_output.cited_evidence_ids == ["E1"]
    assert case.expected_reason_code is None

    assert "deliberada" in case.rationale
    assert "linguagem excessivamente absoluta" in case.rationale


def test_reason_codes_match_the_validation_module() -> None:
    """Lê `validation.py` por AST, sem o importar.

    Importar `app.answering.validation` carregaria `app/answering/__init__.py`
    e, com ele, o adaptador do fornecedor e as Settings. Aqui confirma-se
    apenas que o enum local contém exatamente os cinco códigos definidos
    na aplicação — a ordem interna das condições de
    `validate_generated_answer` é exercitada na Fase 2.
    """
    tree = ast.parse(VALIDATION_MODULE.read_text(encoding="utf-8"))
    declared: set[str] = set()
    for node in tree.body:
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Constant):
            continue
        if not isinstance(node.value.value, str):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id.startswith("REASON_"):
                declared.add(node.value.value)

    assert declared == {code.value for code in ReasonCode}


# --- Regras cruzadas, por mutação dos artefactos -------------------------------


def _answered_without_generator_output(payload: Payload) -> None:
    _case(payload, "C001")["generator_output"] = None


def _answered_with_reason_code(payload: Payload) -> None:
    _case(payload, "C001")["expected_reason_code"] = "empty_answer"


def _answered_without_status(payload: Payload) -> None:
    _case(payload, "C001")["expected_status"] = None


def _insufficient_with_evidence(payload: Payload) -> None:
    _case(payload, "C004")["evidence"] = _case(payload, "C001")["evidence"]


def _insufficient_with_generator_called(payload: Payload) -> None:
    _case(payload, "C004")["expected_generator_called"] = True


def _insufficient_with_generator_output(payload: Payload) -> None:
    _case(payload, "C004")["generator_output"] = {
        "answer": "Resposta.",
        "cited_evidence_ids": ["E1"],
    }


def _rejected_with_status(payload: Payload) -> None:
    _case(payload, "C015")["expected_status"] = "answered"


def _rejected_without_reason_code(payload: Payload) -> None:
    _case(payload, "C015")["expected_reason_code"] = None


def _rejected_without_generator_called(payload: Payload) -> None:
    _case(payload, "C015")["expected_generator_called"] = False


def _rejected_requiring_human_review(payload: Payload) -> None:
    _case(payload, "C015")["human_review_required"] = True


def _answered_without_human_review(payload: Payload) -> None:
    _case(payload, "C001")["human_review_required"] = False


def _insufficient_without_human_review(payload: Payload) -> None:
    _case(payload, "C004")["human_review_required"] = False


def _document_title_mismatch(payload: Payload) -> None:
    _case(payload, "C002")["evidence"][1]["document_title"] = "Outro Documento"


def _document_url_mismatch(payload: Payload) -> None:
    _case(payload, "C002")["evidence"][1]["source_url"] = "https://example.invalid/outro"


def _document_official_source_mismatch(payload: Payload) -> None:
    _case(payload, "C002")["evidence"][1]["official_source"] = False


def _document_validity_mismatch(payload: Payload) -> None:
    _case(payload, "C002")["evidence"][1]["valid_from"] = "2030-01-01"


def _evidence_ids_not_contiguous(payload: Payload) -> None:
    _case(payload, "C002")["evidence"][1]["evidence_id"] = "E3"


def _document_refs_not_contiguous(payload: Payload) -> None:
    _case(payload, "C006")["evidence"][1]["document_ref"] = "D3"


def _expected_evidence_id_unknown(payload: Payload) -> None:
    _case(payload, "C001")["expected_evidence_ids"] = ["E9"]


def _expected_evidence_ids_duplicated(payload: Payload) -> None:
    _case(payload, "C002")["expected_evidence_ids"] = ["E1", "E1"]


def _fact_supported_by_unknown_evidence(payload: Payload) -> None:
    _case(payload, "C001")["expected_facts"][0]["supported_by"] = ["E9"]


def _covered_fact_without_support(payload: Payload) -> None:
    _case(payload, "C001")["expected_facts"][0]["supported_by"] = []


def _uncovered_fact_with_support(payload: Payload) -> None:
    _case(payload, "C003")["expected_facts"][1]["supported_by"] = ["E1"]


def _contradicted_fact_without_support(payload: Payload) -> None:
    _case(payload, "C014")["expected_facts"][0]["supported_by"] = []


def _fact_ids_not_contiguous(payload: Payload) -> None:
    _case(payload, "C003")["expected_facts"][1]["fact_id"] = "F3"


def _duplicate_case_id(payload: Payload) -> None:
    _case(payload, "C002")["case_id"] = "C001"


def _cases_out_of_order(payload: Payload) -> None:
    payload["cases"][0], payload["cases"][1] = payload["cases"][1], payload["cases"][0]


def _scenario_name_mismatch(payload: Payload) -> None:
    _case(payload, "C001")["scenario"] = "Citação correta"


def _unknown_scenario_id(payload: Payload) -> None:
    _case(payload, "C001")["scenario_id"] = 13


def _case_schema_version_mismatch(payload: Payload) -> None:
    _case(payload, "C001")["schema_version"] = "2"


def _evidence_language_mismatch(payload: Payload) -> None:
    _case(payload, "C001")["evidence"][0]["language"] = "en"


def _source_url_not_https(payload: Payload) -> None:
    _case(payload, "C001")["evidence"][0]["source_url"] = "http://example.invalid/x"


def _forbidden_claim_inside_the_answer(payload: Payload) -> None:
    case = _case(payload, "C009")
    case["generator_output"]["answer"] += " " + case["forbidden_claims"][0]


def _valid_answer_above_the_limit(payload: Payload) -> None:
    _case(payload, "C001")["generator_output"]["answer"] = "x" * 4001


def _too_long_case_within_the_limit(payload: Payload) -> None:
    _case(payload, "C016")["generator_output"]["answer"] = "Resposta curta."


def _answered_citing_unknown_evidence(payload: Payload) -> None:
    _case(payload, "C001")["generator_output"]["cited_evidence_ids"] = ["E9"]


def _empty_answer_case_without_citations(payload: Payload) -> None:
    _case(payload, "C015")["generator_output"]["cited_evidence_ids"] = []


def _missing_citations_case_with_a_citation(payload: Payload) -> None:
    _case(payload, "C017")["generator_output"]["cited_evidence_ids"] = ["E1"]


def _duplicate_case_citing_unknown_evidence(payload: Payload) -> None:
    _case(payload, "C018")["generator_output"]["cited_evidence_ids"] = ["E1", "E9"]


def _unknown_case_with_duplicated_citations(payload: Payload) -> None:
    _case(payload, "C019")["generator_output"]["cited_evidence_ids"] = ["E9", "E9"]


def _scenario_left_uncovered(payload: Payload) -> None:
    payload["cases"] = [case for case in payload["cases"] if case["scenario_id"] != 12]


def _reason_code_left_uncovered(payload: Payload) -> None:
    payload["cases"] = [
        case for case in payload["cases"] if case["expected_reason_code"] != "unknown_evidence_ids"
    ]


def _language_left_uncovered(payload: Payload) -> None:
    payload["cases"] = [case for case in payload["cases"] if case["language"] != "en"]


CORPUS_MUTATIONS: tuple[tuple[str, Mutation], ...] = (
    ("answered_without_generator_output", _answered_without_generator_output),
    ("answered_with_reason_code", _answered_with_reason_code),
    ("answered_without_status", _answered_without_status),
    ("insufficient_with_evidence", _insufficient_with_evidence),
    ("insufficient_with_generator_called", _insufficient_with_generator_called),
    ("insufficient_with_generator_output", _insufficient_with_generator_output),
    ("rejected_with_status", _rejected_with_status),
    ("rejected_without_reason_code", _rejected_without_reason_code),
    ("rejected_without_generator_called", _rejected_without_generator_called),
    ("rejected_requiring_human_review", _rejected_requiring_human_review),
    ("answered_without_human_review", _answered_without_human_review),
    ("insufficient_without_human_review", _insufficient_without_human_review),
    ("document_title_mismatch", _document_title_mismatch),
    ("document_url_mismatch", _document_url_mismatch),
    ("document_official_source_mismatch", _document_official_source_mismatch),
    ("document_validity_mismatch", _document_validity_mismatch),
    ("evidence_ids_not_contiguous", _evidence_ids_not_contiguous),
    ("document_refs_not_contiguous", _document_refs_not_contiguous),
    ("expected_evidence_id_unknown", _expected_evidence_id_unknown),
    ("expected_evidence_ids_duplicated", _expected_evidence_ids_duplicated),
    ("fact_supported_by_unknown_evidence", _fact_supported_by_unknown_evidence),
    ("covered_fact_without_support", _covered_fact_without_support),
    ("uncovered_fact_with_support", _uncovered_fact_with_support),
    ("contradicted_fact_without_support", _contradicted_fact_without_support),
    ("fact_ids_not_contiguous", _fact_ids_not_contiguous),
    ("duplicate_case_id", _duplicate_case_id),
    ("cases_out_of_order", _cases_out_of_order),
    ("scenario_name_mismatch", _scenario_name_mismatch),
    ("unknown_scenario_id", _unknown_scenario_id),
    ("case_schema_version_mismatch", _case_schema_version_mismatch),
    ("evidence_language_mismatch", _evidence_language_mismatch),
    ("source_url_not_https", _source_url_not_https),
    ("forbidden_claim_inside_the_answer", _forbidden_claim_inside_the_answer),
    ("valid_answer_above_the_limit", _valid_answer_above_the_limit),
    ("too_long_case_within_the_limit", _too_long_case_within_the_limit),
    ("answered_citing_unknown_evidence", _answered_citing_unknown_evidence),
    ("empty_answer_case_without_citations", _empty_answer_case_without_citations),
    ("missing_citations_case_with_a_citation", _missing_citations_case_with_a_citation),
    ("duplicate_case_citing_unknown_evidence", _duplicate_case_citing_unknown_evidence),
    ("unknown_case_with_duplicated_citations", _unknown_case_with_duplicated_citations),
    ("scenario_left_uncovered", _scenario_left_uncovered),
    ("reason_code_left_uncovered", _reason_code_left_uncovered),
    ("language_left_uncovered", _language_left_uncovered),
)


@pytest.mark.parametrize(
    "mutate", [pytest.param(mutation, id=name) for name, mutation in CORPUS_MUTATIONS]
)
def test_corpus_cross_rules_reject_mutated_copies(mutate: Mutation) -> None:
    payload = _corpus_payload()
    mutate(payload)
    with pytest.raises(ValidationError):
        Corpus.model_validate(payload)


def _rubric_with_extra_field(payload: Payload) -> None:
    payload["criteria"][0]["weight"] = 3


def _rubric_missing_criterion(payload: Payload) -> None:
    payload["criteria"] = payload["criteria"][:-1]


def _rubric_scale_without_not_applicable(payload: Payload) -> None:
    payload["scale"][3]["value"] = "3"


def _rubric_human_criterion_with_automatic_part(payload: Payload) -> None:
    payload["criteria"][0]["automatic_part"] = "A1"


def _rubric_hybrid_criterion_without_automatic_part(payload: Payload) -> None:
    payload["criteria"][3]["automatic_part"] = None


def _rubric_missing_descriptor(payload: Payload) -> None:
    del payload["criteria"][0]["descriptors"]["N/A"]


RUBRIC_MUTATIONS: tuple[tuple[str, Mutation], ...] = (
    ("extra_field", _rubric_with_extra_field),
    ("missing_criterion", _rubric_missing_criterion),
    ("scale_without_not_applicable", _rubric_scale_without_not_applicable),
    ("human_criterion_with_automatic_part", _rubric_human_criterion_with_automatic_part),
    ("hybrid_criterion_without_automatic_part", _rubric_hybrid_criterion_without_automatic_part),
    ("missing_descriptor", _rubric_missing_descriptor),
)


@pytest.mark.parametrize(
    "mutate", [pytest.param(mutation, id=name) for name, mutation in RUBRIC_MUTATIONS]
)
def test_rubric_cross_rules_reject_mutated_copies(mutate: Mutation) -> None:
    payload = _rubric_payload()
    mutate(payload)
    with pytest.raises(ValidationError):
        Rubric.model_validate(payload)


# --- Rubrica ------------------------------------------------------------------


def test_rubric_declares_the_eleven_criteria() -> None:
    rubric = validate_rubric_payload(_rubric_payload())
    assert tuple(item.criterion_id for item in rubric.criteria) == REQUIRED_CRITERION_IDS


def test_rubric_scale_is_exactly_zero_one_two_and_not_applicable() -> None:
    rubric = validate_rubric_payload(_rubric_payload())
    assert tuple(level.value for level in rubric.scale) == SCALE_VALUES
    for criterion in rubric.criteria:
        descriptors = criterion.descriptors
        assert descriptors.zero and descriptors.one and descriptors.two
        assert descriptors.not_applicable


def test_rubric_has_no_weight_or_aggregate_keys() -> None:
    # Verifica as chaves do artefacto, não o texto: os descritores podem
    # (e devem) referir-se à ausência de score agregado em prosa.
    forbidden = ("weight", "score", "threshold", "average", "percent", "aggregate")
    for key in _iter_keys(_rubric_payload()):
        assert not any(token in key.casefold() for token in forbidden), key


# --- Dados proibidos ----------------------------------------------------------


FORBIDDEN_SAMPLES: tuple[tuple[str, str, str], ...] = (
    ("windows_path", "windows_path", "C:\\Users\\aluno\\documentos\\ficheiro.pdf"),
    ("windows_unc_path", "windows_unc_path", "\\\\servidor\\partilha\\ficheiro.pdf"),
    ("linux_path", "unix_path", "/home/aluno/documentos/ficheiro.pdf"),
    ("macos_path", "macos_path", "/Users/aluno/Library/ficheiro.pdf"),
    ("private_key", "private_key", "-----BEGIN RSA PRIVATE KEY-----"),
    (
        "jwt",
        "jwt",
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJzaW50ZXRpY28ifQ.YWJjZGVmZ2hpamtsbW5vcHFy",
    ),
    ("openai_key", "api_key_or_token", "sk-" + "a" * 32),
    ("aws_key", "api_key_or_token", "AKIAABCDEFGHIJKLMNOP"),
    (
        "dsn_with_password",
        "credentials_in_url",
        "postgresql+psycopg://utilizador:segredo@servidor:5432/base",
    ),
    ("url_outside_allowlist", "url_outside_allowlist", "https://www.example.com/pagina"),
    ("uuid", "uuid", "0f9b1d2e-3a4b-4c5d-8e6f-7a8b9c0d1e2f"),
    ("sha256", "hex_digest", "a" * 64),
    ("email", "email_address", "pessoa.exemplo@example.com"),
    ("ip_address", "ip_address", "192.168.1.10"),
)


@pytest.mark.parametrize(
    ("expected_pattern", "sample"),
    [pytest.param(pattern, sample, id=name) for name, pattern, sample in FORBIDDEN_SAMPLES],
)
def test_forbidden_data_is_detected(expected_pattern: str, sample: str) -> None:
    payload = _corpus_payload()
    _case(payload, "C001")["question"] = f"Pergunta sintética {sample} restante"
    findings = scan_forbidden_data(payload)
    assert expected_pattern in {finding.pattern_name for finding in findings}


@pytest.mark.parametrize(
    "sample", [pytest.param(sample, id=name) for name, _, sample in FORBIDDEN_SAMPLES]
)
def test_forbidden_data_rejects_the_artefact_without_echoing_the_value(sample: str) -> None:
    payload = _corpus_payload()
    _case(payload, "C001")["question"] = f"Pergunta sintética {sample} restante"
    with pytest.raises(AssetValidationError) as excinfo:
        validate_corpus_payload(payload, source="corpus-mutado")
    message = str(excinfo.value)
    assert sample not in message
    assert "/cases/0/question" in message


def test_clean_artefacts_have_no_forbidden_data() -> None:
    assert scan_forbidden_data(_corpus_payload()) == ()
    assert scan_forbidden_data(_rubric_payload()) == ()


def test_every_synthetic_url_uses_the_authorised_domain() -> None:
    corpus = validate_corpus_payload(_corpus_payload())
    urls = [
        item.source_url
        for case in corpus.cases
        for item in case.evidence
        if item.source_url is not None
    ]
    assert urls
    assert all(url.startswith("https://example.invalid/") for url in urls)


# --- Isolamento ---------------------------------------------------------------


_ISOLATION_SNIPPET = """
import builtins
import io
import os
import socket
import sys
from pathlib import Path

PROJECT_ROOT = Path.cwd().resolve().parent
STORAGE_ROOT = PROJECT_ROOT / "storage"


class IsolationBreach(RuntimeError):
    pass


def _blocked_network(*args, **kwargs):
    raise IsolationBreach("tentativa de acesso a rede")


# Subclasse, e nao funcao: modulos da biblioteca padrao derivam de
# socket.socket ao serem importados (ssl.SSLSocket, por exemplo). A
# classe mantem a heranca possivel e recusa a instanciacao.
class _BlockedSocket(socket.socket):
    def __init__(self, *args, **kwargs):
        raise IsolationBreach("tentativa de acesso a rede")


socket.socket = _BlockedSocket
socket.create_connection = _blocked_network

_real_open = builtins.open


def _guarded_open(file, *args, **kwargs):
    # Guarda estreita: bloqueia apenas o storage de desenvolvimento do
    # projeto. Import de modulos, corpus, rubrica e schemas continuam a
    # ser legiveis.
    try:
        candidate = Path(os.fspath(file)).resolve()
    except TypeError:
        return _real_open(file, *args, **kwargs)
    if candidate == STORAGE_ROOT or STORAGE_ROOT in candidate.parents:
        raise IsolationBreach("tentativa de acesso ao storage de desenvolvimento")
    return _real_open(file, *args, **kwargs)


builtins.open = _guarded_open
io.open = _guarded_open

# As guardas so provam alguma coisa se estiverem realmente armadas.
try:
    socket.socket()
except IsolationBreach:
    pass
else:
    raise SystemExit("guarda de rede inativa")

try:
    _guarded_open(STORAGE_ROOT / "sonda.txt")
except IsolationBreach:
    pass
else:
    raise SystemExit("guarda de storage inativa")

from app.evaluation.assets import load_corpus, load_rubric

load_corpus()
load_rubric()

imported = [
    name
    for name in ("app.core.config", "app.main", "openai", "fastapi", "sqlalchemy")
    if name in sys.modules
]
if imported:
    raise SystemExit("modulos importados: " + ",".join(imported))
print("ok")
"""


def test_evaluation_package_validates_assets_in_isolation() -> None:
    """Valida os artefactos num processo sem `.env` e sem configuração.

    O subprocesso corre a partir de `backend/` (onde não existe `.env`) e
    com as variáveis de base de dados, autenticação e fornecedor
    removidas. Antes de importar `app.evaluation`, substitui
    `socket.socket`/`socket.create_connection` e envolve `open`/`io.open`
    numa guarda que recusa caminhos sob o `storage/` do projeto, e
    confirma que ambas as guardas disparam.

    O que fica provado: a validação corre sem `.env`, sem configuração de
    fornecedor, sem base de dados, sem rede e sem tocar no storage de
    desenvolvimento. O que **não** fica provado: ausência de qualquer
    outro efeito colateral no sistema de ficheiros — a guarda é estreita
    e deliberada, não um sandbox.
    """
    env = {
        key: value
        for key, value in os.environ.items()
        if key
        not in {
            "DATABASE_URL",
            "TEST_DATABASE_URL",
            "JWT_SECRET_KEY",
            "BOOTSTRAP_TOKEN",
            "OPENAI_API_KEY",
            "OPENAI_MODEL",
            "DOCUMENT_STORAGE_PATH",
        }
    }
    env["PYTHONPATH"] = str(BACKEND_DIR)

    result = subprocess.run(  # noqa: S603 - comando fixo, sem entrada externa
        [sys.executable, "-c", _ISOLATION_SNIPPET],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )

    assert not (BACKEND_DIR / ".env").exists()
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ok" in result.stdout
