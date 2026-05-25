import asyncio
import unittest
from decimal import Decimal

from mm.common.types import Balance, MarketSnapshot, OrderIntent, OrderStatus, OrderType, Side
from mm.config.settings import AppSettings, StrategySettings
from mm.inventory.manager import InventoryManager
from mm.app import MarketMakerApp
from mm.oms.manager import OrderManager
from mm.oms.order import OrderRecord
from mm.quote.engine import QuoteEngine
from mm.risk.engine import RiskEngine
from mm.strategy.engine import PLUGIN_REGISTRY, StrategyEngine


class StrategyQuoteRiskTest(unittest.TestCase):
    def test_all_admin_strategy_templates_are_registered(self):
        self.assertIn("basic_mm", PLUGIN_REGISTRY)
        self.assertIn("inventory_skew", PLUGIN_REGISTRY)
        self.assertIn("ladder_mm", PLUGIN_REGISTRY)
        self.assertIn("volatility_spread", PLUGIN_REGISTRY)
        self.assertIn("hedged_mm", PLUGIN_REGISTRY)
        self.assertIn("range_rebalance", PLUGIN_REGISTRY)
        self.assertIn("microprice_mm", PLUGIN_REGISTRY)
        self.assertIn("order_book_imbalance", PLUGIN_REGISTRY)
        self.assertIn("avellaneda_stoikov", PLUGIN_REGISTRY)

    def test_strategy_generates_quotes_and_quote_engine_places(self):
        async def scenario():
            settings = AppSettings.from_file("config/paper.json")
            strategy = StrategyEngine(settings.market_rules, settings.strategies)
            await strategy.on_balances(
                [
                    Balance("BTC", Decimal("0.01")),
                    Balance("USDT", Decimal("1000")),
                ]
            )
            market = MarketSnapshot(
                symbol="BTC_USDT",
                bid=Decimal("67990"),
                bid_size=Decimal("1"),
                ask=Decimal("68010"),
                ask_size=Decimal("1"),
                last=Decimal("68000"),
            )
            await strategy.on_market(market)
            quotes = await strategy.generate_quotes()
            self.assertEqual(len(quotes), 4)
            quote_engine = QuoteEngine(settings.market_rules, 0)
            intents = quote_engine.build_order_intents(quotes, [], {"BTC_USDT": market})
            self.assertEqual(len(intents), 4)
            self.assertTrue(all(intent.action == "place" for intent in intents))

        asyncio.run(scenario())

    def test_ladder_strategy_generates_asymmetric_depth(self):
        async def scenario():
            settings = AppSettings.from_file("config/paper.json")
            strategy = StrategyEngine(
                settings.market_rules,
                [
                    StrategySettings(
                        name="ladder_mm",
                        symbol="BTC_USDT",
                        enabled=True,
                        params={
                            "base_spread_bps": "20",
                            "bid_levels": 3,
                            "ask_levels": 2,
                            "base_order_size": "0.00005",
                            "level_spacing_bps": "10",
                            "size_multiplier": "2",
                            "max_distance_bps": "80",
                        },
                    )
                ],
            )
            market = MarketSnapshot(
                symbol="BTC_USDT",
                bid=Decimal("67990"),
                bid_size=Decimal("1"),
                ask=Decimal("68010"),
                ask_size=Decimal("1"),
                last=Decimal("68000"),
            )
            await strategy.on_market(market)
            quotes = await strategy.generate_quotes()
            self.assertEqual(len(quotes), 5)
            self.assertEqual(len([quote for quote in quotes if quote.side == Side.BUY]), 3)
            self.assertEqual(len([quote for quote in quotes if quote.side == Side.SELL]), 2)
            self.assertEqual(quotes[1].size, Decimal("0.0001"))

        asyncio.run(scenario())

    def test_volatility_strategy_widens_spread_after_price_move(self):
        async def scenario():
            settings = AppSettings.from_file("config/paper.json")
            strategy = StrategyEngine(
                settings.market_rules,
                [
                    StrategySettings(
                        name="volatility_spread",
                        symbol="BTC_USDT",
                        enabled=True,
                        params={
                            "base_spread_bps": "10",
                            "volatility_window_ms": 60000,
                            "volatility_multiplier": "2",
                            "min_spread_bps": "10",
                            "max_spread_bps": "100",
                            "order_size": "0.00005",
                            "levels": 1,
                        },
                    )
                ],
            )
            first = MarketSnapshot(
                symbol="BTC_USDT",
                bid=Decimal("9995"),
                bid_size=Decimal("1"),
                ask=Decimal("10005"),
                ask_size=Decimal("1"),
                last=Decimal("10000"),
                receive_time_ms=1000,
            )
            second = MarketSnapshot(
                symbol="BTC_USDT",
                bid=Decimal("10095"),
                bid_size=Decimal("1"),
                ask=Decimal("10105"),
                ask_size=Decimal("1"),
                last=Decimal("10100"),
                receive_time_ms=2000,
            )
            await strategy.on_market(first)
            await strategy.on_market(second)
            quotes = await strategy.generate_quotes()
            self.assertEqual(len(quotes), 2)
            spread_bps = ((quotes[1].price - quotes[0].price) / second.mid) * Decimal("10000")
            self.assertGreater(spread_bps, Decimal("10"))

        asyncio.run(scenario())

    def test_hedged_strategy_generates_quotes_and_enables_hedging(self):
        async def scenario():
            settings = AppSettings.from_file("config/paper.json")
            hedged_settings = StrategySettings(
                name="hedged_mm",
                symbol="BTC_USDT",
                enabled=True,
                params={
                    "spread_bps": "22",
                    "order_size": "0.00005",
                    "hedge_exchange": "binance",
                    "hedge_threshold_base": "0.00001",
                    "max_hedge_slippage_bps": "15",
                    "hedge_mode": "reduce_inventory",
                },
            )
            strategy = StrategyEngine(settings.market_rules, [hedged_settings])
            market = MarketSnapshot(
                symbol="BTC_USDT",
                bid=Decimal("67990"),
                bid_size=Decimal("1"),
                ask=Decimal("68010"),
                ask_size=Decimal("1"),
                last=Decimal("68000"),
            )
            await strategy.on_market(market)
            quotes = await strategy.generate_quotes()
            self.assertEqual(len(quotes), 2)
            self.assertTrue(all(quote.strategy == "hedged_mm" for quote in quotes))

            data = {
                "trading_mode": settings.trading_mode.value,
                "live_confirm": settings.live_confirm,
                "enable_order_submission": settings.enable_order_submission,
                "exchange": settings.exchange,
                "symbols": ["BTC_USDT"],
                "quote_interval_ms": settings.quote_interval_ms,
                "min_requote_interval_ms": settings.min_requote_interval_ms,
                "stale_market_data_ms": settings.stale_market_data_ms,
                "cancel_on_shutdown": settings.cancel_on_shutdown,
                "event_log_path": settings.event_log_path,
                "order_store_path": settings.order_store_path,
                "risk": {
                    "max_order_value_usdt": str(settings.risk.max_order_value_usdt),
                    "max_total_open_value_usdt": str(settings.risk.max_total_open_value_usdt),
                    "max_open_orders": settings.risk.max_open_orders,
                    "max_position_base": str(settings.risk.max_position_base),
                    "max_daily_loss_usdt": str(settings.risk.max_daily_loss_usdt),
                    "max_price_deviation_bps": str(settings.risk.max_price_deviation_bps),
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
                "paper": settings.paper,
                "strategies": [
                    {
                        "name": hedged_settings.name,
                        "symbol": hedged_settings.symbol,
                        "enabled": hedged_settings.enabled,
                        "params": hedged_settings.params,
                    }
                ],
                "security": {},
            }
            app = MarketMakerApp(AppSettings.from_config(data))
            self.assertTrue(app.hedging.enabled)
            self.assertEqual(app.hedging.adapter.name, "binance")

        asyncio.run(scenario())

    def test_range_rebalance_generates_passive_buy_quotes_below_buy_band(self):
        async def scenario():
            settings = AppSettings.from_file("config/paper.json")
            strategy = StrategyEngine(
                settings.market_rules,
                [
                    StrategySettings(
                        name="range_rebalance",
                        symbol="BTC_USDT",
                        enabled=True,
                        params={
                            "hard_floor": "67000",
                            "buy_below": "68000",
                            "sell_above": "69000",
                            "hard_ceiling": "70000",
                            "target_base": "0.011",
                            "buy_order_size": "0.00005",
                            "sell_order_size": "0.00005",
                            "levels": 2,
                            "quote_offset_bps": "2",
                            "level_spacing_bps": "5",
                        },
                    )
                ],
            )
            await strategy.on_balances([Balance("BTC", Decimal("0.0109")), Balance("USDT", Decimal("1000"))])
            market = MarketSnapshot(
                symbol="BTC_USDT",
                bid=Decimal("67490"),
                bid_size=Decimal("1"),
                ask=Decimal("67510"),
                ask_size=Decimal("1"),
                last=Decimal("67500"),
            )
            await strategy.on_market(market)
            quotes = await strategy.generate_quotes()
            self.assertEqual(len(quotes), 2)
            self.assertTrue(all(quote.side == Side.BUY for quote in quotes))
            self.assertTrue(all(quote.strategy == "range_rebalance" for quote in quotes))

            quote_engine = QuoteEngine(settings.market_rules, 0)
            intents = quote_engine.build_order_intents(quotes, [], {"BTC_USDT": market})
            self.assertEqual(len(intents), 2)
            self.assertTrue(all(intent.action == "place" for intent in intents))
            self.assertTrue(all(intent.price < market.ask for intent in intents if intent.price is not None))

        asyncio.run(scenario())

    def test_range_rebalance_generates_passive_sell_quotes_above_sell_band(self):
        async def scenario():
            settings = AppSettings.from_file("config/paper.json")
            strategy = StrategyEngine(
                settings.market_rules,
                [
                    StrategySettings(
                        name="range_rebalance",
                        symbol="BTC_USDT",
                        enabled=True,
                        params={
                            "hard_floor": "67000",
                            "buy_below": "68000",
                            "sell_above": "69000",
                            "hard_ceiling": "70000",
                            "target_base": "0.011",
                            "buy_order_size": "0.00005",
                            "sell_order_size": "0.00005",
                            "levels": 2,
                            "quote_offset_bps": "2",
                            "level_spacing_bps": "5",
                        },
                    )
                ],
            )
            await strategy.on_balances([Balance("BTC", Decimal("0.0111")), Balance("USDT", Decimal("1000"))])
            market = MarketSnapshot(
                symbol="BTC_USDT",
                bid=Decimal("69490"),
                bid_size=Decimal("1"),
                ask=Decimal("69510"),
                ask_size=Decimal("1"),
                last=Decimal("69500"),
            )
            await strategy.on_market(market)
            quotes = await strategy.generate_quotes()
            self.assertEqual(len(quotes), 2)
            self.assertTrue(all(quote.side == Side.SELL for quote in quotes))

            quote_engine = QuoteEngine(settings.market_rules, 0)
            intents = quote_engine.build_order_intents(quotes, [], {"BTC_USDT": market})
            self.assertEqual(len(intents), 2)
            self.assertTrue(all(intent.action == "place" for intent in intents))
            self.assertTrue(all(intent.price > market.bid for intent in intents if intent.price is not None))

        asyncio.run(scenario())

    def test_range_rebalance_stops_and_quote_engine_cancels_outside_hard_band(self):
        async def scenario():
            settings = AppSettings.from_file("config/paper.json")
            strategy = StrategyEngine(
                settings.market_rules,
                [
                    StrategySettings(
                        name="range_rebalance",
                        symbol="BTC_USDT",
                        enabled=True,
                        params={
                            "hard_floor": "67000",
                            "buy_below": "68000",
                            "sell_above": "69000",
                            "hard_ceiling": "70000",
                            "target_base": "0.011",
                            "buy_order_size": "0.00005",
                            "levels": 2,
                        },
                    )
                ],
            )
            await strategy.on_balances([Balance("BTC", Decimal("0.0109")), Balance("USDT", Decimal("1000"))])
            market = MarketSnapshot(
                symbol="BTC_USDT",
                bid=Decimal("66490"),
                bid_size=Decimal("1"),
                ask=Decimal("66510"),
                ask_size=Decimal("1"),
                last=Decimal("66500"),
            )
            await strategy.on_market(market)
            quotes = await strategy.generate_quotes()
            self.assertEqual(quotes, [])

            old_order = OrderRecord(
                symbol="BTC_USDT",
                side=Side.BUY,
                price=Decimal("67480"),
                size=Decimal("0.00005"),
                order_type=OrderType.LIMIT_MAKER.value,
                client_order_id="range-old-buy",
                strategy="range_rebalance",
                level=1,
                status=OrderStatus.OPEN,
            )
            quote_engine = QuoteEngine(settings.market_rules, 0)
            intents = quote_engine.build_order_intents(quotes, [old_order], {"BTC_USDT": market})
            self.assertEqual(len(intents), 1)
            self.assertEqual(intents[0].action, "cancel")
            self.assertEqual(intents[0].strategy, "range_rebalance")
            self.assertEqual(intents[0].reason, "quote slot no longer desired")

        asyncio.run(scenario())

    def test_range_rebalance_supports_two_opposite_instances_on_same_symbol(self):
        async def scenario():
            settings = AppSettings.from_file("config/paper.json")
            strategy = StrategyEngine(
                settings.market_rules,
                [
                    StrategySettings(
                        name="range_rebalance",
                        symbol="BTC_USDT",
                        enabled=True,
                        params={
                            "direction": "buy_only",
                            "hard_floor": "67000",
                            "buy_below": "68000",
                            "sell_above": "69000",
                            "hard_ceiling": "70000",
                            "target_base": "0.011",
                            "buy_order_size": "0.00005",
                            "levels": 1,
                        },
                        instance_id="range-buy-test",
                    ),
                    StrategySettings(
                        name="range_rebalance",
                        symbol="BTC_USDT",
                        enabled=True,
                        params={
                            "direction": "sell_only",
                            "hard_floor": "67000",
                            "buy_below": "68000",
                            "sell_above": "67000",
                            "hard_ceiling": "70000",
                            "target_base": "0.009",
                            "sell_order_size": "0.00005",
                            "levels": 1,
                        },
                        instance_id="range-sell-test",
                    ),
                ],
            )
            await strategy.on_balances([Balance("BTC", Decimal("0.0100")), Balance("USDT", Decimal("1000"))])
            market = MarketSnapshot(
                symbol="BTC_USDT",
                bid=Decimal("67490"),
                bid_size=Decimal("1"),
                ask=Decimal("67510"),
                ask_size=Decimal("1"),
                last=Decimal("67500"),
            )
            await strategy.on_market(market)
            quotes = await strategy.generate_quotes()
            self.assertEqual({quote.strategy for quote in quotes}, {"range-buy-test", "range-sell-test"})
            self.assertEqual({quote.side for quote in quotes}, {Side.BUY, Side.SELL})

            quote_engine = QuoteEngine(settings.market_rules, 0)
            intents = quote_engine.build_order_intents(quotes, [], {"BTC_USDT": market})
            self.assertEqual(len(intents), 2)
            self.assertEqual({intent.strategy for intent in intents}, {"range-buy-test", "range-sell-test"})

        asyncio.run(scenario())

    def test_microprice_strategy_moves_fair_value_toward_thicker_bid(self):
        async def scenario():
            settings = AppSettings.from_file("config/paper.json")
            strategy = StrategyEngine(
                settings.market_rules,
                [
                    StrategySettings(
                        name="microprice_mm",
                        symbol="BTC_USDT",
                        enabled=True,
                        params={"spread_bps": "2", "order_size": "0.00005", "levels": 1},
                    )
                ],
            )
            market = MarketSnapshot(
                symbol="BTC_USDT",
                bid=Decimal("100"),
                bid_size=Decimal("10"),
                ask=Decimal("101"),
                ask_size=Decimal("1"),
                last=Decimal("100.5"),
            )
            await strategy.on_market(market)
            quotes = await strategy.generate_quotes()
            self.assertEqual(len(quotes), 2)
            self.assertTrue(all(quote.strategy == "microprice_mm" for quote in quotes))
            self.assertGreater(quotes[0].price, market.mid)

        asyncio.run(scenario())

    def test_microprice_uses_configured_depth_levels(self):
        async def scenario():
            settings = AppSettings.from_file("config/paper.json")
            strategy = StrategyEngine(
                settings.market_rules,
                [
                    StrategySettings(
                        name="microprice_mm",
                        symbol="BTC_USDT",
                        enabled=True,
                        params={"depth_levels": 2, "spread_bps": "2", "order_size": "0.00005", "levels": 1},
                    )
                ],
            )
            market = MarketSnapshot(
                symbol="BTC_USDT",
                bid=Decimal("100"),
                bid_size=Decimal("1"),
                ask=Decimal("101"),
                ask_size=Decimal("1"),
                last=Decimal("100.5"),
                bids=[(Decimal("100"), Decimal("1")), (Decimal("99"), Decimal("9"))],
                asks=[(Decimal("101"), Decimal("1")), (Decimal("102"), Decimal("1"))],
            )
            await strategy.on_market(market)
            quotes = await strategy.generate_quotes()
            self.assertEqual(len(quotes), 2)
            self.assertGreater(quotes[0].price, market.mid)

        asyncio.run(scenario())

    def test_order_book_imbalance_strategy_skews_quotes_with_bid_pressure(self):
        async def scenario():
            settings = AppSettings.from_file("config/paper.json")
            strategy = StrategyEngine(
                settings.market_rules,
                [
                    StrategySettings(
                        name="order_book_imbalance",
                        symbol="BTC_USDT",
                        enabled=True,
                        params={
                            "base_spread_bps": "2",
                            "imbalance_threshold": "0.1",
                            "skew_bps": "30",
                            "spread_widen_bps": "0",
                            "order_size": "0.00005",
                            "levels": 1,
                        },
                    )
                ],
            )
            market = MarketSnapshot(
                symbol="BTC_USDT",
                bid=Decimal("100"),
                bid_size=Decimal("10"),
                ask=Decimal("101"),
                ask_size=Decimal("1"),
                last=Decimal("100.5"),
            )
            await strategy.on_market(market)
            quotes = await strategy.generate_quotes()
            self.assertEqual(len(quotes), 2)
            self.assertTrue(all(quote.strategy == "order_book_imbalance" for quote in quotes))
            self.assertGreater(quotes[0].price, market.mid)

        asyncio.run(scenario())

    def test_order_book_imbalance_uses_configured_depth_levels(self):
        async def scenario():
            settings = AppSettings.from_file("config/paper.json")
            strategy = StrategyEngine(
                settings.market_rules,
                [
                    StrategySettings(
                        name="order_book_imbalance",
                        symbol="BTC_USDT",
                        enabled=True,
                        params={
                            "depth_levels": 2,
                            "base_spread_bps": "2",
                            "imbalance_threshold": "0.1",
                            "skew_bps": "30",
                            "spread_widen_bps": "0",
                            "order_size": "0.00005",
                            "levels": 1,
                        },
                    )
                ],
            )
            market = MarketSnapshot(
                symbol="BTC_USDT",
                bid=Decimal("100"),
                bid_size=Decimal("1"),
                ask=Decimal("101"),
                ask_size=Decimal("1"),
                last=Decimal("100.5"),
                bids=[(Decimal("100"), Decimal("1")), (Decimal("99"), Decimal("9"))],
                asks=[(Decimal("101"), Decimal("1")), (Decimal("102"), Decimal("1"))],
            )
            await strategy.on_market(market)
            quotes = await strategy.generate_quotes()
            self.assertEqual(len(quotes), 2)
            self.assertGreater(quotes[0].price, market.mid)

        asyncio.run(scenario())

    def test_avellaneda_stoikov_shifts_reservation_price_against_inventory(self):
        async def scenario():
            settings = AppSettings.from_file("config/paper.json")
            strategy = StrategyEngine(
                settings.market_rules,
                [
                    StrategySettings(
                        name="avellaneda_stoikov",
                        symbol="BTC_USDT",
                        enabled=True,
                        params={
                            "risk_aversion": "1",
                            "target_base": "0.01",
                            "max_inventory_base": "0.01",
                            "base_spread_bps": "10",
                            "min_spread_bps": "10",
                            "max_spread_bps": "120",
                            "sigma_window_ms": 60000,
                            "time_horizon_ms": 60000,
                            "min_volatility_bps": "5",
                            "inventory_risk_multiplier": "1",
                            "volatility_spread_multiplier": "0.2",
                            "order_size": "0.00005",
                            "levels": 1,
                        },
                    )
                ],
            )
            await strategy.on_balances([Balance("BTC", Decimal("0.02")), Balance("USDT", Decimal("1000"))])
            first = MarketSnapshot(
                symbol="BTC_USDT",
                bid=Decimal("9995"),
                bid_size=Decimal("1"),
                ask=Decimal("10005"),
                ask_size=Decimal("1"),
                last=Decimal("10000"),
                receive_time_ms=1000,
            )
            second = MarketSnapshot(
                symbol="BTC_USDT",
                bid=Decimal("10095"),
                bid_size=Decimal("1"),
                ask=Decimal("10105"),
                ask_size=Decimal("1"),
                last=Decimal("10100"),
                receive_time_ms=2000,
            )
            await strategy.on_market(first)
            await strategy.on_market(second)
            quotes = await strategy.generate_quotes()
            self.assertEqual(len(quotes), 2)
            quote_mid = (quotes[0].price + quotes[1].price) / Decimal("2")
            self.assertLess(quote_mid, second.mid)

        asyncio.run(scenario())

    def test_risk_rejects_crossing_post_only_order(self):
        settings = AppSettings.from_file("config/paper.json")
        inventory = InventoryManager()
        inventory.update([Balance("BTC", Decimal("0.01")), Balance("USDT", Decimal("1000"))])
        risk = RiskEngine(settings.risk, settings.market_rules, settings.stale_market_data_ms)
        market = MarketSnapshot(
            symbol="BTC_USDT",
            bid=Decimal("67990"),
            bid_size=Decimal("1"),
            ask=Decimal("68010"),
            ask_size=Decimal("1"),
            last=Decimal("68000"),
        )
        intent = OrderIntent(
            action="place",
            symbol="BTC_USDT",
            side=Side.BUY,
            price=Decimal("68010"),
            size=Decimal("0.00005"),
            client_order_id="cross",
            old_client_order_id=None,
            strategy="test",
            level=1,
            order_type=OrderType.LIMIT_MAKER,
        )
        result = risk.validate(intent, {"BTC_USDT": market}, inventory, OrderManager())
        self.assertFalse(result.approved)
        self.assertEqual(result.rule, "post_only_cross")

    def test_risk_rejects_max_order_value(self):
        settings = AppSettings.from_file("config/paper.json")
        inventory = InventoryManager()
        inventory.update([Balance("BTC", Decimal("0.01")), Balance("USDT", Decimal("1000"))])
        risk = RiskEngine(settings.risk, settings.market_rules, settings.stale_market_data_ms)
        market = MarketSnapshot(
            symbol="BTC_USDT",
            bid=Decimal("67990"),
            bid_size=Decimal("1"),
            ask=Decimal("68010"),
            ask_size=Decimal("1"),
            last=Decimal("68000"),
        )
        intent = OrderIntent(
            action="place",
            symbol="BTC_USDT",
            side=Side.BUY,
            price=Decimal("67900"),
            size=Decimal("0.001"),
            client_order_id="too-large",
            old_client_order_id=None,
            strategy="test",
            level=1,
            order_type=OrderType.LIMIT_MAKER,
        )
        result = risk.validate(intent, {"BTC_USDT": market}, inventory, OrderManager())
        self.assertFalse(result.approved)
        self.assertEqual(result.rule, "max_order_value")


if __name__ == "__main__":
    unittest.main()
