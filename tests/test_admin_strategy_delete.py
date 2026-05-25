import importlib.util
import json
import os
import tempfile
import unittest


def load_admin_server():
    path = os.path.join(os.getcwd(), "scripts", "admin_server.py")
    spec = importlib.util.spec_from_file_location("admin_server_for_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AdminStrategyDeleteTest(unittest.TestCase):
    def setUp(self):
        self.admin = load_admin_server()
        self.tmp = tempfile.TemporaryDirectory()
        root = self.tmp.name
        self.admin.CONFIG_PATH = os.path.join(root, "paper.json")
        self.admin.ORDERS_PATH = os.path.join(root, "orders.json")
        self.admin.EVENTS_PATH = os.path.join(root, "events.jsonl")
        self.admin.STRATEGY_STATE_PATH = os.path.join(root, "strategy_state.json")
        self.admin.RISK_STATE_PATH = os.path.join(root, "risk_state.json")
        self._write(
            self.admin.CONFIG_PATH,
            {
                "trading_mode": "paper",
                "exchange": "paper",
                "symbols": ["BTC_USDT"],
                "risk": {},
                "strategies": [
                    {"id": "range-buy", "name": "range_rebalance", "symbol": "BTC_USDT", "enabled": True, "params": {}},
                    {"id": "range-sell", "name": "range_rebalance", "symbol": "BTC_USDT", "enabled": True, "params": {}},
                ],
            },
        )
        self._write(self.admin.STRATEGY_STATE_PATH, {"states": {"range-buy": {"status": "paused"}, "range-sell": {"status": "running"}}})

    def tearDown(self):
        self.tmp.cleanup()

    def test_delete_strategy_removes_only_target_instance_and_state(self):
        result = self.admin.delete_strategy({"key": "range-buy"})
        self.assertTrue(result["ok"])
        config = self.admin.read_config()
        self.assertEqual([item["id"] for item in config["strategies"]], ["range-sell"])
        states = self.admin.read_json_file(self.admin.STRATEGY_STATE_PATH, {"states": {}})["states"]
        self.assertNotIn("range-buy", states)
        self.assertIn("range-sell", states)

    def test_delete_strategy_rejects_open_orders_without_force(self):
        self._write(
            self.admin.ORDERS_PATH,
            {
                "orders": [
                    {
                        "strategy": "range-buy",
                        "status": "open",
                        "symbol": "BTC_USDT",
                        "client_order_id": "cid",
                    }
                ]
            },
        )
        result = self.admin.delete_strategy({"key": "range-buy"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["open_orders"], 1)
        self.assertEqual(len(self.admin.read_config()["strategies"]), 2)

        forced = self.admin.delete_strategy({"key": "range-buy", "force": True})
        self.assertTrue(forced["ok"])
        self.assertEqual([item["id"] for item in self.admin.read_config()["strategies"]], ["range-sell"])

    def test_strategy_detail_and_stop_cancel_plan(self):
        self._write(
            self.admin.ORDERS_PATH,
            {
                "orders": [
                    {
                        "strategy": "range-buy",
                        "status": "open",
                        "symbol": "BTC_USDT",
                        "client_order_id": "cid",
                        "price": "100",
                        "size": "0.2",
                        "filled_size": "0.05",
                    }
                ]
            },
        )
        detail = self.admin.strategy_detail_payload("range-buy")
        self.assertTrue(detail["ok"])
        self.assertEqual(detail["strategy"]["metrics"]["open_orders"], 1)
        self.assertEqual(detail["strategy"]["cancel_plan"]["requests"][0]["client_order_id"], "cid")

        result = self.admin.stop_cancel_strategy({"key": "range-buy"})
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "paused")
        self.assertEqual(len(result["cancel_plan"]["requests"]), 1)

    def test_reconcile_diffs_mark_unknown_gate(self):
        diffs = self.admin.build_reconcile_diffs(
            [{"client_order_id": "local-1", "symbol": "BTC_USDT", "status": "open"}],
            [],
            "ok",
        )
        self.assertEqual(diffs[0]["type"], "local_open_missing_remote")
        self.assertEqual(diffs[0]["severity"], "critical")

    def _write(self, path, payload):
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)


if __name__ == "__main__":
    unittest.main()
