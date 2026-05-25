import asyncio
import unittest
from decimal import Decimal

from mm.common.types import Balance, FillEvent, Liquidity, MarketSnapshot, OrderStatus, Side
from mm.config.settings import AppSettings
from mm.hedging.engine import HedgingEngine
from mm.inventory.manager import InventoryManager
from mm.market_data.hub import MarketDataHub
from mm.monitoring.health import HealthChecker
from mm.monitoring.metrics import MetricsRegistry
from mm.oms.manager import OrderManager
from mm.risk.drills import RiskDrillSuite
from mm.risk.engine import RiskEngine


class MarketHubMonitoringHedgingTest(unittest.TestCase):
    def test_market_data_hub_depth_and_fair_price(self):
        hub = MarketDataHub(["BTC_USDT"], stale_ms=10000)
        snapshot = hub.apply_bitmart_depth_row(
            {
                "symbol": "BTC_USDT",
                "type": "snapshot",
                "version": 1,
                "asks": [["101", "2"]],
                "bids": [["99", "3"]],
            }
        )
        self.assertEqual(snapshot.bid, Decimal("99"))
        self.assertEqual(snapshot.ask, Decimal("101"))
        hub.apply_external_snapshot(
            "binance",
            MarketSnapshot(
                exchange="binance",
                symbol="BTC_USDT",
                bid=Decimal("109"),
                bid_size=Decimal("1"),
                ask=Decimal("111"),
                ask_size=Decimal("1"),
                last=Decimal("110"),
            ),
        )
        fair = hub.fair_price("BTC_USDT", {"bitmart": Decimal("0.25"), "binance": Decimal("0.75")})
        self.assertEqual(fair.price, Decimal("107.5"))

    def test_metrics_prometheus_output(self):
        metrics = MetricsRegistry()
        metrics.inc("orders", 2, symbol="BTC_USDT")
        metrics.set("pnl", "-1.5")
        text = metrics.prometheus_text()
        self.assertIn('orders{symbol="BTC_USDT"} 2', text)
        self.assertIn("pnl -1.5", text)

    def test_health_checker_detects_safe_mode(self):
        settings = AppSettings.from_file("config/paper.json")
        hub = MarketDataHub(["BTC_USDT"], stale_ms=10000)
        oms = OrderManager()
        risk = RiskEngine(settings.risk, settings.market_rules, settings.stale_market_data_ms)
        risk.safe_mode = True
        health = HealthChecker(hub, oms, risk).check()
        self.assertFalse(health.ok)
        self.assertTrue(any("SAFE_MODE" in failure for failure in health.failures))

    def test_hedging_intent_from_fill(self):
        engine = HedgingEngine(enabled=True, min_hedge_size="0.1")
        fill = FillEvent(
            symbol="BTC_USDT",
            client_order_id="cid",
            exchange_order_id="eid",
            side=Side.BUY,
            price=Decimal("100"),
            size=Decimal("0.1"),
            fee=Decimal("0"),
            fee_currency="USDT",
            liquidity=Liquidity.MAKER,
            trade_id="tid",
        )
        intent = engine.intent_from_fill(fill)
        self.assertEqual(intent.side, Side.SELL)
        result = asyncio.run(engine.execute(intent))
        self.assertTrue(result.accepted)

    def test_risk_drills_pass(self):
        settings = AppSettings.from_file("config/paper.json")
        inventory = InventoryManager()
        inventory.update([Balance("BTC", Decimal("0.01")), Balance("USDT", Decimal("1000"))])
        oms = OrderManager()
        risk = RiskEngine(settings.risk, settings.market_rules, settings.stale_market_data_ms)
        markets = {
            "BTC_USDT": MarketSnapshot(
                symbol="BTC_USDT",
                bid=Decimal("67990"),
                bid_size=Decimal("1"),
                ask=Decimal("68010"),
                ask_size=Decimal("1"),
                last=Decimal("68000"),
            )
        }
        results = RiskDrillSuite(risk, inventory, oms, markets).run()
        self.assertTrue(all(item.passed for item in results))
        self.assertEqual(
            {item.name for item in results},
            {
                "safe_mode_blocks_new_orders",
                "post_only_cross_rejected",
                "stale_market_rejected",
                "unknown_order_rejected",
            },
        )


if __name__ == "__main__":
    unittest.main()
