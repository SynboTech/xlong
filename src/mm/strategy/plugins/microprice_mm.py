from __future__ import annotations

from decimal import Decimal
from typing import List

from mm.common.decimal import BPS, D
from mm.common.types import QuoteIntent, Side
from mm.market_data.depth_metrics import microprice
from mm.strategy.base import StrategyContext, StrategyPlugin


class MicropriceMarketMaker(StrategyPlugin):
    name = "microprice_mm"

    async def on_timer(self, ctx: StrategyContext, now_ms: int) -> List[QuoteIntent]:
        market = ctx.markets.get(self.symbol)
        if market is None:
            return []
        depth_levels = int(self.params.get("depth_levels", 1))
        fair = microprice(market, depth_levels)
        adjustment = ctx.price_adjustment_bps.get(self.symbol, Decimal("0"))
        fair = fair * (Decimal("1") + adjustment / BPS)
        spread_bps = D(self.params.get("spread_bps", "16"))
        order_size = D(self.params.get("order_size", "0"))
        levels = int(self.params.get("levels", 1))
        level_spacing_bps = D(self.params.get("level_spacing_bps", "8"))
        size_multiplier = D(self.params.get("size_multiplier", "1"))
        quotes: List[QuoteIntent] = []
        for idx in range(max(0, levels)):
            level = idx + 1
            level_bps = (spread_bps / Decimal("2")) + (level_spacing_bps * idx)
            size = order_size * (size_multiplier ** idx)
            quotes.append(
                QuoteIntent(
                    symbol=self.symbol,
                    side=Side.BUY,
                    price=fair * (Decimal("1") - level_bps / BPS),
                    size=size,
                    level=level,
                    strategy=self.strategy_key,
                    reason="microprice bid level {0}".format(level),
                )
            )
            quotes.append(
                QuoteIntent(
                    symbol=self.symbol,
                    side=Side.SELL,
                    price=fair * (Decimal("1") + level_bps / BPS),
                    size=size,
                    level=level,
                    strategy=self.strategy_key,
                    reason="microprice ask level {0}".format(level),
                )
            )
        return quotes
