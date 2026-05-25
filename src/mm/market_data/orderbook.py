from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, Iterable, List, Optional, Tuple

from mm.common.decimal import D
from mm.common.time import utc_ms
from mm.common.types import MarketSnapshot


class OrderBookGap(RuntimeError):
    pass


@dataclass(frozen=True)
class DepthUpdate:
    symbol: str
    update_type: str
    version: int
    asks: List[Tuple[Decimal, Decimal]]
    bids: List[Tuple[Decimal, Decimal]]
    timestamp_ms: int


class OrderBook:
    def __init__(self, symbol: str) -> None:
        self.symbol = symbol
        self.asks: Dict[Decimal, Decimal] = {}
        self.bids: Dict[Decimal, Decimal] = {}
        self.version: Optional[int] = None
        self.last_update_ms: int = 0

    def apply(self, update: DepthUpdate) -> None:
        if update.symbol != self.symbol:
            raise ValueError("depth update symbol mismatch")
        if update.update_type == "snapshot":
            self.asks = self._levels_to_dict(update.asks)
            self.bids = self._levels_to_dict(update.bids)
            self.version = update.version
            self.last_update_ms = update.timestamp_ms
            return
        if self.version is None:
            raise OrderBookGap("received update before snapshot")
        if update.version <= self.version:
            return
        if update.version > self.version + 1:
            raise OrderBookGap("depth version gap {0}->{1}".format(self.version, update.version))
        self._apply_levels(self.asks, update.asks)
        self._apply_levels(self.bids, update.bids)
        self.version = update.version
        self.last_update_ms = update.timestamp_ms

    def snapshot(self, exchange: str = "bitmart", depth_levels: int = 100) -> MarketSnapshot:
        best_bid = max(self.bids.keys()) if self.bids else Decimal("0")
        best_ask = min(self.asks.keys()) if self.asks else Decimal("0")
        bids = self.top_bids(depth_levels)
        asks = self.top_asks(depth_levels)
        return MarketSnapshot(
            exchange=exchange,
            symbol=self.symbol,
            bid=best_bid,
            bid_size=self.bids.get(best_bid, Decimal("0")),
            ask=best_ask,
            ask_size=self.asks.get(best_ask, Decimal("0")),
            last=None,
            timestamp_ms=self.last_update_ms or utc_ms(),
            receive_time_ms=utc_ms(),
            bids=bids,
            asks=asks,
        )

    def top_bids(self, levels: int) -> List[Tuple[Decimal, Decimal]]:
        return [(price, self.bids[price]) for price in sorted(self.bids.keys(), reverse=True)[: max(0, levels)]]

    def top_asks(self, levels: int) -> List[Tuple[Decimal, Decimal]]:
        return [(price, self.asks[price]) for price in sorted(self.asks.keys())[: max(0, levels)]]

    @staticmethod
    def _levels_to_dict(levels: Iterable[Tuple[Decimal, Decimal]]) -> Dict[Decimal, Decimal]:
        return {price: size for price, size in levels if size > 0}

    @staticmethod
    def _apply_levels(book_side: Dict[Decimal, Decimal], levels: Iterable[Tuple[Decimal, Decimal]]) -> None:
        for price, size in levels:
            if size <= 0:
                book_side.pop(price, None)
            else:
                book_side[price] = size


def parse_depth_update(row: Dict[str, object]) -> DepthUpdate:
    return DepthUpdate(
        symbol=str(row["symbol"]),
        update_type=str(row.get("type", "update")),
        version=int(row["version"]),
        asks=[(D(price), D(size)) for price, size in row.get("asks", [])],
        bids=[(D(price), D(size)) for price, size in row.get("bids", [])],
        timestamp_ms=int(row.get("ms_t", utc_ms())),
    )
