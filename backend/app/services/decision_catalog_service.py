"""Configuração versionada da política de decisão: âmbito (D1) e catálogo (D6).

A configuração é do admin institucional (``institution.manage``), sempre da
instituição da sessão. Publicar cria a versão seguinte e desativa a anterior,
na mesma transação e sob o lock exclusivo da instituição; as versões nunca são
alteradas depois de criadas.
"""

from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.permissions import Permission
from app.decision.catalog import resolve_competent_service
from app.decision.dimensions import DestinationResolution
from app.models.decision_catalog import InstitutionDecisionCatalog
from app.models.user import User
from app.schemas.decision_catalog import DecisionCatalogWrite
from app.services import authorization_service


def get_active_catalog(db: Session, institution_id: UUID) -> InstitutionDecisionCatalog | None:
    return db.scalar(
        select(InstitutionDecisionCatalog).where(
            InstitutionDecisionCatalog.institution_id == institution_id,
            InstitutionDecisionCatalog.is_active.is_(True),
        )
    )


def list_catalog_versions(db: Session, admin: User) -> list[InstitutionDecisionCatalog]:
    admin = authorization_service.revalidate_actor(
        db,
        user_id=admin.id,
        institution_id=admin.institution_id,
        permission=Permission.INSTITUTION_MANAGE,
    )
    return list(
        db.scalars(
            select(InstitutionDecisionCatalog)
            .where(InstitutionDecisionCatalog.institution_id == admin.institution_id)
            .order_by(InstitutionDecisionCatalog.version.desc())
        ).all()
    )


def publish_catalog(
    db: Session, admin: User, data: DecisionCatalogWrite
) -> InstitutionDecisionCatalog:
    """Cria a versão seguinte e torna-a a única ativa."""
    admin = authorization_service.revalidate_actor(
        db,
        user_id=admin.id,
        institution_id=admin.institution_id,
        permission=Permission.INSTITUTION_MANAGE,
        # Serializa publicações concorrentes da mesma instituição: o número de
        # versão e a versão ativa são decididos sob este lock.
        exclusive_institution=True,
    )
    institution_id = admin.institution_id
    current_max = db.scalar(
        select(func.max(InstitutionDecisionCatalog.version)).where(
            InstitutionDecisionCatalog.institution_id == institution_id
        )
    )
    db.execute(
        update(InstitutionDecisionCatalog)
        .where(
            InstitutionDecisionCatalog.institution_id == institution_id,
            InstitutionDecisionCatalog.is_active.is_(True),
        )
        .values(is_active=False)
    )
    catalog = InstitutionDecisionCatalog(
        institution_id=institution_id,
        version=(current_max or 0) + 1,
        scope_description=data.scope_description.strip(),
        topics=[topic.model_dump() for topic in data.topics],
        services=[service.model_dump() for service in data.services],
        is_active=True,
        created_by_user_id=admin.id,
    )
    db.add(catalog)
    db.commit()
    db.refresh(catalog)
    return catalog


def topic_codes(catalog: InstitutionDecisionCatalog) -> tuple[str, ...]:
    return tuple(topic["code"] for topic in catalog.topics)


def resolve_destination(
    catalog: InstitutionDecisionCatalog, topic: str | None
) -> DestinationResolution:
    """D6 sobre a versão ativa do catálogo; ver :mod:`app.decision.catalog`."""
    return resolve_competent_service(catalog.services, catalog_version=catalog.version, topic=topic)
