from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, CheckConstraint, DateTime, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class Institution(Base):
    __tablename__ = "institutions"
    __table_args__ = (
        UniqueConstraint("code", name="uq_institutions_code"),
        CheckConstraint(
            "default_language = ANY (supported_languages)",
            name="ck_institutions_default_language_supported",
        ),
    )

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
