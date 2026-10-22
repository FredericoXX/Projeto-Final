"""Contrato público da consulta dos próprios pedidos académicos."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

# Formato aceite para o identificador de pedido vindo do cliente. Validado
# antes de chegar ao adaptador; o adaptador continua a filtrá-lo pela
# identidade autorizada.
REQUEST_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"


class AcademicRequestRead(BaseModel):
    request_id: str
    request_type: str
    # Estado oficial tal como recebido da fonte, sem tradução nem
    # interpretação: o backend não deduz aprovação, conclusão nem prazo.
    official_status: str
    updated_at: datetime
    # Presente apenas quando a fonte o fornece.
    next_step: str | None


AccessResult = Literal["success", "no_data", "access_denied", "not_configured", "unavailable"]


class InstitutionalProvenanceRead(BaseModel):
    """De onde e quando vieram os dados — distinto da proveniência documental.

    Acompanha **todos** os resultados da consulta, incluindo os que não são
    sucesso, onde viaja em ``detail.provenance`` da resposta de erro. Nunca
    contém o identificador externo nem dados de outra conta.
    """

    origin: Literal["institutional_api"]
    # True quando o adaptador ativo é o simulado, com dados sintéticos.
    simulated: bool
    institution_id: UUID
    # Momento em que o backend começou a tratar a consulta.
    attempted_at: datetime
    # False quando o backend recusou ou não pôde consultar antes de chegar à
    # fonte (integração desativada, conta sem associação ou sem permissão).
    source_consulted: bool
    # Momento da consulta à fonte; null quando a fonte não foi consultada.
    queried_at: datetime | None
    source_updated_at: datetime | None
    access_result: AccessResult
    # Campos dos registos efetivamente usados; vazio quando nenhum foi.
    fields_used: list[str]


class AcademicRequestListResponse(BaseModel):
    outcome: Literal["success", "no_data"]
    items: list[AcademicRequestRead]
    provenance: InstitutionalProvenanceRead


class AcademicRequestDetailResponse(BaseModel):
    outcome: Literal["success"]
    item: AcademicRequestRead
    provenance: InstitutionalProvenanceRead


class AcademicRequestAccessRead(BaseModel):
    """Se a conta pode usar a consulta — sem contactar o fornecedor.

    ``reason`` explica um ``available`` falso: ``not_permitted`` (o papel não
    tem a permissão), ``not_configured`` (integração desativada) ou
    ``not_linked`` (sem associação de identidade externa autorizada).
    """

    available: bool
    reason: Literal["available", "not_permitted", "not_configured", "not_linked"]
    simulated: bool
