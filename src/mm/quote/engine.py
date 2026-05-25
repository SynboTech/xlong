from __future__ import annotations

from decimal import Decimal
from typing import Dict, Iterable, List, Optional, Tuple

from mm.common.ids import new_client_order_id
from mm.common.time import utc_ms
from mm.common.types import MarketRule, MarketSnapshot, OrderIntent, OrderType, QuoteIntent, Side
from mm.oms.order import OrderRecord


Slot = Tuple[str, str, Side, int]


class QuoteEngine:
    def __init__(self, market_rules: Dict[str, MarketRule], min_requote_interval_ms: int) -> None:
        self.market_rules = market_rules
        self.min_requote_interval_ms = min_requote_interval_ms
        self._last_requote_ms: Dict[Slot, int] = {}

    def build_order_intents(
        self,
        quotes: Iterable[QuoteIntent],
        open_orders: Iterable[OrderRecord],
        markets: Dict[str, MarketSnapshot],
    ) -> List[OrderIntent]:
        open_by_slot = self._index_open_orders(open_orders)
        desired_by_slot: Dict[Slot, QuoteIntent] = {}
        for quote in quotes:
            desired_by_slot[(quote.strategy, quote.symbol, quote.side, quote.level)] = quote

        intents: List[OrderIntent] = []
        now = utc_ms()

        for slot, order in open_by_slot.items():
            if slot not in desired_by_slot:
                intents.append(
                    OrderIntent(
                        action="cancel",
                        symbol=order.symbol,
                        side=order.side,
                        price=order.price,
                        size=order.remaining_size,
                        client_order_id=order.client_order_id,
                        old_client_order_id=order.client_order_id,
                        strategy=order.strategy,
                        level=order.level,
                        reason="quote slot no longer desired",
                    )
                )

        for slot, quote in desired_by_slot.items():
            rule = self.market_rules[quote.symbol]
            market = markets.get(quote.symbol)
            if market is None:
                continue
            price = self._post_only_price(rule, market, quote.side, quote.price)
            size = rule.align_size(quote.size)
            if not rule.valid_minimums(price, size):
                continue
            existing = open_by_slot.get(slot)
            if existing is not None and self._same_quote(existing, price, size):
                continue
            if existing is not None:
                last = self._last_requote_ms.get(slot, 0)
                if now - last < self.min_requote_interval_ms:
                    continue
                intents.append(
                    OrderIntent(
                        action="cancel",
                        symbol=existing.symbol,
                        side=existing.side,
                        price=existing.price,
                        size=existing.remaining_size,
                        client_order_id=existing.client_order_id,
                        old_client_order_id=existing.client_order_id,
                        strategy=existing.strategy,
                        level=existing.level,
                        reason="replace quote",
                    )
                )
            client_order_id = new_client_order_id(quote.strategy, quote.symbol, quote.side.value, quote.level)
            intents.append(
                OrderIntent(
                    action="place",
                    symbol=quote.symbol,
                    side=quote.side,
                    price=price,
                    size=size,
                    client_order_id=client_order_id,
                    old_client_order_id=existing.client_order_id if existing is not None else None,
                    strategy=quote.strategy,
                    level=quote.level,
                    order_type=OrderType.LIMIT_MAKER,
                    reason=quote.reason,
                )
            )
            self._last_requote_ms[slot] = now
        return intents

    def _post_only_price(
        self,
        rule: MarketRule,
        market: MarketSnapshot,
        side: Side,
        desired_price: Decimal,
    ) -> Decimal:
        price = rule.align_price(side, desired_price)
        if side == Side.BUY and price >= market.ask:
            price = rule.align_price(side, market.ask - rule.price_increment)
        if side == Side.SELL and price <= market.bid:
            price = rule.align_price(side, market.bid + rule.price_increment)
        return price

    @staticmethod
    def _same_quote(order: OrderRecord, price: Decimal, size: Decimal) -> bool:
        return order.price == price and order.remaining_size == size

    @staticmethod
    def _index_open_orders(open_orders: Iterable[OrderRecord]) -> Dict[Slot, OrderRecord]:
        result: Dict[Slot, OrderRecord] = {}
        for order in open_orders:
            if order.level is None:
                continue
            result[(order.strategy, order.symbol, order.side, order.level)] = order
        return result

