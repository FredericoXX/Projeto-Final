"""Contratos versionados dos artefactos de avaliação do Momento 5.

Define a forma do corpus sintético e da rubrica, e as regras cruzadas
que impedem estados impossíveis.

Autonomia deliberada — a validação dos artefactos tem de correr sem
`.env`, base de dados, rede, storage ou credenciais:

- este módulo não importa `app.core.config.settings` nem `app.main`;
- também não importa `app.answering`, porque `app/answering/__init__.py`
  carrega o adaptador do fornecedor e, com ele, o SDK e as Settings. Os
  cinco reason codes são por isso declarados aqui, e a correspondência
  com `app/answering/validation.py` é verificada por teste.

Divisão de responsabilidades da validação:

- os schemas JSON versionados (`*.schema.json`) validam **estrutura** —
  campos, tipos, enums e ausência de campos desconhecidos;
- as regras cruzadas — tríade de desfecho, referências entre IDs,
  cobertura de cenários e forma dos casos de rejeição — são validadas
  **apenas** pelos modelos Pydantic deste módulo, porque JSON Schema não
  as exprime.

Âmbito da Fase 1 quanto às rejeições: verifica-se que cada caso rejeitado
tem uma **forma inequívoca** (um único defeito identificável). A
precedência interna de `validate_generated_answer` não é reproduzida
aqui; é exercitada na Fase 2, chamando a implementação real.
"""

import json
from collections.abc import Sequence
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Final, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

CORPUS_SCHEMA_VERSION: Final = "1"
RUBRIC_SCHEMA_VERSION: Final = "1"
JSON_SCHEMA_DIALECT: Final = "https://json-schema.org/draft/2020-12/schema"

CASE_ID_PATTERN: Final = r"^C[0-9]{3}$"
EVIDENCE_ID_PATTERN: Final = r"^E[1-9][0-9]*$"
DOCUMENT_REF_PATTERN: Final = r"^D[1-9][0-9]*$"
FACT_ID_PATTERN: Final = r"^F[1-9][0-9]*$"
CRITERION_ID_PATTERN: Final = r"^[a-z][a-z0-9_]*$"
SEMVER_PATTERN: Final = r"^[0-9]+\.[0-9]+\.[0-9]+$"
# Único domínio sintético autorizado; a verificação de conteúdo em
# app/evaluation/assets.py repete-a sobre todas as strings.
SYNTHETIC_URL_PATTERN: Final = r"^https://example\.invalid/[^\s]*$"

# Catálogo de cenários de docs/ai/moments/moment-05.md. O corpus refere
# o cenário por número e por nome; ambos têm de coincidir.
SCENARIOS: Final[dict[int, str]] = {
    1: "Pergunta plenamente respondível",
    2: "Pergunta parcialmente respondível",
    3: "Evidência insuficiente",
    4: "Evidências contraditórias",
    5: "Evidência ambígua",
    6: "OCR degradado",
    7: "Várias datas ou regras possíveis",
    8: "Conteúdo documental com prompt injection",
    9: "Citação correta",
    10: "Citação irrelevante",
    11: "Afirmação sem suporte",
    12: "Resposta excessivamente absoluta",
}

# Critérios humanos e partes humanas das métricas híbridas (D2 e a
# tabela de métricas do Momento 5). Sem pesos e sem score agregado.
REQUIRED_CRITERION_IDS: Final[tuple[str, ...]] = (
    "factual_correctness",
    "evidence_faithfulness",
    "completeness",
    "citation_support",
    "citation_coverage",
    "fallback_comprehensibility",
    "clarity",
    "conciseness",
    "ambiguity_handling",
    "contradiction_handling",
    "absolute_language",
)

SCALE_VALUES: Final[tuple[str, ...]] = ("0", "1", "2", "N/A")

# Metadados que descrevem o documento, não o segmento: evidências que
# partilham document_ref representam o mesmo documento lógico e têm de os
# declarar de forma idêntica. Só `content` pode divergir, por serem
# chunks distintos.
DOCUMENT_METADATA_FIELDS: Final[tuple[str, ...]] = (
    "document_title",
    "language",
    "official_source",
    "source_url",
    "valid_from",
    "valid_until",
)


class ExpectedOutcome(StrEnum):
    """Desfecho do turno, que nem sempre coincide com o estado devolvido."""

    ANSWERED = "answered"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    REJECTED = "rejected"


class ExpectedStatus(StrEnum):
    """Estado devolvido em `AnsweringResponse`; ausente numa rejeição."""

    ANSWERED = "answered"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class ReasonCode(StrEnum):
    """Códigos estáveis de rejeição.

    Correspondem exatamente às constantes `REASON_*` de
    `app/answering/validation.py`. São declarados aqui, e não importados,
    para manter este módulo livre do SDK do fornecedor e das Settings; a
    igualdade entre as duas listas é verificada por teste.
    """

    EMPTY_ANSWER = "empty_answer"
    ANSWER_TOO_LONG = "answer_too_long"
    MISSING_CITATIONS = "missing_citations"
    DUPLICATE_EVIDENCE_IDS = "duplicate_evidence_ids"
    UNKNOWN_EVIDENCE_IDS = "unknown_evidence_ids"


class FactCoverage(StrEnum):
    """Classificação esperada de um facto, facto a facto (D4)."""

    COVERED = "covered"
    UNCOVERED = "uncovered"
    CONTRADICTED = "contradicted"


class Language(StrEnum):
    PT = "pt"
    EN = "en"


class AssessmentKind(StrEnum):
    HUMAN = "human"
    HYBRID = "hybrid"


def _normalized(text: str) -> str:
    """Normalização usada na comparação literal de `forbidden_claims`."""
    return " ".join(text.split()).casefold()


def _duplicates(values: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    repeated: list[str] = []
    for value in values:
        if value in seen and value not in repeated:
            repeated.append(value)
        seen.add(value)
    return repeated


class EvaluationModel(BaseModel):
    """Base comum: nenhum artefacto aceita campos desconhecidos."""

    model_config = ConfigDict(extra="forbid")


class CorpusEvidence(EvaluationModel):
    """Uma evidência sintética do contexto de um caso.

    Não contém UUID, institution ID, document ID nem caminhos de storage.
    Os identificadores técnicos exigidos por `app.retrieval.base.Evidence`
    — `chunk_id`, `document_id`, `document_version_id` — e ainda
    `chunk_index` e `score` são derivados deterministicamente na Fase 2 a
    partir de `case_id`, `document_ref` e da posição no array. O `score`
    fica fora do corpus porque o answering usa a **ordem** do ranking e
    não o valor.
    """

    evidence_id: Annotated[str, Field(pattern=EVIDENCE_ID_PATTERN)]
    document_ref: Annotated[str, Field(pattern=DOCUMENT_REF_PATTERN)]
    document_title: Annotated[str, Field(min_length=1, max_length=200)]
    content: Annotated[str, Field(min_length=1, max_length=4000)]
    language: Language
    official_source: bool
    source_url: Annotated[str, Field(pattern=SYNTHETIC_URL_PATTERN, max_length=500)] | None
    valid_from: date | None
    valid_until: date | None

    @model_validator(mode="after")
    def check_validity_window(self) -> Self:
        if (
            self.valid_from is not None
            and self.valid_until is not None
            and self.valid_until < self.valid_from
        ):
            msg = f"{self.evidence_id}: valid_until é anterior a valid_from"
            raise ValueError(msg)
        return self


class ExpectedFact(EvaluationModel):
    """Um facto que a evidência permitia responder, avaliado facto a facto.

    `expected_coverage` declara a classificação esperada para o
    `generator_output` do caso:

    - `covered` — o facto é afirmado corretamente; `supported_by` indica
      as evidências que o suportam;
    - `uncovered` — a evidência não suporta o facto e a resposta tem de o
      declarar como não coberto; `supported_by` é vazio;
    - `contradicted` — a evidência contém o facto correto e a resposta
      contradi-lo; `supported_by` indica onde o facto correto está.
    """

    fact_id: Annotated[str, Field(pattern=FACT_ID_PATTERN)]
    statement: Annotated[str, Field(min_length=1, max_length=500)]
    supported_by: list[Annotated[str, Field(pattern=EVIDENCE_ID_PATTERN)]]
    expected_coverage: FactCoverage

    @model_validator(mode="after")
    def check_support(self) -> Self:
        repeated = _duplicates(self.supported_by)
        if repeated:
            msg = f"{self.fact_id}: supported_by tem IDs repetidos: {sorted(repeated)}"
            raise ValueError(msg)
        if self.expected_coverage is FactCoverage.UNCOVERED and self.supported_by:
            msg = f"{self.fact_id}: um facto uncovered não pode ter supported_by"
            raise ValueError(msg)
        if self.expected_coverage is not FactCoverage.UNCOVERED and not self.supported_by:
            msg = f"{self.fact_id}: {self.expected_coverage.value} exige supported_by não vazio"
            raise ValueError(msg)
        return self


class GeneratorOutput(EvaluationModel):
    """O `GeneratedAnswer` controlado que o gerador falso devolve.

    É **entrada controlada**, não a resposta ideal: os campos `expected_*`
    é que declaram a expectativa. Onde divergem, a divergência é
    deliberada e está declarada no `rationale` do caso.
    """

    answer: Annotated[str, Field(max_length=20000)]
    cited_evidence_ids: list[Annotated[str, Field(pattern=EVIDENCE_ID_PATTERN)]]


class ExecutionConfig(EvaluationModel):
    """Configuração que o avaliador tem de reproduzir.

    Fixada no corpus para que a validação e a avaliação não dependam de
    `settings` nem de `.env`.
    """

    max_answer_chars: Annotated[int, Field(ge=1)]
    max_context_chars: Annotated[int, Field(ge=1)]
    institution_name: Annotated[str, Field(min_length=1, max_length=200)]


class CorpusCase(EvaluationModel):
    """Um caso sintético: entrada, saída controlada e expectativa.

    `human_review_required` indica **se existe uma resposta pública à
    qual a rubrica humana pode ser aplicada**: verdadeiro em `answered` e
    em `insufficient_evidence` — onde o fallback devolvido é ele próprio
    objeto de juízo humano — e falso em `rejected`, porque uma rejeição
    termina em erro e não devolve texto. Não significa que o caso ou o
    corpus dispensem revisão ou aprovação humana: a revisão humana do
    conteúdo é critério de paragem da Fase 1 para todos os casos, sem
    exceção.
    """

    schema_version: Literal["1"]
    case_id: Annotated[str, Field(pattern=CASE_ID_PATTERN)]
    scenario_id: Annotated[int, Field(ge=1, le=12)]
    scenario: Annotated[str, Field(min_length=1, max_length=120)]
    language: Language
    question: Annotated[str, Field(min_length=1, max_length=1000)]
    evidence: list[CorpusEvidence]
    rationale: Annotated[str, Field(min_length=1, max_length=1000)]
    expected_outcome: ExpectedOutcome
    expected_status: ExpectedStatus | None
    expected_evidence_ids: list[Annotated[str, Field(pattern=EVIDENCE_ID_PATTERN)]]
    expected_facts: list[ExpectedFact]
    forbidden_claims: list[Annotated[str, Field(min_length=1, max_length=200)]]
    human_review_required: bool
    expected_generator_called: bool
    generator_output: GeneratorOutput | None
    expected_reason_code: ReasonCode | None

    @property
    def evidence_ids(self) -> tuple[str, ...]:
        return tuple(item.evidence_id for item in self.evidence)

    @model_validator(mode="after")
    def check_case(self) -> Self:
        self._check_scenario()
        self._check_evidence()
        self._check_document_metadata()
        self._check_expected_evidence_ids()
        self._check_expected_facts()
        self._check_outcome_triad()
        self._check_forbidden_claims()
        self._check_citation_shape()
        return self

    def _check_scenario(self) -> None:
        expected = SCENARIOS[self.scenario_id]
        if self.scenario != expected:
            msg = (
                f"{self.case_id}: scenario {self.scenario!r} não corresponde ao "
                f"cenário {self.scenario_id} ({expected!r})"
            )
            raise ValueError(msg)

    def _check_evidence(self) -> None:
        expected_ids = [f"E{index}" for index in range(1, len(self.evidence) + 1)]
        if list(self.evidence_ids) != expected_ids:
            msg = (
                f"{self.case_id}: evidence_id tem de ser contíguo e seguir a ordem do "
                f"array ({expected_ids})"
            )
            raise ValueError(msg)

        seen_refs: list[str] = []
        for item in self.evidence:
            if item.document_ref not in seen_refs:
                seen_refs.append(item.document_ref)
        expected_refs = [f"D{index}" for index in range(1, len(seen_refs) + 1)]
        if seen_refs != expected_refs:
            msg = (
                f"{self.case_id}: document_ref tem de ser contíguo por ordem de primeira "
                f"ocorrência ({expected_refs})"
            )
            raise ValueError(msg)

        for item in self.evidence:
            if item.language is not self.language:
                msg = (
                    f"{self.case_id}: {item.evidence_id} está em {item.language.value} e o "
                    f"caso em {self.language.value}; a recuperação é por idioma"
                )
                raise ValueError(msg)

    def _check_document_metadata(self) -> None:
        """Evidências com o mesmo `document_ref` são o mesmo documento.

        Só `content` pode divergir — são chunks distintos. Metadados
        incompatíveis representariam como um documento único aquilo que a
        recuperação real nunca poderia devolver assim.
        """
        first_by_ref: dict[str, CorpusEvidence] = {}
        for item in self.evidence:
            first = first_by_ref.setdefault(item.document_ref, item)
            if first is item:
                continue
            for field_name in DOCUMENT_METADATA_FIELDS:
                if getattr(first, field_name) != getattr(item, field_name):
                    msg = (
                        f"{self.case_id}: {item.evidence_id} e {first.evidence_id} partilham "
                        f"{item.document_ref} mas divergem em {field_name}"
                    )
                    raise ValueError(msg)

    def _check_expected_evidence_ids(self) -> None:
        repeated = _duplicates(self.expected_evidence_ids)
        if repeated:
            msg = f"{self.case_id}: expected_evidence_ids tem IDs repetidos: {sorted(repeated)}"
            raise ValueError(msg)
        unknown = sorted(set(self.expected_evidence_ids) - set(self.evidence_ids))
        if unknown:
            msg = f"{self.case_id}: expected_evidence_ids refere evidências inexistentes: {unknown}"
            raise ValueError(msg)

    def _check_expected_facts(self) -> None:
        expected_ids = [f"F{index}" for index in range(1, len(self.expected_facts) + 1)]
        actual_ids = [fact.fact_id for fact in self.expected_facts]
        if actual_ids != expected_ids:
            msg = f"{self.case_id}: fact_id tem de ser contíguo e ordenado ({expected_ids})"
            raise ValueError(msg)
        known = set(self.evidence_ids)
        for fact in self.expected_facts:
            unknown = sorted(set(fact.supported_by) - known)
            if unknown:
                msg = (
                    f"{self.case_id}/{fact.fact_id}: supported_by refere evidências "
                    f"inexistentes: {unknown}"
                )
                raise ValueError(msg)

    def _check_outcome_triad(self) -> None:
        has_evidence = bool(self.evidence)
        if self.expected_outcome is ExpectedOutcome.ANSWERED:
            self._require(has_evidence, "answered exige evidência não vazia")
            self._require(self.expected_generator_called, "answered exige gerador chamado")
            self._require(self.generator_output is not None, "answered exige generator_output")
            self._require(
                self.expected_status is ExpectedStatus.ANSWERED,
                'answered exige expected_status="answered"',
            )
            self._require(
                self.expected_reason_code is None,
                "answered não pode ter expected_reason_code",
            )
            self._require(
                self.human_review_required,
                "answered devolve resposta: human_review_required tem de ser true",
            )
        elif self.expected_outcome is ExpectedOutcome.INSUFFICIENT_EVIDENCE:
            self._require(not has_evidence, "insufficient_evidence exige evidência vazia")
            self._require(
                not self.expected_generator_called,
                "insufficient_evidence exige gerador não chamado",
            )
            self._require(
                self.generator_output is None,
                "insufficient_evidence não pode ter generator_output",
            )
            self._require(
                self.expected_status is ExpectedStatus.INSUFFICIENT_EVIDENCE,
                'insufficient_evidence exige expected_status="insufficient_evidence"',
            )
            self._require(
                self.expected_reason_code is None,
                "insufficient_evidence não pode ter expected_reason_code",
            )
            self._require(
                self.human_review_required,
                "o fallback é avaliado por juízo humano: human_review_required tem de ser true",
            )
        else:
            self._require(has_evidence, "rejected exige evidência não vazia")
            self._require(self.expected_generator_called, "rejected exige gerador chamado")
            self._require(self.generator_output is not None, "rejected exige generator_output")
            self._require(
                self.expected_status is None,
                "rejected exige expected_status ausente ou nulo",
            )
            self._require(
                self.expected_reason_code is not None,
                "rejected exige expected_reason_code",
            )
            self._require(
                not self.human_review_required,
                "rejected não devolve resposta: human_review_required tem de ser false",
            )

    def _check_forbidden_claims(self) -> None:
        repeated = _duplicates(self.forbidden_claims)
        if repeated:
            msg = f"{self.case_id}: forbidden_claims tem entradas repetidas: {sorted(repeated)}"
            raise ValueError(msg)
        if self.generator_output is None:
            return
        answer = _normalized(self.generator_output.answer)
        for claim in self.forbidden_claims:
            if _normalized(claim) in answer:
                msg = (
                    f"{self.case_id}: o generator_output declarado contém uma forbidden_claim; "
                    "o corpus não pode violar por construção a sua própria expectativa"
                )
                raise ValueError(msg)

    def _check_citation_shape(self) -> None:
        """Forma inequívoca das citações, por desfecho.

        A Fase 1 não reproduz a precedência de `validate_generated_answer`:
        exige apenas que cada caso rejeitado isole um único defeito
        identificável. As verificações que dependem de `max_answer_chars`
        vivem em `Corpus`, que conhece o `execution_config`.
        """
        if self.generator_output is None:
            return

        cited = self.generator_output.cited_evidence_ids
        answer_is_blank = not self.generator_output.answer.strip()
        repeated = _duplicates(cited)
        unknown = sorted(set(cited) - set(self.evidence_ids))
        code = self.expected_reason_code

        if code is None:
            self._require(not answer_is_blank, "uma resposta válida não pode ser vazia")
            self._require(bool(cited), "uma resposta válida exige pelo menos uma citação")
            self._require(not repeated, "uma resposta válida não pode ter citações duplicadas")
            self._require(not unknown, f"citações desconhecidas numa resposta válida: {unknown}")
            return

        if code is ReasonCode.EMPTY_ANSWER:
            self._require(answer_is_blank, "empty_answer exige resposta vazia")
            self._require(bool(cited), "empty_answer exige citações presentes")
            self._require(not repeated, "empty_answer exige citações únicas")
            self._require(not unknown, "empty_answer exige citações conhecidas")
        elif code is ReasonCode.ANSWER_TOO_LONG:
            self._require(not answer_is_blank, "answer_too_long exige resposta não vazia")
            self._require(bool(cited), "answer_too_long exige citações presentes")
            self._require(not repeated, "answer_too_long exige citações únicas")
            self._require(not unknown, "answer_too_long exige citações conhecidas")
        elif code is ReasonCode.MISSING_CITATIONS:
            self._require(not answer_is_blank, "missing_citations exige resposta não vazia")
            self._require(not cited, "missing_citations exige lista de citações vazia")
        elif code is ReasonCode.DUPLICATE_EVIDENCE_IDS:
            self._require(not answer_is_blank, "duplicate_evidence_ids exige resposta não vazia")
            self._require(bool(repeated), "duplicate_evidence_ids exige citações duplicadas")
            self._require(not unknown, "duplicate_evidence_ids exige IDs conhecidos")
        else:
            self._require(not answer_is_blank, "unknown_evidence_ids exige resposta não vazia")
            self._require(not repeated, "unknown_evidence_ids exige citações únicas")
            self._require(bool(unknown), "unknown_evidence_ids exige pelo menos um ID desconhecido")

    def _require(self, condition: bool, message: str) -> None:
        if not condition:
            msg = f"{self.case_id}: {message}"
            raise ValueError(msg)


class Corpus(EvaluationModel):
    """Envelope do corpus sintético de avaliação."""

    schema_version: Literal["1"]
    corpus_version: Annotated[str, Field(pattern=SEMVER_PATTERN)]
    description: Annotated[str, Field(min_length=1, max_length=2000)]
    execution_config: ExecutionConfig
    cases: Annotated[list[CorpusCase], Field(min_length=1)]

    @model_validator(mode="after")
    def check_corpus(self) -> Self:
        self._check_case_ids()
        self._check_answer_lengths()
        self._check_coverage()
        return self

    def _check_case_ids(self) -> None:
        case_ids = [case.case_id for case in self.cases]
        repeated = _duplicates(case_ids)
        if repeated:
            msg = f"case_id repetido: {sorted(repeated)}"
            raise ValueError(msg)
        if case_ids != sorted(case_ids):
            msg = "os casos têm de estar ordenados por case_id"
            raise ValueError(msg)

    def _check_answer_lengths(self) -> None:
        limit = self.execution_config.max_answer_chars
        for case in self.cases:
            if case.generator_output is None:
                continue
            length = len(case.generator_output.answer)
            too_long = case.expected_reason_code is ReasonCode.ANSWER_TOO_LONG
            if too_long and length <= limit:
                msg = (
                    f"{case.case_id}: answer_too_long exige uma resposta acima de "
                    f"{limit} caracteres (tem {length})"
                )
                raise ValueError(msg)
            if not too_long and length > limit:
                msg = (
                    f"{case.case_id}: a resposta declarada excede max_answer_chars "
                    f"({length} > {limit}) sem ser o caso answer_too_long"
                )
                raise ValueError(msg)

    def _check_coverage(self) -> None:
        scenarios = {case.scenario_id for case in self.cases}
        missing_scenarios = sorted(set(SCENARIOS) - scenarios)
        if missing_scenarios:
            msg = f"cenários sem caso no corpus: {missing_scenarios}"
            raise ValueError(msg)

        codes = {case.expected_reason_code for case in self.cases if case.expected_reason_code}
        missing_codes = sorted(code.value for code in set(ReasonCode) - codes)
        if missing_codes:
            msg = f"reason codes sem caso no corpus: {missing_codes}"
            raise ValueError(msg)

        languages = {case.language for case in self.cases}
        missing_languages = sorted(language.value for language in set(Language) - languages)
        if missing_languages:
            msg = f"idiomas sem caso no corpus: {missing_languages}"
            raise ValueError(msg)

        coverages = {
            fact.expected_coverage for case in self.cases for fact in case.expected_facts
        }
        missing_coverages = sorted(value.value for value in set(FactCoverage) - coverages)
        if missing_coverages:
            msg = f"classificações de expected_coverage sem caso no corpus: {missing_coverages}"
            raise ValueError(msg)


class RubricScaleLevel(EvaluationModel):
    value: Literal["0", "1", "2", "N/A"]
    label: Annotated[str, Field(min_length=1, max_length=100)]
    meaning: Annotated[str, Field(min_length=1, max_length=500)]


class RubricDescriptors(EvaluationModel):
    """Descritores por nível. As chaves JSON são "0", "1", "2" e "N/A"."""

    zero: Annotated[str, Field(alias="0", min_length=1, max_length=1000)]
    one: Annotated[str, Field(alias="1", min_length=1, max_length=1000)]
    two: Annotated[str, Field(alias="2", min_length=1, max_length=1000)]
    not_applicable: Annotated[str, Field(alias="N/A", min_length=1, max_length=1000)]


class RubricCriterion(EvaluationModel):
    criterion_id: Annotated[str, Field(pattern=CRITERION_ID_PATTERN)]
    name: Annotated[str, Field(min_length=1, max_length=120)]
    metric: Annotated[str, Field(min_length=1, max_length=120)]
    assessment: AssessmentKind
    automatic_part: Annotated[str, Field(min_length=1, max_length=500)] | None
    human_part: Annotated[str, Field(min_length=1, max_length=500)]
    applies_to_scenarios: Annotated[list[Annotated[int, Field(ge=1, le=12)]], Field(min_length=1)]
    descriptors: RubricDescriptors
    indicators: list[Annotated[str, Field(min_length=1, max_length=300)]]
    record: Annotated[str, Field(min_length=1, max_length=500)]

    @model_validator(mode="after")
    def check_criterion(self) -> Self:
        scenarios = self.applies_to_scenarios
        if scenarios != sorted(set(scenarios)):
            msg = f"{self.criterion_id}: applies_to_scenarios tem de ser único e ordenado"
            raise ValueError(msg)
        if self.assessment is AssessmentKind.HYBRID and self.automatic_part is None:
            msg = f"{self.criterion_id}: um critério híbrido tem de declarar a parte automática"
            raise ValueError(msg)
        if self.assessment is AssessmentKind.HUMAN and self.automatic_part is not None:
            msg = f"{self.criterion_id}: um critério humano não tem parte automática"
            raise ValueError(msg)
        return self


class RubricRecordingRequirements(EvaluationModel):
    required_fields: Annotated[list[Annotated[str, Field(min_length=1)]], Field(min_length=1)]
    disagreement_protocol: Annotated[str, Field(min_length=1, max_length=1000)]
    single_evaluator_allowed: bool

    @model_validator(mode="after")
    def check_fields(self) -> Self:
        repeated = _duplicates(self.required_fields)
        if repeated:
            msg = f"required_fields tem entradas repetidas: {sorted(repeated)}"
            raise ValueError(msg)
        return self


class Rubric(EvaluationModel):
    """Rubrica de avaliação humana.

    Não tem — nem pode ter, por `extra="forbid"` — pesos, médias,
    percentagens, score agregado ou limiar semântico automático.
    """

    schema_version: Literal["1"]
    rubric_version: Annotated[str, Field(pattern=SEMVER_PATTERN)]
    description: Annotated[str, Field(min_length=1, max_length=2000)]
    scale: Annotated[list[RubricScaleLevel], Field(min_length=4, max_length=4)]
    criteria: Annotated[list[RubricCriterion], Field(min_length=1)]
    recording_requirements: RubricRecordingRequirements
    limitations: Annotated[list[Annotated[str, Field(min_length=1)]], Field(min_length=1)]

    @model_validator(mode="after")
    def check_rubric(self) -> Self:
        values = tuple(level.value for level in self.scale)
        if values != SCALE_VALUES:
            msg = f"a escala tem de ser exatamente {list(SCALE_VALUES)}, pela mesma ordem"
            raise ValueError(msg)

        criterion_ids = tuple(criterion.criterion_id for criterion in self.criteria)
        if criterion_ids != REQUIRED_CRITERION_IDS:
            msg = (
                "a rubrica tem de declarar exatamente os critérios "
                f"{list(REQUIRED_CRITERION_IDS)}, pela mesma ordem"
            )
            raise ValueError(msg)
        return self


def canonical_schema_json(model: type[BaseModel]) -> str:
    """Representação canónica e determinística do JSON Schema do modelo.

    `sort_keys=True` torna a saída imune a mudanças na ordem de inserção;
    a versão do Pydantic está fixada em `requirements.txt` para que o
    resultado seja reproduzível.
    """
    schema = model.model_json_schema(by_alias=True)
    schema["$schema"] = JSON_SCHEMA_DIALECT
    return json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def write_versioned_schemas(directory: Path) -> None:
    """Regenera os schemas versionados a partir dos modelos.

    Não é um mecanismo de avaliação nem uma CLI: é a função que produz os
    artefactos cuja divergência os testes detetam. Regeneração:

        python -c "from pathlib import Path; \
from app.evaluation.contracts import write_versioned_schemas; \
write_versioned_schemas(Path('evaluation'))"
    """
    (directory / "corpus.schema.json").write_text(
        canonical_schema_json(Corpus), encoding="utf-8", newline="\n"
    )
    (directory / "rubric.schema.json").write_text(
        canonical_schema_json(Rubric), encoding="utf-8", newline="\n"
    )
