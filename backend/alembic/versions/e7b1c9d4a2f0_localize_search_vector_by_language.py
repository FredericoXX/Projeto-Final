"""localize search vector by language

Substitui a expressão da coluna gerada ``document_chunks.search_vector``
por uma seleção de configuração FTS por idioma (``portuguese``/``english``/
``simple``), escolhida a partir da subtag primária de ``language``. A
coluna continua gerada e armazenada: os chunks históricos recebem
automaticamente o novo vetor, sem backfill manual, sem tocar em
``content``, ``normalized_content``, hashes, offsets, IDs de chunks nem
``message_sources``.

O nome da configuração é sempre um literal fixo (``portuguese``,
``english``, ``simple``); ``language`` é referenciado como coluna, nunca
interpolado a partir de input do utilizador.

Revision ID: e7b1c9d4a2f0
Revises: 4a7c1e9d2b63
Create Date: 2026-07-29 00:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e7b1c9d4a2f0"
down_revision: str | Sequence[str] | None = "4a7c1e9d2b63"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Expressão localizada: a configuração é escolhida pela subtag primária do
# idioma do chunk. Mantida idêntica ao Computed do modelo SQLAlchemy.
_LOCALIZED_EXPRESSION = (
    "CASE "
    "WHEN lower(split_part(language, '-', 1)) = 'pt' "
    "THEN to_tsvector('portuguese'::regconfig, normalized_content) "
    "WHEN lower(split_part(language, '-', 1)) = 'en' "
    "THEN to_tsvector('english'::regconfig, normalized_content) "
    "ELSE to_tsvector('simple'::regconfig, normalized_content) "
    "END"
)

_SIMPLE_EXPRESSION = "to_tsvector('simple'::regconfig, normalized_content)"


def _replace_search_vector(expression: str) -> None:
    """Recria a coluna gerada e o índice GIN com ``expression``.

    Uma coluna gerada não pode ter a sua expressão alterada de forma
    portável; remove-se e recria-se. O índice GIN depende da coluna, por
    isso é removido antes e recriado depois. A recomputação para todas as
    linhas é automática (coluna STORED).
    """
    op.drop_index(
        "ix_document_chunks_search_vector",
        table_name="document_chunks",
        postgresql_using="gin",
    )
    op.drop_column("document_chunks", "search_vector")
    op.add_column(
        "document_chunks",
        sa.Column(
            "search_vector",
            postgresql.TSVECTOR(),
            sa.Computed(expression, persisted=True),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_document_chunks_search_vector",
        "document_chunks",
        ["search_vector"],
        unique=False,
        postgresql_using="gin",
    )


def upgrade() -> None:
    """Passa a configuração FTS por idioma na coluna gerada."""
    _replace_search_vector(_LOCALIZED_EXPRESSION)


def downgrade() -> None:
    """Restaura a configuração única ``simple`` da baseline anterior."""
    _replace_search_vector(_SIMPLE_EXPRESSION)
