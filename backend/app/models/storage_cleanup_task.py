"""Tarefas duráveis de limpeza do armazenamento local.

Quando um documento é eliminado, os caminhos dos ficheiros a remover são
registados nesta tabela **na mesma transação** que elimina os registos:
ou a eliminação e as tarefas ficam ambas persistidas, ou nada fica — a
falha ao registar a limpeza nunca é silenciosa, faz rollback de tudo.
Depois do commit, cada tarefa é processada e removida quando o ficheiro
correspondente desaparece; as que falharem permanecem para reconciliação
posterior (SELECT ... FOR UPDATE SKIP LOCKED torna a reconciliação
concorrente segura, sem perder nem duplicar tarefas).
"""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class StorageCleanupTask(Base):
    __tablename__ = "storage_cleanup_tasks"
    __table_args__ = (
        CheckConstraint(
            "btrim(storage_path) <> ''",
            name="ck_storage_cleanup_tasks_path_not_blank",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)

    # Apenas para diagnóstico (o documento é eliminado na mesma transação,
    # por isso não há foreign key).
    document_id: Mapped[UUID] = mapped_column(nullable=False)

    # Relativo ao storage root, como em document_versions.storage_path.
    storage_path: Mapped[str] = mapped_column(String(1024), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
