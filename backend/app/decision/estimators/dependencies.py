"""Factory FastAPI do estimador de dimensões ativo.

Como :func:`app.answering.dependencies.get_answer_generator`: o adaptador é
importado **dentro** do ramo que o instancia, para que resolver outro
fornecedor — ou nenhum — não carregue o SDK. Um fornecedor não configurado só
falha aqui, quando a estimação é pedida (503), nunca no arranque.
"""

from app.core.config import settings
from app.decision.estimators.base import (
    ESTIMATOR_UNAVAILABLE_MESSAGE,
    DimensionEstimator,
    EstimatorUnavailableError,
)


def get_dimension_estimator() -> DimensionEstimator:
    if settings.decision_estimator_provider == "openai":
        from app.decision.estimators.providers.openai import OpenAIDimensionEstimator

        return OpenAIDimensionEstimator()
    raise EstimatorUnavailableError(ESTIMATOR_UNAVAILABLE_MESSAGE)
