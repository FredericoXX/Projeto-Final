"""Integração preparatória com serviços institucionais individuais.

Reexporta apenas o contrato neutro. A resolução do adaptador ativo vive em
:mod:`app.institutional.dependencies`, que importa o adaptador concreto só
quando ele é efetivamente selecionado.
"""

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

__all__ = [
    "AcademicRequestQuery",
    "AcademicRequestQueryKind",
    "AcademicRequestRecord",
    "AcademicRequestsResult",
    "AuthorizedInstitutionalIdentity",
    "EvidenceOrigin",
    "InstitutionalAccessOutcome",
    "InstitutionalDataProvider",
]
