"""Adapter OpenAI do contrato AnswerGenerator.

Todo o conhecimento do fornecedor (SDK, modelo, chave, formato de
resposta) vive aqui. O resto do backend só conhece AnsweringContext,
GeneratedAnswer e as exceções internas tipadas.

Segurança e privacidade:
- a chave nunca aparece em logs, exceções ou respostas;
- as exceções do SDK nunca atravessam este módulo — são convertidas em
  AnswerGenerationError com mensagem curta e fixa;
- nos logs ficam apenas dados operacionais (modelo não; tipo de erro sim);
  nunca o contexto documental completo nem a resposta bruta integral.
"""

import json
import logging
from typing import Any

import openai

from app.answering.base import (
    GENERATOR_UNAVAILABLE_MESSAGE,
    AnswerGenerationError,
    AnswerGeneratorUnavailableError,
    AnsweringContext,
    GeneratedAnswer,
)
from app.answering.prompts import build_prompts
from app.core.config import settings

logger = logging.getLogger(__name__)

# A mensagem de indisponibilidade é partilhada com a factory e vive em
# base.py; a de falha de geração é específica de uma chamada ao
# fornecedor e fica aqui.
GENERATION_FAILED_MESSAGE = "The answer generator failed to produce a usable response."

# Resposta estruturada: o modelo devolve exatamente {answer,
# cited_evidence_ids}. O parsing continua defensivo — nunca se confia
# cegamente no output do fornecedor.
_RESPONSE_FORMAT: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "grounded_answer",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "answer": {"type": "string"},
                "cited_evidence_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": ["answer", "cited_evidence_ids"],
            "additionalProperties": False,
        },
    },
}


class OpenAIAnswerGenerator:
    """Gerador experimental baseado no SDK oficial da OpenAI."""

    def __init__(self, client: Any | None = None) -> None:
        # A injeção de um cliente pré-construído existe para os testes
        # (nunca há chamadas reais no CI); em produção o cliente é criado
        # na primeira geração, para que a aplicação arranque sem chave.
        self._client = client

    def generate(self, context: AnsweringContext) -> GeneratedAnswer:
        model = settings.openai_model
        if not model:
            raise AnswerGeneratorUnavailableError(GENERATOR_UNAVAILABLE_MESSAGE)
        client = self._client if self._client is not None else self._build_client()

        system_prompt, user_prompt = build_prompts(context)
        try:
            completion = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_format=_RESPONSE_FORMAT,
            )
        except openai.OpenAIError as exc:
            # Erro externo não confiável: regista-se APENAS o tipo (nunca a
            # mensagem, traceback, request, headers ou resposta do SDK —
            # podem conter a chave, a pergunta ou conteúdo documental).
            # `from None` impede a exceção original de reaparecer num
            # traceback superior. Sem retry próprio: falha uma vez,
            # responde 502 uma vez.
            logger.error(
                "Answer provider request failed: error_type=%s",
                type(exc).__name__,
            )
            raise AnswerGenerationError(GENERATION_FAILED_MESSAGE) from None
        except Exception as exc:
            # Também pode embrulhar dados do pedido (ex.: erros de httpx),
            # por isso recebe a mesma sanitização dos erros do fornecedor.
            logger.error(
                "Answer provider request failed unexpectedly: error_type=%s",
                type(exc).__name__,
            )
            raise AnswerGenerationError(GENERATION_FAILED_MESSAGE) from None

        return _parse_completion(completion)

    def _build_client(self) -> Any:
        api_key = settings.openai_api_key
        if not api_key:
            raise AnswerGeneratorUnavailableError(GENERATOR_UNAVAILABLE_MESSAGE)
        # Política explícita de retries: zero. O default do SDK (2 retries
        # implícitos) tornaria a latência imprevisível e contradiria o
        # comportamento documentado; qualquer retry futuro será decidido
        # na aplicação, não herdado do SDK.
        return openai.OpenAI(
            api_key=api_key,
            timeout=settings.openai_timeout_seconds,
            max_retries=0,
        )


def _parse_completion(completion: Any) -> GeneratedAnswer:
    """Extrai GeneratedAnswer defensivamente da resposta do fornecedor."""
    try:
        content = completion.choices[0].message.content
    except (AttributeError, IndexError, TypeError):
        logger.error("Resposta do fornecedor sem o formato esperado (sem choices)")
        raise AnswerGenerationError(GENERATION_FAILED_MESSAGE) from None

    if not content or not isinstance(content, str):
        logger.error("Resposta do fornecedor sem conteúdo utilizável")
        raise AnswerGenerationError(GENERATION_FAILED_MESSAGE)

    try:
        payload = json.loads(content)
    except ValueError:
        logger.error("Resposta do fornecedor não é JSON válido")
        raise AnswerGenerationError(GENERATION_FAILED_MESSAGE) from None

    answer = payload.get("answer") if isinstance(payload, dict) else None
    cited = payload.get("cited_evidence_ids") if isinstance(payload, dict) else None
    if not isinstance(answer, str) or not isinstance(cited, list):
        logger.error("Resposta do fornecedor sem os campos estruturados esperados")
        raise AnswerGenerationError(GENERATION_FAILED_MESSAGE)
    if not all(isinstance(evidence_id, str) for evidence_id in cited):
        logger.error("Resposta do fornecedor com evidence ids de tipo inválido")
        raise AnswerGenerationError(GENERATION_FAILED_MESSAGE)

    return GeneratedAnswer(answer=answer, cited_evidence_ids=tuple(cited))
