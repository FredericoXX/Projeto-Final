"""Contratos neutros para estratégias substituíveis de retrieval."""

from dataclasses import dataclass
from datetime import date
from typing import Protocol
from uuid import UUID

from sqlalchemy.orm import Session


@dataclass(frozen=True)
class RetrievalContext:
    institution_id: UUID
    language: str
    reference_date: date


@dataclass(frozen=True)
class Evidence:
    chunk_id: UUID
    document_id: UUID
    document_version_id: UUID
    document_title: str
    chunk_index: int
    content: str
    score: float
    language: str
    official_source: bool
    source_url: str | None
    valid_from: date | None
    valid_until: date | None


class Retriever(Protocol):
    def search(
        self,
        db: Session,
        query: str,
        context: RetrievalContext,
        top_k: int,
        official_only: bool,
    ) -> list[Evidence]: ...
