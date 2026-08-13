"""Geração experimental de respostas fundamentadas em evidências.

O pacote reexporta apenas contratos **neutros**. `get_answer_generator`
fica deliberadamente de fora para separar a API pública de contratos da
composition root. O carregamento tardio do adapter é garantido pela factory;
quem precisa dela importa-a de `app.answering.dependencies`.
"""

from app.answering.base import (
    AnswerGenerationError,
    AnswerGenerator,
    AnswerGeneratorUnavailableError,
    AnsweringContext,
    ContextEvidence,
    GeneratedAnswer,
    InvalidGeneratedAnswerError,
)

__all__ = [
    "AnswerGenerationError",
    "AnswerGenerator",
    "AnswerGeneratorUnavailableError",
    "AnsweringContext",
    "ContextEvidence",
    "GeneratedAnswer",
    "InvalidGeneratedAnswerError",
]
