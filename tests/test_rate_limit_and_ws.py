import unittest

from mm.exchange.bitmart.websocket import (
    depth_channel,
    login,
    parse_balance_update,
    parse_private_order_update,
    private_all_orders_channel,
    private_balance_channel,
    subscribe,
)
from mm.config.settings import BitMartCredentials
from mm.exchange.rate_limit import SlidingWindowRateLimiter
from mm.common.types import OrderStatus


class RateLimitAndWebSocketTest(unittest.TestCase):
    def test_rate_limiter_blocks_after_budget(self):
        limiter = SlidingWindowRateLimiter(2, 10)
        self.assertTrue(limiter.allow())
        self.assertTrue(limiter.allow())
        self.assertFalse(limiter.allow())

    def test_websocket_channel_builders(self):
        sub = subscribe([depth_channel("BTC_USDT", 20), private_all_orders_channel(), private_balance_channel()])
        self.assertEqual(sub.as_dict()["op"], "subscribe")
        self.assertIn("spot/depth20:BTC_USDT", sub.as_dict()["args"])
        self.assertIn("spot/user/orders:ALL_SYMBOLS", sub.as_dict()["args"])

    def test_websocket_login_builder(self):
        sub = login(BitMartCredentials("key", "secret", "memo"))
        self.assertEqual(sub.as_dict()["op"], "login")
        self.assertEqual(sub.as_dict()["args"][0], "key")
        self.assertEqual(len(sub.as_dict()["args"]), 3)

    def test_parse_private_order_update(self):
        update = parse_private_order_update(
            {
                "symbol": "BTC_USDT",
                "client_order_id": "cid",
                "order_id": "oid",
                "order_state": "partially_filled",
                "filled_size": "0.1",
                "last_fill_price": "100",
            }
        )
        self.assertEqual(update.status, OrderStatus.PARTIALLY_FILLED)
        self.assertEqual(str(update.filled_size), "0.1")

    def test_parse_balance_update(self):
        balances = parse_balance_update(
            {
                "balance_details": [
                    {"ccy": "USDT", "av_bal": "10", "fz_bal": "2"},
                    {"ccy": "BTC", "av_bal": "1", "fz_bal": "0"},
                ]
            }
        )
        self.assertEqual(len(balances), 2)
        self.assertEqual(balances[0].currency, "USDT")
        self.assertEqual(str(balances[0].total), "12")


if __name__ == "__main__":
    unittest.main()
