from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List

from mm.common.types import OrderIntent


@dataclass(frozen=True)
class StrategyBudget:
    strategy: str
    max_place: int
    max_cancel: int


@dataclass(frozen=True)
class BudgetReport:
    accepted: int
    rejected: int
    used_place: Dict[str, int]
    used_cancel: Dict[str, int]


class OrderBudgetAllocator:
    def __init__(self, budgets: Iterable[StrategyBudget]) -> None:
        self.budgets = {budget.strategy: budget for budget in budgets}

    def apply(self, intents: Iterable[OrderIntent]) -> tuple[List[OrderIntent], BudgetReport]:
        accepted: List[OrderIntent] = []
        rejected = 0
        used_place: Dict[str, int] = {}
        used_cancel: Dict[str, int] = {}
        for intent in intents:
            budget = self.budgets.get(intent.strategy)
            if budget is None:
                accepted.append(intent)
                continue
            if intent.action == "place":
                used = used_place.get(intent.strategy, 0)
                if used >= budget.max_place:
                    rejected += 1
                    continue
                used_place[intent.strategy] = used + 1
            elif intent.action == "cancel":
                used = used_cancel.get(intent.strategy, 0)
                if used >= budget.max_cancel:
                    rejected += 1
                    continue
                used_cancel[intent.strategy] = used + 1
            accepted.append(intent)
        return accepted, BudgetReport(
            accepted=len(accepted),
            rejected=rejected,
            used_place=used_place,
            used_cancel=used_cancel,
        )

