"""Construção do :class:`~app.evaluation.snapshot.EvaluationSnapshot` a partir da base.

Separado de :mod:`app.evaluation.snapshot` porque toca em SQLAlchemy e nas
Settings, e o pacote ``app.evaluation`` tem uma garantia de importação fixada
por teste em subprocesso: importar ``app.evaluation.assets`` não pode carregar
``sqlalchemy``, ``app.core.config`` nem o SDK do fornecedor. Este módulo, tal
como ``app.evaluation.results``, **não** é reexportado por
``app/evaluation/__init__.py``.

A elegibilidade não é redefinida aqui
-------------------------------------

O corpus é exatamente o que ``RetrievalEligibility`` considera admissível — a
mesma política que o retrieval lexical aplica. As condições C1–C11 não são
reescritas, reinterpretadas nem parcialmente copiadas: a consulta parte de
``select_eligible_chunk_ids``, que já reúne os filtros de linha e a subquery da
versão efetiva (C5). Se a política mudar, o corpus do snapshot muda com ela, e
é isso que se pretende — uma segunda definição de "documento elegível"
divergiria da primeira e tornaria o snapshot uma ficção.
"""

from datetime import date
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.documents.retrievability import RetrievabilityContext, RetrievalEligibility
from app.evaluation.snapshot import (
    ChunkIdentity,
    CorpusEntry,
    EvaluationSnapshot,
    RetrievalConfiguration,
    build_snapshot,
    compute_chunk_digest,
)
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.document_version import DocumentVersion
from app.retrieval.fts_config import resolve_fts_config
from app.retrieval.lexical import (
    LEXICAL_PIPELINE_VERSION,
    LEXICAL_SCORE_SEMANTICS,
    global_candidate_limit,
)

#: Nome lógico da estratégia em vigor. Não é uma escolha configurável: existe
#: uma única estratégia implementada, e o campo serve para que um snapshot
#: histórico continue interpretável se alguma vez existir outra.
LEXICAL_STRATEGY = "lexical"


def _sha256_hex(column: object):
    """SHA-256 hexadecimal calculado **no PostgreSQL**, sobre a coluna viva.

    Duas razões para não o fazer em Python: o conteúdo documental nunca precisa
    de atravessar a fronteira da base para ser identificado, e o custo de
    memória deixa de crescer com o tamanho do corpus. ``sha256`` é função de
    core desde o PostgreSQL 11 e não exige extensão; o valor coincide com
    ``hashlib.sha256(...).hexdigest()``, o que é verificado por teste.
    """
    return func.encode(func.sha256(func.convert_to(column, "UTF8")), "hex")


def describe_retrieval_configuration(
    *,
    language: str,
    top_k: int,
    official_only: bool,
) -> RetrievalConfiguration:
    """Fotografa a configuração material da recuperação em vigor.

    Os valores são **lidos** da implementação e da configuração, nunca
    declarados à mão: ``scoring_version`` e a semântica do score vêm de
    ``LEXICAL_SCORE_SEMANTICS``, o limiar das Settings, e ``candidate_limit`` de
    ``global_candidate_limit``. Uma alteração em qualquer um deles muda o
    ``snapshot_id`` sem ninguém ter de se lembrar de o atualizar aqui.
    """
    return RetrievalConfiguration(
        strategy=LEXICAL_STRATEGY,
        pipeline_version=LEXICAL_PIPELINE_VERSION,
        scoring_version=LEXICAL_SCORE_SEMANTICS.version,
        score_kind=LEXICAL_SCORE_SEMANTICS.kind.value,
        comparable_across_queries=LEXICAL_SCORE_SEMANTICS.comparable_across_queries,
        language=language,
        top_k=top_k,
        official_only=official_only,
        fts_config=resolve_fts_config(language).value,
        min_relevance_score=settings.retrieval_min_relevance_score,
        candidate_limit=global_candidate_limit(top_k),
    )


def collect_corpus_entries(
    db: Session,
    context: RetrievabilityContext,
) -> tuple[CorpusEntry, ...]:
    """As versões documentais elegíveis sob ``RetrievalEligibility``.

    Uma entrada por versão, com o digest dos seus segmentos elegíveis. A
    consulta é deliberadamente sem ``ORDER BY``: a ordem de leitura não deve
    influenciar a identidade, e é
    :func:`~app.evaluation.snapshot.sort_corpus_entries` que a impõe.
    """
    eligible_chunk_ids = RetrievalEligibility.select_eligible_chunk_ids(context)

    rows = db.execute(
        select(
            Document.id,
            DocumentVersion.id,
            Document.title,
            Document.source_url,
            Document.language,
            Document.official_source,
            Document.valid_from,
            Document.valid_until,
            DocumentVersion.checksum_sha256,
            DocumentChunk.chunk_index,
            # Recalculados, nunca lidos de document_chunks.content_sha256: o
            # hash persistido é uma afirmação sobre o conteúdo, e a identidade
            # tem de derivar do conteúdo real. `normalized_content` é o texto
            # efetivamente pesquisado, de que a coluna gerada `search_vector`
            # deriva; sem ele, uma renormalização mudaria o comportamento da
            # recuperação sem mudar a identidade.
            _sha256_hex(DocumentChunk.content),
            _sha256_hex(DocumentChunk.normalized_content),
            DocumentChunk.section_title,
            DocumentChunk.structure_type,
        )
        .join(Document, Document.id == DocumentChunk.document_id)
        .join(DocumentVersion, DocumentVersion.id == DocumentChunk.document_version_id)
        .where(DocumentChunk.id.in_(eligible_chunk_ids))
    ).all()

    # Agrupa por versão: a identidade documental é a versão, e os segmentos
    # entram como digest dos sinais que participam na recuperação.
    grouped: dict[tuple[UUID, UUID], list[ChunkIdentity]] = {}
    metadata: dict[tuple[UUID, UUID], tuple] = {}
    for row in rows:
        key = (row[0], row[1])
        grouped.setdefault(key, []).append(
            ChunkIdentity(
                chunk_index=row[9],
                content_sha256=row[10],
                normalized_content_sha256=row[11],
                section_title=row[12],
                structure_type=row[13],
            )
        )
        metadata[key] = (row[2], row[3], row[4], row[5], row[6], row[7], row[8])

    entries: list[CorpusEntry] = []
    for key, chunks in grouped.items():
        document_id, document_version_id = key
        title, source_url, language, official, valid_from, valid_until, checksum = metadata[key]
        entries.append(
            CorpusEntry(
                document_id=document_id,
                document_version_id=document_version_id,
                document_title=title,
                source_url=source_url,
                language=language,
                official_source=official,
                valid_from=valid_from,
                valid_until=valid_until,
                checksum_sha256=checksum,
                chunk_count=len(chunks),
                chunk_digest=compute_chunk_digest(tuple(chunks)),
            )
        )
    return tuple(entries)


def build_evaluation_snapshot(
    db: Session,
    *,
    institution_id: UUID,
    language: str,
    reference_date: date,
    top_k: int,
    official_only: bool,
) -> EvaluationSnapshot:
    """Identidade reprodutível do contexto experimental de uma instituição.

    ``reference_date`` é um parâmetro **obrigatório e explícito**. Não existe
    aqui nenhuma chamada a ``date.today()``: a vigência documental depende de
    ``valid_from``/``valid_until``, e uma reconstrução posterior que fosse
    buscar a data corrente reconstruiria outro corpus e chamar-lhe-ia o mesmo.

    O isolamento institucional decorre de ``institution_id`` atravessar o
    ``RetrievabilityContext`` e, com ele, as condições C1–C3 aplicadas no
    ``WHERE``. Não existe Row-Level Security nesta base: a garantia é a
    combinação do filtro da política, das foreign keys compostas e de quem
    invoca esta função já ter autorizado o pedido.
    """
    context = RetrievabilityContext(
        institution_id=institution_id,
        language=language,
        reference_date=reference_date,
        official_only=official_only,
    )
    entries = collect_corpus_entries(db, context)
    retrieval = describe_retrieval_configuration(
        language=language,
        top_k=top_k,
        official_only=official_only,
    )
    return build_snapshot(
        institution_id=institution_id,
        reference_date=reference_date,
        entries=entries,
        retrieval=retrieval,
    )
