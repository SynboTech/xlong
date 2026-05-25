import asyncio
import unittest
from decimal import Decimal

from mm.common.types import OrderRequest, OrderStatus, OrderType, Side
from mm.config.settings import AppSettings
from mm.exchange.paper import PaperExchange
from mm.oms.manager import OrderManager, OrderStateError


class OmsTest(unittest.TestCase):
    def test_submit_cancel_lifecycle(self):
        async def scenario():
            settings = AppSettings.from_file("config/paper.json")
            exchange = PaperExchange(
                settings.market_rules,
                settings.paper["initial_prices"],
                settings.paper["balances"],
            )
            oms = OrderManager()
            request = OrderRequest(
                symbol="BTC_USDT",
                side=Side.BUY,
                order_type=OrderType.LIMIT_MAKER,
                price=Decimal("67000"),
                size=Decimal("0.00005"),
                client_order_id="test-buy-1",
                strategy="test",
            )
            record = await oms.submit(exchange, request)
            self.assertEqual(record.status, OrderStatus.OPEN)
            record = await oms.cancel(exchange, record_cancel(record))
            self.assertEqual(record.status, OrderStatus.CANCELED)

        asyncio.run(scenario())

    def test_terminal_state_does_not_reopen(self):
        async def scenario():
            settings = AppSettings.from_file("config/paper.json")
            exchange = PaperExchange(
                settings.market_rules,
                settings.paper["initial_prices"],
                settings.paper["balances"],
            )
            oms = OrderManager()
            request = OrderRequest(
                symbol="BTC_USDT",
                side=Side.BUY,
                order_type=OrderType.LIMIT_MAKER,
                price=Decimal("67000"),
                size=Decimal("0.00005"),
                client_order_id="test-buy-2",
                strategy="test",
            )
            record = await oms.submit(exchange, request)
            await oms.cancel(exchange, record_cancel(record))
            with self.assertRaises(OrderStateError):
                oms.mark_unknown("test-buy-2", "should fail")

        asyncio.run(scenario())


def record_cancel(record):
    from mm.common.types import CancelRequest

    return CancelRequest(
        symbol=record.symbol,
        client_order_id=record.client_order_id,
        exchange_order_id=record.exchange_order_id,
        reason="test",
    )


if __name__ == "__main__":
    unittest.main()

