import asyncio
import os
import tempfile
import time
import unittest
from decimal import Decimal

from mm.common.types import Balance, CancelRequest, MarketSnapshot, OrderRequest, OrderStatus, OrderType, Side, TradingMode
from mm.app import MarketMakerApp
from mm.config.settings import AppSettings, BitMartCredentials
from mm.exchange.base import ExchangeGateway
from mm.exchange.bitmart.private_stream import BitMartPrivateStreamProcessor
from mm.exchange.bitmart.preflight import BitMartPreflight
from mm.exchange.bitmart.rest import BitMartRestGateway
from mm.exchange.dry_run import DryRunExchange
from mm.market_data.external import parse_binance_book_ticker
from mm.oms.order import OrderRecord


class FakeGateway(ExchangeGateway):
    async def get_balances(self):
        return [Balance("USDT", Decimal("10"))]

    async def get_open_orders(self, symbol=None):
        return []

    async def submit_order(self, request):
        raise AssertionError("wrapped gateway submit_order must not be called in dry-run")

    async def cancel_order(self, request):
        raise AssertionError("wrapped gateway cancel_order must not be called in dry-run")

    async def next_market_snapshot(self, symbol):
        return MarketSnapshot(
            symbol=symbol,
            bid=Decimal("99"),
            bid_size=Decimal("1"),
            ask=Decimal("101"),
            ask_size=Decimal("1"),
            last=Decimal("100"),
        )


class LiveControlsTest(unittest.TestCase):
    def setUp(self):
        self.old_env = {key: os.environ.get(key) for key in ["BITMART_API_KEY", "BITMART_API_SECRET", "BITMART_API_MEMO"]}
        os.environ["BITMART_API_KEY"] = "key"
        os.environ["BITMART_API_SECRET"] = "secret"
        os.environ["BITMART_API_MEMO"] = "memo"

    def tearDown(self):
        for key, value in self.old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_live_read_only_config_loads_with_credentials(self):
        data = _base_live_config("live_read_only")
        settings = AppSettings.from_config(data)
        self.assertEqual(settings.trading_mode, TradingMode.LIVE_READ_ONLY)
        self.assertFalse(settings.enable_order_submission)

    def test_live_requires_order_submission_enabled(self):
        data = _base_live_config("live")
        data["enable_order_submission"] = False
        with self.assertRaises(ValueError):
            AppSettings.from_config(data)

    def test_dry_run_exchange_does_not_call_wrapped_submit(self):
        async def scenario():
            exchange = DryRunExchange(FakeGateway())
            ack = await exchange.submit_order(
                OrderRequest(
                    symbol="BTC_USDT",
                    side=Side.BUY,
                    order_type=OrderType.LIMIT_MAKER,
                    price=Decimal("99"),
                    size=Decimal("0.1"),
                    client_order_id="cid",
                    strategy="test",
                )
            )
            self.assertTrue(ack.accepted)
            self.assertEqual(len(exchange.submitted), 1)

        asyncio.run(scenario())

    def test_live_dry_run_app_uses_real_gateway_for_market_shadow(self):
        settings = AppSettings.from_config(_base_live_config("live_dry_run"))
        app = MarketMakerApp(settings)
        self.assertIsInstance(app.gateway, DryRunExchange)
        self.assertIs(app.gateway.market_data_fallback, app.gateway.wrapped)

    def test_preflight_read_only_passes_without_network(self):
        async def scenario():
            settings = AppSettings.from_config(_base_live_config("live_read_only"))
            report = await BitMartPreflight(settings, FakeGateway()).run(network=False)
            self.assertTrue(report.passed)

        asyncio.run(scenario())

    def test_bitmart_batch_requests_are_split_by_symbol(self):
        async def scenario():
            gateway = CapturingBitMartGateway()
            await gateway.submit_batch_orders(
                [
                    OrderRequest("BTC_USDT", Side.BUY, OrderType.LIMIT_MAKER, Decimal("0.1"), Decimal("100"), "btc-1", "s"),
                    OrderRequest("SYNBO_USDT", Side.SELL, OrderType.LIMIT_MAKER, Decimal("10"), Decimal("1"), "synbo-1", "s"),
                ]
            )
            submit_symbols = [call["body"]["symbol"] for call in gateway.calls if call["path"] == "/spot/v4/batch_orders"]
            self.assertEqual(submit_symbols, ["BTC_USDT", "SYNBO_USDT"])

            gateway.calls.clear()
            await gateway.cancel_batch_orders(
                [
                    CancelRequest("BTC_USDT", "btc-1", "1"),
                    CancelRequest("SYNBO_USDT", "synbo-1", "2"),
                ]
            )
            cancel_symbols = [call["body"]["symbol"] for call in gateway.calls if call["path"] == "/spot/v4/cancel_orders"]
            self.assertEqual(cancel_symbols, ["BTC_USDT", "SYNBO_USDT"])

        asyncio.run(scenario())

    def test_bitmart_batch_missing_row_is_unknown(self):
        async def scenario():
            gateway = PartialBatchBitMartGateway()
            acks = await gateway.submit_batch_orders(
                [
                    OrderRequest("BTC_USDT", Side.BUY, OrderType.LIMIT_MAKER, Decimal("0.1"), Decimal("100"), "btc-1", "s"),
                    OrderRequest("BTC_USDT", Side.SELL, OrderType.LIMIT_MAKER, Decimal("0.1"), Decimal("101"), "btc-2", "s"),
                ]
            )
            self.assertTrue(acks[0].accepted)
            self.assertFalse(acks[1].accepted)
            self.assertEqual(acks[1].status, OrderStatus.UNKNOWN)

        asyncio.run(scenario())

    def test_bitmart_rest_request_runs_off_event_loop(self):
        async def scenario():
            gateway = SlowBitMartGateway()
            start = time.monotonic()

            async def marker():
                await asyncio.sleep(0.05)
                return time.monotonic() - start

            _, marker_elapsed = await asyncio.gather(gateway.get_balances(), marker())
            self.assertLess(marker_elapsed, 0.22)

        asyncio.run(scenario())

    def test_app_private_stream_feeds_oms_and_inventory(self):
        async def scenario():
            data = _base_live_config("live_read_only")
            with tempfile.TemporaryDirectory() as tmp:
                data["event_log_path"] = os.path.join(tmp, "events.jsonl")
                data["order_store_path"] = os.path.join(tmp, "orders.db")
                settings = AppSettings.from_config(data)
                app = MarketMakerApp(settings)
                self.assertTrue(app._should_start_private_stream())
                request = OrderRequest(
                    "BTC_USDT",
                    Side.BUY,
                    OrderType.LIMIT_MAKER,
                    Decimal("0.1"),
                    Decimal("100"),
                    "cid-private",
                    "basic_mm",
                )
                record = OrderRecord.from_request(request)
                record.status = OrderStatus.OPEN
                app.oms._orders[request.client_order_id] = record
                processor = BitMartPrivateStreamProcessor(app.oms, app.inventory, app.event_log)
                await app._consume_private_stream(
                    FakePrivateStreamClient(
                        [
                            {
                                "table": "spot/user/order:BTC_USDT",
                                "data": [
                                    {
                                        "symbol": "BTC_USDT",
                                        "client_order_id": "cid-private",
                                        "order_id": "remote-private",
                                        "order_state": "filled",
                                        "filled_size": "0.1",
                                        "price": "100",
                                        "side": "buy",
                                    }
                                ],
                            },
                            {
                                "table": "spot/user/balance",
                                "data": [
                                    {
                                        "balance_details": [
                                            {"ccy": "USDT", "av_bal": "9", "fz_bal": "1"}
                                        ]
                                    }
                                ],
                            },
                        ]
                    ),
                    processor,
                )
                self.assertEqual(app.oms.get("cid-private").status, OrderStatus.FILLED)
                self.assertEqual(app._fills, 1)
                self.assertEqual(app.pnl.for_symbol("BTC_USDT").position, Decimal("0.1"))
                self.assertEqual(app.inventory.balance("USDT").available, Decimal("9"))
                self.assertEqual(app.inventory.balance("USDT").frozen, Decimal("1"))

        asyncio.run(scenario())

    def test_binance_book_ticker_parser(self):
        snapshot = parse_binance_book_ticker(
            "BTC_USDT",
            {
                "symbol": "BTCUSDT",
                "bidPrice": "99",
                "bidQty": "1.5",
                "askPrice": "101",
                "askQty": "2.5",
            },
        )
        self.assertEqual(snapshot.exchange, "binance")
        self.assertEqual(snapshot.bid, Decimal("99"))
        self.assertEqual(snapshot.ask_size, Decimal("2.5"))


def _base_live_config(mode):
    return {
        "trading_mode": mode,
        "live_confirm": True,
        "enable_order_submission": mode == "live",
        "exchange": "bitmart",
        "symbols": ["BTC_USDT"],
        "risk": {
            "max_order_value_usdt": "10",
            "max_total_open_value_usdt": "50",
            "max_open_orders": 10,
            "max_position_base": "0.02",
            "max_daily_loss_usdt": "20",
            "max_price_deviation_bps": "50",
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
        "paper": {},
        "security": {
            "api_key_no_withdraw_permission_ack": True,
            "api_key_ip_whitelist_ack": True,
            "production_runbook_ack": True,
        },
        "strategies": [],
    }


class CapturingBitMartGateway(BitMartRestGateway):
    def __init__(self):
        super().__init__(BitMartCredentials("key", "secret", "memo"))
        self.calls = []

    def _request(self, method, path, params=None, body=None, keyed=False, signed=False):
        self.calls.append({"method": method, "path": path, "params": params, "body": body})
        if path == "/spot/v4/batch_orders":
            return {"orderIds": ["remote-{0}".format(item["clientOrderId"]) for item in body["orderParams"]]}
        if path == "/spot/v4/cancel_orders":
            return {"result": True}
        return {}


class PartialBatchBitMartGateway(BitMartRestGateway):
    def __init__(self):
        super().__init__(BitMartCredentials("key", "secret", "memo"))

    def _request(self, method, path, params=None, body=None, keyed=False, signed=False):
        if path == "/spot/v4/batch_orders":
            return {"orderIds": ["remote-{0}".format(body["orderParams"][0]["clientOrderId"])]}
        return {}


class SlowBitMartGateway(BitMartRestGateway):
    def __init__(self):
        super().__init__(BitMartCredentials("key", "secret", "memo"))

    def _request(self, method, path, params=None, body=None, keyed=False, signed=False):
        time.sleep(0.25)
        if path == "/spot/v1/wallet":
            return {"wallet": []}
        return {}


class FakePrivateStreamClient:
    def __init__(self, messages):
        self.messages = messages

    async def stream(self):
        for message in self.messages:
            yield message


if __name__ == "__main__":
    unittest.main()
