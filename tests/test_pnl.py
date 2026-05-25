import unittest
from decimal import Decimal

from mm.accounting.pnl import PnlTracker
from mm.common.types import FillEvent, Liquidity, MarketSnapshot, Side


class PnlTest(unittest.TestCase):
    def test_realized_and_unrealized_pnl(self):
        tracker = PnlTracker()
        tracker.apply_fill(
            FillEvent(
                symbol="BTC_USDT",
                client_order_id="b1",
                exchange_order_id="e1",
                side=Side.BUY,
                price=Decimal("100"),
                size=Decimal("1"),
                fee=Decimal("0"),
                fee_currency="USDT",
                liquidity=Liquidity.MAKER,
                trade_id="t1",
            )
        )
        tracker.apply_fill(
            FillEvent(
                symbol="BTC_USDT",
                client_order_id="s1",
                exchange_order_id="e2",
                side=Side.SELL,
                price=Decimal("110"),
                size=Decimal("0.4"),
                fee=Decimal("1"),
                fee_currency="USDT",
                liquidity=Liquidity.MAKER,
                trade_id="t2",
            )
        )
        market = MarketSnapshot(
            symbol="BTC_USDT",
            bid=Decimal("119"),
            bid_size=Decimal("1"),
            ask=Decimal("121"),
            ask_size=Decimal("1"),
            last=Decimal("120"),
        )
        state = tracker.for_symbol("BTC_USDT")
        self.assertEqual(state.realized_pnl, Decimal("4.0"))
        self.assertEqual(state.position, Decimal("0.6"))
        self.assertEqual(tracker.total_pnl({"BTC_USDT": market}), Decimal("15.0"))


if __name__ == "__main__":
    unittest.main()

