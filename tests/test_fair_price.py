import unittest
from decimal import Decimal

from mm.market_data.fair_price import FairPriceEngine, FairPriceSource
from mm.common.types import MarketSnapshot


class FairPriceTest(unittest.TestCase):
    def test_weighted_fair_price(self):
        engine = FairPriceEngine(stale_ms=10000)
        bitmart = MarketSnapshot(
            exchange="bitmart",
            symbol="BTC_USDT",
            bid=Decimal("99"),
            bid_size=Decimal("1"),
            ask=Decimal("101"),
            ask_size=Decimal("1"),
            last=Decimal("100"),
        )
        binance = MarketSnapshot(
            exchange="binance",
            symbol="BTC_USDT",
            bid=Decimal("109"),
            bid_size=Decimal("1"),
            ask=Decimal("111"),
            ask_size=Decimal("1"),
            last=Decimal("110"),
        )
        fair = engine.compute(
            "BTC_USDT",
            [
                FairPriceSource("bitmart", Decimal("0.25"), bitmart),
                FairPriceSource("binance", Decimal("0.75"), binance),
            ],
        )
        self.assertIsNotNone(fair)
        self.assertEqual(fair.price, Decimal("107.5"))
        self.assertEqual(fair.sources, ["bitmart", "binance"])


if __name__ == "__main__":
    unittest.main()

