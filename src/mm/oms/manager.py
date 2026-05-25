from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Dict, Iterable, List, Optional

from mm.common.time import utc_ms
from mm.common.types import (
    CancelAck,
    CancelRequest,
    FillEvent,
    OrderAck,
    OrderRequest,
    OrderStatus,
    OrderUpdate,
)
from mm.oms.order import OrderRecord
from mm.oms.state import can_transition, is_terminal
from mm.persistence.event_log import JsonlEventLog
from mm.persistence.order_store import OrderStore


class OrderStateError(RuntimeError):
    pass


class OrderManager:
    def __init__(
        self,
        event_log: Optional[JsonlEventLog] = None,
        order_store: Optional[OrderStore] = None,
    ) -> None:
        self._orders: Dict[str, OrderRecord] = {
            order.client_order_id: order for order in order_store.load()
        } if order_store is not None else {}
        self._event_log = event_log
        self._order_store = order_store
        self._lock = None

    def get(self, client_order_id: str) -> Optional[OrderRecord]:
        return self._orders.get(client_order_id)

    def all_orders(self) -> List[OrderRecord]:
        return list(self._orders.values())

    def open_orders(self, symbol: Optional[str] = None) -> List[OrderRecord]:
        orders = []
        for order in self._orders.values():
            if symbol is not None and order.symbol != symbol:
                continue
            if not is_terminal(order.status) and order.status != OrderStatus.UNKNOWN:
                orders.append(order)
        return orders

    def total_open_notional(self, symbol: Optional[str] = None) -> Decimal:
        total = Decimal("0")
        for order in self.open_orders(symbol):
            total += order.open_notional
        return total

    async def submit(self, gateway: object, request: OrderRequest) -> OrderRecord:
        async with self._get_lock():
            record = self._orders.get(request.client_order_id)
            if record is None:
                record = OrderRecord.from_request(request)
                self._orders[request.client_order_id] = record
                self._persist(record)
                self._log("order.created", record)
            self._transition(record, OrderStatus.SUBMITTING, "submit started")
            self._log("order.submit.request", request)

        try:
            ack = await gateway.submit_order(request)
        except Exception as exc:
            async with self._get_lock():
                record = self._orders[request.client_order_id]
                self._transition(record, OrderStatus.UNKNOWN, "submit exception: {0}".format(exc))
                self._log("order.submit.exception", {"client_order_id": request.client_order_id, "error": str(exc)})
                return record

        async with self._get_lock():
            return self.apply_order_ack(ack)

    async def submit_batch(self, gateway: object, requests: List[OrderRequest]) -> List[OrderRecord]:
        if not requests:
            return []
        async with self._get_lock():
            for request in requests:
                record = self._orders.get(request.client_order_id)
                if record is None:
                    record = OrderRecord.from_request(request)
                    self._orders[request.client_order_id] = record
                    self._persist(record)
                    self._log("order.created", record)
                self._transition(record, OrderStatus.SUBMITTING, "batch submit started")
                self._log("order.submit.request", request)
        try:
            acks = await gateway.submit_batch_orders(requests)
        except Exception as exc:
            async with self._get_lock():
                records = []
                for request in requests:
                    record = self._orders[request.client_order_id]
                    self._transition(record, OrderStatus.UNKNOWN, "batch submit exception: {0}".format(exc))
                    records.append(record)
                self._log("order.submit_batch.exception", {"error": str(exc)})
                return records
        async with self._get_lock():
            return [self.apply_order_ack(ack) for ack in acks]

    async def cancel(self, gateway: object, request: CancelRequest) -> Optional[OrderRecord]:
        async with self._get_lock():
            record = self._orders.get(request.client_order_id)
            if record is None:
                self._log("order.cancel.missing", request)
                return None
            if is_terminal(record.status):
                return record
            self._transition(record, OrderStatus.CANCELING, request.reason or "cancel requested")
            self._log("order.cancel.request", request)

        try:
            ack = await gateway.cancel_order(request)
        except Exception as exc:
            async with self._get_lock():
                record = self._orders[request.client_order_id]
                self._transition(record, OrderStatus.UNKNOWN, "cancel exception: {0}".format(exc))
                self._log("order.cancel.exception", {"client_order_id": request.client_order_id, "error": str(exc)})
                return record

        async with self._get_lock():
            return self.apply_cancel_ack(ack)

    async def cancel_batch(self, gateway: object, requests: List[CancelRequest]) -> List[OrderRecord]:
        if not requests:
            return []
        active_requests: List[CancelRequest] = []
        async with self._get_lock():
            for request in requests:
                record = self._orders.get(request.client_order_id)
                if record is None:
                    self._log("order.cancel.missing", request)
                    continue
                if is_terminal(record.status):
                    continue
                self._transition(record, OrderStatus.CANCELING, request.reason or "batch cancel requested")
                self._log("order.cancel.request", request)
                active_requests.append(request)
        if not active_requests:
            return []
        try:
            acks = await gateway.cancel_batch_orders(active_requests)
        except Exception as exc:
            async with self._get_lock():
                records = []
                for request in active_requests:
                    record = self._orders[request.client_order_id]
                    self._transition(record, OrderStatus.UNKNOWN, "batch cancel exception: {0}".format(exc))
                    records.append(record)
                self._log("order.cancel_batch.exception", {"error": str(exc)})
                return records
        async with self._get_lock():
            return [self.apply_cancel_ack(ack) for ack in acks]

    def apply_order_ack(self, ack: OrderAck) -> OrderRecord:
        record = self._require(ack.client_order_id)
        record.exchange_order_id = ack.exchange_order_id or record.exchange_order_id
        if ack.accepted:
            target = ack.status
            if target in {OrderStatus.ACKED, OrderStatus.CREATED, OrderStatus.SUBMITTING}:
                target = OrderStatus.OPEN
            self._transition(record, target, ack.message)
        else:
            self._transition(record, OrderStatus.REJECTED, ack.message)
        self._log("order.submit.ack", ack)
        return record

    def apply_cancel_ack(self, ack: CancelAck) -> OrderRecord:
        record = self._require(ack.client_order_id)
        record.exchange_order_id = ack.exchange_order_id or record.exchange_order_id
        if ack.accepted:
            self._transition(record, ack.status, ack.message or "cancel ack")
        else:
            if record.status == OrderStatus.CANCELING:
                self._transition(record, OrderStatus.UNKNOWN, ack.message or "cancel rejected")
        self._log("order.cancel.ack", ack)
        return record

    def apply_order_update(self, update: OrderUpdate) -> OrderRecord:
        record = self._require(update.client_order_id)
        record.exchange_order_id = update.exchange_order_id or record.exchange_order_id
        record.filled_size = max(record.filled_size, update.filled_size)
        record.avg_fill_price = update.avg_fill_price or record.avg_fill_price
        self._transition(record, update.status, update.message)
        self._log("order.update", update)
        return record

    def apply_fill(self, fill: FillEvent) -> OrderRecord:
        record = self._require(fill.client_order_id)
        previous_size = record.filled_size
        new_size = previous_size + fill.size
        if new_size > record.size:
            new_size = record.size
        if record.avg_fill_price is None or previous_size <= 0:
            avg_price = fill.price
        else:
            avg_price = ((record.avg_fill_price * previous_size) + (fill.price * fill.size)) / new_size
        record.filled_size = new_size
        record.avg_fill_price = avg_price
        target = OrderStatus.FILLED if record.remaining_size <= Decimal("0") else OrderStatus.PARTIALLY_FILLED
        self._transition(record, target, "fill {0}".format(fill.trade_id))
        self._log("order.fill", fill)
        return record

    def mark_unknown(self, client_order_id: str, message: str) -> OrderRecord:
        record = self._require(client_order_id)
        self._transition(record, OrderStatus.UNKNOWN, message)
        self._log("order.unknown", {"client_order_id": client_order_id, "message": message})
        return record

    def apply_remote_order_update(self, update: OrderUpdate, source_message: str = "remote order update") -> OrderRecord:
        if update.client_order_id not in self._orders:
            record = self._orphan_record(update, source_message)
            self._orders[update.client_order_id] = record
            self._persist(record)
            self._log("order.orphan", record)
            return record
        return self.apply_order_update(update)

    def reconcile_open_orders(
        self,
        exchange_orders: Iterable[OrderUpdate],
        symbol: Optional[str] = None,
        mark_missing_local: bool = True,
    ) -> None:
        seen = set()
        for update in exchange_orders:
            seen.add(update.client_order_id)
            if update.client_order_id not in self._orders:
                record = self._orphan_record(update, "orphan order from exchange reconciliation")
                self._orders[update.client_order_id] = record
                self._persist(record)
                self._log("order.orphan", record)
            else:
                self.apply_order_update(update)
        if not mark_missing_local:
            return
        for record in self.open_orders(symbol):
            if record.client_order_id not in seen:
                self.mark_unknown(record.client_order_id, "local open order missing from exchange reconciliation")

    def _require(self, client_order_id: str) -> OrderRecord:
        record = self._orders.get(client_order_id)
        if record is None:
            raise KeyError("unknown client_order_id {0}".format(client_order_id))
        return record

    def _get_lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    def _transition(self, record: OrderRecord, new_status: OrderStatus, message: str = "") -> None:
        if not can_transition(record.status, new_status):
            raise OrderStateError(
                "invalid transition {0} -> {1} for {2}".format(
                    record.status.value,
                    new_status.value,
                    record.client_order_id,
                )
            )
        record.status = new_status
        record.updated_at_ms = utc_ms()
        record.last_message = message
        self._persist(record)

    def _log(self, event_type: str, payload: object) -> None:
        if self._event_log is not None:
            self._event_log.append(event_type, payload)

    def _persist(self, record: Optional[OrderRecord] = None) -> None:
        if self._order_store is not None:
            if record is not None and hasattr(self._order_store, "save_order"):
                self._order_store.save_order(record)
            else:
                self._order_store.save(self._orders.values())

    @staticmethod
    def _infer_side(client_order_id: str):
        if "-b-" in client_order_id:
            from mm.common.types import Side

            return Side.BUY
        from mm.common.types import Side

        return Side.SELL

    def _orphan_record(self, update: OrderUpdate, message: str) -> OrderRecord:
        return OrderRecord(
            symbol=update.symbol,
            side=update.side or self._infer_side(update.client_order_id),
            price=update.avg_fill_price,
            size=update.filled_size,
            order_type="unknown",
            client_order_id=update.client_order_id,
            strategy="orphan",
            level=None,
            status=OrderStatus.UNKNOWN,
            exchange_order_id=update.exchange_order_id,
            filled_size=update.filled_size,
            avg_fill_price=update.avg_fill_price,
            created_at_ms=update.timestamp_ms,
            updated_at_ms=update.timestamp_ms,
            last_message=message,
        )
