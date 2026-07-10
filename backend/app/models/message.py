from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[UUID] = mapped_column(
        primary_key=True,
        default=uuid4,
    )

    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "conversations.id",
            name="fk_messages_conversation_id_conversations",
        ),
        nullable=False,
        index=True,
    )

    # Duplicado de propósito a partir da conversa: facilita isolamento,
    # auditoria e consultas futuras sem precisar de join com "conversations".
    institution_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "institutions.id",
            name="fk_messages_institution_id_institutions",
        ),
        nullable=False,
        index=True,
    )

    # Preenchido quando a mensagem é de um utilizador autenticado
    # (role="user"); pode ser nulo para mensagens "assistant"/"system".
    user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey(
            "users.id",
            name="fk_messages_user_id_users",
        ),
        nullable=True,
    )

    role: Mapped[str] = mapped_column(String(20), nullable=False)

    content: Mapped[str] = mapped_column(Text, nullable=False)

    language: Mapped[str | None] = mapped_column(String(8), nullable=True)

    # Mesmo cuidado de nomenclatura que em Conversation.extra_metadata.
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
