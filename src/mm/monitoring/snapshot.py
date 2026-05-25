from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

from mm.accounting.pnl import PnlTracker
from mm.common.types import Balance
from mm.inventory.manager import InventoryManager
from mm.market_data.hub import MarketDataHub
from mm.monitoring.health import HealthCheckResult
from mm.monitoring.metrics import MetricsRegistry
from mm.oms.manager import OrderManager


@dataclass(frozen=True)
class RuntimeSnapshot:
    trading_mode: str
    symbols: List[str]
    health_ok: bool
    open_orders: int
    total_orders: int
    balances: Dict[str, Dict[str, str]]
    pnl: Dict[str, Dict[str, str]]
    market_data: Dict[str, object]
    metrics: Dict[str, str]


def build_runtime_snapshot(
    trading_mode: str,
    symbols: List[str],
    health: HealthCheckResult,
    oms: OrderManager,
    inventory: InventoryManager,
    pnl: PnlTracker,
    market_data: MarketDataHub,
    metrics: MetricsRegistry,
) -> RuntimeSnapshot:
    balances = {
        currency: {
            "available": str(balance.available),
            "frozen": str(balance.frozen),
            "total": str(balance.total),
        }
        for currency, balance in inventory.as_dict().items()
    }
    market_status = market_data.status()
    metric_rows = {
        "{0}{1}".format(name, dict(labels) if labels else ""): str(value)
        for (name, labels), value in metrics.samples().items()
    }
    return RuntimeSnapshot(
        trading_mode=trading_mode,
        symbols=list(symbols),
        health_ok=health.ok,
        open_orders=len(oms.open_orders()),
        total_orders=len(oms.all_orders()),
        balances=balances,
        pnl=pnl.snapshot(market_data.snapshots),
        market_data={
            "symbols": market_status.symbols,
            "orderbook_versions": market_status.orderbook_versions,
            "depth_levels": market_status.depth_levels,
            "stale_symbols": market_status.stale_symbols,
            "gap_count": market_status.gap_count,
        },
        metrics=metric_rows,
    )
