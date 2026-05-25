from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Dict

from mm.common.decimal import D
from mm.common.time import utc_ms
from mm.common.types import MarketSnapshot


class ExternalMarketDataProvider:
    name = "external"

    async def book_ticker(self, symbol: str) -> MarketSnapshot:
        raise NotImplementedError


class BinanceBookTickerProvider(ExternalMarketDataProvider):
    name = "binance"

    def __init__(self, base_url: str = "https://api.binance.com", timeout_sec: float = 5.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_sec = timeout_sec

    async def book_ticker(self, symbol: str) -> MarketSnapshot:
        binance_symbol = symbol.replace("_", "")
        query = urllib.parse.urlencode({"symbol": binance_symbol})
        url = "{0}/api/v3/ticker/bookTicker?{1}".format(self.base_url, query)
        with urllib.request.urlopen(url, timeout=self.timeout_sec) as response:
            data = json.loads(response.read().decode("utf-8"))
        return parse_binance_book_ticker(symbol, data)


def parse_binance_book_ticker(symbol: str, data: Dict[str, object]) -> MarketSnapshot:
    now = utc_ms()
    return MarketSnapshot(
        exchange="binance",
        symbol=symbol,
        bid=D(data["bidPrice"]),
        bid_size=D(data["bidQty"]),
        ask=D(data["askPrice"]),
        ask_size=D(data["askQty"]),
        last=None,
        timestamp_ms=now,
        receive_time_ms=now,
    )

