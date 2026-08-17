"""Indexação vetorial experimental do corpus admissível (D4.8).

Uso (a partir de ``backend/``, com o virtual environment ativo):

    python -m scripts.embed_pilot_corpus \
        --ground-truth ../docs/evaluation/retrieval-ground-truth-p1-repooled.json \
        --binding ../storage/pilot-corpus/S1-identifier-binding.json \
        [--embedding-model text-embedding-3-small] [--reembed]

Calcula e persiste os vetores dos segmentos **admissíveis** sob
``RetrievalEligibility``, na tabela ``chunk_embeddings``. Não altera
``document_chunks``, não toca em ``search_vector`` e não altera comportamento
nenhum de produção: nenhuma rota lê esta tabela.

Idempotência, e o que conta como "já indexado"
----------------------------------------------

Um segmento é reenviado ao fornecedor a menos que exista já uma linha com a
**identidade completa** — mesmo ``provider``, mesmo ``model``, mesma
``configuration_version`` — e com o SHA-256 do texto atual. Qualquer dos três
divergir torna a linha obsoleta, e ela é substituída em vez de sobreviver.

O SHA é **recalculado** a partir do texto que vai ser enviado, e não lido de
``DocumentChunk.content_sha256``. É a mesma definição, e é a mesma função que
``verify_index_identity`` usa do outro lado: se a indexação e a verificação
divergissem aqui, um índice íntegro passaria a ser recusado, ou um obsoleto a
ser aceite.

Não reembeber sem necessidade não é só economia: reembeber produziria vetores
ligeiramente diferentes — os modelos remotos não garantem reprodutibilidade bit
a bit — e uma execução da avaliação deixaria de ser comparável com a anterior
sem que nada tivesse mudado no corpus. ``--reembed`` força o contrário, e existe
para medir precisamente essa deriva.

O que é embebido, e porquê
--------------------------

O texto enviado é ``DocumentChunk.content`` — a forma **original**, com
acentuação, maiúsculas e pontuação. Não é ``normalized_content``, que é o que a
pesquisa lexical usa. A normalização existe para servir o índice FTS: remove
acentos e caixa porque o *stemmer* e a comparação de termos beneficiam disso.
Um modelo de embeddings é treinado sobre texto natural, e alimentá-lo com texto
normalizado destruiria sinal que ele sabe usar.

Isto é uma diferença real entre C0 e C1, não um detalhe de implementação: as
duas condições não veem literalmente o mesmo texto. Fica declarada aqui, no
artefacto e no relatório.

Aviso sobre transmissão de conteúdo
-----------------------------------

Embeber envia o texto dos segmentos para o fornecedor configurado. É o mesmo
fluxo de dados que a geração de respostas já faz com as evidências
selecionadas, e não uma exposição nova de natureza diferente — mas é
transmissão de conteúdo institucional para um serviço externo, e quem executa
este comando deve sabê-lo. Nenhum conteúdo é escrito em ficheiros versionados.
"""

import argparse
import hashlib
import struct
import sys
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Any, Final
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.documents.retrievability import (
    RetrievabilityContext,
    RetrievalEligibility,
    latest_processed_version_subquery,
)
from app.embeddings.base import EmbeddingIdentity, EmbeddingModel
from app.embeddings.dependencies import get_embedding_model
from app.evaluation.snapshot_builder import build_evaluation_snapshot
from app.models.chunk_embedding import EMBEDDING_DIMENSION, ChunkEmbedding
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.document_version import DocumentVersion

#: Modelo por omissão. Fixado no código, e não lido do ambiente, para que a
#: experiência seja reproduzível a partir do repositório — ver
#: ``get_embedding_model``.
DEFAULT_EMBEDDING_MODEL: Final = "text-embedding-3-small"

#: Segmentos por transação. Confirmar em blocos permite retomar uma indexação
#: interrompida sem repetir o que já foi pago e persistido.
COMMIT_EVERY: Final = 256

EXIT_OK: Final = 0
EXIT_USAGE: Final = 2
EXIT_SNAPSHOT_MISMATCH: Final = 3
EXIT_MODEL_MISMATCH: Final = 4


class IndexingError(RuntimeError):
    def __init__(self, message: str, exit_code: int) -> None:
        super().__init__(message)
        self.exit_code = exit_code


def vector_digest(vector: Sequence[float]) -> str:
    """SHA-256 dos componentes, na sua representação binária de 32 bits.

    A coluna ``vector`` do pgvector guarda ``float4``; empacotar em ``<f`` é,
    por isso, a forma exata do que está na base, e não uma aproximação
    escolhida. É este digest que torna detetável a deriva entre duas
    indexações do mesmo texto pelo mesmo modelo.
    """
    return hashlib.sha256(struct.pack(f"<{len(vector)}f", *vector)).hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    import json

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise IndexingError(f"file not found: {path}", EXIT_USAGE) from error
    except ValueError as error:
        raise IndexingError(f"invalid JSON in {path}: {error}", EXIT_USAGE) from error


def verify_snapshot(
    db: Session,
    *,
    ground_truth: dict[str, Any],
    binding: dict[str, Any],
    language: str,
    top_k: int,
    official_only: bool,
) -> None:
    """Indexar um corpus que já não é S1 produziria um índice incomparável."""
    snapshot = build_evaluation_snapshot(
        db,
        institution_id=UUID(binding["institution_id"]),
        language=language,
        reference_date=date.fromisoformat(ground_truth["reference_date"]),
        top_k=top_k,
        official_only=official_only,
    )
    problems: list[str] = []
    if snapshot.snapshot_id != ground_truth["snapshot_id"]:
        problems.append(f"snapshot_id {snapshot.snapshot_id}")
    if snapshot.corpus_digest != ground_truth["corpus_digest"]:
        problems.append(f"corpus_digest {snapshot.corpus_digest}")
    if problems:
        raise IndexingError(
            "the corpus no longer matches S1; indexing it would produce vectors "
            "for a different corpus than the one being evaluated: "
            + "; ".join(problems),
            EXIT_SNAPSHOT_MISMATCH,
        )


def verify_storable(identity: EmbeddingIdentity) -> None:
    """A dimensão declarada tem de caber na coluna, sem truncagem silenciosa."""
    if identity.dimension != EMBEDDING_DIMENSION:
        raise IndexingError(
            f"model {identity.model!r} declares dimension {identity.dimension}, "
            f"but chunk_embeddings.embedding is vector({EMBEDDING_DIMENSION}); "
            "a model of a different width requires its own migration",
            EXIT_MODEL_MISMATCH,
        )


def admissible_chunks(db: Session, context: RetrievabilityContext) -> list[Any]:
    """Segmentos admissíveis sob ``RetrievalEligibility``, em ordem estável.

    A mesma política, e a mesma forma SQL, que o retriever usa em execução: C1–C4
    e C6–C11 como predicados, C5 pela subquery canónica. Indexar por outro
    critério criaria um índice que cobre um conjunto diferente daquele que a
    pesquisa percorre — e a diferença apareceria depois como falha semântica.
    """
    latest_processed = latest_processed_version_subquery(context)
    statement = (
        select(
            DocumentChunk.id,
            DocumentChunk.content,
        )
        .join(Document, Document.id == DocumentChunk.document_id)
        .join(DocumentVersion, DocumentVersion.id == DocumentChunk.document_version_id)
        .join(
            latest_processed,
            (latest_processed.c.version_id == DocumentChunk.document_version_id)
            & (latest_processed.c.document_id == DocumentChunk.document_id),
        )
        .where(
            *RetrievalEligibility.as_sql_filters(context),
            latest_processed.c.rn == 1,
        )
        .order_by(DocumentChunk.id.asc())
    )
    return list(db.execute(statement))


def content_digest(text: str) -> str:
    """SHA-256 do texto **efetivamente enviado** ao modelo.

    Recalculado, e não copiado de ``DocumentChunk.content_sha256``: copiar faria
    a coluna descrever o que se *supõe* ter sido enviado. São a mesma definição
    — ``sha256(content.encode("utf-8"))`` — e é justamente por isso que a
    diferença só se nota quando algo corre mal, que é quando importa.

    É também a função que ``verify_index_identity`` usa para decidir se um vetor
    está obsoleto, e tem de continuar a ser a mesma nos dois lados: se a
    indexação e a verificação divergissem na definição do hash, um índice
    íntegro passaria a ser recusado, ou um obsoleto a ser aceite.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def existing_index(
    db: Session, identity: EmbeddingIdentity
) -> dict[UUID, tuple[str, str]]:
    """``chunk_id -> (configuration_version, embedded_content_sha256)``.

    Filtrado por fornecedor **e** modelo, que são a chave; a
    ``configuration_version`` vem no valor porque é o que decide se a linha
    existente ainda serve. Uma linha com outra configuração não é ignorada —
    é reconhecida como obsoleta e substituída.
    """
    rows = db.execute(
        select(
            ChunkEmbedding.chunk_id,
            ChunkEmbedding.configuration_version,
            ChunkEmbedding.embedded_content_sha256,
        ).where(
            ChunkEmbedding.provider == identity.provider,
            ChunkEmbedding.model == identity.model,
        )
    ).all()
    return {row[0]: (row[1], row[2]) for row in rows}


def index_corpus(
    db: Session,
    *,
    embedding_model: EmbeddingModel,
    context: RetrievabilityContext,
    reembed: bool,
) -> dict[str, int]:
    """Embebe o que falta e devolve as contagens do que foi feito."""
    identity = embedding_model.identity
    verify_storable(identity)

    rows = admissible_chunks(db, context)
    existing = existing_index(db, identity)

    pending: list[tuple[UUID, str, str]] = []
    stale_configuration = 0
    stale_content = 0
    for chunk_id, content in rows:
        digest = content_digest(content)
        current = existing.get(chunk_id)
        if current is not None and current != (identity.configuration_version, digest):
            if current[0] != identity.configuration_version:
                stale_configuration += 1
            else:
                stale_content += 1
        if current == (identity.configuration_version, digest) and not reembed:
            continue
        pending.append((chunk_id, content, digest))

    written = 0
    for start in range(0, len(pending), COMMIT_EVERY):
        block = pending[start : start + COMMIT_EVERY]
        vectors = embedding_model.embed([content for _, content, _ in block])
        if len(vectors) != len(block):
            msg = "the embedding model returned a different number of vectors"
            raise IndexingError(msg, EXIT_MODEL_MISMATCH)
        chunk_ids = [chunk_id for chunk_id, _, _ in block]
        # Substituição explícita em vez de UPSERT: o que se pretende é que uma
        # linha antiga — de outra configuração ou de outro conteúdo — nunca
        # sobreviva a uma reindexação.
        db.execute(
            delete(ChunkEmbedding).where(
                ChunkEmbedding.provider == identity.provider,
                ChunkEmbedding.model == identity.model,
                ChunkEmbedding.chunk_id.in_(chunk_ids),
            )
        )
        db.add_all(
            [
                ChunkEmbedding(
                    chunk_id=chunk_id,
                    provider=identity.provider,
                    model=identity.model,
                    configuration_version=identity.configuration_version,
                    embedded_content_sha256=digest,
                    embedding=list(vector),
                )
                for (chunk_id, _, digest), vector in zip(block, vectors, strict=True)
            ]
        )
        db.commit()
        written += len(block)
        print(f"  embebidos {written}/{len(pending)}", flush=True)

    return {
        "admissible": len(rows),
        "already_indexed": len(rows) - len(pending),
        "embedded_now": written,
        "replaced_stale_configuration": stale_configuration,
        "replaced_stale_content": stale_content,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ground-truth", type=Path, required=True)
    parser.add_argument("--binding", type=Path, required=True)
    parser.add_argument("--embedding-model", default=DEFAULT_EMBEDDING_MODEL)
    parser.add_argument(
        "--reembed",
        action="store_true",
        help="reenvia mesmo o que já está indexado (mede a deriva do fornecedor)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return _run(args)
    except IndexingError as error:
        print(f"error: {error}", file=sys.stderr)
        return error.exit_code


def _run(args: argparse.Namespace) -> int:
    ground_truth = _load_json(args.ground_truth)
    binding = _load_json(args.binding)
    if binding.get("snapshot_id") != ground_truth.get("snapshot_id"):
        raise IndexingError(
            "the binding file and the ground truth refer to different snapshots",
            EXIT_SNAPSHOT_MISMATCH,
        )

    embedding_model = get_embedding_model(args.embedding_model)
    identity = embedding_model.identity
    verify_storable(identity)

    from scripts.evaluate_retrieval_experiment import SessionLocalFactory

    with SessionLocalFactory() as db:
        snapshot = build_evaluation_snapshot(
            db,
            institution_id=UUID(binding["institution_id"]),
            language="pt",
            reference_date=date.fromisoformat(ground_truth["reference_date"]),
            top_k=5,
            official_only=True,
        )
        retrieval = snapshot.retrieval.canonical()
        verify_snapshot(
            db,
            ground_truth=ground_truth,
            binding=binding,
            language=retrieval["language"],
            top_k=retrieval["top_k"],
            official_only=retrieval["official_only"],
        )
        context = RetrievabilityContext(
            institution_id=UUID(binding["institution_id"]),
            language=retrieval["language"],
            reference_date=date.fromisoformat(ground_truth["reference_date"]),
            official_only=retrieval["official_only"],
        )
        counts = index_corpus(
            db,
            embedding_model=embedding_model,
            context=context,
            reembed=args.reembed,
        )

    print(f"modelo          : {identity.provider}:{identity.model}")
    print(f"configuração    : {identity.configuration_version}")
    print(f"dimensão        : {identity.dimension}")
    print(f"similaridade    : {identity.similarity_metric}")
    print(f"admissíveis     : {counts['admissible']}")
    print(f"já indexados    : {counts['already_indexed']}")
    print(f"embebidos agora : {counts['embedded_now']}")
    print(f"  dos quais por configuração obsoleta : "
          f"{counts['replaced_stale_configuration']}")
    print(f"  dos quais por conteúdo alterado     : {counts['replaced_stale_content']}")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
