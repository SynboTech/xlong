from __future__ import annotations

from decimal import Decimal
from typing import List

from mm.common.decimal import BPS, D
from mm.common.types import QuoteIntent, Side
from mm.strategy.base import StrategyContext, StrategyPlugin


class LadderMarketMaker(StrategyPlugin):
    name = "ladder_mm"

    async def on_timer(self, ctx: StrategyContext, now_ms: int) -> List[QuoteIntent]:
        market = ctx.markets.get(self.symbol)
        if market is None:
            return []
        base_spread_bps = D(self.params.get("base_spread_bps", "18"))
        bid_levels = int(self.params.get("bid_levels", 3))
        ask_levels = int(self.params.get("ask_levels", 3))
        base_order_size = D(self.params.get("base_order_size", self.params.get("order_size", "0")))
        level_spacing_bps = D(self.params.get("level_spacing_bps", "8"))
        size_multiplier = D(self.params.get("size_multiplier", "1"))
        max_distance_bps = D(self.params.get("max_distance_bps", "80"))
        adjustment = ctx.price_adjustment_bps.get(self.symbol, Decimal("0"))
        fair = market.mid * (Decimal("1") + adjustment / BPS)
        quotes: List[QuoteIntent] = []
        quotes.extend(
            self._side_quotes(
                fair=fair,
                side=Side.BUY,
                levels=bid_levels,
                base_spread_bps=base_spread_bps,
                level_spacing_bps=level_spacing_bps,
                max_distance_bps=max_distance_bps,
                base_order_size=base_order_size,
                size_multiplier=size_multiplier,
            )
        )
        quotes.extend(
            self._side_quotes(
                fair=fair,
                side=Side.SELL,
                levels=ask_levels,
                base_spread_bps=base_spread_bps,
                level_spacing_bps=level_spacing_bps,
                max_distance_bps=max_distance_bps,
                base_order_size=base_order_size,
                size_multiplier=size_multiplier,
            )
        )
        return quotes

    def _side_quotes(
        self,
        fair: Decimal,
        side: Side,
        levels: int,
        base_spread_bps: Decimal,
        level_spacing_bps: Decimal,
        max_distance_bps: Decimal,
        base_order_size: Decimal,
        size_multiplier: Decimal,
    ) -> List[QuoteIntent]:
        quotes: List[QuoteIntent] = []
        for idx in range(max(0, levels)):
            level = idx + 1
            distance_bps = (base_spread_bps / Decimal("2")) + (level_spacing_bps * idx)
            if max_distance_bps > 0:
                distance_bps = min(distance_bps, max_distance_bps)
            size = base_order_size * (size_multiplier ** idx)
            if side == Side.BUY:
                price = fair * (Decimal("1") - distance_bps / BPS)
                reason = "ladder bid level {0}".format(level)
            else:
                price = fair * (Decimal("1") + distance_bps / BPS)
                reason = "ladder ask level {0}".format(level)
            quotes.append(
                QuoteIntent(
                    symbol=self.symbol,
                    side=side,
                    price=price,
                    size=size,
                    level=level,
                    strategy=self.strategy_key,
                    reason=reason,
                )
            )
        return quotes
