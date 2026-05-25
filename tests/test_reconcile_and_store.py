import asyncio
import os
import tempfile
import unittest
from decimal import Decimal

from mm.common.types import OrderRequest, OrderStatus, OrderType, Side
from mm.config.settings import AppSettings
from mm.exchange.dry_run import DryRunExchange
from mm.exchange.paper import PaperExchange
from mm.oms.manager import OrderManager
from mm.oms.order import OrderRecord
from mm.oms.reconcile import ReconciliationService
from mm.persistence.order_store import JsonOrderStore, SQLiteOrderStore, build_order_store


class ReconcileAndStoreTest(unittest.TestCase):
    def test_order_store_round_trip(self):
        async def scenario(path):
            settings = AppSettings.from_file("config/paper.json")
            exchange = PaperExchange(settings.market_rules, settings.paper["initial_prices"], settings.paper["balances"])
            store = JsonOrderStore(path)
            oms = OrderManager(order_store=store)
            await oms.submit(
                exchange,
                OrderRequest(
                    symbol="BTC_USDT",
                    side=Side.BUY,
                    order_type=OrderType.LIMIT_MAKER,
                    price=Decimal("67000"),
                    size=Decimal("0.00005"),
                    client_order_id="persist1",
                    strategy="test",
                ),
            )
            restored = OrderManager(order_store=store)
            self.assertIsNotNone(restored.get("persist1"))
            self.assertEqual(restored.get("persist1").status, OrderStatus.OPEN)

        with tempfile.TemporaryDirectory() as tmp:
            asyncio.run(scenario(os.path.join(tmp, "orders.json")))

    def test_sqlite_order_store_round_trip(self):
        async def scenario(path):
            settings = AppSettings.from_file("config/paper.json")
            exchange = PaperExchange(settings.market_rules, settings.paper["initial_prices"], settings.paper["balances"])
            store = SQLiteOrderStore(path)
            oms = OrderManager(order_store=store)
            await oms.submit(
                exchange,
                OrderRequest(
                    symbol="BTC_USDT",
                    side=Side.SELL,
                    order_type=OrderType.LIMIT_MAKER,
                    price=Decimal("69000"),
                    size=Decimal("0.00005"),
                    client_order_id="sqlite-persist",
                    strategy="test",
                ),
            )
            restored = OrderManager(order_store=build_order_store(path))
            self.assertEqual(restored.get("sqlite-persist").status, OrderStatus.OPEN)
            self.assertEqual(restored.get("sqlite-persist").exchange_order_id, "paper-1")

        with tempfile.TemporaryDirectory() as tmp:
            asyncio.run(scenario(os.path.join(tmp, "orders.db")))

    def test_sqlite_save_order_does_not_delete_other_orders(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = SQLiteOrderStore(os.path.join(tmp, "orders.db"))
            first = OrderRecord.from_request(
                OrderRequest(
                    symbol="BTC_USDT",
                    side=Side.BUY,
                    order_type=OrderType.LIMIT_MAKER,
                    price=Decimal("67000"),
                    size=Decimal("0.00005"),
                    client_order_id="sqlite-incremental-1",
                    strategy="test",
                )
            )
            second = OrderRecord.from_request(
                OrderRequest(
                    symbol="SYNBO_USDT",
                    side=Side.BUY,
                    order_type=OrderType.LIMIT_MAKER,
                    price=Decimal("1"),
                    size=Decimal("60"),
                    client_order_id="sqlite-incremental-2",
                    strategy="test",
                )
            )
            first.status = OrderStatus.OPEN
            second.status = OrderStatus.OPEN
            store.save([first, second])
            first.status = OrderStatus.CANCELED
            store.save_order(first)

            restored = {order.client_order_id: order for order in store.load()}
            self.assertEqual(restored["sqlite-incremental-1"].status, OrderStatus.CANCELED)
            self.assertEqual(restored["sqlite-incremental-2"].status, OrderStatus.OPEN)

    def test_reconcile_marks_missing_local_open_unknown(self):
        async def scenario():
            settings = AppSettings.from_file("config/paper.json")
            exchange = PaperExchange(settings.market_rules, settings.paper["initial_prices"], settings.paper["balances"])
            oms = OrderManager()
            await oms.submit(
                exchange,
                OrderRequest(
                    symbol="BTC_USDT",
                    side=Side.BUY,
                    order_type=OrderType.LIMIT_MAKER,
                    price=Decimal("67000"),
                    size=Decimal("0.00005"),
                    client_order_id="local-missing",
                    strategy="test",
                ),
            )
            exchange.open_orders.clear()
            report = await ReconciliationService(oms, exchange).reconcile_open_orders("BTC_USDT")
            self.assertEqual(report.unknown_count, 1)
            self.assertEqual(oms.get("local-missing").status, OrderStatus.UNKNOWN)

        asyncio.run(scenario())

    def test_reconcile_is_symbol_scoped(self):
        async def scenario():
            settings = AppSettings.from_file("config/paper.json")
            exchange = PaperExchange(settings.market_rules, settings.paper["initial_prices"], settings.paper["balances"])
            oms = OrderManager()
            await oms.submit(
                exchange,
                OrderRequest(
                    symbol="BTC_USDT",
                    side=Side.BUY,
                    order_type=OrderType.LIMIT_MAKER,
                    price=Decimal("67000"),
                    size=Decimal("0.00005"),
                    client_order_id="btc-live",
                    strategy="test",
                ),
            )
            await oms.submit(
                exchange,
                OrderRequest(
                    symbol="SYNBO_USDT",
                    side=Side.BUY,
                    order_type=OrderType.LIMIT_MAKER,
                    price=Decimal("1"),
                    size=Decimal("60"),
                    client_order_id="synbo-live",
                    strategy="test",
                ),
            )
            exchange.open_orders.pop("btc-live")
            report = await ReconciliationService(oms, exchange).reconcile_open_orders("BTC_USDT")
            self.assertEqual(report.unknown_count, 1)
            self.assertEqual(oms.get("btc-live").status, OrderStatus.UNKNOWN)
            self.assertEqual(oms.get("synbo-live").status, OrderStatus.OPEN)

        asyncio.run(scenario())

    def test_live_dry_run_shadow_orders_are_not_marked_unknown_by_remote_reconcile(self):
        async def scenario():
            settings = AppSettings.from_file("config/paper.json")
            wrapped = PaperExchange(settings.market_rules, settings.paper["initial_prices"], settings.paper["balances"])
            exchange = DryRunExchange(wrapped)
            oms = OrderManager()
            await oms.submit(
                exchange,
                OrderRequest(
                    symbol="BTC_USDT",
                    side=Side.BUY,
                    order_type=OrderType.LIMIT_MAKER,
                    price=Decimal("67000"),
                    size=Decimal("0.00005"),
                    client_order_id="dry-run-shadow",
                    strategy="test",
                ),
            )
            report = await ReconciliationService(oms, exchange).reconcile_open_orders("BTC_USDT")
            self.assertEqual(report.unknown_count, 0)
            self.assertEqual(oms.get("dry-run-shadow").status, OrderStatus.OPEN)

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
