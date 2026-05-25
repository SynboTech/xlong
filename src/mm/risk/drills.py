from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, List

from mm.common.types import MarketSnapshot, OrderIntent, OrderStatus, OrderType, Side
from mm.inventory.manager import InventoryManager
from mm.oms.manager import OrderManager
from mm.risk.engine import RiskEngine


@dataclass(frozen=True)
class DrillResult:
    name: str
    passed: bool
    message: str


class RiskDrillSuite:
    def __init__(
        self,
        risk: RiskEngine,
        inventory: InventoryManager,
        oms: OrderManager,
        markets: Dict[str, MarketSnapshot],
    ) -> None:
        self.risk = risk
        self.inventory = inventory
        self.oms = oms
        self.markets = markets

    def run(self) -> List[DrillResult]:
        return [
            self._drill_safe_mode_blocks_new_orders(),
            self._drill_crossing_post_only_rejected(),
            self._drill_stale_market_rejected(),
            self._drill_unknown_order_rejected(),
        ]

    def _drill_safe_mode_blocks_new_orders(self) -> DrillResult:
        was_safe = self.risk.safe_mode
        self.risk.safe_mode = True
        intent = self._sample_place_intent("safe-mode-drill", Decimal("1"))
        result = self.risk.validate(intent, self.markets, self.inventory, self.oms)
        self.risk.safe_mode = was_safe
        return DrillResult(
            name="safe_mode_blocks_new_orders",
            passed=not result.approved and result.rule == "safe_mode",
            message=result.message,
        )

    def _drill_crossing_post_only_rejected(self) -> DrillResult:
        market = self.markets["BTC_USDT"]
        intent = self._sample_place_intent("crossing-drill", Decimal("1"))
        intent = OrderIntent(
            action=intent.action,
            symbol=intent.symbol,
            side=Side.BUY,
            price=market.ask,
            size=intent.size,
            client_order_id=intent.client_order_id,
            old_client_order_id=intent.old_client_order_id,
            strategy=intent.strategy,
            level=intent.level,
            order_type=intent.order_type,
            reason=intent.reason,
        )
        result = self.risk.validate(intent, self.markets, self.inventory, self.oms)
        return DrillResult(
            name="post_only_cross_rejected",
            passed=not result.approved and result.rule == "post_only_cross",
            message=result.message,
        )

    def _drill_stale_market_rejected(self) -> DrillResult:
        original = self.markets["BTC_USDT"]
        stale = MarketSnapshot(
            symbol=original.symbol,
            bid=original.bid,
            bid_size=original.bid_size,
            ask=original.ask,
            ask_size=original.ask_size,
            last=original.last,
            exchange=original.exchange,
            timestamp_ms=original.timestamp_ms - 10_000_000,
            receive_time_ms=original.receive_time_ms - 10_000_000,
        )
        self.markets["BTC_USDT"] = stale
        result = self.risk.validate(self._sample_place_intent("stale-drill", Decimal("1")), self.markets, self.inventory, self.oms)
        self.markets["BTC_USDT"] = original
        return DrillResult(
            name="stale_market_rejected",
            passed=not result.approved and result.rule == "stale_market",
            message=result.message,
        )

    def _drill_unknown_order_rejected(self) -> DrillResult:
        client_order_id = "unknown-drill-order"
        created = False
        if self.oms.get(client_order_id) is None:
            self.oms._orders[client_order_id] = self._unknown_order_record(client_order_id)
            created = True
        result = self.risk.validate(self._sample_place_intent("unknown-order-drill", Decimal("1")), self.markets, self.inventory, self.oms)
        if created:
            self.oms._orders.pop(client_order_id, None)
        return DrillResult(
            name="unknown_order_rejected",
            passed=not result.approved and result.rule == "unknown_order",
            message=result.message,
        )

    @staticmethod
    def _sample_place_intent(client_order_id: str, price_offset: Decimal) -> OrderIntent:
        return OrderIntent(
            action="place",
            symbol="BTC_USDT",
            side=Side.BUY,
            price=Decimal("68000") - price_offset,
            size=Decimal("0.00005"),
            client_order_id=client_order_id,
            old_client_order_id=None,
            strategy="drill",
            level=1,
            order_type=OrderType.LIMIT_MAKER,
            reason="risk drill",
        )

    @staticmethod
    def _unknown_order_record(client_order_id: str):
        from mm.oms.order import OrderRecord

        return OrderRecord(
            symbol="BTC_USDT",
            side=Side.BUY,
            price=Decimal("67999"),
            size=Decimal("0.00005"),
            order_type=OrderType.LIMIT_MAKER.value,
            client_order_id=client_order_id,
            strategy="drill",
            level=1,
            status=OrderStatus.UNKNOWN,
            last_message="risk drill synthetic unknown order",
        )
