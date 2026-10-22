"""Factory FastAPI do fornecedor institucional ativo."""

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import INSTITUTIONAL_PROVIDER_DISABLED, INSTITUTIONAL_PROVIDER_MOCK, settings
from app.database.session import get_db
from app.institutional.contracts import InstitutionalDataProvider
from app.models.institution import Institution


def get_institutional_data_provider(
    db: Session = Depends(get_db),
) -> InstitutionalDataProvider | None:
    """Devolve o adaptador configurado, ou ``None`` com a integração desativada.

    ``None`` é o estado por omissão: sem API externa, sem credenciais e sem
    dados simulados. A configuração já foi validada no arranque
    (:class:`app.core.config.Settings`): o modo simulado só é aceite em
    ``development`` ou ``test``.

    Tal como em :mod:`app.answering.dependencies`, o adaptador concreto é
    importado dentro do ramo que o instancia, para que resolver um fornecedor
    não imponha o carregamento de outro.
    """
    provider = settings.institutional_data_provider
    if provider == INSTITUTIONAL_PROVIDER_DISABLED:
        return None
    if provider == INSTITUTIONAL_PROVIDER_MOCK:
        from app.institutional.providers.mock import (
            SYNTHETIC_SNAPSHOT,
            MockInstitutionalDataProvider,
        )

        # O snapshot sintético está indexado pelo código da instituição; aqui
        # é ligado aos ids das instituições existentes com esses códigos. É
        # configuração do adaptador, não dados de nenhuma conta.
        served = db.execute(
            select(Institution.id, Institution.code).where(
                Institution.code.in_(list(SYNTHETIC_SNAPSHOT))
            )
        ).all()
        return MockInstitutionalDataProvider.for_institutions(
            (institution_id, code) for institution_id, code in served
        )
    # Inalcançável com Settings validados; falhar fechado se não for.
    return None
