from __future__ import annotations

from decimal import Decimal
from typing import List

from mm.common.decimal import BPS, D
from mm.common.types import QuoteIntent, Side
from mm.strategy.base import StrategyContext, StrategyPlugin


class RangeRebalanceStrategy(StrategyPlugin):
    name = "range_rebalance"

    async def on_timer(self, ctx: StrategyContext, now_ms: int) -> List[QuoteIntent]:
        market = ctx.markets.get(self.symbol)
        if market is None:
            return []
        mid = market.mid
        hard_floor = D(self.params.get("hard_floor", "0"))
        buy_below = D(self.params.get("buy_below", "0"))
        sell_above = D(self.params.get("sell_above", "0"))
        hard_ceiling = D(self.params.get("hard_ceiling", "0"))
        if hard_floor > 0 and mid < hard_floor:
            return []
        if hard_ceiling > 0 and mid > hard_ceiling:
            return []

        rule = ctx.market_rules[self.symbol]
        base_balance = ctx.balance(rule.base)
        current_base = base_balance.total
        target_base = D(self.params.get("target_base", "0"))
        levels = int(self.params.get("levels", 1))
        quote_offset_bps = D(self.params.get("quote_offset_bps", "2"))
        level_spacing_bps = D(self.params.get("level_spacing_bps", "5"))
        direction = str(self.params.get("direction", "auto")).lower()
        allow_buy = direction in {"auto", "buy", "buy_only"}
        allow_sell = direction in {"auto", "sell", "sell_only"}

        if allow_buy and buy_below > 0 and mid < buy_below and current_base < target_base:
            remaining = target_base - current_base
            order_size = D(self.params.get("buy_order_size", self.params.get("order_size", "0")))
            return self._quotes(
                side=Side.BUY,
                anchor=market.bid,
                remaining=remaining,
                order_size=order_size,
                levels=levels,
                quote_offset_bps=quote_offset_bps,
                level_spacing_bps=level_spacing_bps,
                reason_prefix="range rebalance buy",
            )

        if allow_sell and sell_above > 0 and mid > sell_above and current_base > target_base:
            remaining = min(current_base - target_base, base_balance.available)
            order_size = D(self.params.get("sell_order_size", self.params.get("order_size", "0")))
            return self._quotes(
                side=Side.SELL,
                anchor=market.ask,
                remaining=remaining,
                order_size=order_size,
                levels=levels,
                quote_offset_bps=quote_offset_bps,
                level_spacing_bps=level_spacing_bps,
                reason_prefix="range rebalance sell",
            )

        return []

    def _quotes(
        self,
        side: Side,
        anchor: Decimal,
        remaining: Decimal,
        order_size: Decimal,
        levels: int,
        quote_offset_bps: Decimal,
        level_spacing_bps: Decimal,
        reason_prefix: str,
    ) -> List[QuoteIntent]:
        quotes: List[QuoteIntent] = []
        remaining_size = remaining
        for idx in range(max(0, levels)):
            if remaining_size <= 0:
                break
            level = idx + 1
            distance_bps = quote_offset_bps + (level_spacing_bps * idx)
            size = min(order_size, remaining_size)
            if size <= 0:
                break
            if side == Side.BUY:
                price = anchor * (Decimal("1") - distance_bps / BPS)
            else:
                price = anchor * (Decimal("1") + distance_bps / BPS)
            quotes.append(
                QuoteIntent(
                    symbol=self.symbol,
                    side=side,
                    price=price,
                    size=size,
                    level=level,
                    strategy=self.strategy_key,
                    reason="{0} level {1}".format(reason_prefix, level),
                )
            )
            remaining_size -= size
        return quotes
