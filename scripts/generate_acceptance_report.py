#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from dataclasses import asdict
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from mm.app import MarketMakerApp
from mm.accounting.report import DailyPnlReporter
from mm.backtest.runner import EventLogBacktestRunner
from mm.config.audit import build_config_audit
from mm.config.settings import AppSettings
from mm.common.types import to_jsonable
from mm.exchange.bitmart.preflight import BitMartPreflight
from mm.exchange.bitmart.rest import BitMartRestGateway
from mm.exchange.bitmart.smoke import private_ws_smoke, public_ws_smoke
from mm.config.settings import BitMartCredentials
from mm.risk.drills import RiskDrillSuite


async def run_app() -> tuple[dict, dict, list[dict], dict, list[dict], dict, dict, dict, dict, dict]:
    settings = AppSettings.from_file(os.path.join(ROOT, "config/paper.json"))
    app = MarketMakerApp(settings)
    summary = await app.run(ticks=10)
    health = app.health()
    runtime_snapshot = app.runtime_snapshot()
    drill = RiskDrillSuite(app.risk, app.inventory, app.oms, app.markets)
    drill_results = drill.run()
    preflight = await BitMartPreflight(settings, BitMartRestGateway(settings.bitmart)).run(network=False)
    public_smoke = await public_ws_smoke("BTC_USDT", dry_run=True)
    private_smoke = await private_ws_smoke(BitMartCredentials("dryrun_key", "dryrun_secret", "dryrun_memo"), dry_run=True)
    ws_smoke = []
    for item in [public_smoke, private_smoke]:
        row = to_jsonable(asdict(item))
        row["passed"] = item.passed
        ws_smoke.append(row)
    backtest = await EventLogBacktestRunner(settings, settings.event_log_path).run()
    pnl_report = DailyPnlReporter(settings.event_log_path).build()
    config_audit = build_config_audit(os.path.join(ROOT, "config/paper.json"))
    rate_limit_report = BitMartRestGateway(settings.bitmart).rate_limit_report()
    return (
        to_jsonable(asdict(summary)),
        to_jsonable(asdict(health)),
        [to_jsonable(asdict(item)) for item in drill_results],
        to_jsonable(preflight.as_dict()),
        ws_smoke,
        to_jsonable(asdict(backtest)),
        to_jsonable(asdict(pnl_report)),
        to_jsonable(asdict(config_audit)),
        to_jsonable(rate_limit_report),
        to_jsonable(asdict(runtime_snapshot)),
    )


def run_tests() -> tuple[int, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = "src"
    proc = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests"],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    return proc.returncode, proc.stdout


def main() -> int:
    test_code, test_output = run_tests()
    summary, health, drills, preflight, ws_smoke, backtest, pnl_report, config_audit, rate_limit_report, runtime_snapshot = asyncio.run(run_app())
    ok = (
        test_code == 0
        and health["ok"]
        and all(item["passed"] for item in drills)
        and preflight["passed"]
        and all(item["passed"] for item in ws_smoke)
        and backtest["market_snapshots"] > 0
    )
    report = []
    report.append("# Market Maker Acceptance Report")
    report.append("")
    report.append("Generated: {0}".format(datetime.now(timezone.utc).isoformat()))
    report.append("")
    report.append("## Result")
    report.append("")
    report.append("Status: **{0}**".format("PASS" if ok else "FAIL"))
    report.append("")
    report.append("## Unit Tests")
    report.append("")
    report.append("Exit code: `{0}`".format(test_code))
    report.append("")
    report.append("```text")
    report.append(test_output.strip())
    report.append("```")
    report.append("")
    report.append("## Config Audit")
    report.append("")
    report.append("```json")
    report.append(json.dumps(config_audit, indent=2, sort_keys=True))
    report.append("```")
    report.append("")
    report.append("## Paper Run")
    report.append("")
    report.append("```json")
    report.append(json.dumps(summary, indent=2, sort_keys=True))
    report.append("```")
    report.append("")
    report.append("## Health")
    report.append("")
    report.append("```json")
    report.append(json.dumps(health, indent=2, sort_keys=True))
    report.append("```")
    report.append("")
    report.append("## Runtime Snapshot")
    report.append("")
    report.append("```json")
    report.append(json.dumps(runtime_snapshot, indent=2, sort_keys=True))
    report.append("```")
    report.append("")
    report.append("## Preflight")
    report.append("")
    report.append("```json")
    report.append(json.dumps(preflight, indent=2, sort_keys=True))
    report.append("```")
    report.append("")
    report.append("## Risk Drills")
    report.append("")
    report.append("```json")
    report.append(json.dumps(drills, indent=2, sort_keys=True))
    report.append("```")
    report.append("")
    report.append("## WebSocket Smoke")
    report.append("")
    report.append("```json")
    report.append(json.dumps(ws_smoke, indent=2, sort_keys=True))
    report.append("```")
    report.append("")
    report.append("## Backtest Replay")
    report.append("")
    report.append("```json")
    report.append(json.dumps(backtest, indent=2, sort_keys=True))
    report.append("```")
    report.append("")
    report.append("## PnL Report")
    report.append("")
    report.append("```json")
    report.append(json.dumps(pnl_report, indent=2, sort_keys=True))
    report.append("```")
    report.append("")
    report.append("## Rate Limits")
    report.append("")
    report.append("```json")
    report.append(json.dumps(rate_limit_report, indent=2, sort_keys=True))
    report.append("```")
    path = os.path.join(ROOT, "docs/acceptance_report.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(report) + "\n")
    print(path)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
