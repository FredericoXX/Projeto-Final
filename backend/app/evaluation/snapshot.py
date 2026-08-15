"""Identidade científica reprodutível do contexto de uma avaliação.

Uma pergunta e um resultado não bastam para reprodução científica: se o corpus
documental ou a configuração de recuperação mudarem entretanto, o mesmo pedido
produz outro resultado sem que nada o assinale. Este módulo dá **identidade
determinística** ao contexto experimental, para que duas medições possam ser
declaradas comparáveis — ou declaradas incomparáveis — em vez de presumidas.

Duas identidades, deliberadamente separadas
-------------------------------------------

- :func:`compute_corpus_digest` identifica **apenas o corpus elegível**;
- :func:`compute_snapshot_id` identifica a **experiência**: corpus, instituição,
  data de referência e configuração de recuperação.

A separação é o que torna comparáveis os dois eixos que interessam a seguir:
"mesmo corpus, recuperação diferente" observa-se como ``corpus_digest`` igual
com ``snapshot_id`` diferente; "mesma recuperação, corpus diferente" como o
inverso. Uma identidade única não permitiria distinguir os dois casos.

Este módulo é **puro**: contratos imutáveis, canonicalização e digest. Não
importa SQLAlchemy, Settings, o fornecedor nem a aplicação — a construção a
partir da base de dados vive em :mod:`app.evaluation.snapshot_builder`. A
separação não é estética: ``app/evaluation/__init__.py`` é importado por
``app.evaluation.assets``, e um teste em subprocesso fixa que essa importação
não carrega ``sqlalchemy``, ``app.core.config`` nem o SDK do fornecedor.

Não é experiment tracking
-------------------------

Não há aqui execução, métricas, resultados nem histórico. O snapshot é um
**valor**: descreve o contexto, não a medição. O que se mede com ele, e o
*ground truth* contra o qual se mede, pertencem a fases posteriores.
"""

import hashlib
from dataclasses import dataclass
from datetime import date
from typing import Any, Final
from uuid import UUID

from app.evaluation.results import canonical_json

#: Versão do formato canónico. Participa nos dois digests: uma alteração da
#: forma das entradas ou do payload muda a identidade explicitamente, em vez de
#: dois formatos diferentes poderem colidir no mesmo valor.
SNAPSHOT_SCHEMA_VERSION: Final = "1"

DIGEST_ALGORITHM: Final = "sha256"


def _digest(payload: object) -> str:
    """SHA-256 da serialização canónica única do projeto.

    Reutiliza :func:`app.evaluation.results.canonical_json` — chaves ordenadas,
    UTF-8, ``ensure_ascii=False``, separadores estáveis e sem newline final —
    em vez de declarar uma segunda canonicalização que divergiria da primeira à
    primeira alteração. Nunca se usa ``hash()``, que é aleatorizado por processo
    e não é identidade persistente.
    """
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _date_value(value: date | None) -> str | None:
    """ISO-8601 ``YYYY-MM-DD``, ou ``null``. Formato único e sem fuso."""
    return None if value is None else value.isoformat()


@dataclass(frozen=True)
class ChunkIdentity:
    """Os sinais de um segmento que participam na recuperação.

    Dois hashes, e não um, porque a recuperação lê duas colunas diferentes:

    - ``content_sha256`` identifica o texto original, que é o que o gerador
      recebe como evidência;
    - ``normalized_content_sha256`` identifica o texto **efetivamente
      pesquisado**: é de ``normalized_content`` que a coluna gerada
      ``search_vector`` deriva, e é sobre ele que a cobertura lexical é
      medida. Uma resegmentação ou uma mudança na normalização podem alterar
      esta coluna sem tocar no conteúdo original; sem este hash, o corpus
      mudaria de comportamento mantendo a mesma identidade.

    Ambos são **recalculados a partir das colunas vivas** pelo builder, e não
    lidos de ``document_chunks.content_sha256``: um hash persistido é uma
    afirmação sobre o conteúdo, não o conteúdo, e uma identidade científica não
    deve herdar uma afirmação possivelmente desatualizada.

    ``section_title`` e ``structure_type`` entram porque participam no ranking
    lexical — sobreposição com o título da secção e benefício condicionado de
    ``table_row``. ``page_number`` **não** entra: é transportado pelo candidato
    mas nunca lido por ``build_features``, não viaja em ``Evidence``, e qualquer
    mudança de paginação que altere a recuperação altera também o conteúdo dos
    segmentos, que já é identificado aqui.

    Nenhum texto entra: apenas hashes e metadados estruturais. O digest não pode
    tornar-se um canal para exfiltrar conteúdo documental.
    """

    chunk_index: int
    content_sha256: str
    normalized_content_sha256: str
    section_title: str | None
    structure_type: str | None

    def canonical(self) -> dict[str, Any]:
        return {
            "chunk_index": self.chunk_index,
            "content_sha256": self.content_sha256,
            "normalized_content_sha256": self.normalized_content_sha256,
            "section_title": self.section_title,
            "structure_type": self.structure_type,
        }


def compute_chunk_digest(chunks: tuple[ChunkIdentity, ...]) -> str:
    """Digest dos segmentos de uma versão, ordenados por ``chunk_index``.

    A ordenação é imposta aqui e não assumida da consulta: a ordem em que o
    PostgreSQL devolve linhas sem ``ORDER BY`` é acidental e não deve
    participar na identidade.
    """
    ordered = sorted(chunks, key=lambda chunk: chunk.chunk_index)
    return _digest([chunk.canonical() for chunk in ordered])


@dataclass(frozen=True)
class CorpusEntry:
    """Uma versão documental concreta que estava elegível.

    Todos os campos respondem afirmativamente a "se este valor mudar, pode
    alterar materialmente o resultado da recuperação?" — com uma exceção
    declarada, ``checksum_sha256``, que existe para provar **qual** ficheiro
    concreto compunha o corpus e permitir verificação posterior.

    ``document_title`` e ``source_url`` entram porque atravessam a experiência
    para lá da elegibilidade: o título é sinal de ranking (sobreposição com o
    título do documento) e **ambos** são enviados ao gerador dentro do payload
    de evidência (``app.answering.context.evidence_payload``). Dois corpora que
    diferissem apenas no URL apresentariam ao modelo um contexto diferente; uma
    identidade que os igualasse afirmaria uma comparabilidade que não existe.

    São metadados públicos do documento, do mesmo tipo que ``MessageSource`` já
    persiste como snapshot; não são dados pessoais.
    """

    document_id: UUID
    document_version_id: UUID
    document_title: str
    source_url: str | None
    language: str
    official_source: bool
    valid_from: date | None
    valid_until: date | None
    checksum_sha256: str
    chunk_count: int
    chunk_digest: str

    def canonical(self) -> dict[str, Any]:
        return {
            "document_id": str(self.document_id),
            "document_version_id": str(self.document_version_id),
            "document_title": self.document_title,
            "source_url": self.source_url,
            "language": self.language,
            "official_source": self.official_source,
            "valid_from": _date_value(self.valid_from),
            "valid_until": _date_value(self.valid_until),
            "checksum_sha256": self.checksum_sha256,
            "chunk_count": self.chunk_count,
            "chunk_digest": self.chunk_digest,
        }


def sort_corpus_entries(entries: tuple[CorpusEntry, ...]) -> tuple[CorpusEntry, ...]:
    """Ordem total e determinística, independente da consulta que as produziu.

    A chave é a forma canónica dos UUID, não o objeto: garante a mesma ordem
    entre processos e entre bases de dados.
    """
    return tuple(
        sorted(
            entries,
            key=lambda entry: (str(entry.document_id), str(entry.document_version_id)),
        )
    )


def canonical_corpus_payload(entries: tuple[CorpusEntry, ...]) -> dict[str, Any]:
    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "entries": [entry.canonical() for entry in sort_corpus_entries(entries)],
    }


def compute_corpus_digest(entries: tuple[CorpusEntry, ...]) -> str:
    """Identidade do corpus elegível, e de mais nada.

    Não inclui a data de referência nem a configuração de recuperação: é essa
    ausência que permite observar "o corpus é o mesmo" independentemente da
    experiência em que foi usado.
    """
    return _digest(canonical_corpus_payload(entries))


@dataclass(frozen=True)
class RetrievalConfiguration:
    """Os parâmetros que alteram materialmente a seleção ou a ordenação.

    Todos foram lidos da implementação real (``app.retrieval.lexical``,
    ``app.retrieval.reranking``, ``app.core.config``); nenhum é inventado, e não
    se acrescenta qualquer limiar novo.

    ``pipeline_version`` e ``scoring_version`` não são redundantes e a
    diferença importa: a segunda identifica apenas os pesos e o limiar do
    rerank — é assim que está declarada em ``app.retrieval.reranking`` —,
    enquanto a primeira cobre as etapas que decidem **o que chega a ser
    pontuado**: planeamento da consulta, normalização lexical, elegibilidade
    lexical e expressão de indexação FTS. Com apenas a versão do scoring, uma
    alteração ao planeamento mudaria os resultados mantendo o mesmo
    ``snapshot_id``.

    ``candidate_limit`` é o orçamento **já resolvido** por
    ``global_candidate_limit(top_k)``, e não as três constantes que o compõem:
    guardar o valor efetivo faz com que uma alteração dessas constantes mude a
    identidade mesmo com o mesmo ``top_k``, que é exatamente o que interessa.

    ``score_kind`` e ``comparable_across_queries`` registam a semântica
    declarada do score. O score lexical é **relevância**, não confiança nem
    probabilidade, e não é comparável entre perguntas diferentes; guardar essa
    declaração impede que uma leitura posterior o trate como confidence.
    """

    strategy: str
    pipeline_version: str
    scoring_version: str
    score_kind: str
    comparable_across_queries: bool
    language: str
    top_k: int
    official_only: bool
    fts_config: str
    min_relevance_score: float
    candidate_limit: int

    def canonical(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "pipeline_version": self.pipeline_version,
            "scoring_version": self.scoring_version,
            "score_kind": self.score_kind,
            "comparable_across_queries": self.comparable_across_queries,
            "language": self.language,
            "top_k": self.top_k,
            "official_only": self.official_only,
            "fts_config": self.fts_config,
            "min_relevance_score": self.min_relevance_score,
            "candidate_limit": self.candidate_limit,
        }


def canonical_snapshot_payload(
    *,
    institution_id: UUID,
    reference_date: date,
    corpus_digest: str,
    retrieval: RetrievalConfiguration,
) -> dict[str, Any]:
    """Payload de que deriva o ``snapshot_id``.

    Contém o **digest** do corpus, não as suas entradas: o corpus já tem
    identidade própria, e embuti-lo por inteiro tornaria o payload proporcional
    ao número de documentos sem acrescentar poder discriminante.
    """
    return {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "institution_id": str(institution_id),
        "reference_date": reference_date.isoformat(),
        "corpus_digest": corpus_digest,
        "retrieval": retrieval.canonical(),
    }


def compute_snapshot_id(
    *,
    institution_id: UUID,
    reference_date: date,
    corpus_digest: str,
    retrieval: RetrievalConfiguration,
) -> str:
    return _digest(
        canonical_snapshot_payload(
            institution_id=institution_id,
            reference_date=reference_date,
            corpus_digest=corpus_digest,
            retrieval=retrieval,
        )
    )


@dataclass(frozen=True)
class EvaluationSnapshot:
    """O contexto experimental como **valor** imutável e serializável.

    ``reference_date`` participa sempre na identidade, mesmo quando não altera
    o corpus observado. É uma decisão consciente: a data é uma variável
    experimental declarada, não um detalhe de execução. Duas medições feitas
    com datas de referência diferentes não são a mesma experiência — a
    coincidência dos corpora é contingente e deixaria de valer noutra data,
    tornando o resultado irreprodutível. Quem precisar de saber se o corpus
    coincidiu compara ``corpus_digest``, que deliberadamente **não** inclui a
    data.
    """

    schema_version: str
    snapshot_id: str
    institution_id: UUID
    reference_date: date
    corpus_digest: str
    corpus: tuple[CorpusEntry, ...]
    retrieval: RetrievalConfiguration

    def as_payload(self) -> dict[str, Any]:
        """Forma serializável completa, para versionar como artefacto.

        Inclui as entradas do corpus, ao contrário do payload de que o
        ``snapshot_id`` deriva: um artefacto tem de ser auditável por quem o lê,
        não apenas verificável por quem recalcula o digest.
        """
        return {
            "schema_version": self.schema_version,
            "snapshot_id": self.snapshot_id,
            "digest_algorithm": DIGEST_ALGORITHM,
            "institution_id": str(self.institution_id),
            "reference_date": self.reference_date.isoformat(),
            "corpus_digest": self.corpus_digest,
            "corpus": canonical_corpus_payload(self.corpus)["entries"],
            "retrieval": self.retrieval.canonical(),
        }


def build_snapshot(
    *,
    institution_id: UUID,
    reference_date: date,
    entries: tuple[CorpusEntry, ...],
    retrieval: RetrievalConfiguration,
) -> EvaluationSnapshot:
    """Monta o snapshot e deriva as duas identidades. Puro: sem base de dados."""
    ordered = sort_corpus_entries(entries)
    corpus_digest = compute_corpus_digest(ordered)
    snapshot_id = compute_snapshot_id(
        institution_id=institution_id,
        reference_date=reference_date,
        corpus_digest=corpus_digest,
        retrieval=retrieval,
    )
    return EvaluationSnapshot(
        schema_version=SNAPSHOT_SCHEMA_VERSION,
        snapshot_id=snapshot_id,
        institution_id=institution_id,
        reference_date=reference_date,
        corpus_digest=corpus_digest,
        corpus=ordered,
        retrieval=retrieval,
    )
