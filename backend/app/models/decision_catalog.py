from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class InstitutionDecisionCatalog(Base):
    """Configuração versionada da política de decisão de uma instituição.

    Junta as duas configurações institucionais de que a política v1.7 depende:

    - o **domínio de âmbito** (D1): a descrição do atendimento académico que a
      instituição configura, contra a qual um pedido é ``in_scope`` ou
      ``out_of_scope``;
    - o **catálogo de serviços** (D6): os serviços com competência declarada
      por tema, com contactos validados.

    Cada versão é **imutável**: uma alteração cria a versão seguinte e
    desativa a anterior, que fica no histórico para que uma decisão antiga
    continue interpretável pela versão do catálogo que registou. Há no máximo
    uma versão ativa por instituição (índice parcial).

    O destino genérico ``institutions.human_support_*`` do E1 **não** faz parte
    deste catálogo e não prova competência para nenhum tema.
    """

    __tablename__ = "institution_decision_catalogs"
    __table_args__ = (
        UniqueConstraint(
            "institution_id", "version", name="uq_institution_decision_catalogs_version"
        ),
        ForeignKeyConstraint(
            ["created_by_user_id", "institution_id"],
            ["users.id", "users.institution_id"],
            name="fk_institution_decision_catalogs_created_by_institution",
        ),
        Index(
            "uq_institution_decision_catalogs_one_active",
            "institution_id",
            unique=True,
            postgresql_where=text("is_active"),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    institution_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "institutions.id",
            name="fk_institution_decision_catalogs_institution_id_institutions",
        ),
        nullable=False,
        index=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    scope_description: Mapped[str] = mapped_column(Text, nullable=False)
    # Validados por app.schemas.decision_catalog antes de chegarem aqui.
    topics: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    services: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by_user_id: Mapped[UUID] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
