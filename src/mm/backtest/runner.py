from __future__ import annotations

import asyncio
from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, Iterable, List

from mm.common.decimal import D
from mm.common.types import Balance, MarketSnapshot
from mm.config.settings import AppSettings
from mm.persistence.replay import EventLogReplay
from mm.quote.engine import QuoteEngine
from mm.strategy.engine import StrategyEngine


@dataclass(frozen=True)
class BacktestSummary:
    event_log_path: str
    market_snapshots: int
    generated_quotes: int
    generated_order_intents: int
    symbols: List[str]


class EventLogBacktestRunner:
    def __init__(self, settings: AppSettings, event_log_path: str) -> None:
        self.settings = settings
        self.event_log_path = event_log_path
        self.strategy = StrategyEngine(settings.market_rules, settings.strategies)
        self.quote_engine = QuoteEngine(settings.market_rules, settings.min_requote_interval_ms)
        self.markets: Dict[str, MarketSnapshot] = {}

    async def run(self) -> BacktestSummary:
        balances = self._initial_balances()
        await self.strategy.on_balances(balances)
        snapshot_count = 0
        quote_count = 0
        intent_count = 0
        symbols = set()
        for event in EventLogReplay(self.event_log_path).events("market.snapshot"):
            snapshot = market_snapshot_from_payload(event.payload)
            self.markets[snapshot.symbol] = snapshot
            symbols.add(snapshot.symbol)
            await self.strategy.on_market(snapshot)
            quotes = await self.strategy.generate_quotes()
            intents = self.quote_engine.build_order_intents(quotes, [], self.markets)
            snapshot_count += 1
            quote_count += len(quotes)
            intent_count += len(intents)
        return BacktestSummary(
            event_log_path=self.event_log_path,
            market_snapshots=snapshot_count,
            generated_quotes=quote_count,
            generated_order_intents=intent_count,
            symbols=sorted(symbols),
        )

    def run_sync(self) -> BacktestSummary:
        return asyncio.run(self.run())

    def _initial_balances(self) -> List[Balance]:
        balances = []
        for currency, amount in self.settings.paper.get("balances", {}).items():
            balances.append(Balance(currency=currency, available=D(amount), frozen=Decimal("0")))
        return balances


def market_snapshot_from_payload(payload: Dict[str, object]) -> MarketSnapshot:
    return MarketSnapshot(
        symbol=str(payload["symbol"]),
        bid=D(payload["bid"]),
        bid_size=D(payload["bid_size"]),
        ask=D(payload["ask"]),
        ask_size=D(payload["ask_size"]),
        last=D(payload["last"]) if payload.get("last") is not None else None,
        exchange=str(payload.get("exchange", "replay")),
        timestamp_ms=int(payload.get("timestamp_ms", 0)),
        receive_time_ms=int(payload.get("receive_time_ms", 0)),
        bids=[(D(price), D(size)) for price, size in payload.get("bids", [])],
        asks=[(D(price), D(size)) for price, size in payload.get("asks", [])],
    )
