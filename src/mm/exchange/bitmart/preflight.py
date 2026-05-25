from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from mm.common.types import TradingMode
from mm.config.settings import AppSettings


@dataclass(frozen=True)
class PreflightCheck:
    name: str
    passed: bool
    message: str


@dataclass(frozen=True)
class PreflightReport:
    mode: str
    checks: List[PreflightCheck] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)

    def as_dict(self) -> Dict[str, object]:
        return {
            "mode": self.mode,
            "passed": self.passed,
            "checks": [
                {"name": check.name, "passed": check.passed, "message": check.message}
                for check in self.checks
            ],
        }


class BitMartPreflight:
    def __init__(self, settings: AppSettings, gateway: Optional[object] = None) -> None:
        self.settings = settings
        self.gateway = gateway

    async def run(self, network: bool = False) -> PreflightReport:
        checks: List[PreflightCheck] = []
        checks.append(
            PreflightCheck(
                "credentials_present",
                self.settings.trading_mode == TradingMode.PAPER or self.settings.bitmart.present,
                "BitMart credentials present" if self.settings.bitmart.present else "BitMart credentials missing",
            )
        )
        checks.append(
            PreflightCheck(
                "live_confirm",
                self.settings.trading_mode == TradingMode.PAPER or self.settings.live_confirm,
                "live_confirm is set" if self.settings.live_confirm else "live_confirm is false",
            )
        )
        checks.append(
            PreflightCheck(
                "order_submission_guard",
                self._order_submission_guard_ok(),
                self._order_submission_guard_message(),
            )
        )
        checks.append(
            PreflightCheck(
                "symbols_have_rules",
                all(symbol in self.settings.market_rules for symbol in self.settings.symbols),
                "all configured symbols have market rules",
            )
        )
        checks.extend(self._security_ack_checks())

        if network and self.gateway is not None:
            checks.extend(await self._network_checks())

        return PreflightReport(mode=self.settings.trading_mode.value, checks=checks)

    def _security_ack_checks(self) -> List[PreflightCheck]:
        if self.settings.trading_mode == TradingMode.PAPER:
            return [
                PreflightCheck("api_key_no_withdraw_permission_ack", True, "paper mode does not use live API key"),
                PreflightCheck("api_key_ip_whitelist_ack", True, "paper mode does not use live API key"),
                PreflightCheck("production_runbook_ack", True, "paper mode runbook not required"),
            ]
        security = self.settings.security
        return [
            PreflightCheck(
                "api_key_no_withdraw_permission_ack",
                security.api_key_no_withdraw_permission_ack,
                "API key withdrawal permission disabled"
                if security.api_key_no_withdraw_permission_ack
                else "confirm API key has no withdrawal permission",
            ),
            PreflightCheck(
                "api_key_ip_whitelist_ack",
                security.api_key_ip_whitelist_ack,
                "API key IP whitelist confirmed"
                if security.api_key_ip_whitelist_ack
                else "confirm API key IP whitelist",
            ),
            PreflightCheck(
                "production_runbook_ack",
                security.production_runbook_ack,
                "production runbook acknowledged"
                if security.production_runbook_ack
                else "acknowledge production runbook before live validation",
            ),
        ]

    def _order_submission_guard_ok(self) -> bool:
        if self.settings.trading_mode == TradingMode.LIVE:
            return self.settings.enable_order_submission
        if self.settings.trading_mode == TradingMode.LIVE_READ_ONLY:
            return not self.settings.enable_order_submission
        if self.settings.trading_mode == TradingMode.LIVE_DRY_RUN:
            return not self.settings.enable_order_submission
        return True

    def _order_submission_guard_message(self) -> str:
        if self.settings.trading_mode == TradingMode.LIVE:
            return "live order submission enabled" if self.settings.enable_order_submission else "live order submission disabled"
        if self.settings.trading_mode in {TradingMode.LIVE_READ_ONLY, TradingMode.LIVE_DRY_RUN}:
            return "order submission disabled as expected"
        return "paper mode does not submit live orders"

    async def _network_checks(self) -> List[PreflightCheck]:
        checks: List[PreflightCheck] = []
        try:
            balances = await self.gateway.get_balances()
            checks.append(PreflightCheck("balances_query", True, "balances query returned {0} rows".format(len(balances))))
        except Exception as exc:
            checks.append(PreflightCheck("balances_query", False, str(exc)))
        for symbol in self.settings.symbols:
            try:
                orders = await self.gateway.get_open_orders(symbol)
                checks.append(PreflightCheck("open_orders_query:{0}".format(symbol), True, "open orders returned {0} rows".format(len(orders))))
            except Exception as exc:
                checks.append(PreflightCheck("open_orders_query:{0}".format(symbol), False, str(exc)))
        return checks
