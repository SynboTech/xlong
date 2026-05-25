from __future__ import annotations

from decimal import Decimal
from typing import Dict, Iterable

from mm.common.types import Balance, MarketRule


class InventoryManager:
    def __init__(self) -> None:
        self._balances: Dict[str, Balance] = {}

    def update(self, balances: Iterable[Balance]) -> None:
        for balance in balances:
            self._balances[balance.currency] = balance

    def balance(self, currency: str) -> Balance:
        return self._balances.get(currency, Balance(currency=currency, available=Decimal("0"), frozen=Decimal("0")))

    def base_total(self, rule: MarketRule) -> Decimal:
        return self.balance(rule.base).total

    def quote_total(self, rule: MarketRule) -> Decimal:
        return self.balance(rule.quote).total

    def as_dict(self) -> Dict[str, Balance]:
        return dict(self._balances)

