"""Factory do modelo de embeddings ativo.

Não é uma dependência FastAPI: nenhuma rota usa embeddings nesta fase. Existe
para que os scripts de indexação e de avaliação resolvam o modelo pelo mesmo
caminho, em vez de cada um construir o adapter à sua maneira.
"""

from app.core.config import settings
from app.embeddings.base import (
    EMBEDDING_MODEL_UNAVAILABLE_MESSAGE,
    EmbeddingModel,
    EmbeddingModelUnavailableError,
)


def get_embedding_model(model: str | None = None) -> EmbeddingModel:
    """Devolve o modelo configurado sem acoplar os consumidores à sua classe.

    O adapter é importado **dentro** do ramo que o instancia, pela mesma razão
    fixada na A6.1 para a geração de respostas: configurar outro fornecedor —
    ou nenhum — não deve pagar o custo de carregar um SDK que nunca será usado.

    ``model`` permite fixar explicitamente o modelo em vez de o ler do ambiente.
    Não é uma conveniência: uma experiência cujo modelo dependa de uma variável
    de ambiente local não é reproduzível a partir do repositório, e a diferença
    entre dois modelos não seria visível em lado nenhum. Quem indexa e quem
    avalia passam o mesmo valor, e é esse que fica registado no artefacto.
    """
    if settings.embedding_provider == "openai":
        from app.embeddings.providers.openai import OpenAIEmbeddingModel

        return OpenAIEmbeddingModel(model=model)
    raise EmbeddingModelUnavailableError(EMBEDDING_MODEL_UNAVAILABLE_MESSAGE)
