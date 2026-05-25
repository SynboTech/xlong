from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal
from typing import Any, Dict, List, Optional

from mm.common.decimal import D, decimal_to_str
from mm.common.time import utc_ms
from mm.common.types import (
    Balance,
    CancelAck,
    CancelRequest,
    MarketRule,
    MarketSnapshot,
    OrderAck,
    OrderRequest,
    OrderStatus,
    OrderUpdate,
    Side,
)
from mm.config.settings import BitMartCredentials
from mm.exchange.base import ExchangeGateway
from mm.exchange.bitmart.signer import sign, stable_json
from mm.exchange.rate_limit import SlidingWindowRateLimiter


class BitMartApiError(RuntimeError):
    pass


class BitMartRestGateway(ExchangeGateway):
    name = "bitmart"

    def __init__(
        self,
        credentials: BitMartCredentials,
        base_url: str = "https://api-cloud.bitmart.com",
        timeout_sec: float = 5.0,
    ) -> None:
        self.credentials = credentials
        self.base_url = base_url.rstrip("/")
        self.timeout_sec = timeout_sec
        self._default_limiter = SlidingWindowRateLimiter(40, 2.0)
        self._open_orders_limiter = SlidingWindowRateLimiter(12, 2.0)
        self._query_order_limiter = SlidingWindowRateLimiter(50, 2.0)
        self._cancel_all_limiter = SlidingWindowRateLimiter(1, 3.0)

    async def load_markets(self) -> Dict[str, MarketRule]:
        data = await self._request_async("GET", "/spot/v1/symbols/details")
        result = {}
        for item in data.get("symbols", []):
            symbol = item["symbol"]
            result[symbol] = MarketRule(
                symbol=symbol,
                base=item.get("base_currency", ""),
                quote=item.get("quote_currency", ""),
                price_increment=D(item.get("quote_increment", "0.00000001")),
                size_increment=D(item.get("base_min_size", "0.00000001")),
                base_min_size=D(item.get("base_min_size", "0")),
                min_notional=D(item.get("min_buy_amount", "0")),
            )
        return result

    async def get_balances(self) -> List[Balance]:
        data = await self._request_async("GET", "/spot/v1/wallet", keyed=True)
        wallets = data.get("wallet", [])
        balances = []
        for item in wallets:
            balances.append(
                Balance(
                    currency=item.get("id") or item.get("currency", ""),
                    available=D(item.get("available", "0")),
                    frozen=D(item.get("frozen", "0")),
                )
            )
        return balances

    async def get_open_orders(self, symbol: Optional[str] = None) -> List[OrderUpdate]:
        body: Dict[str, Any] = {"limit": 200, "recvWindow": 5000}
        if symbol:
            body["symbol"] = symbol
        data = await self._request_async("POST", "/spot/v4/query/open-orders", body=body, signed=True)
        rows = data.get("orders", data if isinstance(data, list) else [])
        return [self._parse_order_update(item) for item in rows]

    async def next_market_snapshot(self, symbol: str) -> MarketSnapshot:
        book = await self._request_async("GET", "/spot/quotation/v3/books", params={"symbol": symbol, "limit": 5})
        bids = self._parse_levels(book.get("bids") or book.get("buys") or book.get("bid") or [])
        asks = self._parse_levels(book.get("asks") or book.get("sells") or book.get("ask") or [])
        if not bids or not asks:
            raise BitMartApiError("BitMart book response has no bid/ask levels for {0}".format(symbol))
        last = None
        try:
            ticker = await self._request_async("GET", "/spot/quotation/v3/ticker", params={"symbol": symbol})
            last_value = ticker.get("last") or ticker.get("last_price") or ticker.get("lastPrice")
            if last_value:
                last = D(last_value)
        except Exception:
            last = None
        bid, bid_size = bids[0]
        ask, ask_size = asks[0]
        return MarketSnapshot(
            symbol=symbol,
            bid=bid,
            bid_size=bid_size,
            ask=ask,
            ask_size=ask_size,
            last=last,
            exchange=self.name,
            timestamp_ms=utc_ms(),
            receive_time_ms=utc_ms(),
            bids=bids,
            asks=asks,
        )

    async def query_order(self, client_order_id: str, exchange_order_id: Optional[str] = None) -> OrderUpdate:
        body: Dict[str, Any] = {"queryState": "open", "recvWindow": 5000}
        if exchange_order_id:
            body["orderId"] = exchange_order_id
            path = "/spot/v4/query/order"
        else:
            body["clientOrderId"] = client_order_id
            path = "/spot/v4/query/client-order"
        try:
            data = await self._request_async("POST", path, body=body, signed=True)
        except Exception:
            body["queryState"] = "history"
            data = await self._request_async("POST", path, body=body, signed=True)
        return self._parse_order_update(data)

    async def submit_order(self, request: OrderRequest) -> OrderAck:
        body: Dict[str, Any] = {
            "symbol": request.symbol,
            "side": request.side.value,
            "type": request.order_type.value,
            "size": decimal_to_str(request.size),
            "client_order_id": request.client_order_id,
            "stpMode": request.stp_mode,
            "recvWindow": 5000,
        }
        if request.price is not None:
            body["price"] = decimal_to_str(request.price)
        try:
            data = await self._request_async("POST", "/spot/v2/submit_order", body=body, signed=True)
        except Exception as exc:
            return OrderAck(False, request.client_order_id, None, OrderStatus.UNKNOWN, str(exc))
        return OrderAck(
            accepted=True,
            client_order_id=request.client_order_id,
            exchange_order_id=str(data.get("order_id") or data.get("orderId") or ""),
            status=OrderStatus.OPEN,
            message="bitmart accepted",
            raw=data,
        )

    async def submit_batch_orders(self, requests: List[OrderRequest]) -> List[OrderAck]:
        if not requests:
            return []
        grouped = self._group_requests_by_symbol(requests)
        if len(grouped) > 1:
            acks: List[OrderAck] = []
            for batch in grouped.values():
                acks.extend(await self.submit_batch_orders(batch))
            return acks
        symbol = requests[0].symbol
        body = {
            "symbol": symbol,
            "orderParams": [self._batch_order_param(request) for request in requests],
            "recvWindow": 5000,
        }
        try:
            data = await self._request_async("POST", "/spot/v4/batch_orders", body=body, signed=True)
        except Exception as exc:
            return [
                OrderAck(False, request.client_order_id, None, OrderStatus.UNKNOWN, str(exc))
                for request in requests
            ]
        nested = data.get("data", data)
        rows = nested.get("orderIds") or nested.get("orders") or data.get("orderIds") or data.get("orders") or []
        acks: List[OrderAck] = []
        for idx, request in enumerate(requests):
            row = rows[idx] if idx < len(rows) else {}
            if isinstance(row, str):
                exchange_order_id = row
            else:
                exchange_order_id = str(row.get("order_id") or row.get("orderId") or "")
            acks.append(
                OrderAck(
                    True,
                    request.client_order_id,
                    exchange_order_id,
                    OrderStatus.OPEN,
                    "bitmart batch accepted",
                    data,
                )
            )
        return acks

    async def cancel_order(self, request: CancelRequest) -> CancelAck:
        body: Dict[str, Any] = {"symbol": request.symbol, "recvWindow": 5000}
        if request.exchange_order_id:
            body["order_id"] = request.exchange_order_id
        else:
            body["client_order_id"] = request.client_order_id
        try:
            data = await self._request_async("POST", "/spot/v3/cancel_order", body=body, signed=True)
        except Exception as exc:
            return CancelAck(False, request.client_order_id, request.exchange_order_id, OrderStatus.UNKNOWN, str(exc))
        return CancelAck(
            accepted=True,
            client_order_id=request.client_order_id,
            exchange_order_id=request.exchange_order_id,
            status=OrderStatus.CANCELED,
            message="bitmart cancel accepted",
            raw=data,
        )

    async def cancel_batch_orders(self, requests: List[CancelRequest]) -> List[CancelAck]:
        if not requests:
            return []
        grouped = self._group_requests_by_symbol(requests)
        if len(grouped) > 1:
            acks: List[CancelAck] = []
            for batch in grouped.values():
                acks.extend(await self.cancel_batch_orders(batch))
            return acks
        symbol = requests[0].symbol
        body: Dict[str, Any] = {"symbol": symbol, "recvWindow": 5000}
        if all(request.exchange_order_id for request in requests):
            body["orderIds"] = [request.exchange_order_id for request in requests]
        else:
            body["clientOrderIds"] = [request.client_order_id for request in requests]
        try:
            data = await self._request_async("POST", "/spot/v4/cancel_orders", body=body, signed=True)
        except Exception as exc:
            return [
                CancelAck(False, request.client_order_id, request.exchange_order_id, OrderStatus.UNKNOWN, str(exc))
                for request in requests
            ]
        return [
            CancelAck(
                True,
                request.client_order_id,
                request.exchange_order_id,
                OrderStatus.CANCELED,
                "bitmart batch cancel accepted",
                data,
            )
            for request in requests
        ]

    async def cancel_all(self, symbol: Optional[str] = None) -> List[CancelAck]:
        body: Dict[str, Any] = {"recvWindow": 5000}
        if symbol:
            body["symbol"] = symbol
        data = await self._request_async("POST", "/spot/v4/cancel_all", body=body, signed=True)
        return [
            CancelAck(True, "*", None, OrderStatus.CANCELED, "cancel_all submitted", data)
        ]

    async def _request_async(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        body: Optional[Dict[str, Any]] = None,
        keyed: bool = False,
        signed: bool = False,
    ) -> Any:
        return await asyncio.to_thread(self._request, method, path, params, body, keyed, signed)

    def _request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        body: Optional[Dict[str, Any]] = None,
        keyed: bool = False,
        signed: bool = False,
    ) -> Any:
        if (keyed or signed) and not self.credentials.present:
            raise BitMartApiError("BitMart credentials are required")
        self._limiter_for(path).wait()
        query = ""
        if params:
            query = "?" + urllib.parse.urlencode(params)
        url = self.base_url + path + query
        payload = stable_json(body) if body is not None else None
        headers = {"Content-Type": "application/json"}
        if keyed or signed:
            headers["X-BM-KEY"] = self.credentials.api_key
        if signed:
            ts = utc_ms()
            headers["X-BM-TIMESTAMP"] = str(ts)
            headers["X-BM-SIGN"] = sign(ts, self.credentials.api_memo, payload or "", self.credentials.api_secret)
        request = urllib.request.Request(
            url=url,
            method=method,
            data=payload.encode("utf-8") if payload is not None else None,
            headers=headers,
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_sec) as response:
                text = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise BitMartApiError("HTTP {0}: {1}".format(exc.code, detail))
        response_data = json.loads(text)
        if response_data.get("code") != 1000:
            raise BitMartApiError("BitMart code {0}: {1}".format(response_data.get("code"), response_data.get("message")))
        return response_data.get("data", {})

    def _limiter_for(self, path: str) -> SlidingWindowRateLimiter:
        if path == "/spot/v4/query/open-orders":
            return self._open_orders_limiter
        if path in {"/spot/v4/query/order", "/spot/v4/query/client-order"}:
            return self._query_order_limiter
        if path == "/spot/v4/cancel_all":
            return self._cancel_all_limiter
        return self._default_limiter

    @staticmethod
    def _parse_levels(rows: Any) -> List[tuple[Decimal, Decimal]]:
        levels: List[tuple[Decimal, Decimal]] = []
        for row in rows or []:
            if isinstance(row, dict):
                price = row.get("price") or row.get("px")
                size = row.get("size") or row.get("amount") or row.get("quantity") or row.get("qty")
            else:
                price = row[0] if len(row) > 0 else None
                size = row[1] if len(row) > 1 else None
            if price is None or size is None:
                continue
            levels.append((D(price), D(size)))
        return levels

    def rate_limit_report(self) -> Dict[str, Any]:
        return {
            "default_40_per_2s": self._default_limiter.snapshot(),
            "open_orders_12_per_2s": self._open_orders_limiter.snapshot(),
            "query_order_50_per_2s": self._query_order_limiter.snapshot(),
            "cancel_all_1_per_3s": self._cancel_all_limiter.snapshot(),
        }

    @staticmethod
    def _group_requests_by_symbol(requests: List[Any]) -> Dict[str, List[Any]]:
        grouped: Dict[str, List[Any]] = {}
        for request in requests:
            grouped.setdefault(request.symbol, []).append(request)
        return grouped

    @staticmethod
    def _batch_order_param(request: OrderRequest) -> Dict[str, Any]:
        row: Dict[str, Any] = {
            "clientOrderId": request.client_order_id,
            "size": decimal_to_str(request.size),
            "side": request.side.value,
            "type": request.order_type.value,
            "stpMode": request.stp_mode,
        }
        if request.price is not None:
            row["price"] = decimal_to_str(request.price)
        return row

    @staticmethod
    def _parse_order_update(item: Dict[str, Any]) -> OrderUpdate:
        state = str(item.get("order_state") or item.get("state") or "new")
        mapping = {
            "new": OrderStatus.OPEN,
            "partially_filled": OrderStatus.PARTIALLY_FILLED,
            "filled": OrderStatus.FILLED,
            "canceled": OrderStatus.CANCELED,
            "partially_canceled": OrderStatus.PARTIALLY_CANCELED,
            "failed": OrderStatus.REJECTED,
        }
        return OrderUpdate(
            symbol=str(item.get("symbol", "")),
            client_order_id=str(item.get("client_order_id") or item.get("clientOrderId") or ""),
            exchange_order_id=str(item.get("order_id") or item.get("orderId") or ""),
            status=mapping.get(state, OrderStatus.UNKNOWN),
            filled_size=D(item.get("filled_size", item.get("filledSize", "0"))),
            avg_fill_price=D(item.get("priceAvg", item.get("price", "0"))) if item.get("price") or item.get("priceAvg") else None,
            message="bitmart order update",
            side=Side(str(item.get("side"))) if item.get("side") in {"buy", "sell"} else None,
        )
