"""Contrato neutro de fornecedor para dados institucionais individuais.

Separado, por desenho, da recuperação documental (:mod:`app.retrieval`) e da
geração de linguagem (:mod:`app.answering`): este módulo não importa nenhum
deles, e nenhum deles o importa. A evidência documental e a evidência obtida
de um serviço institucional são origens distintas (:class:`EvidenceOrigin`).

Fronteira de confiança
----------------------

- O adaptador recebe uma :class:`AuthorizedInstitutionalIdentity` construída
  **pelo backend**, a partir da sessão validada e de uma associação persistida
  estabelecida administrativamente. Não recebe texto livre, nem email, nem um
  identificador escolhido pelo utilizador: não tem forma de escolher
  arbitrariamente um aluno.
- A consulta é estruturada (:class:`AcademicRequestQuery`). O único parâmetro
  vindo do cliente é o identificador de um pedido, validado antes de chegar
  aqui, e o adaptador filtra-o sempre pela identidade recebida.
- Cada adaptador declara as instituições que serve (``serves``) e trata os
  dados como delimitados pelo par instituição/identificador externo: o mesmo
  identificador em duas instituições designa duas pessoas distintas. Uma
  identidade de uma instituição que não serve é recusada, nunca resolvida
  contra os dados de outra;
- O que o adaptador devolve é **dado não confiável**: não muda permissões nem
  o comportamento do backend, e nunca é concatenado com instruções a um modelo.

O que este contrato ainda não cobre
-----------------------------------

O contexto académico (curso, ano, situação) será um tipo de consulta futuro do
mesmo contrato. Não é definido aqui porque o protocolo institucional não foi
fornecido, e inventar-lhe campos seria fixar em código um contrato que ninguém
especificou.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID


class EvidenceOrigin(StrEnum):
    """De onde vem a evidência usada numa resposta ou consulta.

    ``DOCUMENT`` — documentos institucionais processados (o que as citações
    persistidas em ``message_sources`` representam). ``INSTITUTIONAL_API`` —
    um serviço institucional autorizado, consultado em nome da conta.
    """

    DOCUMENT = "document"
    INSTITUTIONAL_API = "institutional_api"


class InstitutionalAccessOutcome(StrEnum):
    """Resultado de uma consulta ao fornecedor institucional.

    Cinco resultados distintos, e nenhum é uma decisão do assistente:

    - ``SUCCESS`` — a fonte devolveu dados para a identidade autorizada;
    - ``NO_DATA`` — a fonte respondeu, e não há pedidos (ou o pedido
      indicado não existe para esta identidade — os dois casos são
      indistinguíveis de propósito, para não revelar pedidos de outro aluno);
    - ``ACCESS_DENIED`` — a conta não tem associação autorizada, ou a fonte
      recusou o acesso;
    - ``NOT_CONFIGURED`` — a integração não está ativa nesta instalação;
    - ``UNAVAILABLE`` — falha técnica da fonte.

    Uma falha técnica **não** é abstenção nem encaminhamento
    (:class:`app.decision.contracts.DecisionOutcome`): o sistema não escolheu
    falhar. A ligação destes resultados a uma ação pertence à política de
    decisão, que ainda não está integrada.
    """

    SUCCESS = "success"
    NO_DATA = "no_data"
    ACCESS_DENIED = "access_denied"
    NOT_CONFIGURED = "not_configured"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class AuthorizedInstitutionalIdentity:
    """Identidade já validada pelo backend; o único sujeito que o adaptador vê."""

    institution_id: UUID
    external_subject: str


class AcademicRequestQueryKind(StrEnum):
    LIST = "list"
    DETAIL = "detail"


@dataclass(frozen=True)
class AcademicRequestQuery:
    """Consulta estruturada sobre os pedidos académicos da própria identidade."""

    kind: AcademicRequestQueryKind
    request_id: str | None = None

    def __post_init__(self) -> None:
        if self.kind is AcademicRequestQueryKind.DETAIL and not self.request_id:
            msg = "A detail query requires a request_id."
            raise ValueError(msg)
        if self.kind is AcademicRequestQueryKind.LIST and self.request_id is not None:
            msg = "A list query must not carry a request_id."
            raise ValueError(msg)


@dataclass(frozen=True)
class AcademicRequestRecord:
    """Um pedido existente no sistema académico — não um caso do assistente.

    ``official_status`` é o estado **tal como recebido** da fonte. O backend
    não o interpreta: não deduz aprovação, conclusão nem prazo a partir dele.
    ``next_step`` só existe quando a fonte o fornece.
    """

    request_id: str
    request_type: str
    official_status: str
    updated_at: datetime
    next_step: str | None = None


@dataclass(frozen=True)
class AcademicRequestsResult:
    """O que o adaptador devolve: resultado, registos e atualização da fonte."""

    outcome: InstitutionalAccessOutcome
    records: tuple[AcademicRequestRecord, ...] = field(default=())
    source_updated_at: datetime | None = None

    def __post_init__(self) -> None:
        # Só um sucesso transporta registos, e um sucesso transporta sempre
        # pelo menos um — "sucesso sem dados" é NO_DATA, não SUCCESS.
        if self.outcome is InstitutionalAccessOutcome.SUCCESS and not self.records:
            msg = "A successful result must carry at least one record."
            raise ValueError(msg)
        if self.outcome is not InstitutionalAccessOutcome.SUCCESS and self.records:
            msg = "Only a successful result may carry records."
            raise ValueError(msg)


class InstitutionalDataProvider(Protocol):
    """Adaptador substituível para um sistema académico institucional."""

    @property
    def simulated(self) -> bool:
        """``True`` quando os dados são sintéticos de demonstração."""
        ...

    def serves(self, institution_id: UUID) -> bool:
        """Se o adaptador está configurado para a instituição indicada.

        Uma instituição não servida é, para ela, integração não configurada:
        o backend não chega a consultar a fonte.
        """
        ...

    def query_academic_requests(
        self,
        identity: AuthorizedInstitutionalIdentity,
        query: AcademicRequestQuery,
    ) -> AcademicRequestsResult:
        """Consulta os pedidos da identidade recebida, e apenas dessa.

        Os dados são selecionados pelo par ``(institution_id,
        external_subject)``; uma identidade de instituição não servida
        responde ``ACCESS_DENIED``.
        """
        ...
