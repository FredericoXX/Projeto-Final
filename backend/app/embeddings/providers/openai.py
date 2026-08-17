"""Adapter OpenAI do contrato :class:`~app.embeddings.base.EmbeddingModel`.

Todo o conhecimento do fornecedor — SDK, nome do modelo, chave, formato de
codificação, tamanho do lote — vive aqui. O retrieval denso só conhece
``EmbeddingModel`` e ``EmbeddingIdentity``.

Segurança e privacidade, nas mesmas regras do adapter de geração:

- a chave nunca aparece em logs, exceções ou respostas;
- as exceções do SDK nunca atravessam este módulo;
- os logs registam contagens e o tipo do erro, nunca o texto enviado.

Porque existe uma tabela de dimensões conhecidas
------------------------------------------------

``identity`` tem de estar disponível **antes** da primeira chamada — é ela que
diz à indexação qual a largura da coluna a escrever. Um modelo desconhecido não
tem dimensão declarável, e adivinhá-la produziria uma identidade falsa ou uma
falha tardia a meio da indexação. Por isso um modelo fora da tabela é recusado
na construção, e a dimensão de **cada** vetor recebido é verificada contra a
declarada: um fornecedor que mude a largura do modelo passa a falhar em vez de
contaminar silenciosamente o índice.
"""

import logging
from collections.abc import Mapping, Sequence
from typing import Any, Final

import openai

from app.core.config import settings
from app.embeddings.base import (
    EMBEDDING_MODEL_UNAVAILABLE_MESSAGE,
    EmbeddingError,
    EmbeddingIdentity,
    EmbeddingModelUnavailableError,
)

logger = logging.getLogger(__name__)

PROVIDER_NAME: Final = "openai"

EMBEDDING_FAILED_MESSAGE: Final = "The embedding model failed to produce usable vectors."

#: Modelos cuja dimensão é conhecida e fixa. Não é uma allowlist de segurança:
#: é o que permite declarar :class:`EmbeddingIdentity` antes de embeber o
#: primeiro texto. Acrescentar um modelo é acrescentar uma linha aqui.
KNOWN_MODEL_DIMENSIONS: Final[Mapping[str, int]] = {
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
}

#: Identidade da configuração deste adapter, para lá do nome do modelo: pedido
#: sem parâmetro ``dimensions`` (o modelo devolve a largura nativa), codificação
#: em vírgula flutuante e texto enviado tal como recebido, sem truncagem nem
#: pré-processamento. Subir esta versão é obrigatório se algum destes pontos
#: mudar.
CONFIGURATION_VERSION: Final = "openai_embeddings_v1"

#: A aplicação não normaliza o vetor recebido — ver ``EmbeddingIdentity``.
NORMALIZATION: Final = "none"

#: Métrica sob a qual estes vetores devem ser comparados.
SIMILARITY_METRIC: Final = "cosine"

#: Textos por pedido. Bem abaixo do limite do fornecedor: o objetivo é limitar
#: o tamanho de cada resposta e o custo de uma falha, não maximizar o débito.
BATCH_SIZE: Final = 128


class OpenAIEmbeddingModel:
    """Modelo de embeddings experimental baseado no SDK oficial da OpenAI."""

    def __init__(self, model: str | None = None, client: Any | None = None) -> None:
        """Resolve o modelo na construção, e não a cada chamada.

        Ao contrário do gerador de respostas, aqui a identidade tem de existir
        antes de haver vetores — a indexação precisa dela para saber o que
        escreve. Um modelo em falta ou desconhecido falha já, com o erro de
        indisponibilidade, e nunca a meio de uma indexação.

        A injeção de ``client`` existe para os testes: no CI nunca há chamadas
        reais ao fornecedor.
        """
        resolved = model or settings.openai_embedding_model
        if not resolved or resolved not in KNOWN_MODEL_DIMENSIONS:
            raise EmbeddingModelUnavailableError(EMBEDDING_MODEL_UNAVAILABLE_MESSAGE)
        self._model = resolved
        self._client = client
        self._identity = EmbeddingIdentity(
            provider=PROVIDER_NAME,
            model=resolved,
            dimension=KNOWN_MODEL_DIMENSIONS[resolved],
            normalization=NORMALIZATION,
            similarity_metric=SIMILARITY_METRIC,
            configuration_version=CONFIGURATION_VERSION,
        )

    @property
    def identity(self) -> EmbeddingIdentity:
        return self._identity

    def embed(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        """Embebe os textos em lotes, preservando a ordem de entrada."""
        if not texts:
            return ()
        client = self._client if self._client is not None else self._build_client()

        vectors: list[tuple[float, ...]] = []
        for start in range(0, len(texts), BATCH_SIZE):
            batch = list(texts[start : start + BATCH_SIZE])
            vectors.extend(self._embed_batch(client, batch))
        return tuple(vectors)

    def _embed_batch(
        self, client: Any, batch: Sequence[str]
    ) -> tuple[tuple[float, ...], ...]:
        try:
            response = client.embeddings.create(
                model=self._model,
                input=list(batch),
                encoding_format="float",
            )
        except openai.OpenAIError as exc:
            # Só o tipo do erro é registado: a mensagem do SDK pode transportar
            # a chave, o pedido ou o próprio texto institucional enviado.
            logger.error(
                "Embedding provider request failed: error_type=%s batch_size=%d",
                type(exc).__name__,
                len(batch),
            )
            raise EmbeddingError(EMBEDDING_FAILED_MESSAGE) from None
        except Exception as exc:
            logger.error(
                "Embedding provider request failed unexpectedly: error_type=%s "
                "batch_size=%d",
                type(exc).__name__,
                len(batch),
            )
            raise EmbeddingError(EMBEDDING_FAILED_MESSAGE) from None

        return self._parse_response(response, expected=len(batch))

    def _parse_response(
        self, response: Any, *, expected: int
    ) -> tuple[tuple[float, ...], ...]:
        """Extrai os vetores defensivamente, sem confiar na ordem da resposta.

        A API devolve cada item com o seu ``index``, e é por ele que os vetores
        são reordenados. Assumir a ordem de chegada acoplaria a correspondência
        texto ↔ vetor a um detalhe que o contrato do fornecedor não promete — e
        uma troca silenciosa produziria um índice plausível e errado.
        """
        try:
            items = list(response.data)
        except (AttributeError, TypeError):
            logger.error("Resposta do fornecedor de embeddings sem o campo data")
            raise EmbeddingError(EMBEDDING_FAILED_MESSAGE) from None

        if len(items) != expected:
            logger.error(
                "Resposta do fornecedor com número inesperado de vetores: "
                "esperados=%d recebidos=%d",
                expected,
                len(items),
            )
            raise EmbeddingError(EMBEDDING_FAILED_MESSAGE)

        by_index: dict[int, tuple[float, ...]] = {}
        for item in items:
            index = getattr(item, "index", None)
            raw = getattr(item, "embedding", None)
            if not isinstance(index, int) or not isinstance(raw, list):
                logger.error("Item de embedding sem index inteiro ou sem vetor")
                raise EmbeddingError(EMBEDDING_FAILED_MESSAGE)
            if len(raw) != self._identity.dimension:
                logger.error(
                    "Vetor com dimensão inesperada: declarada=%d recebida=%d",
                    self._identity.dimension,
                    len(raw),
                )
                raise EmbeddingError(EMBEDDING_FAILED_MESSAGE)
            if not all(isinstance(value, (int, float)) for value in raw):
                logger.error("Vetor com componente não numérica")
                raise EmbeddingError(EMBEDDING_FAILED_MESSAGE)
            by_index[index] = tuple(float(value) for value in raw)

        if sorted(by_index) != list(range(expected)):
            logger.error("Resposta do fornecedor com índices em falta ou repetidos")
            raise EmbeddingError(EMBEDDING_FAILED_MESSAGE)

        return tuple(by_index[index] for index in range(expected))

    def _build_client(self) -> Any:
        api_key = settings.openai_api_key
        if not api_key:
            raise EmbeddingModelUnavailableError(EMBEDDING_MODEL_UNAVAILABLE_MESSAGE)
        # Mesma política explícita do adapter de geração: zero retries herdados
        # do SDK. Uma indexação que falhe deve falhar de forma observável.
        return openai.OpenAI(
            api_key=api_key,
            timeout=settings.openai_timeout_seconds,
            max_retries=0,
        )
