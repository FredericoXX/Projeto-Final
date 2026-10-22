"""Mensagens versionadas das ações que não usam o gerador substantivo.

Funções puras, locais e **sem LLM**, no padrão de
:mod:`app.core.handoff_message` e :mod:`app.answering.fallback`: texto fixo por
idioma, com o inglês como fallback documentado.

Apenas ``ANSWER`` chama o gerador substantivo. ``CLARIFY``, ``ABSTAIN`` e
``ESCALATE`` são compostos aqui a partir de campos **já validados** — leituras,
itens, destino do catálogo, títulos de documentos admissíveis e excertos
verbatim de evidência admissível. Nada aqui abre um caminho de geração livre.

O que as mensagens afirmam, e o que não afirmam
-----------------------------------------------

- ``ESCALATE`` é uma **recomendação** (E1): indica serviço, contacto, motivo e o
  resumo a apresentar; nunca afirma que o pedido foi enviado, recebido ou
  resolvido.
- "Não encontrei" descreve o que o fluxo recuperou — não afirma que a
  informação não existe nos documentos da instituição.
- O diagnóstico temporal diz que a informação encontrada não está em vigor na
  data de referência, sem apresentar o seu conteúdo como válido.
- Em conflito, as orientações divergentes são identificadas e as duas são
  citadas, sem escolher uma.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Final

from app.decision.dimensions import CompetentService, ExcludedByValidity, RuleId

MESSAGE_VERSION: Final = "decision_messages_v1"

#: Tamanho máximo de um excerto verbatim acrescentado a um encaminhamento.
MAX_EXCERPT_CHARS: Final = 400

_DEFAULT_LANGUAGE = "en"


@dataclass(frozen=True)
class CitedExcerpt:
    """Excerto verbatim de uma evidência admissível, com o seu identificador."""

    evidence_id: str
    document_title: str
    content: str


@dataclass(frozen=True)
class ConflictingSource:
    evidence_id: str
    document_title: str


_TEXT: dict[str, dict[str, str]] = {
    "pt": {
        "clarify_intro": "O seu pedido pode referir-se a coisas diferentes:",
        "clarify_question": "Qual destas opções pretende?",
        "abstain_R01": (
            "Este pedido está fora do âmbito do atendimento académico desta "
            "instituição, por isso não posso responder."
        ),
        "abstain_R03": (
            "Este pedido exige a prática de um ato administrativo, que não posso "
            "executar, e não tenho indicação de um serviço competente para o tratar."
        ),
        "abstain_R05": (
            "Este pedido exige acesso a dados pessoais, a que não tenho acesso, e "
            "não tenho indicação de um serviço competente para o tratar."
        ),
        "abstain_R08": (
            "Encontrei orientações incompatíveis sobre este pedido e não tenho "
            "indicação de um serviço competente que as esclareça."
        ),
        "abstain_R12": (
            "Não encontrei, nos documentos consultados, informação suficiente para "
            "responder com segurança."
        ),
        "escalate_intro": (
            "Recomendo que contacte diretamente o serviço indicado. Esta é uma "
            "recomendação: o pedido não foi enviado a esse serviço."
        ),
        "escalate_R02": "Motivo: o pedido exige um ato administrativo, que não posso executar.",
        "escalate_R04": "Motivo: o pedido exige acesso a dados pessoais, a que não tenho acesso.",
        "escalate_R07": "Motivo: os documentos consultados dão orientações incompatíveis.",
        "escalate_R11": (
            "Motivo: não encontrei, nos documentos consultados, informação "
            "suficiente para responder com segurança."
        ),
        "service": "Serviço",
        "email": "Email",
        "url": "Ligação",
        "summary": "Ao contactar o serviço, indique:",
        "conflict_intro": "Orientações divergentes encontradas:",
        "procedure_intro": "Informação documentada sobre o procedimento:",
        "gap_intro": "Não encontrei suporte nos documentos consultados para:",
        "temporal": (
            "Encontrei informação sobre este tema em «{title}», mas não está em "
            "vigor na data de referência ({reference_date}) e por isso não foi usada."
        ),
    },
    "en": {
        "clarify_intro": "Your request could refer to different things:",
        "clarify_question": "Which of these options do you mean?",
        "abstain_R01": (
            "This request is outside the scope of this institution's academic "
            "support, so I cannot answer it."
        ),
        "abstain_R03": (
            "This request requires an administrative action, which I cannot carry "
            "out, and I have no competent service on record to handle it."
        ),
        "abstain_R05": (
            "This request requires access to personal data, which I do not have, "
            "and I have no competent service on record to handle it."
        ),
        "abstain_R08": (
            "I found incompatible guidance about this request and I have no "
            "competent service on record to clarify it."
        ),
        "abstain_R12": (
            "I could not find, in the documents consulted, sufficient information to answer safely."
        ),
        "escalate_intro": (
            "I recommend contacting the service below directly. This is a "
            "recommendation: the request has not been sent to that service."
        ),
        "escalate_R02": "Reason: the request requires an administrative action I cannot carry out.",
        "escalate_R04": "Reason: the request requires access to personal data I do not have.",
        "escalate_R07": "Reason: the documents consulted give incompatible guidance.",
        "escalate_R11": (
            "Reason: I could not find, in the documents consulted, sufficient "
            "information to answer safely."
        ),
        "service": "Service",
        "email": "Email",
        "url": "Link",
        "summary": "When contacting the service, mention:",
        "conflict_intro": "Divergent guidance found:",
        "procedure_intro": "Documented information about the procedure:",
        "gap_intro": "I found no support in the documents consulted for:",
        "temporal": (
            "I found information on this topic in “{title}”, but it is not in force "
            "on the reference date ({reference_date}), so it was not used."
        ),
    },
}


def _resolve(language: str) -> dict[str, str]:
    normalized = language.strip().lower()
    if normalized in _TEXT:
        return _TEXT[normalized]
    primary = normalized.split("-")[0]
    return _TEXT.get(primary, _TEXT[_DEFAULT_LANGUAGE])


def excerpt(content: str) -> str:
    """Excerto verbatim, cortado numa fronteira de palavra quando é longo."""
    text = " ".join(content.split())
    if len(text) <= MAX_EXCERPT_CHARS:
        return text
    cut = text[:MAX_EXCERPT_CHARS].rsplit(" ", 1)[0]
    return f"{cut} …"


def temporal_notice(
    language: str, excluded: Sequence[ExcludedByValidity], reference_date: date
) -> str | None:
    """Nota do diagnóstico temporal; ``None`` quando nada foi excluído."""
    if not excluded:
        return None
    text = _resolve(language)
    return text["temporal"].format(
        title=excluded[0].document_title, reference_date=reference_date.isoformat()
    )


def _with_notice(lines: list[str], notice: str | None) -> str:
    if notice is not None:
        lines.extend(["", notice])
    return "\n".join(lines)


def build_clarify_message(language: str, reading_labels: Sequence[str]) -> str:
    text = _resolve(language)
    lines = [text["clarify_intro"]]
    lines.extend(f"{index}. {label}" for index, label in enumerate(reading_labels, start=1))
    lines.extend(["", text["clarify_question"]])
    return "\n".join(lines)


def build_abstain_message(
    language: str,
    rule: RuleId,
    *,
    conflicting: Sequence[ConflictingSource] = (),
    notice: str | None = None,
) -> str:
    text = _resolve(language)
    lines = [text[f"abstain_{rule.value}"]]
    if conflicting:
        lines.extend(["", text["conflict_intro"]])
        lines.extend(f"[{item.evidence_id}] {item.document_title}" for item in conflicting)
    return _with_notice(lines, notice)


def build_escalate_message(
    language: str,
    rule: RuleId,
    destination: CompetentService,
    *,
    summary_items: Sequence[str] = (),
    conflicting: Sequence[ConflictingSource] = (),
    procedure: Sequence[CitedExcerpt] = (),
    notice: str | None = None,
) -> str:
    text = _resolve(language)
    lines = [text["escalate_intro"], text[f"escalate_{rule.value}"], ""]
    lines.append(f"{text['service']}: {destination.name}")
    if destination.email is not None:
        lines.append(f"{text['email']}: {destination.email}")
    if destination.url is not None:
        lines.append(f"{text['url']}: {destination.url}")
    if summary_items:
        lines.extend(["", text["summary"]])
        lines.extend(f"- {item}" for item in summary_items)
    if conflicting:
        lines.extend(["", text["conflict_intro"]])
        lines.extend(f"[{item.evidence_id}] {item.document_title}" for item in conflicting)
    if procedure:
        lines.extend(["", text["procedure_intro"]])
        lines.extend(
            f"[{item.evidence_id}] {item.document_title}: «{excerpt(item.content)}»"
            for item in procedure
        )
    return _with_notice(lines, notice)


def build_gap_statement(language: str, unsupported_labels: Sequence[str]) -> str:
    """Declaração explícita dos itens não suportados, acrescentada em R10."""
    text = _resolve(language)
    lines = [text["gap_intro"]]
    lines.extend(f"- {label}" for label in unsupported_labels)
    return "\n".join(lines)
