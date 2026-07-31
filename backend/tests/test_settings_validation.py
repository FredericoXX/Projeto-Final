"""Validação do limiar mínimo de relevância lexical na configuração.

O limiar é comparado com um score composto finito em ``[0, 1]``: um valor
fora desse domínio (NaN, ±infinito, negativo ou acima de 1) tornaria a
comparação incoerente e é rejeitado no arranque, não silenciosamente
aceite. Sem rede e sem base de dados: apenas a validação de Settings.
"""

import pytest

from app.core.config import Settings

_REQUIRED = {
    "database_url": "postgresql+psycopg://user:pass@localhost:5432/db",
    "jwt_secret_key": "test-secret-key",
}


def _settings(score: float) -> Settings:
    return Settings(**_REQUIRED, retrieval_min_relevance_score=score)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "score",
    [float("nan"), float("inf"), float("-inf")],
)
def test_non_finite_threshold_is_rejected(score: float) -> None:
    with pytest.raises(ValueError, match="must be a finite number"):
        _settings(score)


@pytest.mark.parametrize("score", [-0.01, -1.0, 1.01, 2.0])
def test_threshold_outside_the_unit_interval_is_rejected(score: float) -> None:
    with pytest.raises(ValueError, match="must be between 0 and 1"):
        _settings(score)


@pytest.mark.parametrize("score", [0.0, 0.05, 0.5, 1.0])
def test_threshold_inside_the_unit_interval_is_accepted(score: float) -> None:
    assert _settings(score).retrieval_min_relevance_score == score


def test_default_threshold_is_a_valid_low_floor() -> None:
    """O padrão é um piso residual: a decisão de evidência pertence à
    elegibilidade, não ao limiar."""
    default = Settings(**_REQUIRED).retrieval_min_relevance_score  # type: ignore[arg-type]
    assert default == 0.05
    assert 0.0 <= default <= 1.0
