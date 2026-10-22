"""Resolução pura do destino competente (D6) a partir de um catálogo.

Partilhada pelo fluxo operacional (catálogo lido da base de dados) e pela
avaliação (catálogo arquivado no packet), para que ambos resolvam D6 da mesma
forma. Determinística: o catálogo garante, na publicação, no máximo um serviço
por tema.
"""

from collections.abc import Mapping, Sequence
from typing import Any

from app.decision.dimensions import CompetentService, DestinationResolution, EstimateOrigin


def resolve_competent_service(
    services: Sequence[Mapping[str, Any]], *, catalog_version: int, topic: str | None
) -> DestinationResolution:
    """O serviço com competência declarada para o tema, ou nenhum.

    Um tema desconhecido, ou ``None``, não tem serviço — e nunca se recorre ao
    destino genérico da instituição para preencher a lacuna.
    """
    service: CompetentService | None = None
    if topic is not None:
        for entry in services:
            if topic in entry.get("topics", ()):
                service = CompetentService(
                    service_id=entry["service_id"],
                    name=entry["name"],
                    email=entry.get("email"),
                    url=entry.get("url"),
                )
                break
    return DestinationResolution(
        service=service,
        topic=topic,
        catalog_version=catalog_version,
        origin=EstimateOrigin.BACKEND,
    )
