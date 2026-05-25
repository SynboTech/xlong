from __future__ import annotations

from dataclasses import dataclass
from typing import List

from mm.market_data.hub import MarketDataHub
from mm.oms.manager import OrderManager
from mm.common.types import OrderStatus


@dataclass(frozen=True)
class HealthCheckResult:
    ok: bool
    checks: List[str]
    failures: List[str]


class HealthChecker:
    def __init__(self, market_data: MarketDataHub, oms: OrderManager, risk: object) -> None:
        self.market_data = market_data
        self.oms = oms
        self.risk = risk

    def check(self) -> HealthCheckResult:
        checks: List[str] = []
        failures: List[str] = []

        checks.append("safe_mode")
        if getattr(self.risk, "safe_mode", False):
            failures.append("risk engine is in SAFE_MODE")

        checks.append("unknown_orders")
        unknown = [order.client_order_id for order in self.oms.all_orders() if order.status == OrderStatus.UNKNOWN]
        if unknown:
            failures.append("unknown orders: {0}".format(",".join(unknown[:5])))

        checks.append("market_data_stale")
        status = self.market_data.status()
        if status.stale_symbols:
            failures.append("stale market data: {0}".format(",".join(status.stale_symbols)))

        checks.append("orderbook_gaps")
        if status.gap_count > 0:
            failures.append("order book gap count: {0}".format(status.gap_count))

        return HealthCheckResult(ok=not failures, checks=checks, failures=failures)

