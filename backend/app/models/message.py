from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, ForeignKeyConstraint, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        # Substitui a FK simples em conversation_id: garante não só que a
        # conversa existe, mas que message.institution_id é obrigatoriamente
        # igual ao institution_id dessa conversa.
        ForeignKeyConstraint(
            ["conversation_id", "institution_id"],
            ["conversations.id", "conversations.institution_id"],
            name="fk_messages_conversation_id_institution_id_conversations",
        ),
        # Substitui a FK simples em user_id: quando presente, garante que o
        # autor pertence à mesma instituição da mensagem. user_id nulo
        # (mensagens "assistant" futuras) continua a não ser validado por
        # esta constraint — o Postgres não a aplica quando alguma das
        # colunas da FK composta é NULL (MATCH SIMPLE, o comportamento por
        # omissão).
        ForeignKeyConstraint(
            ["user_id", "institution_id"],
            ["users.id", "users.institution_id"],
            name="fk_messages_user_id_institution_id_users",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        primary_key=True,
        default=uuid4,
    )

    # A referência real à conversa é a foreign key composta
    # (conversation_id, institution_id) em __table_args__.
    conversation_id: Mapped[UUID] = mapped_column(
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

    # Guarda sempre o autor real da mensagem: para role="user" é o próprio
    # utilizador; para role="system", o admin que a criou manualmente (ver
    # message_service.create_message) — isto permite auditoria de quem
    # escreveu a mensagem. Só fica nulo para mensagens "assistant" futuras,
    # criadas automaticamente sem um utilizador autenticado por trás.
    user_id: Mapped[UUID | None] = mapped_column(
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
