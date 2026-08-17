"""Modelos de embeddings substituíveis (experimental, D4.8).

O pacote reexporta apenas contratos **neutros**. ``get_embedding_model`` fica
deliberadamente de fora, pela mesma razão que em :mod:`app.answering`: importar
os contratos não deve carregar o SDK de fornecedor nenhum. Quem precisa da
factory importa-a de :mod:`app.embeddings.dependencies`.
"""

from app.embeddings.base import (
    EMBEDDING_MODEL_UNAVAILABLE_MESSAGE,
    EmbeddingError,
    EmbeddingIdentity,
    EmbeddingModel,
    EmbeddingModelUnavailableError,
)

__all__ = [
    "EMBEDDING_MODEL_UNAVAILABLE_MESSAGE",
    "EmbeddingError",
    "EmbeddingIdentity",
    "EmbeddingModel",
    "EmbeddingModelUnavailableError",
]
