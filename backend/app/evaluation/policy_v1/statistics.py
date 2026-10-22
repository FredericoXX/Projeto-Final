"""Estatística da avaliação da política v1: intervalos e acordo.

Funções puras, só biblioteca padrão.

- :func:`wilson_interval` — intervalo de score de Wilson para uma proporção.
  Escolhido por continuar informativo com 0 ou N sucessos (o intervalo de Wald
  colapsa em [0, 0] e sugeriria, falsamente, risco nulo).
- :func:`paired_difference_interval` — diferença entre duas proporções
  **emparelhadas** pelo caso, pelo método 10 de Newcombe (1998), que combina os
  intervalos de Wilson de cada proporção com a correlação dos pares. O caso é a
  unidade: as duas condições são medidas sobre os mesmos casos.
- :func:`cohen_kappa` — κ de Cohen com erro padrão assintótico; ``None`` quando
  não está definido (uma só categoria observada).

Nenhuma destas funções conclui equivalência ou risco nulo: um intervalo que
inclui zero não prova ausência de diferença.
"""

import math
from collections import Counter
from collections.abc import Hashable, Sequence
from dataclasses import dataclass
from typing import Final

#: Quantil normal para 95 %.
Z_95: Final = 1.959963984540054


@dataclass(frozen=True)
class Interval:
    estimate: float | None
    lower: float | None
    upper: float | None
    numerator: int
    denominator: int

    def as_dict(self) -> dict[str, object]:
        return {
            "estimate": self.estimate,
            "lower": self.lower,
            "upper": self.upper,
            "numerator": self.numerator,
            "denominator": self.denominator,
        }


def wilson_interval(successes: int, total: int, z: float = Z_95) -> Interval:
    if total < 0 or not 0 <= successes <= total:
        msg = "successes must be between 0 and total"
        raise ValueError(msg)
    if total == 0:
        # Sem denominador não há estimativa — nunca se reporta 0 %.
        return Interval(None, None, None, successes, total)
    p = successes / total
    denominator = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denominator
    margin = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return Interval(p, max(0.0, centre - margin), min(1.0, centre + margin), successes, total)


@dataclass(frozen=True)
class PairedDifference:
    """Diferença p_a − p_b sobre os mesmos casos, com IC de Newcombe."""

    estimate: float | None
    lower: float | None
    upper: float | None
    n_pairs: int
    both: int
    only_a: int
    only_b: int
    neither: int

    def as_dict(self) -> dict[str, object]:
        return {
            "estimate": self.estimate,
            "lower": self.lower,
            "upper": self.upper,
            "n_pairs": self.n_pairs,
            "both": self.both,
            "only_a": self.only_a,
            "only_b": self.only_b,
            "neither": self.neither,
        }


def paired_difference_interval(
    outcomes_a: Sequence[bool], outcomes_b: Sequence[bool], z: float = Z_95
) -> PairedDifference:
    """Newcombe (1998), método 10, para proporções emparelhadas."""
    if len(outcomes_a) != len(outcomes_b):
        msg = "paired outcomes must have the same length"
        raise ValueError(msg)
    n = len(outcomes_a)
    both = sum(1 for a, b in zip(outcomes_a, outcomes_b, strict=True) if a and b)
    only_a = sum(1 for a, b in zip(outcomes_a, outcomes_b, strict=True) if a and not b)
    only_b = sum(1 for a, b in zip(outcomes_a, outcomes_b, strict=True) if b and not a)
    neither = n - both - only_a - only_b
    if n == 0:
        return PairedDifference(None, None, None, 0, 0, 0, 0, 0)
    a_total, b_total = both + only_a, both + only_b
    p_a, p_b = a_total / n, b_total / n
    difference = p_a - p_b
    wa = wilson_interval(a_total, n, z)
    wb = wilson_interval(b_total, n, z)
    assert wa.lower is not None and wa.upper is not None
    assert wb.lower is not None and wb.upper is not None
    # Correlação phi dos pares; 0 quando alguma margem é degenerada.
    margins = (both + only_a) * (only_b + neither) * (both + only_b) * (only_a + neither)
    phi = 0.0 if margins == 0 else (both * neither - only_a * only_b) / math.sqrt(margins)
    d_lower = (
        (p_a - wa.lower) ** 2
        - 2 * phi * (p_a - wa.lower) * (wb.upper - p_b)
        + (wb.upper - p_b) ** 2
    )
    d_upper = (
        (wa.upper - p_a) ** 2
        - 2 * phi * (wa.upper - p_a) * (p_b - wb.lower)
        + (p_b - wb.lower) ** 2
    )
    lower = difference - math.sqrt(max(d_lower, 0.0))
    upper = difference + math.sqrt(max(d_upper, 0.0))
    return PairedDifference(
        difference, max(-1.0, lower), min(1.0, upper), n, both, only_a, only_b, neither
    )


@dataclass(frozen=True)
class KappaResult:
    n: int
    raw_agreement: Interval
    kappa: float | None
    kappa_lower: float | None
    kappa_upper: float | None
    disagreements: dict[str, int]

    def as_dict(self) -> dict[str, object]:
        return {
            "n": self.n,
            "raw_agreement": self.raw_agreement.as_dict(),
            "kappa": self.kappa,
            "kappa_ci": [self.kappa_lower, self.kappa_upper],
            "disagreements": dict(sorted(self.disagreements.items())),
        }


def _key(value: Hashable) -> str:
    return str(value)


def cohen_kappa(
    first: Sequence[Hashable], second: Sequence[Hashable], z: float = Z_95
) -> KappaResult:
    """κ de Cohen, acordo bruto com IC de Wilson e matriz de desacordos.

    Simétrico: trocar ``first`` e ``second`` não altera κ, o acordo nem as
    contagens; a matriz de desacordos usa pares não ordenados.
    """
    if len(first) != len(second):
        msg = "annotations must have the same length"
        raise ValueError(msg)
    n = len(first)
    agreements = sum(1 for a, b in zip(first, second, strict=True) if a == b)
    raw = wilson_interval(agreements, n, z)
    disagreements: Counter[str] = Counter(
        " | ".join(sorted((_key(a), _key(b)))) for a, b in zip(first, second, strict=True) if a != b
    )
    categories = set(first) | set(second)
    if n == 0 or len(categories) < 2:
        return KappaResult(n, raw, None, None, None, dict(disagreements))
    count_a, count_b = Counter(first), Counter(second)
    p_o = agreements / n
    p_e = sum(count_a[c] * count_b[c] for c in categories) / (n * n)
    if p_e == 1:
        return KappaResult(n, raw, None, None, None, dict(disagreements))
    kappa = (p_o - p_e) / (1 - p_e)
    se = math.sqrt(p_o * (1 - p_o) / (n * (1 - p_e) ** 2))
    return KappaResult(
        n, raw, kappa, max(-1.0, kappa - z * se), min(1.0, kappa + z * se), dict(disagreements)
    )
