from __future__ import annotations

from typing import List, Optional

from mm.common.types import CancelRequest
from mm.oms.manager import OrderManager


class KillSwitch:
    def __init__(self, oms: OrderManager) -> None:
        self.oms = oms

    def build_cancel_requests(self, symbol: Optional[str] = None, reason: str = "kill_switch") -> List[CancelRequest]:
        requests = []
        for order in self.oms.open_orders(symbol):
            requests.append(
                CancelRequest(
                    symbol=order.symbol,
                    client_order_id=order.client_order_id,
                    exchange_order_id=order.exchange_order_id,
                    reason=reason,
                )
            )
        return requests

