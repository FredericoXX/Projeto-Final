"""Identidade das mensagens avaliadas e juízos humanos M7 vinculados a elas.

O esquema v1 das avaliações (``policy_v1_message_ratings_1``,
:class:`~app.evaluation.policy_v1.labels.MessageRatingSet`) identifica um juízo
apenas por ``case_id`` e condição. Não diz **que texto** foi julgado: aplicado a
outra recolha, o mesmo juízo passaria a valer para outra mensagem. Fica como
formato legado de fixtures técnicas; a reanálise offline não o aceita.

O esquema v2 (``policy_v1_message_ratings_2``, :class:`BoundMessageRatingSet`)
liga cada juízo à resposta concreta que foi apresentada ao avaliador:

- a recolha — ``source_report``: ``collection_id`` e SHA-256 dos bytes exatos do
  relatório arquivado;
- ``case_id``, condição e número da execução — só a primeira, a principal, sobre
  a qual M7 é calculada;
- ``message_sha256`` — o hash do texto exato da mensagem;
- ``packet_digest`` — o packet que a condição recebeu;
- ``outcome_id`` — o hash canónico do resultado arquivado.

Representação canónica
----------------------

- :func:`message_sha256` — SHA-256 dos bytes UTF-8 da mensagem tal como está no
  relatório depois de descodificado o JSON, **sem** normalização Unicode, sem
  remover espaços e sem alterar quebras de linha.
- :func:`outcome_id` — SHA-256 de
  :func:`~app.evaluation.policy_v1.freeze.canonical_bytes` aplicado ao objeto do
  resultado exatamente como foi arquivado.

A exportação para revisão e a validação na reanálise usam estas mesmas funções.

Rascunho e avaliação concluída
------------------------------

A exportação escreve um **rascunho** (``policy_v1_message_ratings_draft_1``) em
que ``acceptable`` e cada critério valem ``"pending"``: não é um booleano nem
``null`` (não aplicável), e nenhum esquema de avaliação concluída o aceita. Os
booleanos da avaliação concluída são estritos — ``"true"`` em texto é recusado.

Um juízo por mensagem
---------------------

M7 usa **uma** avaliação consolidada por mensagem. Com vários avaliadores, cada
um preenche o seu rascunho; as divergências são resolvidas por pessoas
identificadas, que escrevem o ficheiro consolidado
(``provenance.kind = "human_consolidation"``). Nenhuma média, votação ou
adjudicação automática é feita aqui. Nenhum modelo produz estes juízos.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Annotated, Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator

from app.evaluation.policy_v1.annotation_contracts import MessageRubric
from app.evaluation.policy_v1.conditions import CaseOutcome, Condition
from app.evaluation.policy_v1.freeze import canonical_bytes, sha256
from app.evaluation.policy_v1.labels import MessageRating, MessageRatingSet
from app.evaluation.policy_v1.runs import PRIMARY_RUN

MESSAGE_IDENTITY_VERSION: Final = "policy_v1_message_identity_1"
BOUND_RATINGS_SCHEMA_VERSION: Final = "policy_v1_message_ratings_2"
RATINGS_DRAFT_SCHEMA_VERSION: Final = "policy_v1_message_ratings_draft_1"
LEGACY_RATINGS_SCHEMA_VERSION: Final = "policy_v1_message_ratings_1"
PENDING: Final = "pending"

#: Critérios da rubrica M7 (secção 9.1 da v1.7), pela ordem do contrato.
RUBRIC_CRITERIA: Final = tuple(MessageRubric.model_fields)

Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Identifier = Annotated[str, Field(min_length=1, max_length=64)]
Pending = Literal["pending"]


def message_sha256(text: str) -> str:
    """Hash do texto exato de uma mensagem: bytes UTF-8, sem normalização."""
    return sha256(text.encode("utf-8"))


def outcome_id(archived: Mapping[str, Any]) -> str:
    """Hash canónico de um resultado, tal como está arquivado no relatório."""
    return sha256(canonical_bytes(dict(archived)))


def required_criteria(
    *, action: str | None, rule: str | None, family: str | None
) -> tuple[str, ...]:
    """Critérios que exigem um juízo (verdadeiro ou falso) para esta mensagem.

    São as regras que a validação formal já aplicava às avaliações v1: ANSWER
    exige o juízo de suporte e completude; R10, o da lacuna declarada; CLARIFY,
    o da materialidade e cobertura; ESCALATE, o de não afirmar transmissão; e um
    caso F02, o do aviso temporal. Nos restantes critérios, ``null`` (não
    aplicável) é admitido — e continua distinto de uma avaliação negativa.
    """
    required = set()
    if action == "answer":
        required.add("supported_and_complete")
    if rule == "R10":
        required.add("gap_declared")
    if action == "clarify":
        required.add("clarification_material_and_covered")
    if family == "F02":
        required.add("outdated_notice_present")
    if action == "escalate":
        required.add("escalation_without_transmission")
    return tuple(criterion for criterion in RUBRIC_CRITERIA if criterion in required)


def unrateable_reason(outcome: CaseOutcome) -> str | None:
    """Porque é que um resultado não tem mensagem avaliável, ou ``None``.

    Uma falha técnica não produziu mensagem e nunca é avaliada como se a tivesse
    produzido; P-oráculo não compõe mensagens; M7 só avalia a execução principal.
    """
    if outcome.condition is Condition.P_ORACLE:
        return "condition_without_message"
    if outcome.failure is not None:
        return "technical_failure"
    if outcome.run_number != PRIMARY_RUN:
        return "not_primary_run"
    if not outcome.message:
        return "no_message"
    return None


@dataclass(frozen=True)
class MessageReference:
    """A identidade completa de uma mensagem avaliável de uma recolha."""

    case_id: str
    condition: Condition
    run_number: int
    message_sha256: str
    packet_digest: str | None
    outcome_id: str

    @property
    def key(self) -> tuple[str, str, int]:
        return (self.case_id, self.condition.value, self.run_number)


def message_reference(outcome: CaseOutcome, archived: Mapping[str, Any]) -> MessageReference:
    """Referência de uma mensagem avaliável. Recusa resultados sem mensagem."""
    reason = unrateable_reason(outcome)
    if reason is not None or outcome.message is None:
        msg = f"case {outcome.case_id} ({outcome.condition.value}) has no rateable message"
        raise ValueError(msg)
    return MessageReference(
        case_id=outcome.case_id,
        condition=outcome.condition,
        run_number=outcome.run_number,
        message_sha256=message_sha256(outcome.message),
        packet_digest=outcome.packet_digest,
        outcome_id=outcome_id(archived),
    )


# ---------------------------------------------------------------------------
# Contratos
# ---------------------------------------------------------------------------


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class SourceReport(_Strict):
    """A recolha a que os juízos pertencem."""

    #: ``None`` só para relatórios anteriores a ``policy_v1_report_2``, que não
    #: registavam identidade da recolha; o SHA-256 dos bytes é então a única.
    collection_id: Identifier | None
    report_sha256: Sha256


class RatingProvenance(_Strict):
    """Quem julgou.

    - ``one_rater_per_message`` — cada mensagem tem o juízo de um só avaliador
      (``raters``), e ``rater_id`` identifica-o;
    - ``human_consolidation`` — vários avaliadores (``raters``) julgaram em
      separado e pessoas identificadas (``consolidated_by``) escreveram o juízo
      consolidado; ``rater_id`` identifica quem o consolidou.
    """

    kind: Literal["one_rater_per_message", "human_consolidation"]
    raters: Annotated[list[Identifier], Field(min_length=1)]
    consolidated_by: list[Identifier] = []

    @model_validator(mode="after")
    def coherent(self) -> "RatingProvenance":
        if len(set(self.raters)) != len(self.raters):
            raise ValueError("raters must be unique")
        if (self.kind == "human_consolidation") != bool(self.consolidated_by):
            raise ValueError("consolidated_by is required exactly for a human consolidation")
        return self

    @property
    def accountable(self) -> set[str]:
        return set(self.consolidated_by if self.consolidated_by else self.raters)


class BoundMessageRubric(MessageRubric):
    """A rubrica M7 com booleanos estritos. ``None`` é não aplicável."""

    model_config = ConfigDict(extra="forbid", strict=True)


class BoundMessageRating(MessageRating):
    """Juízo humano sobre uma mensagem identificada da execução principal."""

    model_config = ConfigDict(extra="forbid", strict=True)

    acceptable: StrictBool
    criteria: BoundMessageRubric
    run_number: Annotated[int, Field(ge=1)]
    message_sha256: Sha256
    packet_digest: Sha256 | None
    outcome_id: Sha256
    #: Remissão para o item do material de revisão; não entra na identidade.
    review_item_id: Annotated[str, Field(min_length=1, max_length=32)] | None = None


class BoundMessageRatingSet(_Strict):
    schema_version: Literal["policy_v1_message_ratings_2"]
    identity_version: Literal["policy_v1_message_identity_1"]
    set_id: Identifier
    source_report: SourceReport
    provenance: RatingProvenance
    ratings: list[BoundMessageRating]

    @model_validator(mode="after")
    def one_rating_per_message(self) -> "BoundMessageRatingSet":
        keys = [(r.case_id, r.condition, r.run_number) for r in self.ratings]
        if len(set(keys)) != len(keys):
            raise ValueError("one rating per case, condition and run")
        accountable = self.provenance.accountable
        if any(rating.rater_id not in accountable for rating in self.ratings):
            raise ValueError("every rater_id must be accountable under the declared provenance")
        return self


#: Conjuntos de avaliações que as métricas sabem ler: o v1 só em fixtures
#: técnicas; o v2 depois de vinculado às mensagens de uma recolha.
RatingSet = MessageRatingSet | BoundMessageRatingSet


class DraftRubric(_Strict):
    supported_and_complete: StrictBool | None | Pending
    gap_declared: StrictBool | None | Pending
    clarification_material_and_covered: StrictBool | None | Pending
    outdated_notice_present: StrictBool | None | Pending
    escalation_without_transmission: StrictBool | None | Pending


class DraftRating(_Strict):
    """Item do rascunho: a identidade completa da mensagem e juízos por fazer."""

    review_item_id: Annotated[str, Field(min_length=1, max_length=32)]
    case_id: Identifier
    condition: Annotated[str, Field(min_length=1, max_length=32)]
    run_number: Annotated[int, Field(ge=1)]
    message_sha256: Sha256
    packet_digest: Sha256 | None
    outcome_id: Sha256
    rater_id: Identifier | None
    acceptable: StrictBool | Pending
    criteria: DraftRubric
    notes: Annotated[str, Field(max_length=2000)] | None = None


class DraftProvenance(_Strict):
    kind: Literal["one_rater_per_message", "human_consolidation"] | Pending
    raters: list[Identifier]
    consolidated_by: list[Identifier] = []


class MessageRatingDraft(_Strict):
    """Rascunho exportado para revisão. Nunca é uma avaliação concluída."""

    schema_version: Literal["policy_v1_message_ratings_draft_1"]
    identity_version: Literal["policy_v1_message_identity_1"]
    set_id: Identifier
    source_report: SourceReport
    provenance: DraftProvenance
    ratings: list[DraftRating]


def draft_rating(reference: MessageReference, review_item_id: str) -> DraftRating:
    """Item de rascunho com todos os juízos por fazer — nenhum booleano por omissão."""
    return DraftRating(
        review_item_id=review_item_id,
        case_id=reference.case_id,
        condition=reference.condition.value,
        run_number=reference.run_number,
        message_sha256=reference.message_sha256,
        packet_digest=reference.packet_digest,
        outcome_id=reference.outcome_id,
        rater_id=None,
        acceptable=PENDING,
        criteria=DraftRubric.model_validate(dict.fromkeys(RUBRIC_CRITERIA, PENDING)),
        notes=None,
    )


# ---------------------------------------------------------------------------
# Vinculação à recolha
# ---------------------------------------------------------------------------


class RatingBindingError(ValueError):
    """Uma avaliação não corresponde a uma mensagem avaliável desta recolha."""


def bind_ratings(
    ratings: BoundMessageRatingSet,
    *,
    source: SourceReport,
    set_id: str,
    outcomes: Mapping[tuple[str, str, int], tuple[CaseOutcome, Mapping[str, Any]]],
    families: Mapping[str, str | None],
) -> None:
    """Confirma que cada juízo aponta para a mensagem exata desta recolha.

    ``outcomes`` são **todos** os resultados arquivados, por
    ``(case_id, condição, execução)``, com o objeto arquivado de cada um.
    Recusa — nunca ignora — referências desconhecidas, mensagens alteradas,
    outra recolha, outra condição ou outra execução, falhas técnicas e
    critérios obrigatórios sem juízo.
    """
    if ratings.source_report.report_sha256 != source.report_sha256:
        raise RatingBindingError("the ratings refer to another report")
    if ratings.source_report.collection_id != source.collection_id:
        raise RatingBindingError("the ratings refer to another collection")
    if ratings.set_id != set_id:
        raise RatingBindingError("the ratings belong to another case set")
    for rating in ratings.ratings:
        where = f"case {rating.case_id} ({rating.condition}, run {rating.run_number})"
        found = outcomes.get((rating.case_id, rating.condition, rating.run_number))
        if found is None:
            raise RatingBindingError(f"{where}: unknown message reference")
        outcome, archived = found
        reason = unrateable_reason(outcome)
        if reason is not None:
            raise RatingBindingError(f"{where}: not a rateable message ({reason})")
        reference = message_reference(outcome, archived)
        if rating.message_sha256 != reference.message_sha256:
            raise RatingBindingError(f"{where}: the rated text differs from the archived message")
        if rating.packet_digest != reference.packet_digest:
            raise RatingBindingError(f"{where}: the rated packet differs from the archived one")
        if rating.outcome_id != reference.outcome_id:
            raise RatingBindingError(f"{where}: the rated outcome differs from the archived one")
        for criterion in required_criteria(
            action=outcome.action, rule=outcome.rule, family=families.get(rating.case_id)
        ):
            if getattr(rating.criteria, criterion) is None:
                raise RatingBindingError(f"{where}: {criterion} requires a human judgment")
