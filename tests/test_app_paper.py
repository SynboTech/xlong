import asyncio
import json
import os
import tempfile
import unittest

from mm.app import MarketMakerApp
from mm.config.settings import AppSettings


class PaperAppTest(unittest.TestCase):
    def test_paper_app_runs_and_cancels_on_shutdown(self):
        async def scenario():
            settings = AppSettings.from_file("config/paper.json")
            app = MarketMakerApp(settings)
            summary = await app.run(ticks=2)
            self.assertGreater(summary.orders_total, 0)
            self.assertEqual(summary.open_orders, 0)
            self.assertFalse(summary.safe_mode)

        asyncio.run(scenario())

    def test_runtime_strategy_pause_cancels_existing_quotes(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as tmp:
                data = paper_config(tmp)
                settings = AppSettings.from_config(data)
                app = MarketMakerApp(settings)
                await app.tick_once()
                self.assertGreater(len(app.oms.open_orders()), 0)

                with open(data["strategy_state_path"], "w", encoding="utf-8") as fh:
                    json.dump({"states": {"basic_mm:BTC_USDT": {"status": "paused"}}}, fh)
                await app.tick_once()
                self.assertEqual(len(app.oms.open_orders()), 0)

        asyncio.run(scenario())

    def test_runtime_safe_mode_blocks_new_orders(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as tmp:
                data = paper_config(tmp)
                with open(data["risk_state_path"], "w", encoding="utf-8") as fh:
                    json.dump({"safe_mode": True, "reason": "test safe mode"}, fh)
                app = MarketMakerApp(AppSettings.from_config(data))
                await app.tick_once()
                self.assertEqual(len(app.oms.all_orders()), 0)
                self.assertTrue(app.risk.safe_mode)
                self.assertGreater(app._rejected, 0)

        asyncio.run(scenario())


def paper_config(tmp):
    with open("config/paper.json", "r", encoding="utf-8") as fh:
        data = json.load(fh)
    data["symbols"] = ["BTC_USDT"]
    data["market_rules"] = {"BTC_USDT": data["market_rules"]["BTC_USDT"]}
    data["paper"]["initial_prices"] = {"BTC_USDT": data["paper"]["initial_prices"]["BTC_USDT"]}
    data["strategies"] = [
        {
            "name": "basic_mm",
            "symbol": "BTC_USDT",
            "enabled": True,
            "params": {
                "spread_bps": "20",
                "order_size": "0.00005",
                "levels": 2,
                "level_spacing_bps": "10",
                "size_multiplier": "1.0",
            },
        }
    ]
    data["event_log_path"] = os.path.join(tmp, "events.jsonl")
    data["order_store_path"] = os.path.join(tmp, "orders.json")
    data["strategy_state_path"] = os.path.join(tmp, "strategy_state.json")
    data["risk_state_path"] = os.path.join(tmp, "risk_state.json")
    return data


if __name__ == "__main__":
    unittest.main()
