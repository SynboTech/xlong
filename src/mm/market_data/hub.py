from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, Iterable, List, Optional

from mm.common.types import MarketSnapshot
from mm.market_data.fair_price import FairPrice, FairPriceEngine, FairPriceSource
from mm.market_data.orderbook import OrderBook, OrderBookGap, parse_depth_update


@dataclass(frozen=True)
class MarketDataStatus:
    symbols: List[str]
    orderbook_versions: Dict[str, Optional[int]]
    depth_levels: Dict[str, Dict[str, int]]
    stale_symbols: List[str]
    gap_count: int


class MarketDataHub:
    def __init__(self, symbols: Iterable[str], stale_ms: int) -> None:
        self.symbols = list(symbols)
        self.stale_ms = stale_ms
        self.orderbooks: Dict[str, OrderBook] = {symbol: OrderBook(symbol) for symbol in self.symbols}
        self.snapshots: Dict[str, MarketSnapshot] = {}
        self.external_snapshots: Dict[str, Dict[str, MarketSnapshot]] = {}
        self.fair_engine = FairPriceEngine(stale_ms)
        self.gap_count = 0

    def apply_snapshot(self, snapshot: MarketSnapshot) -> None:
        self.snapshots[snapshot.symbol] = snapshot

    def apply_external_snapshot(self, exchange: str, snapshot: MarketSnapshot) -> None:
        self.external_snapshots.setdefault(snapshot.symbol, {})[exchange] = snapshot

    def apply_bitmart_depth_row(self, row: Dict[str, object]) -> Optional[MarketSnapshot]:
        update = parse_depth_update(row)
        if update.symbol not in self.orderbooks:
            self.orderbooks[update.symbol] = OrderBook(update.symbol)
            if update.symbol not in self.symbols:
                self.symbols.append(update.symbol)
        try:
            self.orderbooks[update.symbol].apply(update)
        except OrderBookGap:
            self.gap_count += 1
            raise
        snapshot = self.orderbooks[update.symbol].snapshot(exchange="bitmart")
        self.snapshots[update.symbol] = snapshot
        return snapshot

    def market(self, symbol: str) -> Optional[MarketSnapshot]:
        return self.snapshots.get(symbol)

    def fair_price(self, symbol: str, weights: Optional[Dict[str, Decimal]] = None) -> Optional[FairPrice]:
        weights = weights or {}
        sources: List[FairPriceSource] = []
        local = self.snapshots.get(symbol)
        if local is not None:
            sources.append(FairPriceSource(local.exchange, weights.get(local.exchange, Decimal("1")), local))
        for exchange, snapshot in self.external_snapshots.get(symbol, {}).items():
            sources.append(FairPriceSource(exchange, weights.get(exchange, Decimal("1")), snapshot))
        return self.fair_engine.compute(symbol, sources)

    def status(self) -> MarketDataStatus:
        stale = [
            symbol
            for symbol, snapshot in self.snapshots.items()
            if snapshot.age_ms > self.stale_ms
        ]
        return MarketDataStatus(
            symbols=list(self.symbols),
            orderbook_versions={
                symbol: book.version for symbol, book in self.orderbooks.items()
            },
            depth_levels={
                symbol: {"bids": len(book.bids), "asks": len(book.asks)}
                for symbol, book in self.orderbooks.items()
            },
            stale_symbols=stale,
            gap_count=self.gap_count,
        )
