"""Contrato do ficheiro de casos do conjunto de avaliação da política v1 (P2).

Vive à parte do executor para não depender da configuração da aplicação nem da
base de dados: a reanálise offline e a ferramenta de rótulos leem casos sem
precisar de ``DATABASE_URL`` ou de chaves. ``executor.py`` reexporta estes
nomes, e o esquema JSON gerado não muda.
"""

from datetime import date
from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.evaluation.policy_v1.annotation_contracts import Family, SourceKind

CASES_SCHEMA_VERSION: Final = "policy_v1_cases_1"


class EvaluationCase(BaseModel):
    """Um caso do conjunto de avaliação da política v1 (P2). Sem rótulos."""

    model_config = ConfigDict(extra="forbid")

    case_id: Annotated[str, Field(min_length=1, max_length=64)]
    query: Annotated[str, Field(min_length=1, max_length=1000)]
    language: str
    reference_date: date
    #: Papel simulado, só no executor offline.
    requester_role: Literal["admin", "knowledge_manager", "staff", "student", "user"]
    official_only: bool = True
    #: Missing only in legacy development fixtures; formal runs refuse it.
    family: Family | None = None
    source_kind: SourceKind | None = None
    expected_snapshot_id: str | None = None


class EvaluationCaseSet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["policy_v1_cases_1"]
    set_id: Annotated[str, Field(min_length=1, max_length=64)]
    corpus: Literal["P2"]
    institution_code: str
    cases: list[EvaluationCase]

    @model_validator(mode="after")
    def unique_case_ids(self) -> "EvaluationCaseSet":
        ids = [case.case_id for case in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError("evaluation case ids must be unique")
        return self
