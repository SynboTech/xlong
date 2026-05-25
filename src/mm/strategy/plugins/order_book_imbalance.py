from __future__ import annotations

from decimal import Decimal
from typing import List

from mm.common.decimal import BPS, D
from mm.common.types import QuoteIntent, Side
from mm.market_data.depth_metrics import order_book_imbalance
from mm.strategy.base import StrategyContext, StrategyPlugin


class OrderBookImbalanceMarketMaker(StrategyPlugin):
    name = "order_book_imbalance"

    async def on_timer(self, ctx: StrategyContext, now_ms: int) -> List[QuoteIntent]:
        market = ctx.markets.get(self.symbol)
        if market is None:
            return []
        depth_levels = int(self.params.get("depth_levels", 1))
        imbalance = order_book_imbalance(market, depth_levels)
        threshold = D(self.params.get("imbalance_threshold", "0.15"))
        effective_imbalance = imbalance if abs(imbalance) >= threshold else Decimal("0")
        skew_bps = D(self.params.get("skew_bps", "24"))
        base_spread_bps = D(self.params.get("base_spread_bps", "18"))
        spread_widen_bps = D(self.params.get("spread_widen_bps", "8")) * abs(effective_imbalance)
        order_size = D(self.params.get("order_size", "0"))
        levels = int(self.params.get("levels", 1))
        level_spacing_bps = D(self.params.get("level_spacing_bps", "8"))
        fair = market.mid * (Decimal("1") + (effective_imbalance * skew_bps) / BPS)
        fair_adjustment = ctx.price_adjustment_bps.get(self.symbol, Decimal("0"))
        fair = fair * (Decimal("1") + fair_adjustment / BPS)
        quotes: List[QuoteIntent] = []
        for idx in range(max(0, levels)):
            level = idx + 1
            level_bps = ((base_spread_bps + spread_widen_bps) / Decimal("2")) + (level_spacing_bps * idx)
            quotes.append(
                QuoteIntent(
                    symbol=self.symbol,
                    side=Side.BUY,
                    price=fair * (Decimal("1") - level_bps / BPS),
                    size=order_size,
                    level=level,
                    strategy=self.strategy_key,
                    reason="imbalance bid level {0}".format(level),
                )
            )
            quotes.append(
                QuoteIntent(
                    symbol=self.symbol,
                    side=Side.SELL,
                    price=fair * (Decimal("1") + level_bps / BPS),
                    size=order_size,
                    level=level,
                    strategy=self.strategy_key,
                    reason="imbalance ask level {0}".format(level),
                )
            )
        return quotes
