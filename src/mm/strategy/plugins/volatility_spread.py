from __future__ import annotations

from decimal import Decimal
from typing import List, Tuple

from mm.common.decimal import BPS, D
from mm.common.types import MarketSnapshot, QuoteIntent, Side
from mm.strategy.base import StrategyContext, StrategyPlugin


class VolatilitySpreadMarketMaker(StrategyPlugin):
    name = "volatility_spread"

    def __init__(self, symbol: str, params: dict) -> None:
        super().__init__(symbol, params)
        self._history: List[Tuple[int, Decimal]] = []

    async def on_market(self, ctx: StrategyContext, event: MarketSnapshot) -> None:
        self._history.append((event.receive_time_ms, event.mid))
        window_ms = int(self.params.get("volatility_window_ms", 60000))
        cutoff = event.receive_time_ms - max(1, window_ms)
        self._history = [(ts, mid) for ts, mid in self._history if ts >= cutoff]

    async def on_timer(self, ctx: StrategyContext, now_ms: int) -> List[QuoteIntent]:
        market = ctx.markets.get(self.symbol)
        if market is None:
            return []
        spread_bps = self._dynamic_spread_bps()
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
                    reason="volatility bid level {0}".format(level),
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
                    reason="volatility ask level {0}".format(level),
                )
            )
        return quotes

    def _dynamic_spread_bps(self) -> Decimal:
        base_spread_bps = D(self.params.get("base_spread_bps", "18"))
        min_spread_bps = D(self.params.get("min_spread_bps", base_spread_bps))
        max_spread_bps = D(self.params.get("max_spread_bps", "120"))
        multiplier = D(self.params.get("volatility_multiplier", "2"))
        if len(self._history) < 2:
            return max(min_spread_bps, min(base_spread_bps, max_spread_bps))
        mids = [mid for _, mid in self._history if mid > 0]
        if not mids:
            return max(min_spread_bps, min(base_spread_bps, max_spread_bps))
        latest = mids[-1]
        volatility_bps = ((max(mids) - min(mids)) / latest) * BPS
        spread = base_spread_bps + (volatility_bps * multiplier)
        return max(min_spread_bps, min(spread, max_spread_bps))
