from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional

from mm.common.decimal import D
from mm.common.types import Balance, FillEvent, Liquidity, OrderStatus, OrderUpdate
from mm.exchange.bitmart.websocket import (
    parse_balance_update,
    parse_private_order_update,
    parse_trade_liquidity,
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
    fills: List[FillEvent] = field(default_factory=list)

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
        fills: List[FillEvent] = []
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
            previous_filled = before.filled_size if before is not None else Decimal("0")
            record = self.oms.apply_remote_order_update(update, "orphan order from bitmart private stream")
            filled_delta = record.filled_size - previous_filled if before is not None else Decimal("0")
            if filled_delta > 0 and record.status != OrderStatus.UNKNOWN:
                fills.append(self._fill_from_private_row(row, update, record, filled_delta))
            if before is None:
                orphan_orders += 1
            if record.status == OrderStatus.UNKNOWN:
                unknown_orders += 1
            applied += 1
            self._log("bitmart.private.order", update)
        return PrivateStreamApplyReport(applied, 0, orphan_orders, unknown_orders, 0, fills)

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

    @staticmethod
    def _fill_from_private_row(row, update, record, filled_delta: Decimal) -> FillEvent:
        price = update.avg_fill_price or record.avg_fill_price or record.price or Decimal("0")
        fee_value = row.get("fee", row.get("deal_fee", row.get("filled_fee", "0")))
        fee_currency = str(
            row.get("fee_currency")
            or row.get("feeCurrency")
            or row.get("fee_ccy")
            or row.get("feeCcy")
            or ""
        )
        liquidity_raw = str(row.get("exec_type") or row.get("execType") or row.get("liquidity") or "")
        liquidity = parse_trade_liquidity(liquidity_raw)
        if liquidity == Liquidity.UNKNOWN and liquidity_raw.lower() in {"maker", "taker"}:
            liquidity = Liquidity(liquidity_raw.lower())
        trade_id = str(
            row.get("trade_id")
            or row.get("tradeId")
            or row.get("detail_id")
            or row.get("detailId")
            or "{0}:{1}".format(record.exchange_order_id or update.exchange_order_id or record.client_order_id, record.filled_size)
        )
        return FillEvent(
            symbol=record.symbol or update.symbol,
            client_order_id=record.client_order_id,
            exchange_order_id=record.exchange_order_id or update.exchange_order_id,
            side=record.side,
            price=price,
            size=filled_delta,
            fee=D(fee_value),
            fee_currency=fee_currency,
            liquidity=liquidity,
            trade_id=trade_id,
            timestamp_ms=update.timestamp_ms,
        )
