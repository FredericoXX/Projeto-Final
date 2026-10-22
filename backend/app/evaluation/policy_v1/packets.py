"""Packets arquiváveis de evidência — a base da comparação emparelhada.

Um packet congela, para um caso e uma execução numerada, tudo o que uma
condição recebe: pedido, data de referência, papel, passagens admissíveis
finais (com conteúdo e hash), diagnóstico permitido, catálogo e configuração da
recuperação, mais ``snapshot_id`` e ``corpus_digest`` quando disponíveis.

- Família ``p_e2e``: recuperação da política (por leitura, quando P-e2e a pede).
  P-e2e, B1-plena, B1-composição e A-sem-diagnóstico recebem **o mesmo**
  packet nessa execução — mesmas passagens finais e mesmos limites de contexto.
- Família ``b0``: recuperação do B0; A-sem-filtro usa um packet ``b0`` com C9/C10
  relaxadas, construído em ambiente offline isolado.

O packet é um valor: o seu digest é a identidade da evidência que a condição
viu, e entra no registo de cada resultado.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Final, Literal
from uuid import UUID

from app.answering.base import ContextEvidence
from app.decision.dimensions import ExcludedByValidity, TemporalDiagnostic
from app.evaluation.policy_v1.freeze import canonical_bytes, sha256
from app.retrieval.base import Evidence

PACKET_VERSION: Final = "policy_v1_packet_1"

PacketFamily = Literal["p_e2e", "b0", "b0_without_validity_filter"]


@dataclass(frozen=True)
class PacketPassage:
    evidence_id: str
    chunk_id: str
    document_id: str
    document_version_id: str
    document_title: str
    chunk_index: int
    content: str
    content_sha256: str
    official_source: bool
    source_url: str | None
    language: str
    valid_from: date | None
    valid_until: date | None

    @classmethod
    def from_entry(cls, entry: ContextEvidence) -> "PacketPassage":
        evidence = entry.evidence
        return cls(
            evidence_id=entry.evidence_id,
            chunk_id=str(evidence.chunk_id),
            document_id=str(evidence.document_id),
            document_version_id=str(evidence.document_version_id),
            document_title=evidence.document_title,
            chunk_index=evidence.chunk_index,
            content=evidence.content,
            content_sha256=sha256(evidence.content.encode("utf-8")),
            official_source=evidence.official_source,
            source_url=evidence.source_url,
            language=evidence.language,
            valid_from=evidence.valid_from,
            valid_until=evidence.valid_until,
        )

    def to_entry(self) -> ContextEvidence:
        return ContextEvidence(
            evidence_id=self.evidence_id,
            evidence=Evidence(
                chunk_id=UUID(self.chunk_id),
                document_id=UUID(self.document_id),
                document_version_id=UUID(self.document_version_id),
                document_title=self.document_title,
                chunk_index=self.chunk_index,
                content=self.content,
                # O score não participa em nenhuma decisão a jusante do packet.
                score=0.0,
                language=self.language,
                official_source=self.official_source,
                source_url=self.source_url,
                valid_from=self.valid_from,
                valid_until=self.valid_until,
            ),
        )


def _date(value: date | None) -> str | None:
    return None if value is None else value.isoformat()


def _parse(value: str | None) -> date | None:
    return None if value is None else date.fromisoformat(value)


@dataclass(frozen=True)
class EvidencePacket:
    case_id: str
    family: PacketFamily
    run_number: int
    query: str
    language: str
    reference_date: date
    requester_role: str
    catalog: Mapping[str, Any]
    passages: tuple[PacketPassage, ...]
    diagnostic: TemporalDiagnostic = field(default_factory=TemporalDiagnostic)
    retrieval: Mapping[str, Any] = field(default_factory=dict)
    snapshot_id: str | None = None
    corpus_digest: str | None = None

    def entries(self) -> tuple[ContextEvidence, ...]:
        return tuple(passage.to_entry() for passage in self.passages)

    def to_dict(self) -> dict[str, Any]:
        return {
            "packet_version": PACKET_VERSION,
            "case_id": self.case_id,
            "family": self.family,
            "run_number": self.run_number,
            "query": self.query,
            "language": self.language,
            "reference_date": self.reference_date.isoformat(),
            "requester_role": self.requester_role,
            "catalog": dict(self.catalog),
            "passages": [
                {
                    "evidence_id": p.evidence_id,
                    "chunk_id": p.chunk_id,
                    "document_id": p.document_id,
                    "document_version_id": p.document_version_id,
                    "document_title": p.document_title,
                    "chunk_index": p.chunk_index,
                    "content": p.content,
                    "content_sha256": p.content_sha256,
                    "official_source": p.official_source,
                    "source_url": p.source_url,
                    "language": p.language,
                    "valid_from": _date(p.valid_from),
                    "valid_until": _date(p.valid_until),
                }
                for p in self.passages
            ],
            "diagnostic": [
                {
                    "document_id": item.document_id,
                    "document_title": item.document_title,
                    "valid_from": _date(item.valid_from),
                    "valid_until": _date(item.valid_until),
                }
                for item in self.diagnostic.excluded
            ],
            "retrieval": dict(self.retrieval),
            "snapshot_id": self.snapshot_id,
            "corpus_digest": self.corpus_digest,
        }

    @property
    def digest(self) -> str:
        return sha256(canonical_bytes(self.to_dict()))

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "EvidencePacket":
        if payload.get("packet_version") != PACKET_VERSION:
            msg = "unsupported packet version"
            raise ValueError(msg)
        return cls(
            case_id=payload["case_id"],
            family=payload["family"],
            run_number=payload["run_number"],
            query=payload["query"],
            language=payload["language"],
            reference_date=date.fromisoformat(payload["reference_date"]),
            requester_role=payload["requester_role"],
            catalog=payload["catalog"],
            passages=tuple(
                PacketPassage(
                    evidence_id=p["evidence_id"],
                    chunk_id=p["chunk_id"],
                    document_id=p["document_id"],
                    document_version_id=p["document_version_id"],
                    document_title=p["document_title"],
                    chunk_index=p["chunk_index"],
                    content=p["content"],
                    content_sha256=p["content_sha256"],
                    official_source=p["official_source"],
                    source_url=p["source_url"],
                    language=p["language"],
                    valid_from=_parse(p["valid_from"]),
                    valid_until=_parse(p["valid_until"]),
                )
                for p in payload["passages"]
            ),
            diagnostic=TemporalDiagnostic(
                excluded=tuple(
                    ExcludedByValidity(
                        document_id=item["document_id"],
                        document_title=item["document_title"],
                        valid_from=_parse(item["valid_from"]),
                        valid_until=_parse(item["valid_until"]),
                    )
                    for item in payload["diagnostic"]
                )
            ),
            retrieval=payload["retrieval"],
            snapshot_id=payload["snapshot_id"],
            corpus_digest=payload["corpus_digest"],
        )
