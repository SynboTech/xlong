#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from mm.config.settings import AppSettings
from mm.persistence.order_store import build_order_store


def parse_args():
    parser = argparse.ArgumentParser(description="Validate shadow/canary launch gates")
    parser.add_argument("--config", default="config/live_dry_run.example.json")
    parser.add_argument("--stage", choices=["shadow", "canary"], default="shadow")
    parser.add_argument("--max-order-usdt", default="10")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    checks = []
    try:
        settings = AppSettings.from_file(args.config)
        checks.append(check("config_loads", True, settings.trading_mode.value))
    except Exception as exc:
        print(json.dumps({"passed": False, "checks": [check("config_loads", False, str(exc))]}, indent=2, sort_keys=True))
        return 1

    checks.append(check("bitmart_credentials_present", settings.bitmart.present, "env BITMART_API_KEY/SECRET/MEMO"))
    checks.append(check("live_confirm", settings.live_confirm, str(settings.live_confirm)))
    checks.append(check("no_withdraw_key", settings.security.api_key_no_withdraw_permission_ack, "security ack"))
    checks.append(check("ip_whitelist", settings.security.api_key_ip_whitelist_ack, "security ack"))
    checks.append(check("production_runbook_ack", settings.security.production_runbook_ack, "security ack"))
    checks.append(check("order_submission_gate", order_submission_gate(args.stage, settings), gate_message(args.stage, settings)))
    checks.append(check("max_order_value_cap", settings.risk.max_order_value_usdt <= decimal(args.max_order_usdt), str(settings.risk.max_order_value_usdt)))
    checks.append(check("strategies_configured", len(settings.strategies) > 0, "{0} strategies".format(len(settings.strategies))))
    checks.append(check("unknown_orders_clear", unknown_orders(settings.order_store_path) == 0, "{0} unknown".format(unknown_orders(settings.order_store_path))))

    passed = all(item["passed"] for item in checks)
    print(json.dumps({"stage": args.stage, "config": args.config, "passed": passed, "checks": checks}, indent=2, sort_keys=True))
    return 0 if passed else 1


def check(name, passed, message):
    return {"name": name, "passed": bool(passed), "message": str(message)}


def decimal(value):
    from decimal import Decimal

    return Decimal(str(value))


def order_submission_gate(stage, settings):
    if stage == "shadow":
        return not settings.enable_order_submission
    return settings.trading_mode.value == "live" and settings.enable_order_submission


def gate_message(stage, settings):
    if stage == "shadow":
        return "orders disabled" if not settings.enable_order_submission else "orders must be disabled in shadow"
    return "{0}, submit={1}".format(settings.trading_mode.value, settings.enable_order_submission)


def unknown_orders(path):
    resolved = path if os.path.isabs(path) else os.path.join(ROOT, path)
    if not os.path.exists(resolved) and not path.startswith(("postgres://", "postgresql://", "sqlite://")):
        return 0
    store = build_order_store(resolved)
    return len([order for order in store.load() if order.status.value == "unknown"])


if __name__ == "__main__":
    raise SystemExit(main())
