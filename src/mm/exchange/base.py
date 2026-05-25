from __future__ import annotations

from typing import Dict, List, Optional

from mm.common.types import (
    Balance,
    CancelAck,
    CancelRequest,
    FillEvent,
    MarketRule,
    MarketSnapshot,
    OrderAck,
    OrderRequest,
    OrderUpdate,
)


class ExchangeGateway:
    name = "base"

    async def connect(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def load_markets(self) -> Dict[str, MarketRule]:
        raise NotImplementedError

    async def get_balances(self) -> List[Balance]:
        raise NotImplementedError

    async def get_open_orders(self, symbol: Optional[str] = None) -> List[OrderUpdate]:
        raise NotImplementedError

    async def query_order(self, client_order_id: str, exchange_order_id: Optional[str] = None) -> OrderUpdate:
        raise NotImplementedError

    async def submit_order(self, request: OrderRequest) -> OrderAck:
        raise NotImplementedError

    async def submit_batch_orders(self, requests: List[OrderRequest]) -> List[OrderAck]:
        return [await self.submit_order(request) for request in requests]

    async def cancel_order(self, request: CancelRequest) -> CancelAck:
        raise NotImplementedError

    async def cancel_batch_orders(self, requests: List[CancelRequest]) -> List[CancelAck]:
        return [await self.cancel_order(request) for request in requests]

    async def cancel_all(self, symbol: Optional[str] = None) -> List[CancelAck]:
        raise NotImplementedError

    async def next_market_snapshot(self, symbol: str) -> MarketSnapshot:
        raise NotImplementedError

    async def simulate_fills(self, snapshot: MarketSnapshot) -> List[FillEvent]:
        return []
