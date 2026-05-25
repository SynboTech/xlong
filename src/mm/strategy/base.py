from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, List

from mm.common.types import Balance, MarketRule, MarketSnapshot, QuoteIntent


@dataclass
class StrategyContext:
    market_rules: Dict[str, MarketRule]
    balances: Dict[str, Balance] = field(default_factory=dict)
    markets: Dict[str, MarketSnapshot] = field(default_factory=dict)
    price_adjustment_bps: Dict[str, Decimal] = field(default_factory=dict)

    def balance(self, currency: str) -> Balance:
        return self.balances.get(currency, Balance(currency=currency, available=Decimal("0"), frozen=Decimal("0")))


class StrategyPlugin:
    name = "base"

    def __init__(self, symbol: str, params: Dict[str, object]) -> None:
        self.symbol = symbol
        self.params = params
        self.instance_id = ""

    @property
    def strategy_key(self) -> str:
        return self.instance_id or self.name

    async def on_start(self, ctx: StrategyContext) -> None:
        return None

    async def on_market(self, ctx: StrategyContext, event: MarketSnapshot) -> None:
        return None

    async def on_balance(self, ctx: StrategyContext, balances: Dict[str, Balance]) -> None:
        return None

    async def prepare(self, ctx: StrategyContext) -> None:
        return None

    async def on_timer(self, ctx: StrategyContext, now_ms: int) -> List[QuoteIntent]:
        return []

    async def on_stop(self) -> None:
        return None
