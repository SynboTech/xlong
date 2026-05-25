import asyncio
import unittest
from decimal import Decimal

from mm.common.types import FillEvent, Liquidity, Side
from mm.config.settings import BitMartCredentials
from mm.exchange.bitmart.smoke import private_ws_smoke, public_ws_smoke
from mm.hedging.adapters import BinanceHedgeAdapter
from mm.hedging.engine import HedgingEngine


class SmokeAndHedgeAdaptersTest(unittest.TestCase):
    def test_public_ws_smoke_dry_run(self):
        report = asyncio.run(public_ws_smoke("BTC_USDT", dry_run=True))
        self.assertTrue(report.passed)
        self.assertTrue(report.dry_run)
        self.assertEqual(report.subscription["op"], "subscribe")
        self.assertIn("spot/depth/increase100:BTC_USDT", report.channels)

    def test_private_ws_smoke_dry_run(self):
        report = asyncio.run(private_ws_smoke(BitMartCredentials("key", "secret", "memo"), dry_run=True))
        self.assertTrue(report.passed)
        self.assertIsNotNone(report.login_payload)
        self.assertEqual(report.login_payload["op"], "login")

    def test_binance_hedge_adapter_builds_dry_run_market_order(self):
        adapter = BinanceHedgeAdapter(dry_run=True)
        engine = HedgingEngine(enabled=True, min_hedge_size="0", adapter=adapter)
        fill = FillEvent(
            symbol="BTC_USDT",
            client_order_id="cid",
            exchange_order_id="eid",
            side=Side.SELL,
            price=Decimal("100"),
            size=Decimal("0.25"),
            fee=Decimal("0"),
            fee_currency="USDT",
            liquidity=Liquidity.MAKER,
            trade_id="tid",
        )
        intent = engine.intent_from_fill(fill)
        result = asyncio.run(engine.execute(intent))
        self.assertTrue(result.accepted)
        self.assertEqual(adapter.last_order.symbol, "BTCUSDT")
        self.assertEqual(adapter.last_order.side, "BUY")


if __name__ == "__main__":
    unittest.main()

