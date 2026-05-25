from __future__ import annotations

from decimal import Decimal
from typing import Dict, Iterable, Optional

from mm.common.decimal import BPS
from mm.common.types import MarketRule, MarketSnapshot, OrderIntent, OrderStatus, RiskDecision, RiskResult, Side
from mm.config.settings import RiskSettings
from mm.inventory.manager import InventoryManager
from mm.oms.manager import OrderManager


class RiskEngine:
    def __init__(
        self,
        settings: RiskSettings,
        market_rules: Dict[str, MarketRule],
        stale_market_data_ms: int,
    ) -> None:
        self.settings = settings
        self.market_rules = market_rules
        self.stale_market_data_ms = stale_market_data_ms
        self.safe_mode = False
        self.daily_pnl = Decimal("0")

    def enter_safe_mode(self, reason: str) -> RiskResult:
        self.safe_mode = True
        return RiskResult(RiskDecision.SAFE_MODE, "safe_mode", reason)

    def exit_safe_mode(self) -> None:
        self.safe_mode = False

    def validate(
        self,
        intent: OrderIntent,
        markets: Dict[str, MarketSnapshot],
        inventory: InventoryManager,
        oms: OrderManager,
    ) -> RiskResult:
        if intent.action == "cancel":
            return RiskResult(RiskDecision.APPROVED, "cancel_allowed", "cancel requests are allowed", intent)

        if intent.action != "place":
            return self._reject("unknown_action", "unknown order intent action", intent)

        if self.safe_mode:
            return self._reject("safe_mode", "system is in SAFE_MODE", intent)

        if intent.symbol not in self.market_rules:
            return self._reject("symbol_not_allowed", "symbol is not in market rules", intent)

        market = markets.get(intent.symbol)
        if market is None:
            return self._reject("missing_market", "missing market snapshot", intent)

        if market.age_ms > self.stale_market_data_ms:
            return self._reject("stale_market", "market data is stale", intent)

        if intent.price is None or intent.size is None or intent.side is None:
            return self._reject("invalid_intent", "place intent requires side/price/size", intent)

        if any(order.status == OrderStatus.UNKNOWN for order in oms.all_orders()):
            return self._reject("unknown_order", "OMS has UNKNOWN orders; reconciliation required", intent)

        if self.daily_pnl <= -self.settings.max_daily_loss_usdt:
            return self._reject("daily_loss", "daily loss limit reached", intent)

        rule = self.market_rules[intent.symbol]
        notional = intent.price * intent.size
        if not rule.valid_minimums(intent.price, intent.size):
            return self._reject("market_minimums", "order violates market minimums", intent)

        if notional > self.settings.max_order_value_usdt:
            return self._reject("max_order_value", "order value exceeds max_order_value_usdt", intent)

        strategy_max_order_value = self.settings.per_strategy_max_order_value_usdt.get(intent.strategy)
        if strategy_max_order_value is not None and notional > strategy_max_order_value:
            return self._reject("strategy_max_order_value", "order value exceeds strategy limit", intent)

        if len(oms.open_orders(intent.symbol)) >= self.settings.max_open_orders:
            return self._reject("max_open_orders", "open order count exceeds max_open_orders", intent)

        if oms.total_open_notional(intent.symbol) + notional > self.settings.max_total_open_value_usdt:
            return self._reject("max_total_open_value", "total open notional exceeds limit", intent)

        strategy_open_orders = [
            order for order in oms.open_orders(intent.symbol) if order.strategy == intent.strategy
        ]
        strategy_max_open_orders = self.settings.per_strategy_max_open_orders.get(intent.strategy)
        if strategy_max_open_orders is not None and len(strategy_open_orders) >= strategy_max_open_orders:
            return self._reject("strategy_max_open_orders", "strategy open order count exceeds limit", intent)

        strategy_max_open_value = self.settings.per_strategy_max_open_value_usdt.get(intent.strategy)
        if strategy_max_open_value is not None:
            strategy_open_value = sum((order.open_notional for order in strategy_open_orders), Decimal("0"))
            if strategy_open_value + notional > strategy_max_open_value:
                return self._reject("strategy_max_open_value", "strategy open notional exceeds limit", intent)

        deviation_bps = abs(intent.price - market.mid) / market.mid * BPS
        if deviation_bps > self.settings.max_price_deviation_bps:
            return self._reject("price_deviation", "price deviates too far from fair price", intent)

        if intent.side == Side.BUY and intent.price >= market.ask:
            return self._reject("post_only_cross", "buy price would cross ask", intent)

        if intent.side == Side.SELL and intent.price <= market.bid:
            return self._reject("post_only_cross", "sell price would cross bid", intent)

        current_base = inventory.base_total(rule)
        if intent.side == Side.BUY and current_base + intent.size > self.settings.max_position_base:
            return self._reject("max_position", "buy would exceed max base position", intent)

        if intent.side == Side.SELL and inventory.balance(rule.base).available < intent.size:
            return self._reject("insufficient_inventory", "sell size exceeds available base balance", intent)

        return RiskResult(RiskDecision.APPROVED, "approved", "approved", intent)

    @staticmethod
    def _reject(rule: str, message: str, intent: Optional[OrderIntent]) -> RiskResult:
        return RiskResult(RiskDecision.REJECTED, rule, message, intent)
