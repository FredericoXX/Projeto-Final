"""Factory FastAPI do gerador de respostas ativo."""

from app.answering.base import (
    GENERATOR_UNAVAILABLE_MESSAGE,
    AnswerGenerator,
    AnswerGeneratorUnavailableError,
)
from app.core.config import settings


def get_answer_generator() -> AnswerGenerator:
    """Devolve o gerador configurado sem acoplar rota/service à classe.

    Um provider desconhecido só falha aqui, quando a geração é pedida
    (503) — nunca no arranque da aplicação.

    O adapter é importado **dentro** do ramo que o instancia, e não no
    topo do módulo: assim o SDK do fornecedor só é carregado quando esse
    fornecedor é efetivamente resolvido. Com o import no topo, configurar
    outro provider — ou nenhum — continuaria a pagar o custo de importar
    o SDK da OpenAI, e nem os contratos neutros de `base.py` eram
    importáveis sem ele. É uma exceção deliberada ao estilo do
    repositório, fixada por teste.
    """
    if settings.answer_generator_provider == "openai":
        from app.answering.providers.openai import OpenAIAnswerGenerator

        return OpenAIAnswerGenerator()
    raise AnswerGeneratorUnavailableError(GENERATOR_UNAVAILABLE_MESSAGE)
