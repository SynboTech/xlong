from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from mm.common.types import OrderStatus
from mm.oms.manager import OrderManager


@dataclass(frozen=True)
class ReconciliationReport:
    symbol: Optional[str]
    exchange_open_count: int
    local_open_count_before: int
    local_open_count_after: int
    unknown_count: int
    orphan_count: int


class ReconciliationService:
    def __init__(self, oms: OrderManager, gateway: object) -> None:
        self.oms = oms
        self.gateway = gateway

    async def reconcile_open_orders(self, symbol: Optional[str] = None) -> ReconciliationReport:
        before_ids = {order.client_order_id for order in self.oms.open_orders(symbol)}
        exchange_updates = await self.gateway.get_open_orders(symbol)
        known_before = {order.client_order_id for order in self.oms.all_orders()}
        self.oms.reconcile_open_orders(
            exchange_updates,
            symbol=symbol,
            mark_missing_local=bool(getattr(self.gateway, "reconcile_missing_local_orders", True)),
        )
        after_open = self.oms.open_orders(symbol)
        unknown_count = sum(
            1
            for order in self.oms.all_orders()
            if order.status == OrderStatus.UNKNOWN and (symbol is None or order.symbol == symbol)
        )
        exchange_ids = {update.client_order_id for update in exchange_updates}
        orphan_count = len([client_id for client_id in exchange_ids if client_id not in known_before])
        return ReconciliationReport(
            symbol=symbol,
            exchange_open_count=len(exchange_updates),
            local_open_count_before=len(before_ids),
            local_open_count_after=len(after_open),
            unknown_count=unknown_count,
            orphan_count=orphan_count,
        )

    async def repair_unknown_orders(self) -> List[str]:
        repaired: List[str] = []
        for order in list(self.oms.all_orders()):
            if order.status != OrderStatus.UNKNOWN:
                continue
            update = await self.gateway.query_order(order.client_order_id, order.exchange_order_id)
            if update.status != OrderStatus.UNKNOWN:
                self.oms.apply_order_update(update)
                repaired.append(order.client_order_id)
        return repaired
