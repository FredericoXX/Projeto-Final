"""Vetores das perguntas congelados, como modelo de embeddings (D4.8.2a).

Módulo puro no sentido que importa aqui: não contacta fornecedor nenhum e não
lê ficheiros. Recebe vetores já lidos e serve-os.

Porque é que isto é um ``EmbeddingModel`` e não um retriever novo
-----------------------------------------------------------------

A experiência precisa de que a recuperação densa corra **sem** pedir embeddings
ao fornecedor a cada execução: a D4.8.1 mediu que o mesmo texto produz vetores
diferentes entre chamadas, e uma decisão de admissão que dependa da terceira
casa decimal de uma similaridade não pode assentar nisso.

A tentação seria escrever um retriever denso paralelo que aceitasse um vetor. A
consequência seria ter **duas** implementações da mesma consulta, e a
experiência deixaria de medir o retriever que a D4.8.1 mediu. Em vez disso,
congela-se do lado do **modelo**: :class:`FrozenQuestionEmbeddings` satisfaz o
protocolo ``EmbeddingModel``, e ``PostgresDenseRetriever`` corre exatamente como
corre em qualquer outra fase, sem uma linha alterada.

O efeito colateral é a guarda mais forte desta fase: como a procura é feita pelo
**texto** que o retriever pede para embeber, um vetor congelado só pode ser
usado com a pergunta de que foi derivado. Alterar a pergunta sem reembeber não
produz um resultado errado — produz um erro.
"""

import hashlib
import struct
from collections.abc import Mapping, Sequence
from typing import Any, Final

from app.embeddings.base import EmbeddingError, EmbeddingIdentity
from app.evaluation.dense_admission import frozen_vectors_digest

#: Campos obrigatórios de cada vetor persistido. Um vetor a que falte qualquer
#: um deles não é utilizável: não se sabe o que ele representa.
REQUIRED_FIELDS: Final = (
    "question_id",
    "content_sha256",
    "provider",
    "model",
    "dimension",
    "normalization",
    "similarity_metric",
    "configuration_version",
    "vector_digest",
    "vector",
)


class FrozenVectorError(RuntimeError):
    """O conjunto de vetores congelados não descreve o que diz descrever."""


def content_sha256(text: str) -> str:
    """SHA-256 do texto efetivamente enviado ao modelo.

    Mesma definição que ``scripts.embed_pilot_corpus.content_digest`` usa para
    os segmentos. É deliberado que sejam a mesma: as duas respondem à pergunta
    «que texto produziu este vetor?», e defini-las de maneiras diferentes faria
    com que a resposta dependesse de quem pergunta.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def vector_digest(vector: Sequence[float]) -> str:
    """SHA-256 dos componentes na representação binária de 32 bits.

    Igual à do índice de segmentos, e pela mesma razão: é a forma exata do que o
    pgvector guarda, e é o que torna detetável a deriva entre duas chamadas ao
    fornecedor com o mesmo texto.
    """
    return hashlib.sha256(struct.pack(f"<{len(vector)}f", *vector)).hexdigest()


def verify_frozen_vectors(
    vectors: Sequence[Mapping[str, Any]],
    questions: Sequence[Mapping[str, Any]],
    identity: EmbeddingIdentity,
) -> tuple[str, ...]:
    """As dez guardas do §12, todas, antes de qualquer medição.

    Devolve a lista de problemas em vez de levantar: quem chama decide se para,
    e o artefacto pode registar exatamente o que falhou. Nenhuma delas é
    redundante:

    - **campos e identidade** apanham o vetor de outro modelo ou de outra
      configuração, que é comparável em dimensão e incomparável em significado;
    - **``content_sha256``** apanha a pergunta editada depois de embebida — o
      caso em que tudo parece bem e o vetor descreve outro texto;
    - **``vector_digest``** apanha o vetor alterado depois de persistido;
    - **cobertura** apanha a pergunta sem vetor, que de outro modo apareceria
      como falha de recuperação;
    - **homogeneidade** apanha o conjunto misto, onde metade dos vetores é de
      uma configuração e metade de outra.
    """
    problems: list[str] = []

    by_id: dict[str, Mapping[str, Any]] = {}
    for entry in vectors:
        for field in REQUIRED_FIELDS:
            if field not in entry:
                problems.append(f"a frozen vector is missing {field!r}")
                break
        else:
            question_id = str(entry["question_id"])
            if question_id in by_id:
                problems.append(f"{question_id}: duplicate frozen vector")
            by_id[question_id] = entry

    identities = {
        (
            entry.get("provider"),
            entry.get("model"),
            entry.get("dimension"),
            entry.get("normalization"),
            entry.get("similarity_metric"),
            entry.get("configuration_version"),
        )
        for entry in vectors
    }
    if len(identities) > 1:
        problems.append(
            f"the frozen vectors mix {len(identities)} embedding identities"
        )

    declared = (
        identity.provider,
        identity.model,
        identity.dimension,
        identity.normalization,
        identity.similarity_metric,
        identity.configuration_version,
    )
    for entry in vectors:
        question_id = entry.get("question_id", "?")
        found = (
            entry.get("provider"),
            entry.get("model"),
            entry.get("dimension"),
            entry.get("normalization"),
            entry.get("similarity_metric"),
            entry.get("configuration_version"),
        )
        if found != declared:
            problems.append(
                f"{question_id}: embedding identity {found} != declared {declared}"
            )
            continue
        vector = entry.get("vector") or []
        if len(vector) != identity.dimension:
            problems.append(
                f"{question_id}: vector has {len(vector)} components, "
                f"declared dimension is {identity.dimension}"
            )
            continue
        if vector_digest(vector) != entry.get("vector_digest"):
            problems.append(f"{question_id}: vector_digest does not match the vector")

    for question in questions:
        question_id = str(question["question_id"])
        frozen = by_id.get(question_id)
        if frozen is None:
            problems.append(f"{question_id}: no frozen vector")
            continue
        if frozen.get("content_sha256") != content_sha256(str(question["question"])):
            problems.append(
                f"{question_id}: content_sha256 does not match the current question text"
            )

    return tuple(problems)


def verify_frozen_vector_artefact(
    payload: Mapping[str, Any],
    questions: Sequence[Mapping[str, Any]],
    identity: EmbeddingIdentity,
    *,
    digest_field: str = "frozen_vectors_digest",
    expected_digest: str | None = None,
) -> tuple[str, ...]:
    """Verifica componentes e o compromisso do conjunto antes de o consumir.

    As guardas por vetor nao bastam: quem adultera um componente pode recalcular
    tambem o respetivo ``vector_digest``. O digest do conjunto e a ancora externa
    que torna essa alteracao detetavel. Para uma projecao (por exemplo, DEV), o
    chamador indica o campo que compromete exatamente o subconjunto persistido.
    """
    vectors = payload.get("vectors")
    if not isinstance(vectors, list):
        return ("the frozen-vector artefact has no vectors list",)

    problems = list(verify_frozen_vectors(vectors, questions, identity))
    try:
        recomputed = frozen_vectors_digest(vectors)
    except KeyError as error:
        problems.append(f"the frozen-vector set cannot be digested: missing {error}")
        return tuple(problems)

    declared = payload.get(digest_field)
    if declared != recomputed:
        problems.append(
            f"{digest_field} does not match the frozen-vector set: "
            f"artefact {declared} != recomputed {recomputed}"
        )
    if expected_digest is not None and recomputed != expected_digest:
        problems.append(
            f"the frozen-vector set does not match the sealed digest: "
            f"recomputed {recomputed} != sealed {expected_digest}"
        )
    return tuple(problems)


class FrozenQuestionEmbeddings:
    """``EmbeddingModel`` que só sabe devolver vetores que já existem.

    A procura é feita pelo **SHA-256 do texto**, e não pelo ``question_id``: o
    retriever pede o embedding de uma string, não de um identificador, e é essa
    string que tem de corresponder. Um texto desconhecido levanta
    :class:`~app.embeddings.base.EmbeddingError` em vez de contactar o
    fornecedor — que é o comportamento que torna impossível uma execução
    experimental introduzir um vetor novo sem que se note.
    """

    def __init__(
        self, vectors: Sequence[Mapping[str, Any]], identity: EmbeddingIdentity
    ) -> None:
        self._identity = identity
        self._by_content: dict[str, tuple[float, ...]] = {}
        for entry in vectors:
            digest = str(entry["content_sha256"])
            self._by_content[digest] = tuple(float(v) for v in entry["vector"])

    @property
    def identity(self) -> EmbeddingIdentity:
        return self._identity

    def embed(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        vectors: list[tuple[float, ...]] = []
        for text in texts:
            digest = content_sha256(text)
            vector = self._by_content.get(digest)
            if vector is None:
                msg = (
                    "no frozen vector for the requested text; the experiment would "
                    "have to call the provider, and the decision would stop being "
                    "the one that was frozen"
                )
                raise EmbeddingError(msg)
            vectors.append(vector)
        return tuple(vectors)
