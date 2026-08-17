"""Retrieval denso experimental (pgvector), para comparação com a baseline.

**Não é a estratégia de produção.** Nenhuma rota, service ou factory o resolve:
``app.retrieval.dependencies.get_retriever`` continua a devolver o retriever
lexical. Existe para responder a uma pergunta científica — se a recuperação
semântica acrescenta capacidade que o ajuste do ranking lexical demonstrou não
acrescentar (D4.5–D4.7) — e a resposta pode perfeitamente ser "não".

Uma etapa, não duas
-------------------

O retriever lexical tem duas etapas: gera candidatos por correspondência de
termos e depois decide, por **elegibilidade lexical**, quais deles constituem
evidência. Este não tem a segunda. A razão não é economia de esforço: a
elegibilidade lexical é definida sobre cobertura de termos da pergunta
(``app.retrieval.eligibility``), e uma estratégia densa não tem termos. Aplicar
"pelo menos metade dos termos correspondidos" a um vizinho vetorial não é ser
conservador — é medir uma coisa com o instrumento de outra.

O que **é** reutilizado, tal e qual, é a admissibilidade documental:
``RetrievalEligibility`` de :mod:`app.documents.retrievability`, com as mesmas
condições C1–C11 aplicadas no PostgreSQL. Isolamento institucional, idioma,
documento ativo, validade temporal, ``official_only`` e versão ``processed``
mais recente valem exatamente como valem no lexical. **Similaridade vetorial
nunca contorna admissibilidade**: o filtro está no ``WHERE`` da mesma consulta,
não numa verificação posterior sobre os vizinhos já escolhidos.

Consequência declarada: este retriever devolve quase sempre ``top_k``
resultados
------------------------------------------------------------------------------

Sem elegibilidade de conteúdo e sem limiar mínimo, qualquer pergunta cujo
corpus admissível tenha pelo menos ``top_k`` segmentos embebidos recebe
``top_k`` vizinhos — por mais distante que o mais próximo esteja. Isto contraria
o princípio de que **ausência de resultados é uma resposta legítima**, que a
baseline lexical respeita, e é uma diferença comportamental de primeira ordem
entre as duas estratégias, não um detalhe de afinação.

Não se acrescenta aqui um limiar sobre a similaridade para corrigir isso: qual
seria o seu valor é uma pergunta empírica que esta fase não mediu, e um número
escolhido à mão pareceria medição sem o ser. Fica declarado como limitação.

Porque não há limiar herdado do lexical
---------------------------------------

``settings.retrieval_min_relevance_score`` é um piso sobre o score composto
lexical, em [0, 1]. Aplicá-lo à similaridade do cosseno seria tratar duas
quantidades incomparáveis como se fossem a mesma — exatamente o erro que
``ScoreKind`` existe para tornar impossível de cometer por distração.
"""

import logging
from dataclasses import dataclass
from typing import Final

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.documents.retrievability import (
    RetrievabilityContext,
    RetrievalEligibility,
    latest_processed_version_subquery,
)
from app.embeddings.base import EmbeddingError, EmbeddingIdentity, EmbeddingModel
from app.models.chunk_embedding import ChunkEmbedding
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.document_version import DocumentVersion
from app.retrieval.base import (
    Evidence,
    RetrievalContext,
    RetrievalResult,
    RetrievalTrace,
    ScoreKind,
    ScoreSemantics,
)
from app.retrieval.lexical import global_candidate_limit

logger = logging.getLogger(__name__)

#: Identidade da pipeline densa, análoga a ``LEXICAL_PIPELINE_VERSION``. Cobre
#: tudo o que pode mudar o resultado sem mudar o modelo: o texto que é embebido
#: (``content``, não ``normalized_content``), a métrica, a ausência de limiar e
#: a ordenação de desempate. Subir esta versão é obrigatório quando qualquer um
#: destes pontos mudar.
DENSE_PIPELINE_VERSION: Final = "dense_pipeline_v1"


@dataclass(frozen=True)
class DenseResultTrace:
    """Linha auditável de um resultado — apenas métricas, nunca conteúdo."""

    chunk_id: str
    document_id: str
    chunk_index: int
    similarity: float
    structure_type: str | None


@dataclass(frozen=True)
class DenseRetrievalTrace(RetrievalTrace):
    """Trace do retrieval denso: a base neutra mais o detalhe da estratégia.

    ``admissible_chunks`` e ``embedded_chunks`` existem para uma razão precisa:
    um segmento admissível **sem vetor desta identidade** é invisível para esta
    estratégia, e a sua ausência do resultado seria indistinguível de uma falha
    semântica. Com as duas contagens lado a lado, a cobertura do índice deixa de
    ser uma suposição — quem avalia pode exigir que sejam iguais antes de
    atribuir qualquer falha ao modelo.

    A identidade viaja no trace **inteira**, e não só o nome do modelo: é ela
    que diz de que índice estas contagens falam.

    ``candidates_evaluated`` e ``result_count_before_limit`` são iguais entre
    si, e não por acaso: não existe etapa de filtragem entre a recuperação dos
    vizinhos e o corte por ``top_k``. Ver o docstring do módulo.
    """

    embedding_provider: str
    embedding_model: str
    embedding_configuration_version: str
    similarity_metric: str
    candidate_limit: int
    admissible_chunks: int
    embedded_chunks: int
    results: tuple[DenseResultTrace, ...]


def dense_score_semantics(embedding_model: EmbeddingModel) -> ScoreSemantics:
    """Semântica do score, com a identidade do modelo que a produziu.

    A ``version`` combina a pipeline com a identidade do modelo porque **ambas**
    mudam o significado quantitativo do número: trocar o modelo mantendo a
    pipeline produz scores incomparáveis com os anteriores, e a versão tem de o
    revelar.

    ``comparable_across_queries`` é ``False`` pela mesma disciplina do lexical, e
    por uma razão própria: a similaridade do cosseno entre a pergunta e o
    segmento depende de onde a **pergunta** cai no espaço de embeddings.
    Perguntas curtas, genéricas ou fora do domínio produzem similaridades
    sistematicamente mais altas ou mais baixas do que perguntas específicas, sem
    que isso diga nada sobre a qualidade do resultado. Não existe calibração que
    o corrija, e nenhuma foi feita.
    """
    identity = embedding_model.identity
    return ScoreSemantics(
        kind=ScoreKind.DENSE_SIMILARITY,
        version=(
            f"{DENSE_PIPELINE_VERSION}/{identity.provider}:{identity.model}"
            f"/{identity.configuration_version}"
        ),
        comparable_across_queries=False,
    )


class PostgresDenseRetriever:
    """Vizinhos mais próximos sobre os segmentos admissíveis (pgvector).

    O modelo de embeddings é injetado, não resolvido aqui: o retriever conhece
    o contrato ``EmbeddingModel`` e nada sobre fornecedores. É também o que
    permite testá-lo com um modelo determinístico, sem rede.
    """

    def __init__(self, embedding_model: EmbeddingModel) -> None:
        self._embedding_model = embedding_model

    def search(
        self,
        db: Session,
        query: str,
        context: RetrievalContext,
        top_k: int,
        official_only: bool,
    ) -> RetrievalResult:
        identity = self._embedding_model.identity
        vectors = self._embedding_model.embed([query])
        if len(vectors) != 1:
            msg = "the embedding model returned no vector for the query"
            raise EmbeddingError(msg)
        query_vector = list(vectors[0])

        # Mesmo orçamento nominal do lexical, para que os dois traces sejam
        # lidos na mesma escala. Ao contrário do lexical, aqui o orçamento não
        # altera o top_k: os vizinhos já vêm ordenados globalmente e não há
        # etapa posterior que possa promover um candidato de fora.
        candidate_limit = global_candidate_limit(top_k)
        retrievability = RetrievabilityContext(
            institution_id=context.institution_id,
            language=context.language,
            reference_date=context.reference_date,
            official_only=official_only,
        )

        rows = list(
            db.execute(
                self._build_statement(
                    query_vector, retrievability, identity, candidate_limit
                )
            )
        )
        top_rows = rows[:top_k]
        evidence = tuple(_row_to_evidence(row) for row in top_rows)

        admissible, embedded = self._coverage(db, retrievability, identity)
        trace = DenseRetrievalTrace(
            candidates_evaluated=len(rows),
            result_count_before_limit=len(rows),
            embedding_provider=identity.provider,
            embedding_model=identity.model,
            embedding_configuration_version=identity.configuration_version,
            similarity_metric=identity.similarity_metric,
            candidate_limit=candidate_limit,
            admissible_chunks=admissible,
            embedded_chunks=embedded,
            results=tuple(_row_to_trace(row) for row in top_rows),
        )

        # Apenas metadados operacionais: nunca a pergunta nem o conteúdo.
        logger.info(
            "Dense retrieval: model=%s:%s/%s candidates=%d results=%d "
            "admissible=%d embedded=%d institution=%s language=%s",
            identity.provider,
            identity.model,
            identity.configuration_version,
            len(rows),
            len(evidence),
            admissible,
            embedded,
            context.institution_id,
            context.language,
        )
        return RetrievalResult(
            evidence=evidence,
            trace=trace,
            score_semantics=dense_score_semantics(self._embedding_model),
        )

    def _build_statement(
        self,
        query_vector: list[float],
        retrievability: RetrievabilityContext,
        identity: EmbeddingIdentity,
        candidate_limit: int,
    ) -> Select:
        """Vizinhos mais próximos entre os segmentos admissíveis.

        A admissibilidade documental vem inteira de ``RetrievalEligibility`` e
        executa no PostgreSQL — C1–C4 e C6–C11 como predicados do ``WHERE``, C5
        pela subquery canónica —, exatamente como no retriever lexical. O que
        muda é apenas o mecanismo de pesquisa: distância vetorial em vez de
        correspondência de termos.

        O join a ``chunk_embeddings`` é interno **e filtrado pela identidade
        completa** — fornecedor, modelo e ``configuration_version`` — através de
        ``ChunkEmbedding.matches_identity``, que é a definição única desse
        filtro. Filtrar apenas pelo nome do modelo misturaria vetores de
        fornecedores ou configurações diferentes, que não são comparáveis entre
        si, sem que nada falhasse.

        Um segmento admissível sem vetor **desta** identidade não é recuperável
        por esta estratégia. Essa perda é **medida** pelo trace, e não
        silenciada: é assim que uma reindexação interrompida deixa de passar por
        um índice íntegro.

        O desempate por ``document_id``/``chunk_index``/``chunk_id`` reproduz o
        do lexical: sem ele, dois segmentos à mesma distância poderiam trocar de
        posição entre execuções e a experiência deixaria de ser reprodutível.
        """
        latest_processed = latest_processed_version_subquery(retrievability)
        distance = ChunkEmbedding.embedding.cosine_distance(query_vector)
        similarity = (1 - distance).label("similarity")

        return (
            select(
                DocumentChunk.id.label("chunk_id"),
                Document.id.label("document_id"),
                DocumentChunk.document_version_id.label("document_version_id"),
                Document.title.label("document_title"),
                DocumentChunk.chunk_index,
                DocumentChunk.content,
                similarity,
                DocumentChunk.language,
                Document.official_source,
                Document.source_url,
                Document.valid_from,
                Document.valid_until,
                DocumentChunk.structure_type,
            )
            .join(Document, Document.id == DocumentChunk.document_id)
            .join(
                DocumentVersion,
                DocumentVersion.id == DocumentChunk.document_version_id,
            )
            .join(
                latest_processed,
                (latest_processed.c.version_id == DocumentChunk.document_version_id)
                & (latest_processed.c.document_id == DocumentChunk.document_id),
            )
            .join(
                ChunkEmbedding,
                (ChunkEmbedding.chunk_id == DocumentChunk.id)
                & ChunkEmbedding.matches_identity(identity),
            )
            .where(
                *RetrievalEligibility.as_sql_filters(retrievability),
                latest_processed.c.rn == 1,
            )
            .order_by(
                distance.asc(),
                Document.id.asc(),
                DocumentChunk.chunk_index.asc(),
                DocumentChunk.id.asc(),
            )
            .limit(candidate_limit)
        )

    def _coverage(
        self,
        db: Session,
        retrievability: RetrievabilityContext,
        identity: EmbeddingIdentity,
    ) -> tuple[int, int]:
        """``(admissíveis, admissíveis com vetor desta identidade)``.

        Reutiliza ``select_eligible_chunk_ids``, que é a forma SQL **integral**
        de ``RetrievalEligibility``, e o mesmo predicado de identidade da
        consulta de pesquisa. Contar por outro caminho — ou por menos campos —
        arriscaria declarar cobertura completa sobre um conjunto diferente
        daquele que a pesquisa percorre.
        """
        eligible = RetrievalEligibility.select_eligible_chunk_ids(
            retrievability
        ).subquery("eligible_chunks")
        admissible = db.execute(select(eligible.c.id)).fetchall()
        embedded = db.execute(
            select(eligible.c.id).join(
                ChunkEmbedding,
                (ChunkEmbedding.chunk_id == eligible.c.id)
                & ChunkEmbedding.matches_identity(identity),
            )
        ).fetchall()
        return len(admissible), len(embedded)


def _row_to_evidence(row) -> Evidence:
    return Evidence(
        chunk_id=row.chunk_id,
        document_id=row.document_id,
        document_version_id=row.document_version_id,
        document_title=row.document_title,
        chunk_index=row.chunk_index,
        content=row.content,
        # Score público = similaridade do cosseno. Não é uma relevância
        # composta nem uma confiança: ver ScoreKind.DENSE_SIMILARITY.
        score=float(row.similarity),
        language=row.language,
        official_source=row.official_source,
        source_url=row.source_url,
        valid_from=row.valid_from,
        valid_until=row.valid_until,
    )


def _row_to_trace(row) -> DenseResultTrace:
    return DenseResultTrace(
        chunk_id=str(row.chunk_id),
        document_id=str(row.document_id),
        chunk_index=row.chunk_index,
        similarity=float(row.similarity),
        structure_type=row.structure_type,
    )
