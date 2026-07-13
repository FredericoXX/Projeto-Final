"""Geração experimental de respostas fundamentadas em evidências."""

from app.answering.base import (
    AnswerGenerationError,
    AnswerGenerator,
    AnswerGeneratorUnavailableError,
    AnsweringContext,
    ContextEvidence,
    GeneratedAnswer,
    InvalidGeneratedAnswerError,
)
from app.answering.dependencies import get_answer_generator

__all__ = [
    "AnswerGenerationError",
    "AnswerGenerator",
    "AnswerGeneratorUnavailableError",
    "AnsweringContext",
    "ContextEvidence",
    "GeneratedAnswer",
    "InvalidGeneratedAnswerError",
    "get_answer_generator",
]
