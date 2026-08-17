"""Contratos neutros para modelos de embeddings substituíveis.

Espelham deliberadamente a forma de :mod:`app.answering.base`: um ``Protocol``
estrutural, um dataclass de identidade e erros próprios, sem qualquer SDK.
Nenhum nome aqui menciona fornecedor, chave, custo ou latência.

Porque existe uma identidade explícita
--------------------------------------

Um vetor não diz de onde veio. Dois modelos diferentes produzem vetores da
mesma dimensão que **não são comparáveis**, e uma alteração silenciosa de modelo
transformaria uma experiência reprodutível numa comparação entre coisas
distintas sem que nada falhasse. :class:`EmbeddingIdentity` viaja com os vetores
até ao artefacto experimental e até à base, para que a incomparabilidade seja
detetável em vez de presumida.

``configuration_version`` cobre o que o nome do modelo não cobre — dimensão
pedida, formato de codificação, pré-processamento do texto. Subir esta versão é
obrigatório quando qualquer um desses aspetos muda, mesmo que o modelo seja o
mesmo.

O que este contrato não é
-------------------------

Não é um contrato de recuperação. Não sabe o que é um chunk, uma instituição ou
uma pergunta: recebe texto e devolve vetores. A política de admissibilidade
documental, o corte por ``top_k`` e a interpretação do score vivem em
:mod:`app.retrieval.dense`, que é quem os conhece.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from app.core.exceptions import ServiceUnavailableError, UpstreamServiceError

#: Mensagem devolvida quando não há modelo de embeddings utilizável. Não nomeia
#: fornecedor nem revela que configuração falta.
EMBEDDING_MODEL_UNAVAILABLE_MESSAGE = "Embedding model is not configured on this server."


class EmbeddingModelUnavailableError(ServiceUnavailableError):
    """Não existe modelo de embeddings configurado ou utilizável."""


class EmbeddingError(UpstreamServiceError):
    """O modelo foi contactado e não produziu vetores utilizáveis.

    A mensagem é curta e não transporta o texto enviado, a chave nem o tipo
    de exceção do SDK — as mesmas regras que valem para a geração de respostas.
    """


@dataclass(frozen=True)
class EmbeddingIdentity:
    """Identidade completa da configuração que produziu um conjunto de vetores.

    ``normalization`` descreve o que a **aplicação** faz ao vetor recebido, não
    o que o fornecedor faz internamente: ``"none"`` significa que o vetor é
    persistido tal como chegou. Isto não é uma omissão — a similaridade do
    cosseno é invariante à escala, pelo que normalizar ou não normalizar produz
    exatamente a mesma ordenação. Declarar ``"l2_unit"`` sem que a aplicação
    normalize seria uma afirmação falsa sobre os dados guardados.

    ``similarity_metric`` é parte da identidade porque a mesma família de
    vetores admite métricas diferentes, e trocá-la muda os vizinhos devolvidos
    sem mudar um único vetor.
    """

    provider: str
    model: str
    dimension: int
    normalization: str
    similarity_metric: str
    configuration_version: str

    def __post_init__(self) -> None:
        if self.dimension <= 0:
            msg = f"dimension must be positive, got {self.dimension}"
            raise ValueError(msg)


class EmbeddingModel(Protocol):
    """Produz vetores a partir de texto.

    ``embed`` recebe uma sequência e devolve uma tupla da **mesma dimensão e
    pela mesma ordem**. A API é em lote porque a alternativa — um texto de cada
    vez — obrigaria cada consumidor a inventar o seu próprio agrupamento, e o
    agrupamento é matéria do adaptador, que conhece os limites do fornecedor.

    Devolver tuplas, e não listas, é deliberado: um vetor persistido não deve
    poder ser alterado por engano a jusante da sua produção.
    """

    @property
    def identity(self) -> EmbeddingIdentity: ...

    def embed(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]: ...
