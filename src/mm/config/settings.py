from __future__ import annotations

import json
import os
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, List, Optional

from mm.common.decimal import D
from mm.common.types import MarketRule, TradingMode


@dataclass(frozen=True)
class RiskSettings:
    max_order_value_usdt: Decimal
    max_total_open_value_usdt: Decimal
    max_open_orders: int
    max_position_base: Decimal
    max_daily_loss_usdt: Decimal
    max_price_deviation_bps: Decimal
    per_strategy_max_order_value_usdt: Dict[str, Decimal]
    per_strategy_max_open_orders: Dict[str, int]
    per_strategy_max_open_value_usdt: Dict[str, Decimal]

    @classmethod
    def from_config(cls, data: Dict[str, Any]) -> "RiskSettings":
        return cls(
            max_order_value_usdt=D(data["max_order_value_usdt"]),
            max_total_open_value_usdt=D(data["max_total_open_value_usdt"]),
            max_open_orders=int(data["max_open_orders"]),
            max_position_base=D(data["max_position_base"]),
            max_daily_loss_usdt=D(data["max_daily_loss_usdt"]),
            max_price_deviation_bps=D(data["max_price_deviation_bps"]),
            per_strategy_max_order_value_usdt={
                str(key): D(value)
                for key, value in data.get("per_strategy_max_order_value_usdt", {}).items()
            },
            per_strategy_max_open_orders={
                str(key): int(value)
                for key, value in data.get("per_strategy_max_open_orders", {}).items()
            },
            per_strategy_max_open_value_usdt={
                str(key): D(value)
                for key, value in data.get("per_strategy_max_open_value_usdt", {}).items()
            },
        )


@dataclass(frozen=True)
class StrategySettings:
    name: str
    symbol: str
    enabled: bool
    params: Dict[str, Any]
    instance_id: str = ""

    @classmethod
    def from_config(cls, data: Dict[str, Any]) -> "StrategySettings":
        return cls(
            name=str(data["name"]),
            symbol=str(data["symbol"]),
            enabled=bool(data.get("enabled", True)),
            params=dict(data.get("params", {})),
            instance_id=str(data.get("id") or data.get("instance_id") or ""),
        )

    @property
    def key(self) -> str:
        return self.instance_id or "{0}:{1}".format(self.name, self.symbol)


@dataclass(frozen=True)
class SecurityAcknowledgements:
    api_key_no_withdraw_permission_ack: bool
    api_key_ip_whitelist_ack: bool
    production_runbook_ack: bool

    @classmethod
    def from_config(cls, data: Dict[str, Any]) -> "SecurityAcknowledgements":
        return cls(
            api_key_no_withdraw_permission_ack=bool(data.get("api_key_no_withdraw_permission_ack", False)),
            api_key_ip_whitelist_ack=bool(data.get("api_key_ip_whitelist_ack", False)),
            production_runbook_ack=bool(data.get("production_runbook_ack", False)),
        )


@dataclass(frozen=True)
class BitMartCredentials:
    api_key: str
    api_secret: str
    api_memo: str

    @property
    def present(self) -> bool:
        return bool(self.api_key and self.api_secret and self.api_memo)

    @classmethod
    def from_env(cls) -> "BitMartCredentials":
        return cls(
            api_key=os.environ.get("BITMART_API_KEY", ""),
            api_secret=os.environ.get("BITMART_API_SECRET", ""),
            api_memo=os.environ.get("BITMART_API_MEMO", ""),
        )


@dataclass(frozen=True)
class AppSettings:
    trading_mode: TradingMode
    live_confirm: bool
    enable_order_submission: bool
    exchange: str
    symbols: List[str]
    quote_interval_ms: int
    min_requote_interval_ms: int
    stale_market_data_ms: int
    cancel_on_shutdown: bool
    event_log_path: str
    order_store_path: str
    strategy_state_path: str
    risk_state_path: str
    private_stream_enabled: bool
    risk: RiskSettings
    market_rules: Dict[str, MarketRule]
    paper: Dict[str, Any]
    strategies: List[StrategySettings]
    security: SecurityAcknowledgements
    bitmart: BitMartCredentials

    @classmethod
    def from_file(cls, path: str) -> "AppSettings":
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return cls.from_config(data)

    @classmethod
    def from_config(cls, data: Dict[str, Any]) -> "AppSettings":
        market_rules = {
            symbol: MarketRule.from_config(symbol, rule_data)
            for symbol, rule_data in data.get("market_rules", {}).items()
        }
        trading_mode = TradingMode(str(data.get("trading_mode", "paper")))
        settings = cls(
            trading_mode=trading_mode,
            live_confirm=bool(data.get("live_confirm", False)),
            enable_order_submission=bool(data.get("enable_order_submission", False)),
            exchange=str(data.get("exchange", "paper")),
            symbols=[str(symbol) for symbol in data.get("symbols", [])],
            quote_interval_ms=int(data.get("quote_interval_ms", 1000)),
            min_requote_interval_ms=int(data.get("min_requote_interval_ms", 1000)),
            stale_market_data_ms=int(data.get("stale_market_data_ms", 3000)),
            cancel_on_shutdown=bool(data.get("cancel_on_shutdown", True)),
            event_log_path=str(data.get("event_log_path", "runtime/events.jsonl")),
            order_store_path=str(data.get("order_store_path", "runtime/orders.json")),
            strategy_state_path=str(data.get("strategy_state_path", "runtime/strategy_state.json")),
            risk_state_path=str(data.get("risk_state_path", "runtime/risk_state.json")),
            private_stream_enabled=bool(data.get("private_stream_enabled", trading_mode != TradingMode.PAPER)),
            risk=RiskSettings.from_config(data["risk"]),
            market_rules=market_rules,
            paper=dict(data.get("paper", {})),
            strategies=[
                StrategySettings.from_config(item)
                for item in data.get("strategies", [])
            ],
            security=SecurityAcknowledgements.from_config(data.get("security", {})),
            bitmart=BitMartCredentials.from_env(),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if not self.symbols:
            raise ValueError("at least one symbol is required")
        missing_rules = [symbol for symbol in self.symbols if symbol not in self.market_rules]
        if missing_rules:
            raise ValueError("missing market rules for: {0}".format(",".join(missing_rules)))
        if self.trading_mode == TradingMode.PAPER:
            initial_prices = self.paper.get("initial_prices", {})
            missing_prices = [symbol for symbol in self.symbols if symbol not in initial_prices]
            if missing_prices:
                raise ValueError("missing paper initial prices for: {0}".format(",".join(missing_prices)))
        if self.trading_mode != TradingMode.PAPER:
            if not self.live_confirm:
                raise ValueError("{0} mode requires live_confirm=true".format(self.trading_mode.value))
            if not self.bitmart.present:
                raise ValueError("{0} mode requires BITMART_API_KEY/SECRET/MEMO".format(self.trading_mode.value))
            if self.risk.max_order_value_usdt <= 0:
                raise ValueError("{0} mode requires positive max_order_value_usdt".format(self.trading_mode.value))
            if self.risk.max_total_open_value_usdt <= 0:
                raise ValueError("{0} mode requires positive max_total_open_value_usdt".format(self.trading_mode.value))
        if self.trading_mode == TradingMode.LIVE and not self.enable_order_submission:
            raise ValueError("live mode requires enable_order_submission=true")
        if self.trading_mode == TradingMode.LIVE_READ_ONLY and self.enable_order_submission:
            raise ValueError("live_read_only mode cannot enable order submission")

    def rule_for(self, symbol: str) -> MarketRule:
        return self.market_rules[symbol]
