from __future__ import annotations

from decimal import Decimal
from typing import List

from mm.common.decimal import BPS, D
from mm.common.types import QuoteIntent, Side
from mm.strategy.base import StrategyContext, StrategyPlugin


class HedgedMarketMaker(StrategyPlugin):
    name = "hedged_mm"

    async def on_timer(self, ctx: StrategyContext, now_ms: int) -> List[QuoteIntent]:
        market = ctx.markets.get(self.symbol)
        if market is None:
            return []
        spread_bps = D(self.params.get("spread_bps", "22"))
        order_size = D(self.params.get("order_size", "0"))
        levels = int(self.params.get("levels", 1))
        level_spacing_bps = D(self.params.get("level_spacing_bps", spread_bps / Decimal("2")))
        adjustment = ctx.price_adjustment_bps.get(self.symbol, Decimal("0"))
        fair = market.mid * (Decimal("1") + adjustment / BPS)
        quotes: List[QuoteIntent] = []
        for idx in range(max(0, levels)):
            level = idx + 1
            level_bps = (spread_bps / Decimal("2")) + (level_spacing_bps * idx)
            bid = fair * (Decimal("1") - level_bps / BPS)
            ask = fair * (Decimal("1") + level_bps / BPS)
            quotes.append(
                QuoteIntent(
                    symbol=self.symbol,
                    side=Side.BUY,
                    price=bid,
                    size=order_size,
                    level=level,
                    strategy=self.strategy_key,
                    reason="hedged bid level {0}".format(level),
                )
            )
            quotes.append(
                QuoteIntent(
                    symbol=self.symbol,
                    side=Side.SELL,
                    price=ask,
                    size=order_size,
                    level=level,
                    strategy=self.strategy_key,
                    reason="hedged ask level {0}".format(level),
                )
            )
        return quotes
