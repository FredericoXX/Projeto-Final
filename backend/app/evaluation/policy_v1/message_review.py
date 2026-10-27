"""Pacote de revisão humana das mensagens (M7), a partir de um relatório arquivado.

Três ficheiros, com papéis separados:

- ``review-material.md`` — o que o avaliador lê. Por caso: o pedido, a data de
  referência e o papel simulado; por mensagem: condição, ação, regra, destino,
  os critérios que exigem juízo, o texto exato e as citações; e as passagens e o
  diagnóstico temporal de cada packet que as condições receberam. **Contém
  conteúdo dos documentos consultados e as mensagens produzidas**: fica no
  ambiente autorizado e nunca vai para logs, issues ou repositórios.
- ``ratings-draft.json`` — o ficheiro de importação, em **rascunho**
  (``policy_v1_message_ratings_draft_1``): a identidade completa de cada
  mensagem e todos os juízos a ``"pending"``. Não é confundível com uma
  avaliação concluída e a reanálise recusa-o.
- ``review-manifest.json`` — a proveniência da exportação: o relatório de origem,
  os hashes dos dois ficheiros e as mensagens excluídas, por motivo.

Só entram as mensagens da **execução principal** sem falha técnica: M7 é
calculada sobre ela, uma falha técnica não produziu mensagem e P-oráculo não
compõe mensagens.

A condição de cada mensagem é visível no material e no rascunho: o pacote **não**
garante revisão cega. Se o protocolo a exigir, é uma decisão a tomar antes de
recolher as avaliações.

Nada aqui gera juízos, justificações, ações preferidas ou adjudicações.
"""

import json
import re
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Final

from app.evaluation.policy_v1.conditions import CaseOutcome, Condition
from app.evaluation.policy_v1.freeze import sha256
from app.evaluation.policy_v1.message_ratings import (
    MESSAGE_IDENTITY_VERSION,
    PENDING,
    RATINGS_DRAFT_SCHEMA_VERSION,
    RUBRIC_CRITERIA,
    DraftProvenance,
    MessageRatingDraft,
    MessageReference,
    SourceReport,
    draft_rating,
    message_reference,
    required_criteria,
    unrateable_reason,
)
from app.evaluation.policy_v1.packets import EvidencePacket
from app.evaluation.policy_v1.report import ArchivedCollection, CaseMetadataEntry
from app.evaluation.policy_v1.runs import PRIMARY_RUN

REVIEW_EXPORT_VERSION: Final = "policy_v1_message_review_1"
MATERIAL_FILE: Final = "review-material.md"
DRAFT_FILE: Final = "ratings-draft.json"
MANIFEST_FILE: Final = "review-manifest.json"

#: Leitura humana de cada critério da rubrica M7 (secção 9.1 da v1.7).
CRITERION_GUIDE: Final[Mapping[str, str]] = {
    "supported_and_complete": (
        "a resposta é sustentada pelas passagens que a condição recebeu e responde "
        "ao que afirma responder (ANSWER)"
    ),
    "gap_declared": "os itens sem suporte são declarados como lacuna (R10)",
    "clarification_material_and_covered": (
        "o pedido de esclarecimento oferece leituras materiais, distinguíveis pelo "
        "utilizador e cobertas por evidência admissível (CLARIFY)"
    ),
    "outdated_notice_present": (
        "quando só foi encontrada informação fora de vigor, a mensagem di-lo (F02)"
    ),
    "escalation_without_transmission": (
        "o encaminhamento indica o serviço e não afirma que o pedido foi enviado (ESCALATE)"
    ),
}


@dataclass(frozen=True)
class ReviewPackage:
    files: Mapping[str, bytes]
    items: int
    excluded: Mapping[str, int]


@dataclass(frozen=True)
class _Item:
    review_item_id: str
    outcome: CaseOutcome
    reference: MessageReference
    required: tuple[str, ...]


def _fence(text: str) -> str:
    longest = max((len(run) for run in re.findall(r"~+", text)), default=0)
    return "~" * max(3, longest + 1)


def _verbatim(text: str) -> list[str]:
    fence = _fence(text)
    return [f"{fence}text", text, fence, ""]


def _date(value: date | None) -> str:
    return "sem limite" if value is None else value.isoformat()


def _code(value: str | None) -> str:
    return "—" if value is None else f"`{value}`"


def _guide() -> list[str]:
    lines = [
        "## Como avaliar",
        "",
        "Para cada item, preencha no `ratings-draft.json` o item com o mesmo",
        "`review_item_id`:",
        "",
        "- `rater_id` — o seu identificador;",
        "- `acceptable` — `true` ou `false`: a mensagem é aceitável no seu conjunto;",
        "- cada critério — `true`, `false` ou `null`. `false` é uma avaliação",
        "  **negativa**; `null` significa **não aplicável**. Os critérios marcados como",
        "  obrigatórios exigem `true` ou `false`;",
        "- `notes` — opcional.",
        "",
        f'`"{PENDING}"` nunca é um juízo: um ficheiro com `"{PENDING}"` é recusado.',
        "Mensagens que não avaliar são retiradas do ficheiro, não deixadas por fazer.",
        "",
        "Critérios da rubrica:",
        "",
    ]
    lines += [f"- `{name}` — {CRITERION_GUIDE[name]}." for name in RUBRIC_CRITERIA]
    lines += [
        "",
        "Julgue cada mensagem com as passagens do packet que a sua condição recebeu.",
        "Um identificador como `E1` só tem sentido dentro desse packet.",
        "",
    ]
    return lines


def _packet_section(packet: EvidencePacket, receivers: list[str]) -> list[str]:
    lines = [
        f"#### Packet `{packet.family}` · `{packet.digest[:12]}`",
        "",
        f"Recebido por: {', '.join(receivers)}.",
        "",
    ]
    if not packet.passages:
        lines += ["Sem passagens admissíveis.", ""]
    for passage in packet.passages:
        lines += [
            f"##### {passage.evidence_id} — {passage.document_title}",
            "",
            f"- documento `{passage.document_id}`, versão `{passage.document_version_id}`, "
            f"segmento `{passage.chunk_id}` (índice {passage.chunk_index})",
            f"- oficial: {'sim' if passage.official_source else 'não'} · vigência: "
            f"{_date(passage.valid_from)} → {_date(passage.valid_until)}",
            "",
            *_verbatim(passage.content),
        ]
    if packet.diagnostic.excluded:
        lines += ["Diagnóstico temporal (documentos excluídos apenas por validade):", ""]
        lines += [
            f"- {item.document_title} ({_date(item.valid_from)} → {_date(item.valid_until)})"
            for item in packet.diagnostic.excluded
        ]
        lines.append("")
    return lines


def _service(packet: EvidencePacket | None, service_id: str | None) -> str:
    if service_id is None:
        return "—"
    services = [] if packet is None else packet.catalog.get("services", [])
    service = next((s for s in services if s.get("service_id") == service_id), None)
    if service is None:
        return f"`{service_id}`"
    contacts = ", ".join(str(service[key]) for key in ("email", "url") if service.get(key))
    return f"`{service_id}` — {service.get('name')}" + (f" ({contacts})" if contacts else "")


def _material(
    archived: ArchivedCollection,
    report_sha256: str,
    items: list[_Item],
    excluded: Mapping[str, int],
) -> str:
    report = archived.report
    lines = [
        "# Revisão humana das mensagens — M7",
        "",
        "> **Material do ambiente autorizado.** Contém os pedidos, o texto das",
        "> mensagens produzidas e excertos dos documentos consultados. Não o copie",
        "> para logs, issues, conversas externas ou repositórios.",
        "",
        f"- Recolha: {_code(report.collection_id)}"
        + ("" if report.collection_id else " (relatório sem identidade de recolha)"),
        f"- SHA-256 do relatório: `{report_sha256}`",
        f"- Conjunto: `{report.set_id}` · modo da recolha: `{report.mode}`",
        f"- Mensagens a avaliar: {len(items)} (execução principal, sem falhas técnicas)",
        "- Excluídas: "
        + (", ".join(f"{reason} {count}" for reason, count in sorted(excluded.items())) or "—"),
        "- A condição de cada mensagem está visível: este pacote não garante revisão cega.",
        "",
        *_guide(),
    ]
    metadata: Mapping[str, CaseMetadataEntry] = {
        entry.case_id: entry for entry in report.case_metadata
    }
    by_case: dict[str, list[_Item]] = {}
    for item in items:
        by_case.setdefault(item.outcome.case_id, []).append(item)
    for case_id, case_items in by_case.items():
        entry = metadata[case_id]
        packets = {
            digest: archived.packets[digest]
            for digest in dict.fromkeys(
                item.outcome.packet_digest for item in case_items if item.outcome.packet_digest
            )
        }
        first = next(iter(packets.values()), None)
        lines += [f"## Caso {case_id}", ""]
        if first is not None:
            lines += [
                "Pedido:",
                "",
                *_verbatim(first.query),
                f"- Data de referência: {first.reference_date.isoformat()} · papel simulado: "
                f"`{first.requester_role}` · idioma: `{first.language}`",
            ]
        lines += [
            f"- Família: {_code(entry.family)} · origem: {_code(entry.source_kind)} · "
            f"estrato: `{entry.stratum}`",
            "",
            "### Mensagens",
            "",
        ]
        seen: dict[str, str] = {}
        for item in case_items:
            outcome = item.outcome
            packet = archived.packets.get(outcome.packet_digest or "")
            assert outcome.message is not None
            lines += [
                f"#### {item.review_item_id} — {outcome.condition.value} "
                f"(execução {outcome.run_number})",
                "",
                f"- Ação: `{outcome.action}` · regra: {_code(outcome.rule)} · destino: "
                f"{_service(packet, outcome.destination_service_id)}",
                "- Critérios obrigatórios: "
                + (", ".join(f"`{name}`" for name in item.required) or "nenhum"),
                f"- Citações: {', '.join(f'`{e}`' for e in outcome.cited_evidence_ids) or '—'}",
                "- Packet: "
                + ("—" if packet is None else f"`{packet.family}` · `{packet.digest[:12]}`"),
                f"- `message_sha256`: `{item.reference.message_sha256}`",
                "",
            ]
            same = seen.get(item.reference.message_sha256)
            if same is not None:
                lines += [f"Texto idêntico ao de {same}.", ""]
            else:
                seen[item.reference.message_sha256] = item.review_item_id
                lines += ["Mensagem (texto exato):", "", *_verbatim(outcome.message)]
        lines += [f"### Evidência recebida pelas condições (execução {PRIMARY_RUN})", ""]
        for digest, packet in packets.items():
            receivers = [
                item.outcome.condition.value
                for item in case_items
                if item.outcome.packet_digest == digest
            ]
            lines += _packet_section(packet, receivers)
    return "\n".join(lines).rstrip("\n") + "\n"


def build_review_package(
    archived: ArchivedCollection,
    report_data: bytes,
    *,
    exported_at: datetime,
    export_git: tuple[str | None, bool],
) -> ReviewPackage:
    """Material, rascunho e manifesto da revisão das mensagens de uma recolha."""
    report = archived.report
    report_sha256 = sha256(report_data)
    order = {entry.case_id: index for index, entry in enumerate(report.case_metadata)}
    conditions = list(Condition)
    families = {entry.case_id: entry.family for entry in report.case_metadata}
    excluded: Counter[str] = Counter()
    rateable: list[tuple[CaseOutcome, Mapping[str, Any]]] = []
    for outcome, raw in zip(archived.outcomes, archived.raw_outcomes, strict=True):
        reason = unrateable_reason(outcome)
        if reason is None:
            rateable.append((outcome, raw))
        else:
            excluded[reason] += 1
    rateable.sort(key=lambda pair: (order[pair[0].case_id], conditions.index(pair[0].condition)))
    items = [
        _Item(
            review_item_id=f"M{index:03d}",
            outcome=outcome,
            reference=message_reference(outcome, raw),
            required=required_criteria(
                action=outcome.action, rule=outcome.rule, family=families[outcome.case_id]
            ),
        )
        for index, (outcome, raw) in enumerate(rateable, start=1)
    ]
    source = SourceReport(collection_id=report.collection_id, report_sha256=report_sha256)
    draft = MessageRatingDraft(
        schema_version=RATINGS_DRAFT_SCHEMA_VERSION,
        identity_version=MESSAGE_IDENTITY_VERSION,
        set_id=report.set_id,
        source_report=source,
        provenance=DraftProvenance(kind=PENDING, raters=[], consolidated_by=[]),
        ratings=[draft_rating(item.reference, item.review_item_id) for item in items],
    )
    material = _material(archived, report_sha256, items, excluded).encode("utf-8")
    draft_data = (
        json.dumps(draft.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")
    manifest = {
        "review_export_version": REVIEW_EXPORT_VERSION,
        "identity_version": MESSAGE_IDENTITY_VERSION,
        "source_report": {
            "collection_id": report.collection_id,
            "report_sha256": report_sha256,
            "report_schema_version": report.report_schema_version,
            "mode": report.mode,
            "set_id": report.set_id,
        },
        "exported_at": exported_at.isoformat(),
        "export_git": {"head": export_git[0], "working_tree_clean": export_git[1]},
        "items": len(items),
        "excluded": dict(sorted(excluded.items())),
        "files": {
            name: {"sha256": sha256(data), "bytes": len(data)}
            for name, data in ((MATERIAL_FILE, material), (DRAFT_FILE, draft_data))
        },
        "blind_review": False,
        "confidentiality": (
            f"{MATERIAL_FILE} contains document content and produced messages; "
            "keep it in the authorised environment"
        ),
    }
    manifest_data = (
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")
    return ReviewPackage(
        files={MATERIAL_FILE: material, DRAFT_FILE: draft_data, MANIFEST_FILE: manifest_data},
        items=len(items),
        excluded=dict(sorted(excluded.items())),
    )
