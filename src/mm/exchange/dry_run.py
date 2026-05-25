from __future__ import annotations

import itertools
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
    OrderStatus,
    OrderUpdate,
)
from mm.exchange.base import ExchangeGateway


class DryRunExchange(ExchangeGateway):
    name = "dry_run"
    reconcile_missing_local_orders = False

    def __init__(self, wrapped: ExchangeGateway, market_data_fallback: Optional[ExchangeGateway] = None) -> None:
        self.wrapped = wrapped
        self.market_data_fallback = market_data_fallback
        self.submitted: List[OrderRequest] = []
        self.canceled: List[CancelRequest] = []
        self._order_id = itertools.count(1)

    async def connect(self) -> None:
        await self.wrapped.connect()
        if self.market_data_fallback is not None:
            await self.market_data_fallback.connect()

    async def close(self) -> None:
        await self.wrapped.close()
        if self.market_data_fallback is not None:
            await self.market_data_fallback.close()

    async def load_markets(self) -> Dict[str, MarketRule]:
        return await self.wrapped.load_markets()

    async def get_balances(self) -> List[Balance]:
        return await self.wrapped.get_balances()

    async def get_open_orders(self, symbol: Optional[str] = None) -> List[OrderUpdate]:
        return await self.wrapped.get_open_orders(symbol)

    async def query_order(self, client_order_id: str, exchange_order_id: Optional[str] = None) -> OrderUpdate:
        return await self.wrapped.query_order(client_order_id, exchange_order_id)

    async def submit_order(self, request: OrderRequest) -> OrderAck:
        self.submitted.append(request)
        return OrderAck(
            accepted=True,
            client_order_id=request.client_order_id,
            exchange_order_id="dry-run-{0}".format(next(self._order_id)),
            status=OrderStatus.OPEN,
            message="dry-run submit accepted locally; not sent to exchange",
        )

    async def submit_batch_orders(self, requests: List[OrderRequest]) -> List[OrderAck]:
        return [await self.submit_order(request) for request in requests]

    async def cancel_order(self, request: CancelRequest) -> CancelAck:
        self.canceled.append(request)
        return CancelAck(
            accepted=True,
            client_order_id=request.client_order_id,
            exchange_order_id=request.exchange_order_id,
            status=OrderStatus.CANCELED,
            message="dry-run cancel accepted locally; not sent to exchange",
        )

    async def cancel_batch_orders(self, requests: List[CancelRequest]) -> List[CancelAck]:
        return [await self.cancel_order(request) for request in requests]

    async def cancel_all(self, symbol: Optional[str] = None) -> List[CancelAck]:
        return []

    async def next_market_snapshot(self, symbol: str) -> MarketSnapshot:
        if self.market_data_fallback is None:
            return await self.wrapped.next_market_snapshot(symbol)
        return await self.market_data_fallback.next_market_snapshot(symbol)

    async def simulate_fills(self, snapshot: MarketSnapshot) -> List[FillEvent]:
        if self.market_data_fallback is None:
            return []
        return await self.market_data_fallback.simulate_fills(snapshot)
