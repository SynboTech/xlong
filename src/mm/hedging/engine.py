from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import List, Optional

from mm.common.types import FillEvent, Side


@dataclass(frozen=True)
class HedgeIntent:
    symbol: str
    side: Side
    size: Decimal
    reason: str
    source_client_order_id: str


@dataclass(frozen=True)
class HedgeResult:
    intent: HedgeIntent
    accepted: bool
    message: str


class HedgingEngine:
    def __init__(self, enabled: bool = False, min_hedge_size: object = "0", adapter: Optional[object] = None) -> None:
        self.enabled = enabled
        self.min_hedge_size = Decimal(str(min_hedge_size))
        if adapter is None:
            from mm.hedging.adapters import PaperHedgeAdapter

            adapter = PaperHedgeAdapter()
        self.adapter = adapter
        self.results: List[HedgeResult] = []

    def intent_from_fill(self, fill: FillEvent) -> Optional[HedgeIntent]:
        if not self.enabled:
            return None
        if fill.size < self.min_hedge_size:
            return None
        hedge_side = Side.SELL if fill.side == Side.BUY else Side.BUY
        return HedgeIntent(
            symbol=fill.symbol,
            side=hedge_side,
            size=fill.size,
            reason="offset BitMart fill",
            source_client_order_id=fill.client_order_id,
        )

    async def execute(self, intent: HedgeIntent) -> HedgeResult:
        result = await self.adapter.execute(intent)
        self.results.append(result)
        return result
