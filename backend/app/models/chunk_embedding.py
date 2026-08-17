from datetime import datetime
from uuid import UUID

# O pgvector não publica stubs nem marcador ``py.typed``. O ignore é local e
# estreito de propósito: preferível a criar configuração global de mypy por
# causa de uma única dependência sem tipos.
from pgvector.sqlalchemy import Vector  # type: ignore[import-untyped]
from sqlalchemy import (
    CheckConstraint,
    ColumnElement,
    DateTime,
    ForeignKey,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.embeddings.base import EmbeddingIdentity

#: Largura da coluna vetorial. Um modelo de dimensão diferente **não** é
#: armazenável sem migration própria, e isso é deliberado: o tipo do PostgreSQL
#: é a única garantia estrutural de que os vetores de uma mesma coluna são
#: comparáveis. Quem indexa verifica esta constante contra a dimensão declarada
#: pelo modelo e recusa a indexação se divergirem.
EMBEDDING_DIMENSION = 1536


class ChunkEmbedding(Base):
    """Vetor experimental de um :class:`~app.models.document_chunk.DocumentChunk`.

    Tabela **separada**, e não uma coluna em ``document_chunks``, por três
    razões concretas:

    - o comportamento lexical de produção não é tocado — ``search_vector`` e as
      restantes colunas ficam exatamente como estavam, e a tabela pode ser
      removida sem migration sobre a tabela de produção;
    - a mesma segmentação pode ser embebida por mais do que um modelo ao mesmo
      tempo, porque o fornecedor e o modelo fazem parte da chave primária.
      Comparar dois modelos não exige apagar o primeiro;
    - o vetor é um artefacto de indexação derivado, com ciclo de vida próprio:
      pode ficar desatualizado sem que o chunk esteja errado.

    A identidade é guardada **inteira**
    -----------------------------------

    :class:`~app.embeddings.base.EmbeddingIdentity` declara ``provider``,
    ``model`` e ``configuration_version``, e as três colunas existem aqui porque
    quem consome tem de poder filtrar pelas três. Guardar menos do que se declara
    não é uma simplificação: ``text-embedding-3-small`` de dois fornecedores
    diferentes, ou o mesmo modelo com pré-processamento diferente, produzem
    vetores que não são comparáveis entre si — e uma recuperação que filtrasse só
    pelo nome do modelo misturá-los-ia sem nada falhar.

    ``provider`` e ``model`` formam a chave com ``chunk_id``;
    ``configuration_version`` **não** entra na chave, de propósito: mudar a
    configuração invalida o vetor anterior em vez de coexistir com ele, e a
    reindexação substitui a linha. Como a substituição pode ficar a meio, quem
    lê tem de filtrar também por ``configuration_version`` — caso contrário uma
    reindexação interrompida produziria um índice com metade dos vetores da
    configuração antiga, indistinguível de um índice íntegro.

    ``embedded_content_sha256`` regista o SHA-256 do texto **efetivamente
    enviado** ao modelo, recalculado no momento do envio. Coincide, na prática,
    com ``DocumentChunk.content_sha256``, mas não é copiado dele: copiá-lo faria
    a coluna descrever o que se *supõe* ter sido enviado em vez do que foi.
    É o que permite detetar um vetor obsoleto quando o chunk é reprocessado.

    Sem índice ANN (HNSW/IVFFlat) por decisão explícita: com um corpus desta
    ordem a pesquisa exata é barata, e um índice aproximado tornaria o resultado
    dependente de parâmetros de recall do índice — precisamente o que uma
    experiência comparativa não pode ter.
    """

    __tablename__ = "chunk_embeddings"
    __table_args__ = (
        # ``btrim(x)`` sem segundo argumento corta **apenas** espaços, pelo que
        # um valor composto só por tabulações ou mudanças de linha passaria por
        # um identificador válido. O conjunto é explícito por isso.
        CheckConstraint(
            r"btrim(provider, E' \t\n\r\f\v') <> ''",
            name="ck_chunk_embeddings_provider_not_blank",
        ),
        CheckConstraint(
            r"btrim(model, E' \t\n\r\f\v') <> ''",
            name="ck_chunk_embeddings_model_not_blank",
        ),
        CheckConstraint(
            r"btrim(configuration_version, E' \t\n\r\f\v') <> ''",
            name="ck_chunk_embeddings_configuration_version_not_blank",
        ),
    )

    # A chave primária composta é o que permite coexistirem vetores de
    # fornecedores e modelos diferentes para o mesmo chunk.
    chunk_id: Mapped[UUID] = mapped_column(
        ForeignKey(
            "document_chunks.id",
            name="fk_chunk_embeddings_chunk_id_document_chunks",
            ondelete="CASCADE",
        ),
        primary_key=True,
    )

    provider: Mapped[str] = mapped_column(String(64), primary_key=True)

    model: Mapped[str] = mapped_column(String(128), primary_key=True)

    configuration_version: Mapped[str] = mapped_column(String(64), nullable=False)

    embedded_content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)

    embedding: Mapped[list[float]] = mapped_column(
        Vector(EMBEDDING_DIMENSION),
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    @staticmethod
    def matches_identity(identity: EmbeddingIdentity) -> ColumnElement[bool]:
        """Predicado «esta linha pertence a esta identidade», definido uma vez.

        Existe para que a recuperação, a contagem de cobertura, o digest do
        índice e a indexação não possam divergir quanto ao que consideram «o
        índice». Três definições paralelas do mesmo filtro é exatamente a forma
        de um deles ficar a filtrar por menos campos do que a identidade declara
        — e de um índice misto passar por íntegro.

        A dimensão **não** entra: é garantida estruturalmente pelo tipo da
        coluna, e um vetor de outra largura nem sequer é armazenável.
        """
        return (
            (ChunkEmbedding.provider == identity.provider)
            & (ChunkEmbedding.model == identity.model)
            & (ChunkEmbedding.configuration_version == identity.configuration_version)
        )
