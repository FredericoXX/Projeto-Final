from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base

# Únicos mecanismos aceites para estabelecer a associação. "administrative" é
# o único implementado: um admin autenticado da mesma instituição. A futura
# autenticação institucional validada terá um valor próprio, acrescentado por
# migration quando o protocolo existir — não é antecipado aqui.
LINK_METHOD_ADMINISTRATIVE = "administrative"


class UserExternalIdentity(Base):
    """Associação entre uma conta local e o identificador externo estável.

    É a única prova aceite de que uma conta local corresponde a uma pessoa no
    sistema académico da instituição. A igualdade de email **não** é prova: o
    email nem sequer participa nesta tabela.

    A associação só é criada pela superfície administrativa (permissão
    ``EXTERNAL_IDENTITY_MANAGE``); nenhum payload, parâmetro ou mensagem do
    próprio utilizador a altera. Não guarda dados académicos — apenas o
    identificador necessário para pedir esses dados ao fornecedor.
    """

    __tablename__ = "user_external_identities"
    __table_args__ = (
        # A conta associada pertence obrigatoriamente à mesma instituição da
        # associação: impede ligar um identificador de uma instituição a uma
        # conta de outra.
        ForeignKeyConstraint(
            ["user_id", "institution_id"],
            ["users.id", "users.institution_id"],
            name="fk_user_external_identities_user_institution",
        ),
        ForeignKeyConstraint(
            ["linked_by_user_id", "institution_id"],
            ["users.id", "users.institution_id"],
            name="fk_user_external_identities_linked_by_institution",
        ),
        # Uma conta tem no máximo uma associação.
        UniqueConstraint("user_id", name="uq_user_external_identities_user_id"),
        # Um identificador externo corresponde, dentro de uma instituição, a
        # no máximo uma conta local — duas contas não podem ler os mesmos
        # registos individuais.
        UniqueConstraint(
            "institution_id",
            "external_subject",
            name="uq_user_external_identities_institution_subject",
        ),
        CheckConstraint(
            r"btrim(external_subject, E' \t\n\r\f\v') <> ''",
            name="ck_user_external_identities_subject_not_blank",
        ),
        CheckConstraint(
            "link_method IN ('administrative')",
            name="ck_user_external_identities_link_method_allowed",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)

    institution_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "institutions.id",
            name="fk_user_external_identities_institution_id_institutions",
        ),
        nullable=False,
        index=True,
    )

    user_id: Mapped[UUID] = mapped_column(nullable=False)

    # Identificador estável do sistema académico (por exemplo, um número
    # interno de aluno). Opaco para esta aplicação: nunca é interpretado.
    external_subject: Mapped[str] = mapped_column(String(128), nullable=False)

    link_method: Mapped[str] = mapped_column(
        String(30), nullable=False, default=LINK_METHOD_ADMINISTRATIVE
    )

    # O admin que estabeleceu a associação, para auditoria.
    linked_by_user_id: Mapped[UUID] = mapped_column(nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
