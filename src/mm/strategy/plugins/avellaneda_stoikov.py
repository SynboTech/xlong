from __future__ import annotations

from decimal import Decimal
from typing import List, Tuple

from mm.common.decimal import BPS, D
from mm.common.types import MarketSnapshot, QuoteIntent, Side
from mm.strategy.base import StrategyContext, StrategyPlugin


class AvellanedaStoikovMarketMaker(StrategyPlugin):
    name = "avellaneda_stoikov"

    def __init__(self, symbol: str, params: dict) -> None:
        super().__init__(symbol, params)
        self._history: List[Tuple[int, Decimal]] = []

    async def on_market(self, ctx: StrategyContext, event: MarketSnapshot) -> None:
        self._history.append((event.receive_time_ms, event.mid))
        window_ms = int(self.params.get("sigma_window_ms", 60000))
        cutoff = event.receive_time_ms - max(1, window_ms)
        self._history = [(ts, mid) for ts, mid in self._history if ts >= cutoff]

    async def on_timer(self, ctx: StrategyContext, now_ms: int) -> List[QuoteIntent]:
        market = ctx.markets.get(self.symbol)
        if market is None:
            return []
        rule = ctx.market_rules[self.symbol]
        risk_aversion = D(self.params.get("risk_aversion", "0.15"))
        sigma_bps = self._sigma_bps()
        target_base = D(self.params.get("target_base", "0"))
        max_inventory = D(self.params.get("max_inventory_base", self.params.get("max_inventory", "0.01")))
        inventory_ratio = Decimal("0")
        if max_inventory > 0:
            inventory_ratio = (ctx.balance(rule.base).total - target_base) / max_inventory
            inventory_ratio = max(Decimal("-1"), min(Decimal("1"), inventory_ratio))
        inventory_multiplier = D(self.params.get("inventory_risk_multiplier", "1"))
        reservation_shift_bps = -inventory_ratio * risk_aversion * sigma_bps * inventory_multiplier
        fair_adjustment = ctx.price_adjustment_bps.get(self.symbol, Decimal("0"))
        reservation_price = market.mid * (Decimal("1") + (reservation_shift_bps + fair_adjustment) / BPS)

        base_spread_bps = D(self.params.get("base_spread_bps", "16"))
        min_spread_bps = D(self.params.get("min_spread_bps", base_spread_bps))
        max_spread_bps = D(self.params.get("max_spread_bps", "120"))
        volatility_multiplier = D(self.params.get("volatility_spread_multiplier", "0.5"))
        spread_bps = base_spread_bps + (risk_aversion * sigma_bps * volatility_multiplier)
        spread_bps = max(min_spread_bps, min(spread_bps, max_spread_bps))

        order_size = D(self.params.get("order_size", "0"))
        levels = int(self.params.get("levels", 1))
        level_spacing_bps = D(self.params.get("level_spacing_bps", spread_bps / Decimal("2")))
        quotes: List[QuoteIntent] = []
        for idx in range(max(0, levels)):
            level = idx + 1
            level_bps = (spread_bps / Decimal("2")) + (level_spacing_bps * idx)
            quotes.append(
                QuoteIntent(
                    symbol=self.symbol,
                    side=Side.BUY,
                    price=reservation_price * (Decimal("1") - level_bps / BPS),
                    size=order_size,
                    level=level,
                    strategy=self.strategy_key,
                    reason="avellaneda bid level {0}".format(level),
                )
            )
            quotes.append(
                QuoteIntent(
                    symbol=self.symbol,
                    side=Side.SELL,
                    price=reservation_price * (Decimal("1") + level_bps / BPS),
                    size=order_size,
                    level=level,
                    strategy=self.strategy_key,
                    reason="avellaneda ask level {0}".format(level),
                )
            )
        return quotes

    def _sigma_bps(self) -> Decimal:
        min_sigma_bps = D(self.params.get("min_volatility_bps", "5"))
        if len(self._history) < 2:
            return min_sigma_bps
        returns: List[Decimal] = []
        for idx in range(1, len(self._history)):
            previous = self._history[idx - 1][1]
            current = self._history[idx][1]
            if previous > 0:
                returns.append(abs(current - previous) / previous * BPS)
        if not returns:
            return min_sigma_bps
        mean_square = sum((item * item for item in returns), Decimal("0")) / Decimal(len(returns))
        sigma = mean_square.sqrt()
        window_ms = Decimal(max(1, int(self.params.get("sigma_window_ms", 60000))))
        horizon_ms = Decimal(max(1, int(self.params.get("time_horizon_ms", window_ms))))
        horizon_scale = (horizon_ms / window_ms).sqrt()
        return max(min_sigma_bps, sigma * horizon_scale)
