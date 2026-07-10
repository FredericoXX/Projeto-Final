from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[UUID] = mapped_column(
        primary_key=True,
        default=uuid4,
    )

    # Toda a conversa pertence a exatamente uma instituição; esta FK
    # sustenta o isolamento multi-institucional dos dados na aplicação.
    institution_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "institutions.id",
            name="fk_conversations_institution_id_institutions",
        ),
        nullable=False,
        index=True,
    )

    # O dono da conversa é sempre o utilizador autenticado que a criou;
    # nunca é aceite a partir do payload.
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "users.id",
            name="fk_conversations_user_id_users",
        ),
        nullable=False,
        index=True,
    )

    title: Mapped[str | None] = mapped_column(String(255), nullable=True)

    language: Mapped[str | None] = mapped_column(String(8), nullable=True)

    status: Mapped[str] = mapped_column(String(50), nullable=False, default="active")

    # Nome do atributo Python evita conflito com o `metadata` reservado
    # pelo DeclarativeBase do SQLAlchemy; a coluna na base de dados
    # continua a chamar-se "metadata".
    extra_metadata: Mapped[dict | None] = mapped_column(
        "metadata",
        JSONB,
        nullable=True,
    )

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
