"""Factory FastAPI do gerador de respostas ativo."""

from app.answering.base import AnswerGenerator, AnswerGeneratorUnavailableError
from app.answering.providers.openai import (
    GENERATOR_UNAVAILABLE_MESSAGE,
    OpenAIAnswerGenerator,
)
from app.core.config import settings


def get_answer_generator() -> AnswerGenerator:
    """Devolve o gerador configurado sem acoplar rota/service à classe.

    Um provider desconhecido só falha aqui, quando a geração é pedida
    (503) — nunca no arranque da aplicação.
    """
    if settings.answer_generator_provider == "openai":
        return OpenAIAnswerGenerator()
    raise AnswerGeneratorUnavailableError(GENERATOR_UNAVAILABLE_MESSAGE)
