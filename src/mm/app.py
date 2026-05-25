from __future__ import annotations

import asyncio
import json
import os
import tempfile
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Callable, Dict, List, Optional

from mm.accounting.pnl import PnlTracker
from mm.common.time import utc_ms
from mm.common.types import CancelRequest, MarketSnapshot, OrderIntent, OrderRequest, TradingMode, to_jsonable
from mm.config.settings import AppSettings
from mm.exchange.base import ExchangeGateway
from mm.exchange.bitmart.private_stream import BitMartPrivateStreamProcessor
from mm.exchange.bitmart.rest import BitMartRestGateway
from mm.exchange.bitmart.ws_client import WebSocketDependencyError, private_client
from mm.exchange.dry_run import DryRunExchange
from mm.exchange.paper import PaperExchange
from mm.hedging.engine import HedgingEngine
from mm.inventory.manager import InventoryManager
from mm.market_data.hub import MarketDataHub
from mm.monitoring.health import HealthChecker
from mm.monitoring.metrics import MetricsRegistry
from mm.monitoring.snapshot import build_runtime_snapshot
from mm.oms.manager import OrderManager
from mm.oms.reconcile import ReconciliationService
from mm.persistence.event_log import JsonlEventLog
from mm.persistence.order_store import build_order_store
from mm.quote.engine import QuoteEngine
from mm.risk.engine import RiskEngine
from mm.runtime.control import RuntimeControlReader
from mm.strategy.engine import StrategyEngine


@dataclass
class RunSummary:
    ticks: int
    orders_total: int
    open_orders: int
    fills: int
    rejected_intents: int
    safe_mode: bool


class MarketMakerApp:
    def __init__(
        self,
        settings: AppSettings,
        private_stream_client_factory: Optional[Callable[[List[str], object], Any]] = None,
    ) -> None:
        self.settings = settings
        self.event_log = JsonlEventLog(settings.event_log_path)
        self.order_store = build_order_store(settings.order_store_path)
        self.gateway = self._build_gateway()
        self.inventory = InventoryManager()
        self.oms = OrderManager(self.event_log, self.order_store)
        self.reconciliation = ReconciliationService(self.oms, self.gateway)
        self.risk = RiskEngine(settings.risk, settings.market_rules, settings.stale_market_data_ms)
        self.strategy = StrategyEngine(settings.market_rules, settings.strategies)
        self.quote_engine = QuoteEngine(settings.market_rules, settings.min_requote_interval_ms)
        self.pnl = PnlTracker()
        self.market_data = MarketDataHub(settings.symbols, settings.stale_market_data_ms)
        self.metrics = MetricsRegistry()
        self.hedging = self._build_hedging_engine()
        self.runtime_controls = RuntimeControlReader(settings.strategy_state_path, settings.risk_state_path)
        self.markets: Dict[str, MarketSnapshot] = {}
        self._fills = 0
        self._rejected = 0
        self._stop_requested = False
        self._private_stream_client_factory = private_stream_client_factory or private_client
        self._private_stream_task: Optional[asyncio.Task] = None
        self._internal_safe_mode_reasons: Dict[str, str] = {}

    async def run(self, ticks: Optional[int] = 10) -> RunSummary:
        await self.gateway.connect()
        self._start_private_stream()
        start_order_count = len(self.oms.all_orders())
        ticks_done = 0
        try:
            await self._refresh_balances()
            for symbol in self.settings.symbols:
                report = await self.reconciliation.reconcile_open_orders(symbol)
                self.event_log.append("oms.reconcile.startup", report)
                if report.unknown_count > 0:
                    self._enter_internal_safe_mode(
                        "startup_reconciliation",
                        "startup reconciliation has UNKNOWN orders",
                    )
            while not self._stop_requested and (ticks is None or ticks_done < ticks):
                await self.tick_once()
                ticks_done += 1
                await asyncio.sleep(self.settings.quote_interval_ms / 1000)
        finally:
            if self.settings.cancel_on_shutdown:
                await self.cancel_all("shutdown")
            await self._stop_private_stream()
            await self.gateway.close()
        return RunSummary(
            ticks=ticks_done,
            orders_total=max(0, len(self.oms.all_orders()) - start_order_count),
            open_orders=len(self.oms.open_orders()),
            fills=self._fills,
            rejected_intents=self._rejected,
            safe_mode=self.risk.safe_mode,
        )

    def request_stop(self) -> None:
        self._stop_requested = True

    def health(self):
        return HealthChecker(self.market_data, self.oms, self.risk).check()

    def runtime_snapshot(self):
        return build_runtime_snapshot(
            self.settings.trading_mode.value,
            self.settings.symbols,
            self.health(),
            self.oms,
            self.inventory,
            self.pnl,
            self.market_data,
            self.metrics,
        )

    async def tick_once(self) -> None:
        self._apply_runtime_controls()
        await self._apply_runtime_commands()
        for symbol in self.settings.symbols:
            market = await self.gateway.next_market_snapshot(symbol)
            self.markets[symbol] = market
            self.market_data.apply_snapshot(market)
            self.metrics.set("market_data_lag_ms", market.age_ms, symbol=symbol, exchange=market.exchange)
            self.event_log.append("market.snapshot", market)
            await self.strategy.on_market(market)

            fills = await self.gateway.simulate_fills(market)
            for fill in fills:
                self.oms.apply_fill(fill)
                self.pnl.apply_fill(fill)
                hedge_intent = self.hedging.intent_from_fill(fill)
                if hedge_intent is not None:
                    hedge_result = await self.hedging.execute(hedge_intent)
                    self.event_log.append("hedge.result", hedge_result)
                self._fills += 1
                self.metrics.inc("fill_count", symbol=fill.symbol, side=fill.side.value)

        await self._refresh_balances()
        self.risk.daily_pnl = self.pnl.total_pnl(self.markets)
        self.metrics.set("daily_pnl", self.risk.daily_pnl)
        self.event_log.append("account.pnl", self.pnl.snapshot(self.markets))
        quotes = await self.strategy.generate_quotes()
        self.event_log.append("strategy.quotes", quotes)
        intents = self.quote_engine.build_order_intents(quotes, self.oms.open_orders(), self.markets)
        self.event_log.append("quote.order_intents", intents)
        await self._execute_intents(intents)

    async def cancel_all(self, reason: str) -> None:
        requests = [
            CancelRequest(
                symbol=order.symbol,
                client_order_id=order.client_order_id,
                exchange_order_id=order.exchange_order_id,
                reason=reason,
            )
            for order in list(self.oms.open_orders())
        ]
        await self.oms.cancel_batch(self.gateway, requests)

    async def _execute_intents(self, intents: List[OrderIntent]) -> None:
        cancel_intents = [intent for intent in intents if intent.action == "cancel"]
        place_intents = [intent for intent in intents if intent.action == "place"]
        cancel_requests: List[CancelRequest] = []
        for intent in cancel_intents:
            result = self.risk.validate(intent, self.markets, self.inventory, self.oms)
            self.event_log.append("risk.result", result)
            if not result.approved:
                self._rejected += 1
                continue
            if intent.client_order_id is None:
                continue
            cancel_requests.append(
                CancelRequest(
                    symbol=intent.symbol,
                    client_order_id=intent.client_order_id,
                    reason=intent.reason,
                )
            )
        for batch in self._group_by_symbol(cancel_requests).values():
            await self.oms.cancel_batch(self.gateway, batch)
        self.metrics.inc("cancel_request_count", len(cancel_requests))

        place_requests: List[OrderRequest] = []
        for intent in place_intents:
            result = self.risk.validate(intent, self.markets, self.inventory, self.oms)
            self.event_log.append("risk.result", result)
            if not result.approved:
                self._rejected += 1
                continue
            if intent.action == "place":
                place_requests.append(self._request_from_intent(intent))
        for batch in self._group_by_symbol(place_requests).values():
            await self.oms.submit_batch(self.gateway, batch)
        self.metrics.inc("place_request_count", len(place_requests))
        await self._refresh_balances()

    def _apply_runtime_controls(self) -> None:
        controls = self.runtime_controls.load()
        self.strategy.set_paused_strategies(controls.paused_strategy_keys)
        if controls.safe_mode:
            self.risk.enter_safe_mode(controls.safe_mode_reason or "admin safe mode")
        elif self._internal_safe_mode_reasons:
            self.risk.enter_safe_mode(self._internal_safe_mode_reason())
        else:
            self.risk.exit_safe_mode()

    def _enter_internal_safe_mode(self, key: str, reason: str) -> None:
        self._internal_safe_mode_reasons[key] = reason
        self.risk.enter_safe_mode(self._internal_safe_mode_reason())

    def _internal_safe_mode_reason(self) -> str:
        return "; ".join(self._internal_safe_mode_reasons[key] for key in sorted(self._internal_safe_mode_reasons))

    async def _apply_runtime_commands(self) -> None:
        payload = self._read_runtime_commands()
        commands = payload.get("commands", [])
        if not isinstance(commands, list):
            return
        for command in commands:
            if not isinstance(command, dict) or command.get("status") != "pending":
                continue
            command["status"] = "processing"
            command["started_at_ms"] = utc_ms()
            self._write_runtime_commands(payload)
            try:
                result = await self._execute_runtime_command(command)
                command["status"] = "done"
                command["result"] = to_jsonable(result)
            except Exception as exc:
                command["status"] = "failed"
                command["error"] = str(exc)
                self._enter_internal_safe_mode(
                    "runtime_command_{0}".format(command.get("id", "unknown")),
                    "runtime command failed: {0}".format(exc),
                )
            command["finished_at_ms"] = utc_ms()
            self._write_runtime_commands(payload)

    async def _execute_runtime_command(self, command: Dict[str, Any]) -> Dict[str, Any]:
        command_type = str(command.get("type") or "")
        if command_type != "stop_cancel_strategy":
            raise ValueError("unknown runtime command type {0}".format(command_type))
        requests = self._cancel_requests_from_command(command)
        records = []
        for batch in self._group_by_symbol(requests).values():
            records.extend(await self.oms.cancel_batch(self.gateway, batch))
        self.event_log.append("runtime.command.executed", {"command": command, "records": records})
        return {"request_count": len(requests), "records": records}

    def _cancel_requests_from_command(self, command: Dict[str, Any]) -> List[CancelRequest]:
        requests_by_client_id: Dict[str, CancelRequest] = {}
        for item in command.get("requests", []):
            if not isinstance(item, dict):
                continue
            client_order_id = str(item.get("client_order_id") or "")
            symbol = str(item.get("symbol") or "")
            if not client_order_id or not symbol:
                continue
            requests_by_client_id[client_order_id] = CancelRequest(
                symbol=symbol,
                client_order_id=client_order_id,
                exchange_order_id=item.get("exchange_order_id"),
                reason="runtime command {0}".format(command.get("id", "")),
            )
        strategy_key = str(command.get("strategy") or command.get("key") or "")
        strategy_aliases = set(str(item) for item in command.get("strategy_aliases", []) if item)
        if strategy_key:
            strategy_aliases.add(strategy_key)
        for order in self.oms.open_orders():
            if strategy_aliases and order.strategy not in strategy_aliases:
                continue
            requests_by_client_id.setdefault(
                order.client_order_id,
                CancelRequest(
                    symbol=order.symbol,
                    client_order_id=order.client_order_id,
                    exchange_order_id=order.exchange_order_id,
                    reason="runtime command {0}".format(command.get("id", "")),
                ),
            )
        return list(requests_by_client_id.values())

    def _read_runtime_commands(self) -> Dict[str, Any]:
        path = self.settings.runtime_command_path
        if not path or not os.path.exists(path):
            return {"commands": []}
        try:
            with open(path, "r", encoding="utf-8") as fh:
                payload = json.load(fh)
        except (OSError, json.JSONDecodeError):
            return {"commands": []}
        return payload if isinstance(payload, dict) else {"commands": []}

    def _write_runtime_commands(self, payload: Dict[str, Any]) -> None:
        path = self.settings.runtime_command_path
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(prefix=".{0}-".format(os.path.basename(path)), suffix=".tmp", dir=parent or None)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=2, sort_keys=True)
                fh.write("\n")
            os.replace(tmp_path, path)
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    @staticmethod
    def _group_by_symbol(requests):
        grouped = {}
        for request in requests:
            grouped.setdefault(request.symbol, []).append(request)
        return grouped

    def _request_from_intent(self, intent: OrderIntent) -> OrderRequest:
        if intent.side is None or intent.price is None or intent.size is None or intent.client_order_id is None:
            raise ValueError("place intent missing required fields")
        return OrderRequest(
            symbol=intent.symbol,
            side=intent.side,
            order_type=intent.order_type,
            price=intent.price,
            size=intent.size,
            client_order_id=intent.client_order_id,
            strategy=intent.strategy,
            level=intent.level,
        )

    async def _refresh_balances(self) -> None:
        balances = await self.gateway.get_balances()
        self.inventory.update(balances)
        await self.strategy.on_balances(balances)
        self.event_log.append("account.balances", balances)
        for balance in balances:
            self.metrics.set("balance_available", balance.available, currency=balance.currency)
            self.metrics.set("balance_frozen", balance.frozen, currency=balance.currency)

    def _start_private_stream(self) -> None:
        if not self._should_start_private_stream():
            return
        if self._private_stream_task is not None and not self._private_stream_task.done():
            return
        self._private_stream_task = asyncio.create_task(self._run_private_stream())

    async def _stop_private_stream(self) -> None:
        task = self._private_stream_task
        if task is None:
            return
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._private_stream_task = None

    def _should_start_private_stream(self) -> bool:
        return (
            self.settings.private_stream_enabled
            and self.settings.trading_mode != TradingMode.PAPER
            and self.settings.exchange == "bitmart"
            and self.settings.bitmart.present
        )

    async def _run_private_stream(self) -> None:
        channels = BitMartPrivateStreamProcessor.channels(self.settings.symbols)
        processor = BitMartPrivateStreamProcessor(self.oms, self.inventory, self.event_log)
        reconnect_delay_sec = 3
        while not self._stop_requested:
            try:
                client = self._private_stream_client_factory(channels, self.settings.bitmart)
                await self._consume_private_stream(client, processor)
                if not self._stop_requested:
                    await asyncio.sleep(reconnect_delay_sec)
            except asyncio.CancelledError:
                raise
            except WebSocketDependencyError as exc:
                self.event_log.append("bitmart.private.error", {"error": str(exc), "fatal": True})
                if self.settings.trading_mode == TradingMode.LIVE:
                    self._enter_internal_safe_mode(
                        "bitmart_private_ws_dependency",
                        "BitMart private WebSocket dependency missing",
                    )
                return
            except Exception as exc:
                self.event_log.append("bitmart.private.error", {"error": str(exc), "fatal": False})
                if self.settings.trading_mode == TradingMode.LIVE:
                    self._enter_internal_safe_mode(
                        "bitmart_private_ws_disconnected",
                        "BitMart private WebSocket disconnected",
                    )
                await asyncio.sleep(reconnect_delay_sec)

    async def _consume_private_stream(self, client: object, processor: BitMartPrivateStreamProcessor) -> None:
        async for message in client.stream():
            report = processor.apply_message(message)
            self.event_log.append("bitmart.private.report", report)
            self.metrics.inc("bitmart_private_stream_messages")
            self.metrics.inc("bitmart_private_order_updates", report.order_updates)
            self.metrics.inc("bitmart_private_balance_updates", report.balance_updates)
            for fill in report.fills:
                self.pnl.apply_fill(fill)
                hedge_intent = self.hedging.intent_from_fill(fill)
                if hedge_intent is not None:
                    hedge_result = await self.hedging.execute(hedge_intent)
                    self.event_log.append("hedge.result", hedge_result)
                self.event_log.append("order.fill.private", fill)
                self._fills += 1
                self.metrics.inc("fill_count", symbol=fill.symbol, side=fill.side.value)
            if report.unknown_orders > 0:
                self._enter_internal_safe_mode(
                    "bitmart_private_unknown_order",
                    "BitMart private stream produced UNKNOWN order state",
                )
            if self._stop_requested:
                break

    def _build_gateway(self) -> ExchangeGateway:
        if self.settings.trading_mode == TradingMode.PAPER:
            paper = self.settings.paper
            return PaperExchange(
                market_rules=self.settings.market_rules,
                initial_prices=paper.get("initial_prices", {}),
                balances=paper.get("balances", {}),
                maker_fee_bps=paper.get("maker_fee_bps", "0"),
                taker_fee_bps=paper.get("taker_fee_bps", "10"),
            )
        live_gateway = BitMartRestGateway(self.settings.bitmart)
        if self.settings.trading_mode == TradingMode.LIVE_READ_ONLY:
            return DryRunExchange(live_gateway, live_gateway)
        if self.settings.trading_mode == TradingMode.LIVE_DRY_RUN:
            return DryRunExchange(live_gateway, live_gateway)
        return live_gateway

    def _build_hedging_engine(self) -> HedgingEngine:
        hedged = [
            strategy
            for strategy in self.settings.strategies
            if strategy.enabled and strategy.name == "hedged_mm" and strategy.params.get("hedge_mode") != "manual_review"
        ]
        if not hedged:
            return HedgingEngine(enabled=False)
        thresholds = [
            Decimal(str(strategy.params.get("hedge_threshold_base", strategy.params.get("order_size", "0"))))
            for strategy in hedged
        ]
        min_hedge_size = min([item for item in thresholds if item > 0], default=Decimal("0"))
        hedge_exchange = str(hedged[0].params.get("hedge_exchange", "paper")).lower()
        if hedge_exchange == "binance":
            from mm.hedging.adapters import BinanceHedgeAdapter

            adapter = BinanceHedgeAdapter(dry_run=True)
        else:
            from mm.hedging.adapters import PaperHedgeAdapter

            adapter = PaperHedgeAdapter()
        return HedgingEngine(enabled=True, min_hedge_size=min_hedge_size, adapter=adapter)
