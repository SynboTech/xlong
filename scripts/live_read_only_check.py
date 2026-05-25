#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from mm.common.types import to_jsonable
from mm.config.settings import AppSettings
from mm.exchange.bitmart.private_stream import BitMartPrivateStreamProcessor
from mm.exchange.bitmart.preflight import BitMartPreflight
from mm.exchange.bitmart.rest import BitMartRestGateway
from mm.exchange.bitmart.smoke import private_ws_smoke, public_ws_smoke
from mm.inventory.manager import InventoryManager
from mm.oms.manager import OrderManager


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Live read-only validation without submitting orders")
    parser.add_argument("--config", default="config/live_read_only.example.json")
    parser.add_argument("--symbol", default="BTC_USDT")
    parser.add_argument("--network", action="store_true")
    parser.add_argument("--timeout", type=float, default=5.0)
    return parser.parse_args()


async def async_main() -> int:
    args = parse_args()
    settings = AppSettings.from_file(args.config)
    gateway = BitMartRestGateway(settings.bitmart)
    preflight = await BitMartPreflight(settings, gateway).run(network=args.network)
    public_smoke = await public_ws_smoke(args.symbol, dry_run=not args.network, timeout_sec=args.timeout)
    private_smoke = await private_ws_smoke(settings.bitmart, dry_run=not args.network, timeout_sec=args.timeout)
    private_closed_loop = private_stream_closed_loop_probe(settings.symbols)
    report = {
        "mode": settings.trading_mode.value,
        "order_submission_enabled": settings.enable_order_submission,
        "preflight": preflight.as_dict(),
        "public_ws": public_smoke,
        "private_ws": private_smoke,
        "private_stream_closed_loop": private_closed_loop,
        "passed": preflight.passed and public_smoke.passed and private_smoke.passed and private_closed_loop["passed"] and not settings.enable_order_submission,
    }
    print(json.dumps(to_jsonable(report), indent=2, sort_keys=True))
    return 0 if report["passed"] else 1


def main() -> None:
    raise SystemExit(asyncio.run(async_main()))


def private_stream_closed_loop_probe(symbols):
    oms = OrderManager()
    inventory = InventoryManager()
    processor = BitMartPrivateStreamProcessor(oms, inventory)
    symbol = symbols[0]
    order_report = processor.apply_message(
        {
            "table": "spot/user/orders",
            "data": [
                {
                    "symbol": symbol,
                    "client_order_id": "live-read-only-probe",
                    "order_id": "probe-remote",
                    "order_state": "new",
                    "filled_size": "0",
                    "side": "buy",
                }
            ],
        }
    )
    balance_report = processor.apply_message(
        {
            "table": "spot/user/balance",
            "data": [{"balance_details": [{"ccy": "USDT", "av_bal": "1", "fz_bal": "0"}]}],
        }
    )
    return {
        "channels": BitMartPrivateStreamProcessor.channels(symbols),
        "order_updates": order_report.order_updates,
        "orphan_orders": order_report.orphan_orders,
        "unknown_orders": order_report.unknown_orders,
        "balance_updates": balance_report.balance_updates,
        "passed": order_report.orphan_orders == 1 and order_report.unknown_orders == 1 and balance_report.balance_updates == 1,
    }


if __name__ == "__main__":
    main()
