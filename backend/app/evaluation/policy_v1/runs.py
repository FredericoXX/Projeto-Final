"""Execuções numeradas e agregação por caso.

- Condições com modelo — incluindo o B0, porque usa o gerador — correm **três**
  vezes, com números de execução fixados antes de correr; P-oráculo corre uma.
- A **primeira** execução é a análise principal: a sua ação, mensagem, fontes e
  destino são os reportados como resultado.
- A ação modal é secundária; em empate, prevalece a primeira execução.
- O caso é a unidade estatística: três execuções não multiplicam a amostra.
- Falhas técnicas ficam fora das ações e são contadas à parte, com
  denominadores explícitos.
"""

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from app.evaluation.policy_v1.conditions import CaseOutcome, Condition

RUN_NUMBERS: Final = (1, 2, 3)
ORACLE_RUN_NUMBERS: Final = (1,)
PRIMARY_RUN: Final = 1


def run_numbers(condition: Condition) -> tuple[int, ...]:
    return ORACLE_RUN_NUMBERS if condition is Condition.P_ORACLE else RUN_NUMBERS


@dataclass(frozen=True)
class CaseSummary:
    case_id: str
    condition: Condition
    primary: CaseOutcome
    modal_action: str | None
    unstable: bool
    runs: int
    failures: int


def summarize(outcomes: Sequence[CaseOutcome]) -> CaseSummary:
    """Agrega as execuções de um caso numa condição."""
    if not outcomes:
        msg = "no outcomes to summarize"
        raise ValueError(msg)
    keys = {(outcome.case_id, outcome.condition) for outcome in outcomes}
    if len(keys) != 1:
        msg = "outcomes must belong to one case and one condition"
        raise ValueError(msg)
    ordered = sorted(outcomes, key=lambda outcome: outcome.run_number)
    numbers = [outcome.run_number for outcome in ordered]
    if len(set(numbers)) != len(numbers):
        msg = "run numbers must be unique"
        raise ValueError(msg)
    primary = next((o for o in ordered if o.run_number == PRIMARY_RUN), None)
    if primary is None:
        msg = "the primary (first) run is missing"
        raise ValueError(msg)
    actions = [o.action for o in ordered if o.failure is None and o.action is not None]
    counts = Counter(actions)
    modal: str | None = None
    if counts:
        best = max(counts.values())
        tied = {action for action, count in counts.items() if count == best}
        # Empate: a primeira execução decide; se falhou, a execução numerada
        # mais baixa entre as empatadas.
        modal = next(o.action for o in ordered if o.action in tied)
    case_id, condition = next(iter(keys))
    return CaseSummary(
        case_id=case_id,
        condition=condition,
        primary=primary,
        modal_action=modal,
        unstable=len(counts) > 1,
        runs=len(ordered),
        failures=sum(1 for o in ordered if o.failure is not None),
    )
