from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, Optional

from mm.common.types import Side
from mm.hedging.engine import HedgeIntent, HedgeResult


class HedgeAdapter:
    name = "base"

    async def execute(self, intent: HedgeIntent) -> HedgeResult:
        raise NotImplementedError


class PaperHedgeAdapter(HedgeAdapter):
    name = "paper"

    async def execute(self, intent: HedgeIntent) -> HedgeResult:
        return HedgeResult(intent=intent, accepted=True, message="paper hedge accepted")


@dataclass(frozen=True)
class BinanceHedgeOrder:
    symbol: str
    side: str
    order_type: str
    quantity: str


class BinanceHedgeAdapter(HedgeAdapter):
    name = "binance"

    def __init__(self, dry_run: bool = True) -> None:
        self.dry_run = dry_run
        self.last_order: Optional[BinanceHedgeOrder] = None

    async def execute(self, intent: HedgeIntent) -> HedgeResult:
        order = self.build_market_order(intent)
        self.last_order = order
        if self.dry_run:
            return HedgeResult(intent=intent, accepted=True, message="binance dry-run hedge accepted")
        return HedgeResult(intent=intent, accepted=False, message="live Binance hedge execution not configured")

    @staticmethod
    def build_market_order(intent: HedgeIntent) -> BinanceHedgeOrder:
        return BinanceHedgeOrder(
            symbol=intent.symbol.replace("_", ""),
            side="BUY" if intent.side == Side.BUY else "SELL",
            order_type="MARKET",
            quantity=str(intent.size.normalize()),
        )

