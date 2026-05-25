from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

from mm.common.types import Balance, OrderStatus, OrderUpdate
from mm.exchange.bitmart.websocket import (
    parse_balance_update,
    parse_private_order_update,
    private_all_orders_channel,
    private_balance_channel,
    private_order_channel,
)
from mm.inventory.manager import InventoryManager
from mm.oms.manager import OrderManager
from mm.persistence.event_log import JsonlEventLog


@dataclass(frozen=True)
class PrivateStreamApplyReport:
    order_updates: int
    balance_updates: int
    orphan_orders: int
    unknown_orders: int
    ignored: int

    @property
    def passed(self) -> bool:
        return self.unknown_orders == 0


class BitMartPrivateStreamProcessor:
    def __init__(
        self,
        oms: OrderManager,
        inventory: InventoryManager,
        event_log: Optional[JsonlEventLog] = None,
    ) -> None:
        self.oms = oms
        self.inventory = inventory
        self.event_log = event_log

    @staticmethod
    def channels(symbols: Iterable[str], all_symbols: bool = True) -> List[str]:
        channels = [private_balance_channel()]
        if all_symbols:
            channels.append(private_all_orders_channel())
        else:
            channels.extend(private_order_channel(symbol) for symbol in symbols)
        return channels

    def apply_message(self, message: Dict[str, Any]) -> PrivateStreamApplyReport:
        table = str(message.get("table") or "")
        rows = [row for row in message.get("data", []) if isinstance(row, dict)]
        if not rows:
            return PrivateStreamApplyReport(0, 0, 0, 0, 1)

        if table.startswith("spot/user/order"):
            return self._apply_order_rows(rows)
        if table == "spot/user/orders":
            return self._apply_order_rows(rows)
        if table == "spot/user/balance":
            return self._apply_balance_rows(rows)
        return PrivateStreamApplyReport(0, 0, 0, 0, len(rows))

    def _apply_order_rows(self, rows: List[Dict[str, Any]]) -> PrivateStreamApplyReport:
        orphan_orders = 0
        unknown_orders = 0
        applied = 0
        for row in rows:
            update = parse_private_order_update(row)
            if not update.client_order_id and update.exchange_order_id:
                update = OrderUpdate(
                    symbol=update.symbol,
                    client_order_id="exchange:{0}".format(update.exchange_order_id),
                    exchange_order_id=update.exchange_order_id,
                    status=OrderStatus.UNKNOWN,
                    filled_size=update.filled_size,
                    avg_fill_price=update.avg_fill_price,
                    message="private stream order has no client_order_id",
                    timestamp_ms=update.timestamp_ms,
                    side=update.side,
                )
            before = self.oms.get(update.client_order_id)
            record = self.oms.apply_remote_order_update(update, "orphan order from bitmart private stream")
            if before is None:
                orphan_orders += 1
            if record.status == OrderStatus.UNKNOWN:
                unknown_orders += 1
            applied += 1
            self._log("bitmart.private.order", update)
        return PrivateStreamApplyReport(applied, 0, orphan_orders, unknown_orders, 0)

    def _apply_balance_rows(self, rows: List[Dict[str, Any]]) -> PrivateStreamApplyReport:
        balances: List[Balance] = []
        for row in rows:
            balances.extend(parse_balance_update(row))
        if balances:
            self.inventory.update(balances)
            self._log("bitmart.private.balances", balances)
        return PrivateStreamApplyReport(0, len(balances), 0, 0, 0)

    def _log(self, event_type: str, payload: object) -> None:
        if self.event_log is not None:
            self.event_log.append(event_type, payload)
