import os
import unittest

from mm.config.settings import AppSettings
from mm.common.ids import new_client_order_id
from mm.exchange.bitmart.signer import sign


class ConfigAndSignerTest(unittest.TestCase):
    def test_load_paper_config(self):
        settings = AppSettings.from_file("config/paper.json")
        self.assertEqual(settings.trading_mode.value, "paper")
        self.assertIn("BTC_USDT", settings.market_rules)
        self.assertFalse(settings.live_confirm)

    def test_live_mode_requires_credentials(self):
        for key in ["BITMART_API_KEY", "BITMART_API_SECRET", "BITMART_API_MEMO"]:
            os.environ.pop(key, None)
        data = {
            "trading_mode": "live",
            "live_confirm": True,
            "exchange": "bitmart",
            "symbols": ["BTC_USDT"],
            "risk": {
                "max_order_value_usdt": "1",
                "max_total_open_value_usdt": "1",
                "max_open_orders": 1,
                "max_position_base": "1",
                "max_daily_loss_usdt": "1",
                "max_price_deviation_bps": "10",
            },
            "market_rules": {
                "BTC_USDT": {
                    "base": "BTC",
                    "quote": "USDT",
                    "price_increment": "0.01",
                    "size_increment": "0.000001",
                    "base_min_size": "0.000001",
                    "min_notional": "1",
                }
            },
        }
        with self.assertRaises(ValueError):
            AppSettings.from_config(data)

    def test_bitmart_signature_doc_vector_with_raw_body(self):
        body = '{"symbol":"BTC_USDT","price":"8600","count":"100"}'
        digest = sign(
            1589793796145,
            "test001",
            body,
            "6c6c98544461bbe71db2bca4c6d7fd0021e0ba9efc215f9c6ad41852df9d9df9",
        )
        self.assertEqual(
            digest,
            "c31dc326bf87f38bfb49a3f8494961abfa291bd549d0d98d9578e87516cee46d",
        )

    def test_client_order_id_is_bitmart_safe(self):
        client_id = new_client_order_id("basic_mm", "BTC_USDT", "buy", 1)
        self.assertLessEqual(len(client_id), 32)
        self.assertTrue(client_id.isalnum())


if __name__ == "__main__":
    unittest.main()
