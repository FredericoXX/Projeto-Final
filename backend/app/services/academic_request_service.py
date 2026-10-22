"""Consulta dos próprios pedidos académicos através do fornecedor institucional.

Determinística e iniciada pelo utilizador: não usa o Retriever, o
AnswerGenerator nem nenhum modelo de linguagem, não classifica perguntas e não
está ligada ao chat. Os dados obtidos não são persistidos, não entram na base
vetorial nem no corpus documental, e nunca são escritos em logs.

A identidade enviada ao adaptador é construída aqui, a partir da sessão
validada e da associação persistida — nunca de um valor do pedido.

Revalidação em três tempos
--------------------------

1. **Antes da fonte**: conta, instituição, permissão e associação são relidas
   sob lock (:func:`app.services.authorization_service.revalidate_actor`).
2. **Durante a fonte**: a transação é terminada antes de chamar o adaptador,
   para que nenhum lock fique retido durante uma futura chamada de rede.
3. **Depois da fonte**: tudo é relido de novo sob lock antes de entregar o
   resultado. Uma desativação, uma alteração de papel ou uma associação
   removida ou substituída durante a consulta descartam os registos obtidos.

Proveniência
------------

Todos os resultados — incluindo os que não são sucesso — transportam
proveniência mínima (:class:`InstitutionalProvenanceRead`). Quando a fonte não
chegou a ser consultada, ``source_consulted`` é falso, ``queried_at`` e
``source_updated_at`` são nulos e ``fields_used`` é vazio. Uma desativação da
conta continua a responder como falha de autenticação (401), sem proveniência:
deixou de haver uma conta autorizada a quem a entregar.
"""

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.exceptions import InstitutionalAccessError
from app.core.permissions import Permission, has_permission
from app.institutional.contracts import (
    AcademicRequestQuery,
    AcademicRequestQueryKind,
    AcademicRequestRecord,
    AcademicRequestsResult,
    AuthorizedInstitutionalIdentity,
    EvidenceOrigin,
    InstitutionalAccessOutcome,
    InstitutionalDataProvider,
)
from app.models.user import User
from app.schemas.academic_request import (
    AcademicRequestAccessRead,
    AcademicRequestDetailResponse,
    AcademicRequestListResponse,
    AcademicRequestRead,
    InstitutionalProvenanceRead,
)
from app.services import authorization_service
from app.services.external_identity_service import find_link_for_account

logger = logging.getLogger(__name__)

ACCESS_DENIED_MESSAGE = (
    "Access to institutional academic records is not authorized for this account."
)
NOT_CONFIGURED_MESSAGE = "The institutional integration is not configured."
UNAVAILABLE_MESSAGE = "The institutional service is temporarily unavailable."
REQUEST_NOT_FOUND_MESSAGE = "Academic request not found."

_MESSAGES = {
    InstitutionalAccessOutcome.ACCESS_DENIED: ACCESS_DENIED_MESSAGE,
    InstitutionalAccessOutcome.NOT_CONFIGURED: NOT_CONFIGURED_MESSAGE,
    InstitutionalAccessOutcome.UNAVAILABLE: UNAVAILABLE_MESSAGE,
    InstitutionalAccessOutcome.NO_DATA: REQUEST_NOT_FOUND_MESSAGE,
}

# Campos mínimos que a consulta usa de cada registo. next_step só é
# declarado quando algum registo o traz de facto.
BASE_FIELDS_USED = ("request_id", "request_type", "official_status", "updated_at")


@dataclass
class _Attempt:
    """Estado de uma consulta, a partir do qual a proveniência é construída."""

    institution_id: UUID
    attempted_at: datetime
    simulated: bool = False
    queried_at: datetime | None = None
    source_updated_at: datetime | None = None
    records: tuple[AcademicRequestRecord, ...] = field(default=())

    def provenance(self, outcome: InstitutionalAccessOutcome) -> InstitutionalProvenanceRead:
        fields_used: list[str] = []
        if self.records:
            fields_used = list(BASE_FIELDS_USED)
            if any(record.next_step is not None for record in self.records):
                fields_used.append("next_step")
        return InstitutionalProvenanceRead(
            origin=EvidenceOrigin.INSTITUTIONAL_API.value,
            simulated=self.simulated,
            institution_id=self.institution_id,
            attempted_at=self.attempted_at,
            source_consulted=self.queried_at is not None,
            queried_at=self.queried_at,
            source_updated_at=self.source_updated_at if self.queried_at else None,
            access_result=outcome.value,
            fields_used=fields_used,
        )

    def fail(self, outcome: InstitutionalAccessOutcome) -> InstitutionalAccessError:
        # Nenhum registo sobrevive a uma falha: a proveniência de erro nunca
        # declara campos usados.
        self.records = ()
        return InstitutionalAccessError(
            outcome.value,
            _MESSAGES[outcome],
            provenance=self.provenance(outcome).model_dump(mode="json"),
        )


def get_access(
    db: Session,
    current_user: User,
    provider: InstitutionalDataProvider | None,
) -> AcademicRequestAccessRead:
    """Diz se a consulta está disponível para a conta, sem contactar a fonte.

    Decide sobre o estado persistido, relido sob lock — conta, instituição e
    associação, por esta ordem —, nunca sobre o objeto da autenticação: uma
    revogação concorrente já gravada é vista, e uma posterior espera pela
    resposta.
    """
    user_id = current_user.id
    institution_id = current_user.institution_id
    actor = authorization_service.revalidate_actor(
        db, user_id=user_id, institution_id=institution_id
    )
    simulated = provider is not None and provider.simulated
    if not has_permission(actor.role, Permission.ACADEMIC_REQUESTS_READ_OWN):
        return AcademicRequestAccessRead(
            available=False, reason="not_permitted", simulated=simulated
        )
    if provider is None or not provider.serves(institution_id):
        return AcademicRequestAccessRead(available=False, reason="not_configured", simulated=False)
    link = find_link_for_account(db, institution_id=institution_id, user_id=user_id, lock=True)
    if link is None:
        return AcademicRequestAccessRead(available=False, reason="not_linked", simulated=simulated)
    return AcademicRequestAccessRead(available=True, reason="available", simulated=simulated)


def _authorized_identity(
    db: Session,
    attempt: _Attempt,
    *,
    user_id: UUID,
    institution_id: UUID,
) -> AuthorizedInstitutionalIdentity:
    """Relê conta, permissão e associação sob lock e devolve a identidade.

    Usado antes e depois da chamada à fonte. Uma conta ou instituição inativa
    responde 401 (``AuthenticationError``); um papel sem a permissão ou uma
    associação ausente responde ``access_denied``.
    """
    actor = authorization_service.revalidate_actor(
        db, user_id=user_id, institution_id=institution_id
    )
    if not has_permission(actor.role, Permission.ACADEMIC_REQUESTS_READ_OWN):
        raise attempt.fail(InstitutionalAccessOutcome.ACCESS_DENIED)
    # Instituição e conta vêm exclusivamente da sessão validada. A associação
    # fica bloqueada, depois da instituição e da conta, até ao fim da transação.
    link = find_link_for_account(db, institution_id=institution_id, user_id=user_id, lock=True)
    if link is None:
        raise attempt.fail(InstitutionalAccessOutcome.ACCESS_DENIED)
    return AuthorizedInstitutionalIdentity(
        institution_id=link.institution_id,
        external_subject=link.external_subject,
    )


def _query(
    db: Session,
    current_user: User,
    query: AcademicRequestQuery,
    provider: InstitutionalDataProvider | None,
) -> tuple[AcademicRequestsResult, _Attempt]:
    # Só escalares: a transação é terminada antes da chamada à fonte, e o
    # objeto da autenticação deixa de ser fiável a partir daí.
    user_id = current_user.id
    institution_id = current_user.institution_id
    attempt = _Attempt(institution_id=institution_id, attempted_at=datetime.now(UTC))

    if provider is None or not provider.serves(institution_id):
        # A permissão é verificada primeiro, para que uma conta sem ela nunca
        # receba informação sobre a configuração da integração.
        actor = authorization_service.revalidate_actor(
            db, user_id=user_id, institution_id=institution_id
        )
        if not has_permission(actor.role, Permission.ACADEMIC_REQUESTS_READ_OWN):
            raise attempt.fail(InstitutionalAccessOutcome.ACCESS_DENIED)
        raise attempt.fail(InstitutionalAccessOutcome.NOT_CONFIGURED)
    attempt.simulated = provider.simulated

    # 1. Antes da fonte, sob lock.
    identity = _authorized_identity(db, attempt, user_id=user_id, institution_id=institution_id)

    # 2. Nenhum lock atravessa a chamada à fonte.
    db.rollback()
    attempt.queried_at = datetime.now(UTC)
    try:
        result = provider.query_academic_requests(identity, query)
    except Exception as exc:
        # Só o tipo da exceção: nunca identificadores, dados académicos nem a
        # mensagem do fornecedor, que pode transportar qualquer um deles.
        logger.warning("Institutional provider failed (%s).", type(exc).__name__)
        # A falha técnica só é comunicada a uma conta que continua autorizada.
        _authorized_identity(db, attempt, user_id=user_id, institution_id=institution_id)
        raise attempt.fail(InstitutionalAccessOutcome.UNAVAILABLE) from None

    # 3. Depois da fonte, sob lock, antes de entregar o que quer que seja: a
    # associação tem de continuar a ser exatamente a que foi consultada.
    current_identity = _authorized_identity(
        db, attempt, user_id=user_id, institution_id=institution_id
    )
    if current_identity != identity:
        raise attempt.fail(InstitutionalAccessOutcome.ACCESS_DENIED)

    if query.kind is AcademicRequestQueryKind.DETAIL and any(
        record.request_id != query.request_id for record in result.records
    ):
        # Um adaptador que devolve outro pedido em vez do pedido indicado
        # produziu output inconsistente; não é apresentado.
        logger.warning("Institutional provider returned an inconsistent detail result.")
        raise attempt.fail(InstitutionalAccessOutcome.UNAVAILABLE)

    attempt.source_updated_at = result.source_updated_at
    if result.outcome in (
        InstitutionalAccessOutcome.ACCESS_DENIED,
        InstitutionalAccessOutcome.NOT_CONFIGURED,
        InstitutionalAccessOutcome.UNAVAILABLE,
    ):
        raise attempt.fail(result.outcome)
    attempt.records = result.records
    return result, attempt


def _access_result(result: AcademicRequestsResult) -> Literal["success", "no_data"]:
    return "success" if result.outcome is InstitutionalAccessOutcome.SUCCESS else "no_data"


def _read(record: AcademicRequestRecord) -> AcademicRequestRead:
    return AcademicRequestRead(
        request_id=record.request_id,
        request_type=record.request_type,
        official_status=record.official_status,
        updated_at=record.updated_at,
        next_step=record.next_step,
    )


def list_own_requests(
    db: Session,
    current_user: User,
    provider: InstitutionalDataProvider | None,
) -> AcademicRequestListResponse:
    query = AcademicRequestQuery(kind=AcademicRequestQueryKind.LIST)
    result, attempt = _query(db, current_user, query, provider)
    return AcademicRequestListResponse(
        outcome=_access_result(result),
        items=[_read(record) for record in result.records],
        provenance=attempt.provenance(result.outcome),
    )


def get_own_request(
    db: Session,
    current_user: User,
    request_id: str,
    provider: InstitutionalDataProvider | None,
) -> AcademicRequestDetailResponse:
    query = AcademicRequestQuery(kind=AcademicRequestQueryKind.DETAIL, request_id=request_id)
    result, attempt = _query(db, current_user, query, provider)
    if result.outcome is InstitutionalAccessOutcome.NO_DATA:
        # Um pedido de outro aluno e um pedido inexistente respondem da mesma
        # forma — incluindo a proveniência: a existência de recursos alheios
        # não é revelada.
        raise attempt.fail(InstitutionalAccessOutcome.NO_DATA)
    return AcademicRequestDetailResponse(
        outcome="success",
        item=_read(result.records[0]),
        provenance=attempt.provenance(result.outcome),
    )
