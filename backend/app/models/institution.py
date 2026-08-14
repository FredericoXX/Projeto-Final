from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, CheckConstraint, DateTime, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class Institution(Base):
    __tablename__ = "institutions"
    __table_args__ = (
        # O código é um identificador institucional único e legível
        # (ex.: "DEMO-HEI"); o isolamento multi-institucional dos dados
        # é feito por institution_id, não por este campo.
        UniqueConstraint("code", name="uq_institutions_code"),
        # Garante que o idioma padrão está sempre entre os idiomas suportados.
        CheckConstraint(
            "default_language = ANY (supported_languages)",
            name="ck_institutions_default_language_supported",
        ),
        # Destino humano default, em duas partes que se complementam:
        #
        # 1. nenhum campo presente pode ser vazio ou só whitespace. "IS NOT
        #    NULL" sozinho aceitaria "   " como nome/contacto, produzindo uma
        #    configuração formalmente completa mas inutilizável. O conjunto de
        #    corte é explícito porque o btrim(x) sem argumento — o padrão usado
        #    em document_chunks — corta apenas espaços, deixando passar um
        #    valor composto só por tabs ou newlines;
        # 2. a configuração está ou totalmente ausente, ou com nome e pelo
        #    menos uma via de contacto. Um nome sem contacto não encaminha
        #    ninguém, e um contacto sem nome não identifica o serviço.
        CheckConstraint(
            "(human_support_name IS NULL"
            r" OR btrim(human_support_name, E' \t\n\r\f\v') <> '')"
            " AND (human_support_email IS NULL"
            r" OR btrim(human_support_email, E' \t\n\r\f\v') <> '')"
            " AND (human_support_url IS NULL"
            r" OR btrim(human_support_url, E' \t\n\r\f\v') <> '')"
            " AND ("
            "(human_support_name IS NULL"
            " AND human_support_email IS NULL"
            " AND human_support_url IS NULL)"
            " OR (human_support_name IS NOT NULL"
            " AND (human_support_email IS NOT NULL OR human_support_url IS NOT NULL))"
            ")",
            name="ck_institutions_human_support_configuration",
        ),
    )

    # UUID gerado em Python (não pela base de dados) para que o valor
    # esteja disponível antes do commit, por exemplo em relações ou testes.
    id: Mapped[UUID] = mapped_column(
        primary_key=True,
        default=uuid4,
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)

    code: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    domain: Mapped[str | None] = mapped_column(String(255), nullable=True)

    default_language: Mapped[str] = mapped_column(String(8), nullable=False)

    supported_languages: Mapped[list[str]] = mapped_column(
        ARRAY(String(8)),
        nullable=False,
    )

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Destino humano default da instituição, usado pelo encaminhamento E1
    # (app/services/human_handoff_service.py). É um único destino por
    # instituição: não existe tipologia de serviços, encaminhamento por
    # assunto, fila, horário nem operador. Os três campos começam NULL e
    # continuam opcionais — uma instituição sem atendimento humano
    # configurado permanece válida e apenas não oferece handoff.
    human_support_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    human_support_email: Mapped[str | None] = mapped_column(String(320), nullable=True)

    human_support_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)

    # Campos de auditoria: created_at fixa-se na inserção; updated_at
    # é recalculado pela base de dados em cada atualização (onupdate).
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
