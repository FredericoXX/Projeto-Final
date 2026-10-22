"""Adapter OpenAI do modelo das condições B1 (avaliação offline).

Isolado como os restantes adaptadores: o SDK só é importado aqui, e este
módulo só é importado pelo executor. Uma falha ou uma saída inválida é falha
técnica (``EstimationError``), nunca uma ação.
"""

import json
from typing import Any

import openai

from app.core.config import settings
from app.decision.estimators.base import EstimationError, EstimatorUnavailableError
from app.evaluation.policy_v1.conditions import BaselineResponse

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["answer", "clarify", "abstain", "escalate"]},
        "message": {"type": "string"},
        "cited_evidence_ids": {"type": "array", "items": {"type": "string"}},
        "destination_service_id": {"type": ["string", "null"]},
        "dimensions": {"type": ["object", "null"], "additionalProperties": True},
    },
    "required": [
        "action",
        "message",
        "cited_evidence_ids",
        "destination_service_id",
        "dimensions",
    ],
    "additionalProperties": False,
}


class OpenAIBaselineModel:
    def __init__(self, client: Any | None = None) -> None:
        self._client = client

    def respond(self, system_prompt: str, user_prompt: str) -> BaselineResponse:
        model = settings.decision_estimator_model or settings.openai_model
        if not model:
            raise EstimatorUnavailableError("Baseline model is not configured.")
        client = self._client
        if client is None:
            if not settings.openai_api_key:
                raise EstimatorUnavailableError("Baseline model is not configured.")
            client = openai.OpenAI(
                api_key=settings.openai_api_key,
                timeout=settings.decision_estimator_timeout_seconds,
                max_retries=0,
            )
        try:
            completion = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {"name": "b1_decision", "strict": False, "schema": _SCHEMA},
                },
            )
            content = completion.choices[0].message.content
            if not isinstance(content, str):
                raise EstimationError("invalid_output")
            payload = json.loads(content)
            usage = getattr(completion, "usage", None)
            input_tokens = getattr(usage, "prompt_tokens", None)
            output_tokens = getattr(usage, "completion_tokens", None)
            return BaselineResponse(
                action=str(payload["action"]),
                message=str(payload["message"]),
                cited_evidence_ids=tuple(str(item) for item in payload["cited_evidence_ids"]),
                destination_service_id=payload["destination_service_id"],
                dimensions=payload.get("dimensions"),
                usage={"input_tokens": input_tokens, "output_tokens": output_tokens}
                if isinstance(input_tokens, int) and isinstance(output_tokens, int)
                else None,
            )
        except openai.APITimeoutError:
            raise EstimationError("timeout") from None
        except openai.OpenAIError:
            raise EstimationError("provider_error") from None
        except (KeyError, TypeError, ValueError, IndexError, AttributeError):
            raise EstimationError("invalid_output") from None
