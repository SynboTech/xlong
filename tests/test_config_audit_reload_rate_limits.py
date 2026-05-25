import json
import os
import tempfile
import time
import unittest

from mm.config.audit import build_config_audit
from mm.config.reloader import ConfigReloader
from mm.exchange.bitmart.rest import BitMartRestGateway
from mm.exchange.rate_limit import SlidingWindowRateLimiter
from mm.config.settings import BitMartCredentials


class ConfigAuditReloadRateLimitTest(unittest.TestCase):
    def test_config_audit_fingerprint(self):
        report = build_config_audit("config/paper.json")
        self.assertEqual(len(report.sha256), 64)
        self.assertEqual(report.trading_mode, "paper")
        self.assertIn("BTC_USDT", report.symbols)
        self.assertTrue(any(item.startswith("basic_mm:") for item in report.enabled_strategies))

    def test_config_reloader_detects_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "config.json")
            with open("config/paper.json", "r", encoding="utf-8") as src:
                data = json.load(src)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(data, fh)
            reloader = ConfigReloader(path)
            first = reloader.check()
            self.assertFalse(first.changed)
            time.sleep(0.01)
            data["quote_interval_ms"] = 777
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(data, fh)
            second = reloader.check()
            self.assertTrue(second.changed)
            self.assertEqual(second.settings.quote_interval_ms, 777)

    def test_rate_limiter_snapshot(self):
        limiter = SlidingWindowRateLimiter(2, 10)
        limiter.allow()
        snap = limiter.snapshot()
        self.assertEqual(snap.used, 1)
        self.assertEqual(snap.remaining, 1)
        self.assertEqual(snap.max_calls, 2)

    def test_bitmart_rate_limit_report(self):
        report = BitMartRestGateway(BitMartCredentials("", "", "")).rate_limit_report()
        self.assertIn("default_40_per_2s", report)
        self.assertEqual(report["cancel_all_1_per_3s"].max_calls, 1)


if __name__ == "__main__":
    unittest.main()

