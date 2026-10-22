"""Adaptador simulado de pedidos académicos — apenas desenvolvimento e testes.

Dados **sintéticos e fixos**, versionados aqui para que demonstração e ensaios
sejam reprodutíveis. Nenhum identificador, pedido ou estado corresponde a uma
pessoa ou instituição real. O adaptador não faz chamadas de rede, não lê
ficheiros e não usa nenhum modelo de linguagem.

Âmbito institucional
--------------------

O snapshot está delimitado por instituição e, dentro dela, por identificador
externo: ``SYNTHETIC_SNAPSHOT[código da instituição][external_subject]``. O
mesmo ``SYNTH-STUDENT-0001`` em ``DEMO-HEI`` e em ``DEMO-HEI-B`` designa dois
alunos distintos, com pedidos distintos. Cada instância do adaptador é ligada
às instituições que serve — resolvidas pelo código, na base de dados, quando a
integração é selecionada — e recusa identidades de qualquer outra instituição.
Instituições cujo código não está no snapshot não são servidas: para elas, a
integração não está configurada.

Os identificadores externos sintéticos têm o prefixo ``SYNTH-``. Dois deles
existem apenas para exercitar resultados que não são sucesso:
``SYNTH-ACCESS-DENIED`` (a fonte recusa o acesso) e ``SYNTH-UNAVAILABLE``
(falha técnica da fonte). Um identificador desconhecido numa instituição
servida responde como ``NO_DATA`` — exatamente como um aluno sem pedidos.
"""

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Self
from uuid import UUID

from app.institutional.contracts import (
    AcademicRequestQuery,
    AcademicRequestQueryKind,
    AcademicRequestRecord,
    AcademicRequestsResult,
    AuthorizedInstitutionalIdentity,
    InstitutionalAccessOutcome,
)

MOCK_PROVIDER_NAME = "mock"

# Momento da última atualização do snapshot sintético, devolvido como
# atualização da fonte. Fixo de propósito: o resultado não depende do relógio.
SNAPSHOT_UPDATED_AT = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)

SUBJECT_ACCESS_DENIED = "SYNTH-ACCESS-DENIED"
SUBJECT_UNAVAILABLE = "SYNTH-UNAVAILABLE"

# Códigos das instituições sintéticas servidas. DEMO-HEI é a instituição criada
# por scripts/seed_demo_institution.py.
DEMO_INSTITUTION_CODE = "DEMO-HEI"
SECOND_DEMO_INSTITUTION_CODE = "DEMO-HEI-B"

InstitutionSnapshot = Mapping[str, tuple[AcademicRequestRecord, ...]]

# Os estados e tipos estão escritos como uma fonte institucional os
# devolveria, e são apresentados sem tradução nem interpretação.
SYNTHETIC_SNAPSHOT: dict[str, dict[str, tuple[AcademicRequestRecord, ...]]] = {
    DEMO_INSTITUTION_CODE: {
        "SYNTH-STUDENT-0001": (
            AcademicRequestRecord(
                request_id="REQ-0001-A",
                request_type="Certidão de matrícula",
                official_status="Emitida",
                updated_at=datetime(2026, 9, 12, 9, 30, tzinfo=UTC),
                next_step="Disponível para descarga no portal académico.",
            ),
            AcademicRequestRecord(
                request_id="REQ-0001-B",
                request_type="Creditação de unidades curriculares",
                official_status="Em apreciação",
                updated_at=datetime(2026, 9, 25, 15, 0, tzinfo=UTC),
            ),
            AcademicRequestRecord(
                request_id="REQ-0001-C",
                request_type="Revisão de prova",
                official_status="Aguarda documentação",
                updated_at=datetime(2026, 9, 28, 11, 45, tzinfo=UTC),
                next_step="Submeter o comprovativo em falta.",
            ),
        ),
        "SYNTH-STUDENT-0002": (
            AcademicRequestRecord(
                request_id="REQ-0002-A",
                request_type="Mudança de turma",
                official_status="Submetido",
                updated_at=datetime(2026, 9, 20, 8, 15, tzinfo=UTC),
            ),
        ),
        # Aluno sintético sem pedidos: exercita o estado vazio.
        "SYNTH-STUDENT-0003": (),
    },
    # Segunda instituição sintética: reutiliza o identificador SYNTH-STUDENT-0001
    # para outra pessoa, com outros pedidos. Fixa que o identificador externo
    # só tem significado dentro da sua instituição.
    SECOND_DEMO_INSTITUTION_CODE: {
        "SYNTH-STUDENT-0001": (
            AcademicRequestRecord(
                request_id="REQ-B001-A",
                request_type="Pedido de estatuto de trabalhador-estudante",
                official_status="Deferido",
                updated_at=datetime(2026, 9, 18, 10, 0, tzinfo=UTC),
            ),
        ),
    },
}


class MockInstitutionalDataProvider:
    """Implementa :class:`InstitutionalDataProvider` sobre o snapshot fixo.

    ``scope`` associa cada instituição servida (pelo seu id) ao respetivo
    snapshot. Instituições fora de ``scope`` não são servidas.
    """

    def __init__(self, scope: Mapping[UUID, InstitutionSnapshot]) -> None:
        self._scope = dict(scope)

    @classmethod
    def for_institutions(cls, institutions: Iterable[tuple[UUID, str]]) -> Self:
        """Liga o snapshot sintético às instituições ``(id, código)`` indicadas."""
        return cls(
            {
                institution_id: SYNTHETIC_SNAPSHOT[code]
                for institution_id, code in institutions
                if code in SYNTHETIC_SNAPSHOT
            }
        )

    @property
    def simulated(self) -> bool:
        return True

    def serves(self, institution_id: UUID) -> bool:
        return institution_id in self._scope

    def query_academic_requests(
        self,
        identity: AuthorizedInstitutionalIdentity,
        query: AcademicRequestQuery,
    ) -> AcademicRequestsResult:
        institution_snapshot = self._scope.get(identity.institution_id)
        if institution_snapshot is None:
            # Uma identidade de outra instituição nunca é resolvida contra os
            # dados desta: o backend não devia tê-la enviado, e a fonte recusa.
            return AcademicRequestsResult(outcome=InstitutionalAccessOutcome.ACCESS_DENIED)

        subject = identity.external_subject
        if subject == SUBJECT_ACCESS_DENIED:
            return AcademicRequestsResult(outcome=InstitutionalAccessOutcome.ACCESS_DENIED)
        if subject == SUBJECT_UNAVAILABLE:
            return AcademicRequestsResult(outcome=InstitutionalAccessOutcome.UNAVAILABLE)

        # O filtro pela identidade — instituição e identificador — é aplicado
        # antes de qualquer procura pelo identificador do pedido: um pedido de
        # outro aluno nunca é sequer candidato, e a sua inexistência é
        # indistinguível da de um pedido que não existe.
        own_records = institution_snapshot.get(subject, ())
        if query.kind is AcademicRequestQueryKind.DETAIL:
            own_records = tuple(
                record for record in own_records if record.request_id == query.request_id
            )

        if not own_records:
            return AcademicRequestsResult(
                outcome=InstitutionalAccessOutcome.NO_DATA,
                source_updated_at=SNAPSHOT_UPDATED_AT,
            )
        return AcademicRequestsResult(
            outcome=InstitutionalAccessOutcome.SUCCESS,
            records=own_records,
            source_updated_at=SNAPSHOT_UPDATED_AT,
        )
