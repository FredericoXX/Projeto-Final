from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        # id já é único por si só (é a primary key); esta constraint
        # "degenerada" existe apenas para que (id, institution_id) possa
        # ser referenciado por foreign keys compostas a partir de
        # conversations/messages, garantindo que essas linhas só podem
        # apontar para um utilizador da mesma instituição.
        UniqueConstraint("id", "institution_id", name="uq_users_id_institution_id"),
    )

    id: Mapped[UUID] = mapped_column(
        primary_key=True,
        default=uuid4,
    )

    # Todo o utilizador pertence a exatamente uma instituição; esta FK
    # sustenta o isolamento multi-institucional dos dados na aplicação.
    institution_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "institutions.id",
            name="fk_users_institution_id_institutions",
        ),
        nullable=False,
        index=True,
    )

    full_name: Mapped[str] = mapped_column(String(255), nullable=False)

    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        index=True,
        nullable=False,
    )

    password_hash: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    role: Mapped[str] = mapped_column(String(50), nullable=False, default="user")

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Campos de auditoria: updated_at é atualizado automaticamente
    # pela base de dados sempre que o registo é alterado.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
