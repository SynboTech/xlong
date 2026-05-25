import unittest
from decimal import Decimal

from mm.exchange.bitmart.websocket import depth_increase_channel, parse_depth_messages
from mm.market_data.orderbook import OrderBook, OrderBookGap, parse_depth_update


class OrderBookTest(unittest.TestCase):
    def test_depth_channel_name(self):
        self.assertEqual(depth_increase_channel("BTC_USDT"), "spot/depth/increase100:BTC_USDT")

    def test_snapshot_and_incremental_update(self):
        book = OrderBook("BTC_USDT")
        book.apply(
            parse_depth_update(
                {
                    "symbol": "BTC_USDT",
                    "type": "snapshot",
                    "version": 4,
                    "ms_t": 1000,
                    "asks": [["101", "2"], ["102", "3"]],
                    "bids": [["99", "1"]],
                }
            )
        )
        book.apply(
            parse_depth_update(
                {
                    "symbol": "BTC_USDT",
                    "type": "update",
                    "version": 5,
                    "ms_t": 1100,
                    "asks": [["101", "0"], ["100.5", "4"]],
                    "bids": [["99.5", "2"]],
                }
            )
        )
        snapshot = book.snapshot()
        self.assertEqual(snapshot.bid, Decimal("99.5"))
        self.assertEqual(snapshot.ask, Decimal("100.5"))
        self.assertEqual(snapshot.bid_size, Decimal("2"))
        self.assertEqual(snapshot.ask_size, Decimal("4"))
        self.assertEqual(snapshot.bid_levels(2), [(Decimal("99.5"), Decimal("2")), (Decimal("99"), Decimal("1"))])
        self.assertEqual(snapshot.ask_levels(2), [(Decimal("100.5"), Decimal("4")), (Decimal("102"), Decimal("3"))])

    def test_depth_gap_raises(self):
        book = OrderBook("BTC_USDT")
        book.apply(
            parse_depth_update(
                {
                    "symbol": "BTC_USDT",
                    "type": "snapshot",
                    "version": 4,
                    "asks": [],
                    "bids": [],
                }
            )
        )
        with self.assertRaises(OrderBookGap):
            book.apply(
                parse_depth_update(
                    {
                        "symbol": "BTC_USDT",
                        "type": "update",
                        "version": 7,
                        "asks": [],
                        "bids": [],
                    }
                )
            )

    def test_parse_depth_ws_message(self):
        rows = parse_depth_messages(
            {
                "table": "spot/depth/increase100",
                "data": [
                    {
                        "symbol": "BTC_USDT",
                        "type": "snapshot",
                        "version": 1,
                        "asks": [],
                        "bids": [],
                    }
                ],
            }
        )
        self.assertEqual(len(rows), 1)


if __name__ == "__main__":
    unittest.main()
