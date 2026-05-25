from __future__ import annotations

from typing import Dict, Iterable, List, Set

from mm.common.time import utc_ms
from mm.common.types import Balance, MarketRule, MarketSnapshot, QuoteIntent
from mm.config.settings import StrategySettings
from mm.strategy.base import StrategyContext, StrategyPlugin
from mm.strategy.plugins.avellaneda_stoikov import AvellanedaStoikovMarketMaker
from mm.strategy.plugins.basic_mm import BasicMarketMaker
from mm.strategy.plugins.hedged_mm import HedgedMarketMaker
from mm.strategy.plugins.inventory_skew import InventorySkewStrategy
from mm.strategy.plugins.ladder_mm import LadderMarketMaker
from mm.strategy.plugins.microprice_mm import MicropriceMarketMaker
from mm.strategy.plugins.order_book_imbalance import OrderBookImbalanceMarketMaker
from mm.strategy.plugins.range_rebalance import RangeRebalanceStrategy
from mm.strategy.plugins.volatility_spread import VolatilitySpreadMarketMaker


PLUGIN_REGISTRY = {
    BasicMarketMaker.name: BasicMarketMaker,
    InventorySkewStrategy.name: InventorySkewStrategy,
    LadderMarketMaker.name: LadderMarketMaker,
    VolatilitySpreadMarketMaker.name: VolatilitySpreadMarketMaker,
    HedgedMarketMaker.name: HedgedMarketMaker,
    RangeRebalanceStrategy.name: RangeRebalanceStrategy,
    MicropriceMarketMaker.name: MicropriceMarketMaker,
    OrderBookImbalanceMarketMaker.name: OrderBookImbalanceMarketMaker,
    AvellanedaStoikovMarketMaker.name: AvellanedaStoikovMarketMaker,
}


class StrategyEngine:
    def __init__(self, market_rules: Dict[str, MarketRule], configs: Iterable[StrategySettings]) -> None:
        self.ctx = StrategyContext(market_rules=market_rules)
        self.plugins: List[StrategyPlugin] = []
        self.paused_strategy_keys: Set[str] = set()
        for config in configs:
            if not config.enabled:
                continue
            cls = PLUGIN_REGISTRY.get(config.name)
            if cls is None:
                raise ValueError("unknown strategy plugin {0}".format(config.name))
            plugin = cls(config.symbol, config.params)
            plugin.instance_id = config.instance_id
            self.plugins.append(plugin)

    def set_paused_strategies(self, keys: Iterable[str]) -> None:
        self.paused_strategy_keys = {str(key) for key in keys}

    async def on_market(self, event: MarketSnapshot) -> None:
        self.ctx.markets[event.symbol] = event
        for plugin in self.plugins:
            if plugin.symbol == event.symbol and self._plugin_enabled(plugin):
                await plugin.on_market(self.ctx, event)

    async def on_balances(self, balances: Iterable[Balance]) -> None:
        self.ctx.balances = {balance.currency: balance for balance in balances}
        for plugin in self.plugins:
            if self._plugin_enabled(plugin):
                await plugin.on_balance(self.ctx, self.ctx.balances)

    async def generate_quotes(self) -> List[QuoteIntent]:
        self.ctx.price_adjustment_bps = {}
        for plugin in self.plugins:
            if self._plugin_enabled(plugin):
                await plugin.prepare(self.ctx)
        now = utc_ms()
        quotes: List[QuoteIntent] = []
        for plugin in self.plugins:
            if self._plugin_enabled(plugin):
                quotes.extend(await plugin.on_timer(self.ctx, now))
        return quotes

    def _plugin_enabled(self, plugin: StrategyPlugin) -> bool:
        return not (self._runtime_key(plugin) in self.paused_strategy_keys or plugin.strategy_key in self.paused_strategy_keys)

    @staticmethod
    def _runtime_key(plugin: StrategyPlugin) -> str:
        return plugin.instance_id or "{0}:{1}".format(plugin.name, plugin.symbol)
