"""Human evidence trace and the v1.7 message rubric; never model-produced."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Family = Literal[
    "F01",
    "F02",
    "F03",
    "F04",
    "F05",
    "F06",
    "F07",
    "F08",
    "F09",
    "F10",
    "F11",
    "F12",
    "F13",
    "F14",
    "F15",
]
SourceKind = Literal["real", "synthetic"]


class ItemAnnotation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    item_id: Annotated[str, Field(min_length=1, max_length=32)]
    label: Annotated[str, Field(min_length=1, max_length=1000)]
    supported: bool
    #: IDs of chunks in the frozen corpus, never packet-local E1/E2 labels.
    evidence_ids: list[str]

    @model_validator(mode="after")
    def coherent(self) -> "ItemAnnotation":
        if self.supported != bool(self.evidence_ids):
            raise ValueError("supported items require evidence; unsupported items have none")
        if any(not value.strip() for value in self.evidence_ids):
            raise ValueError("evidence ids cannot be blank")
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("evidence ids must be unique")
        return self


class ReadingAnnotation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reading_id: Annotated[str, Field(min_length=1, max_length=32)]
    label: Annotated[str, Field(min_length=1, max_length=1000)]
    evidence_ids: list[str]


class ConflictAnnotation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    item_id: str
    evidence_ids: Annotated[list[str], Field(min_length=2)]
    same_conditions: Annotated[str, Field(min_length=20, max_length=2000)]

    @model_validator(mode="after")
    def distinct_evidence(self) -> "ConflictAnnotation":
        if len(set(self.evidence_ids)) < 2:
            raise ValueError("a conflict requires two distinct pieces of evidence")
        return self


class AnnotationTrace(BaseModel):
    model_config = ConfigDict(extra="forbid")
    family: Family
    source_kind: SourceKind
    snapshot_id: Annotated[str, Field(min_length=1, max_length=128)]
    rationale: Annotated[str, Field(min_length=40, max_length=8000)]
    items: list[ItemAnnotation]
    readings: list[ReadingAnnotation] = Field(default_factory=list)
    conflicts: list[ConflictAnnotation] = Field(default_factory=list)

    @model_validator(mode="after")
    def unique_ids(self) -> "AnnotationTrace":
        if len(self.rationale.strip()) < 40:
            raise ValueError("a written human rationale is required")
        for collection, field in ((self.items, "item_id"), (self.readings, "reading_id")):
            values = [getattr(item, field) for item in collection]
            if len(values) != len(set(values)):
                raise ValueError(f"duplicate {field}")
        return self


class MessageRubric(BaseModel):
    """Human binary judgments. None means not applicable, not failure."""

    model_config = ConfigDict(extra="forbid")
    supported_and_complete: bool | None
    gap_declared: bool | None
    clarification_material_and_covered: bool | None
    outdated_notice_present: bool | None
    escalation_without_transmission: bool | None
