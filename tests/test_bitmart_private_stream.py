import unittest
from decimal import Decimal

from mm.common.types import OrderRequest, OrderStatus, OrderType, Side
from mm.exchange.bitmart.private_stream import BitMartPrivateStreamProcessor
from mm.inventory.manager import InventoryManager
from mm.oms.manager import OrderManager
from mm.oms.order import OrderRecord


class BitMartPrivateStreamProcessorTest(unittest.TestCase):
    def test_private_order_update_closes_local_order(self):
        oms = OrderManager()
        request = OrderRequest(
            symbol="BTC_USDT",
            side=Side.BUY,
            order_type=OrderType.LIMIT_MAKER,
            price=Decimal("100"),
            size=Decimal("0.1"),
            client_order_id="cid-1",
            strategy="basic_mm",
        )
        record = oms._orders[request.client_order_id] = OrderRecord.from_request(request)
        record.status = OrderStatus.OPEN

        processor = BitMartPrivateStreamProcessor(oms, InventoryManager())
        report = processor.apply_message(
            {
                "table": "spot/user/order:BTC_USDT",
                "data": [
                    {
                        "symbol": "BTC_USDT",
                        "client_order_id": "cid-1",
                        "order_id": "remote-1",
                        "order_state": "filled",
                        "filled_size": "0.1",
                        "price": "100",
                        "side": "buy",
                    }
                ],
            }
        )
        self.assertEqual(report.order_updates, 1)
        self.assertEqual(len(report.fills), 1)
        self.assertEqual(report.fills[0].client_order_id, "cid-1")
        self.assertEqual(report.fills[0].size, Decimal("0.1"))
        self.assertEqual(oms.get("cid-1").status, OrderStatus.FILLED)
        self.assertEqual(oms.get("cid-1").exchange_order_id, "remote-1")

    def test_private_fill_can_arrive_before_rest_ack(self):
        oms = OrderManager()
        request = OrderRequest(
            symbol="BTC_USDT",
            side=Side.BUY,
            order_type=OrderType.LIMIT_MAKER,
            price=Decimal("100"),
            size=Decimal("0.1"),
            client_order_id="cid-submitting",
            strategy="basic_mm",
        )
        record = oms._orders[request.client_order_id] = OrderRecord.from_request(request)
        record.status = OrderStatus.SUBMITTING

        processor = BitMartPrivateStreamProcessor(oms, InventoryManager())
        report = processor.apply_message(
            {
                "table": "spot/user/order:BTC_USDT",
                "data": [
                    {
                        "symbol": "BTC_USDT",
                        "client_order_id": "cid-submitting",
                        "order_id": "remote-submitting",
                        "order_state": "filled",
                        "filled_size": "0.1",
                        "last_fill_price": "100",
                        "side": "buy",
                        "exec_type": "M",
                        "trade_id": "trade-1",
                    }
                ],
            }
        )
        self.assertEqual(oms.get("cid-submitting").status, OrderStatus.FILLED)
        self.assertEqual(len(report.fills), 1)
        self.assertEqual(report.fills[0].liquidity.value, "maker")
        self.assertEqual(report.fills[0].trade_id, "trade-1")

    def test_private_orphan_order_becomes_unknown(self):
        oms = OrderManager()
        processor = BitMartPrivateStreamProcessor(oms, InventoryManager())
        report = processor.apply_message(
            {
                "table": "spot/user/orders",
                "data": [
                    {
                        "symbol": "BTC_USDT",
                        "client_order_id": "orphan-1",
                        "order_id": "remote-2",
                        "order_state": "new",
                        "filled_size": "0",
                        "side": "sell",
                    }
                ],
            }
        )
        self.assertEqual(report.orphan_orders, 1)
        self.assertEqual(report.unknown_orders, 1)
        self.assertEqual(oms.get("orphan-1").status, OrderStatus.UNKNOWN)


if __name__ == "__main__":
    unittest.main()
