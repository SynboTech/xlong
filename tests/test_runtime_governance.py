import asyncio
import copy
import unittest
from decimal import Decimal

from mm.app import MarketMakerApp
from mm.common.types import Balance, MarketSnapshot, OrderIntent, OrderType, Side
from mm.config.change_audit import diff_settings
from mm.config.settings import AppSettings
from mm.inventory.manager import InventoryManager
from mm.oms.manager import OrderManager
from mm.quote.budget import OrderBudgetAllocator, StrategyBudget
from mm.risk.engine import RiskEngine


class RuntimeGovernanceTest(unittest.TestCase):
    def test_config_change_audit_detects_strategy_param_change(self):
        old = AppSettings.from_file("config/paper.json")
        data = _paper_data()
        data["strategies"][0]["params"]["spread_bps"] = "25"
        new = AppSettings.from_config(data)
        report = diff_settings(old, new)
        self.assertTrue(report.changed)
        self.assertTrue(any(change.path.startswith("strategies.basic_mm") for change in report.changes))

    def test_order_budget_allocator_limits_per_strategy(self):
        intents = [
            _intent("a", "basic_mm"),
            _intent("b", "basic_mm"),
            _intent("c", "basic_mm"),
        ]
        allocator = OrderBudgetAllocator([StrategyBudget("basic_mm", max_place=2, max_cancel=1)])
        accepted, report = allocator.apply(intents)
        self.assertEqual(len(accepted), 2)
        self.assertEqual(report.rejected, 1)
        self.assertEqual(report.used_place["basic_mm"], 2)

    def test_runtime_snapshot_after_paper_run(self):
        async def scenario():
            app = MarketMakerApp(AppSettings.from_file("config/paper.json"))
            await app.run(ticks=1)
            snapshot = app.runtime_snapshot()
            self.assertTrue(snapshot.health_ok)
            self.assertIn("BTC_USDT", snapshot.symbols)
            self.assertIn("USDT", snapshot.balances)

        asyncio.run(scenario())

    def test_strategy_max_order_value_rejects(self):
        data = _paper_data()
        data["risk"]["per_strategy_max_order_value_usdt"] = {"basic_mm": "1"}
        settings = AppSettings.from_config(data)
        inventory = InventoryManager()
        inventory.update([Balance("BTC", Decimal("0.01")), Balance("USDT", Decimal("1000"))])
        risk = RiskEngine(settings.risk, settings.market_rules, settings.stale_market_data_ms)
        market = MarketSnapshot(
            symbol="BTC_USDT",
            bid=Decimal("67990"),
            bid_size=Decimal("1"),
            ask=Decimal("68010"),
            ask_size=Decimal("1"),
            last=Decimal("68000"),
        )
        intent = _intent("too-large", "basic_mm")
        result = risk.validate(intent, {"BTC_USDT": market}, inventory, OrderManager())
        self.assertFalse(result.approved)
        self.assertEqual(result.rule, "strategy_max_order_value")


def _paper_data():
    import json

    with open("config/paper.json", "r", encoding="utf-8") as fh:
        return json.load(fh)


def _intent(client_order_id, strategy):
    return OrderIntent(
        action="place",
        symbol="BTC_USDT",
        side=Side.BUY,
        price=Decimal("67900"),
        size=Decimal("0.00005"),
        client_order_id=client_order_id,
        old_client_order_id=None,
        strategy=strategy,
        level=1,
        order_type=OrderType.LIMIT_MAKER,
    )


if __name__ == "__main__":
    unittest.main()

