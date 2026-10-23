"""Inventário documental do corpus P2 — o artefacto congelado ``manifest``.

O manifesto documental não é uma declaração escrita à mão: é o inventário de
**todos** os documentos, versões e segmentos da instituição, lido da base de
dados. Entram também os documentos fora de vigor, inativos ou restritos por
papel, porque A-sem-filtro e o diagnóstico temporal os veem, e uma mudança num
papel ou numa data altera o que cada condição recebe.

O executor recolhe o inventário da base antes do primeiro caso e volta a
recolhê-lo antes de escrever o relatório. Em ambos os momentos tem de coincidir,
byte a byte, com o congelado: uma alteração à base deixa de passar despercebida.

O ``corpus_digest`` de cada snapshot continua registado em cada packet. Mede só
o corpus elegível para a língua, a data e o papel de um caso, e por isso não
substitui este inventário.

Os hashes dos segmentos são recalculados a partir do conteúdo, nunca lidos de
``document_chunks.content_sha256``: tal como no snapshot, a identidade deriva
do conteúdo real. O retriever em uso é lexical; não há embeddings a congelar.
"""

import hashlib
from datetime import date
from typing import Annotated, Any, Final, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.evaluation.policy_v1.freeze import FreezeError, canonical_bytes
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.document_version import DocumentVersion
from app.models.institution import Institution

CORPUS_INVENTORY_VERSION: Final = "policy_v1_corpus_inventory_1"

Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ChunkEntry(_Strict):
    chunk_id: UUID
    chunk_index: int
    language: str
    content_sha256: Sha256
    normalized_content_sha256: Sha256
    section_title: str | None
    structure_type: str | None


class VersionEntry(_Strict):
    document_version_id: UUID
    version_number: int
    checksum_sha256: Sha256
    processing_status: str
    chunks: list[ChunkEntry]

    @model_validator(mode="after")
    def ordered(self) -> "VersionEntry":
        indexes = [chunk.chunk_index for chunk in self.chunks]
        if indexes != sorted(set(indexes)):
            msg = "chunks must be unique and ordered by chunk_index"
            raise ValueError(msg)
        return self


class DocumentEntry(_Strict):
    document_id: UUID
    title: str
    language: str
    official_source: bool
    is_active: bool
    access_roles: list[str]
    valid_from: date | None
    valid_until: date | None
    source_url: str | None
    versions: list[VersionEntry]

    @model_validator(mode="after")
    def ordered(self) -> "DocumentEntry":
        if self.access_roles != sorted(set(self.access_roles)):
            msg = "access_roles must be unique and sorted"
            raise ValueError(msg)
        numbers = [version.version_number for version in self.versions]
        if numbers != sorted(set(numbers)):
            msg = "versions must be unique and ordered by version_number"
            raise ValueError(msg)
        return self


class CorpusInventory(_Strict):
    inventory_version: Literal["policy_v1_corpus_inventory_1"]
    institution_id: UUID
    institution_code: str
    documents: list[DocumentEntry]

    @model_validator(mode="after")
    def ordered(self) -> "CorpusInventory":
        ids = [str(document.document_id) for document in self.documents]
        if ids != sorted(set(ids)):
            msg = "documents must be unique and ordered by document_id"
            raise ValueError(msg)
        return self


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def collect_corpus_inventory(db: Session, institution_id: UUID) -> dict[str, Any]:
    """Inventário canónico da instituição, já na ordem que a validação exige."""
    institution = db.get_one(Institution, institution_id)
    documents = db.scalars(select(Document).where(Document.institution_id == institution_id)).all()
    versions = db.scalars(
        select(DocumentVersion).where(DocumentVersion.institution_id == institution_id)
    ).all()
    chunks = db.execute(
        select(
            DocumentChunk.id,
            DocumentChunk.document_version_id,
            DocumentChunk.chunk_index,
            DocumentChunk.language,
            DocumentChunk.content,
            DocumentChunk.normalized_content,
            DocumentChunk.section_title,
            DocumentChunk.structure_type,
        ).where(DocumentChunk.institution_id == institution_id)
    ).all()

    chunks_by_version: dict[UUID, list[dict[str, Any]]] = {}
    for row in chunks:
        chunks_by_version.setdefault(row.document_version_id, []).append(
            {
                "chunk_id": str(row.id),
                "chunk_index": row.chunk_index,
                "language": row.language,
                "content_sha256": _sha256(row.content),
                "normalized_content_sha256": _sha256(row.normalized_content),
                "section_title": row.section_title,
                "structure_type": row.structure_type,
            }
        )
    versions_by_document: dict[UUID, list[dict[str, Any]]] = {}
    for version in versions:
        versions_by_document.setdefault(version.document_id, []).append(
            {
                "document_version_id": str(version.id),
                "version_number": version.version_number,
                "checksum_sha256": version.checksum_sha256,
                "processing_status": version.processing_status,
                "chunks": sorted(
                    chunks_by_version.get(version.id, []), key=lambda c: c["chunk_index"]
                ),
            }
        )
    entries = [
        {
            "document_id": str(document.id),
            "title": document.title,
            "language": document.language,
            "official_source": document.official_source,
            "is_active": document.is_active,
            "access_roles": sorted(set(document.access_roles)),
            "valid_from": None if document.valid_from is None else document.valid_from.isoformat(),
            "valid_until": (
                None if document.valid_until is None else document.valid_until.isoformat()
            ),
            "source_url": document.source_url,
            "versions": sorted(
                versions_by_document.get(document.id, []), key=lambda v: v["version_number"]
            ),
        }
        for document in documents
    ]
    return {
        "inventory_version": CORPUS_INVENTORY_VERSION,
        "institution_id": str(institution.id),
        "institution_code": institution.code,
        "documents": sorted(entries, key=lambda d: d["document_id"]),
    }


def corpus_inventory_bytes(payload: Any) -> bytes:
    """Bytes congelados do inventário, depois de validado.

    A ordem dos arrays é **exigida**, não reposta: a receita de congelamento
    preserva a ordem de todos os arrays, e um inventário fora de ordem não foi
    produzido por :func:`collect_corpus_inventory`.
    """
    try:
        inventory = CorpusInventory.model_validate(payload)
    except ValidationError as exc:
        msg = f"invalid corpus inventory: {exc.error_count()} error(s)"
        raise FreezeError(msg) from exc
    return canonical_bytes(inventory.model_dump(mode="json"))
