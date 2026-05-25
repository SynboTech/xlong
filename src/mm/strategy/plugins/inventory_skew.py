from __future__ import annotations

from decimal import Decimal

from mm.common.decimal import D
from mm.strategy.base import StrategyContext, StrategyPlugin


class InventorySkewStrategy(StrategyPlugin):
    name = "inventory_skew"

    async def prepare(self, ctx: StrategyContext) -> None:
        rule = ctx.market_rules[self.symbol]
        target_base = D(self.params.get("target_base", "0"))
        skew_bps = D(self.params.get("skew_bps_per_full_deviation", "0"))
        if target_base <= 0:
            ctx.price_adjustment_bps[self.symbol] = Decimal("0")
            return
        current = ctx.balance(rule.base).total
        deviation = (current - target_base) / target_base
        if deviation > Decimal("1"):
            deviation = Decimal("1")
        if deviation < Decimal("-1"):
            deviation = Decimal("-1")
        ctx.price_adjustment_bps[self.symbol] = -deviation * skew_bps

