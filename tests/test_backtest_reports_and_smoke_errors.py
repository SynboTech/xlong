import asyncio
import json
import os
import tempfile
import unittest
from dataclasses import asdict

from mm.accounting.report import DailyPnlReporter
from mm.backtest.runner import EventLogBacktestRunner
from mm.config.settings import AppSettings
from mm.exchange.bitmart.smoke import SmokeError, classify_ws_exception, private_ws_smoke


class BacktestReportsAndSmokeErrorsTest(unittest.TestCase):
    def test_backtest_runner_replays_market_snapshots(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "events.jsonl")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(
                    json.dumps(
                        {
                            "ts": 1,
                            "type": "market.snapshot",
                            "payload": {
                                "exchange": "paper",
                                "symbol": "BTC_USDT",
                                "bid": "67990",
                                "bid_size": "1",
                                "ask": "68010",
                                "ask_size": "1",
                                "last": "68000",
                                "timestamp_ms": 1,
                                "receive_time_ms": 1,
                            },
                        }
                    )
                    + "\n"
                )
            summary = EventLogBacktestRunner(AppSettings.from_file("config/paper.json"), path).run_sync()
            self.assertEqual(summary.market_snapshots, 1)
            self.assertGreater(summary.generated_quotes, 0)
            self.assertGreater(summary.generated_order_intents, 0)

    def test_daily_pnl_report_reads_fills_and_latest_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "events.jsonl")
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(json.dumps({"ts": 1, "type": "order.fill", "payload": {"fee": "0.1"}}) + "\n")
                fh.write(json.dumps({"ts": 2, "type": "order.fill", "payload": {"fee": "0.2"}}) + "\n")
                fh.write(
                    json.dumps(
                        {
                            "ts": 3,
                            "type": "account.pnl",
                            "payload": {
                                "BTC_USDT": {
                                    "position": "1",
                                    "realized_pnl": "2",
                                    "unrealized_pnl": "3",
                                    "fees": "0.3",
                                    "total_pnl": "4.7",
                                }
                            },
                        }
                    )
                    + "\n"
                )
            report = DailyPnlReporter(path).build()
            self.assertEqual(report.fills, 2)
            self.assertEqual(str(report.total_fees), "0.3")
            self.assertEqual(report.symbols["BTC_USDT"]["total_pnl"], "4.7")

    def test_ws_exception_classifier(self):
        self.assertEqual(classify_ws_exception(TimeoutError("timed out")).category, "timeout")
        self.assertEqual(classify_ws_exception(RuntimeError("Install optional dependency websockets")).category, "dependency")
        self.assertEqual(classify_ws_exception(RuntimeError("handshake failed")).category, "protocol")
        self.assertEqual(classify_ws_exception(RuntimeError("connection reset")).category, "network")

    def test_private_ws_missing_credentials_error_is_structured(self):
        from mm.config.settings import BitMartCredentials

        report = asyncio.run(private_ws_smoke(BitMartCredentials("", "", ""), dry_run=False))
        self.assertFalse(report.passed)
        self.assertEqual(report.errors[0].category, "credentials")


if __name__ == "__main__":
    unittest.main()

