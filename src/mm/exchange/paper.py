from __future__ import annotations

import itertools
from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, List, Optional

from mm.common.decimal import BPS, D
from mm.common.time import utc_ms
from mm.common.types import (
    Balance,
    CancelAck,
    CancelRequest,
    FillEvent,
    Liquidity,
    MarketRule,
    MarketSnapshot,
    OrderAck,
    OrderRequest,
    OrderStatus,
    OrderUpdate,
    Side,
)
from mm.exchange.base import ExchangeGateway


@dataclass
class PaperOpenOrder:
    request: OrderRequest
    exchange_order_id: str
    remaining: Decimal


class PaperExchange(ExchangeGateway):
    name = "paper"

    def __init__(
        self,
        market_rules: Dict[str, MarketRule],
        initial_prices: Dict[str, object],
        balances: Dict[str, object],
        maker_fee_bps: object = "0",
        taker_fee_bps: object = "10",
    ) -> None:
        self.market_rules = market_rules
        self.prices = {symbol: D(price) for symbol, price in initial_prices.items()}
        self.balances: Dict[str, Balance] = {
            currency: Balance(currency=currency, available=D(amount), frozen=Decimal("0"))
            for currency, amount in balances.items()
        }
        self.maker_fee_bps = D(maker_fee_bps)
        self.taker_fee_bps = D(taker_fee_bps)
        self.open_orders: Dict[str, PaperOpenOrder] = {}
        self._order_id = itertools.count(1)
        self._trade_id = itertools.count(1)
        self._tick = itertools.count(1)

    async def load_markets(self) -> Dict[str, MarketRule]:
        return self.market_rules

    async def get_balances(self) -> List[Balance]:
        return [
            Balance(currency=item.currency, available=item.available, frozen=item.frozen)
            for item in self.balances.values()
        ]

    async def get_open_orders(self, symbol: Optional[str] = None) -> List[OrderUpdate]:
        updates = []
        for order in self.open_orders.values():
            if symbol is not None and order.request.symbol != symbol:
                continue
            filled = order.request.size - order.remaining
            updates.append(
                OrderUpdate(
                    symbol=order.request.symbol,
                    client_order_id=order.request.client_order_id,
                    exchange_order_id=order.exchange_order_id,
                    status=OrderStatus.OPEN if filled <= 0 else OrderStatus.PARTIALLY_FILLED,
                    filled_size=filled,
                    avg_fill_price=order.request.price,
                    message="paper open order",
                )
            )
        return updates

    async def query_order(self, client_order_id: str, exchange_order_id: Optional[str] = None) -> OrderUpdate:
        order = self.open_orders.get(client_order_id)
        if order is None:
            return OrderUpdate(
                symbol="",
                client_order_id=client_order_id,
                exchange_order_id=exchange_order_id,
                status=OrderStatus.UNKNOWN,
                message="paper order not found",
            )
        filled = order.request.size - order.remaining
        return OrderUpdate(
            symbol=order.request.symbol,
            client_order_id=order.request.client_order_id,
            exchange_order_id=order.exchange_order_id,
            status=OrderStatus.OPEN if filled <= 0 else OrderStatus.PARTIALLY_FILLED,
            filled_size=filled,
            avg_fill_price=order.request.price,
            message="paper query order",
        )

    async def submit_order(self, request: OrderRequest) -> OrderAck:
        rule = self.market_rules[request.symbol]
        price = request.price
        if price is None:
            return OrderAck(False, request.client_order_id, None, OrderStatus.REJECTED, "paper requires limit price")
        if not rule.valid_minimums(price, request.size):
            return OrderAck(False, request.client_order_id, None, OrderStatus.REJECTED, "below market minimums")
        reserve_error = self._reserve(rule, request)
        if reserve_error:
            return OrderAck(False, request.client_order_id, None, OrderStatus.REJECTED, reserve_error)
        exchange_order_id = "paper-{0}".format(next(self._order_id))
        self.open_orders[request.client_order_id] = PaperOpenOrder(
            request=request,
            exchange_order_id=exchange_order_id,
            remaining=request.size,
        )
        return OrderAck(
            accepted=True,
            client_order_id=request.client_order_id,
            exchange_order_id=exchange_order_id,
            status=OrderStatus.OPEN,
            message="accepted by paper exchange",
        )

    async def cancel_order(self, request: CancelRequest) -> CancelAck:
        order = self.open_orders.pop(request.client_order_id, None)
        if order is None:
            return CancelAck(
                accepted=False,
                client_order_id=request.client_order_id,
                exchange_order_id=request.exchange_order_id,
                status=OrderStatus.UNKNOWN,
                message="paper order not found",
            )
        self._release_remaining(order)
        filled = order.request.size - order.remaining
        status = OrderStatus.PARTIALLY_CANCELED if filled > 0 else OrderStatus.CANCELED
        return CancelAck(
            accepted=True,
            client_order_id=request.client_order_id,
            exchange_order_id=order.exchange_order_id,
            status=status,
            message="canceled by paper exchange",
        )

    async def cancel_all(self, symbol: Optional[str] = None) -> List[CancelAck]:
        acks = []
        for client_order_id, order in list(self.open_orders.items()):
            if symbol is not None and order.request.symbol != symbol:
                continue
            acks.append(
                await self.cancel_order(
                    CancelRequest(
                        symbol=order.request.symbol,
                        client_order_id=client_order_id,
                        exchange_order_id=order.exchange_order_id,
                        reason="cancel_all",
                    )
                )
            )
        return acks

    async def next_market_snapshot(self, symbol: str) -> MarketSnapshot:
        tick = Decimal(next(self._tick))
        mid = self.prices[symbol]
        wave = ((tick % Decimal("12")) - Decimal("6")) / Decimal("6")
        move_bps = wave * Decimal("8")
        mid = mid * (Decimal("1") + move_bps / BPS)
        self.prices[symbol] = mid
        spread = mid * Decimal("6") / BPS
        bid = mid - spread / Decimal("2")
        ask = mid + spread / Decimal("2")
        level_gap = spread / Decimal("2")
        bids = [(bid - (level_gap * Decimal(idx)), Decimal("10") + Decimal(idx * 2)) for idx in range(5)]
        asks = [(ask + (level_gap * Decimal(idx)), Decimal("10") + Decimal(idx * 2)) for idx in range(5)]
        return MarketSnapshot(
            exchange="paper",
            symbol=symbol,
            bid=bid,
            bid_size=Decimal("10"),
            ask=ask,
            ask_size=Decimal("10"),
            last=mid,
            timestamp_ms=utc_ms(),
            receive_time_ms=utc_ms(),
            bids=bids,
            asks=asks,
        )

    async def simulate_fills(self, snapshot: MarketSnapshot) -> List[FillEvent]:
        fills = []
        for client_order_id, order in list(self.open_orders.items()):
            if order.request.symbol != snapshot.symbol:
                continue
            price = order.request.price
            if price is None:
                continue
            should_fill = (
                order.request.side == Side.BUY and snapshot.ask <= price
            ) or (
                order.request.side == Side.SELL and snapshot.bid >= price
            )
            if not should_fill:
                continue
            fill_size = min(order.remaining, order.request.size / Decimal("2"))
            if fill_size <= 0:
                continue
            order.remaining -= fill_size
            fill = self._settle_fill(order, fill_size, price)
            fills.append(fill)
            if order.remaining <= 0:
                self.open_orders.pop(client_order_id, None)
        return fills

    def _reserve(self, rule: MarketRule, request: OrderRequest) -> Optional[str]:
        price = request.price
        if price is None:
            return "missing price"
        if request.side == Side.BUY:
            quote_balance = self._balance(rule.quote)
            needed = price * request.size
            if quote_balance.available < needed:
                return "insufficient {0}".format(rule.quote)
            quote_balance.available -= needed
            quote_balance.frozen += needed
            return None
        base_balance = self._balance(rule.base)
        if base_balance.available < request.size:
            return "insufficient {0}".format(rule.base)
        base_balance.available -= request.size
        base_balance.frozen += request.size
        return None

    def _release_remaining(self, order: PaperOpenOrder) -> None:
        rule = self.market_rules[order.request.symbol]
        price = order.request.price or Decimal("0")
        if order.request.side == Side.BUY:
            quote_balance = self._balance(rule.quote)
            amount = price * order.remaining
            quote_balance.frozen -= amount
            quote_balance.available += amount
        else:
            base_balance = self._balance(rule.base)
            base_balance.frozen -= order.remaining
            base_balance.available += order.remaining

    def _settle_fill(self, order: PaperOpenOrder, fill_size: Decimal, fill_price: Decimal) -> FillEvent:
        rule = self.market_rules[order.request.symbol]
        fee = fill_price * fill_size * self.maker_fee_bps / BPS
        if order.request.side == Side.BUY:
            quote_balance = self._balance(rule.quote)
            base_balance = self._balance(rule.base)
            cost = fill_price * fill_size
            quote_balance.frozen -= cost
            base_balance.available += fill_size
            fee_currency = rule.quote
            if fee > 0:
                quote_balance.available -= fee
        else:
            base_balance = self._balance(rule.base)
            quote_balance = self._balance(rule.quote)
            base_balance.frozen -= fill_size
            proceeds = fill_price * fill_size
            quote_balance.available += proceeds - fee
            fee_currency = rule.quote
        return FillEvent(
            symbol=order.request.symbol,
            client_order_id=order.request.client_order_id,
            exchange_order_id=order.exchange_order_id,
            side=order.request.side,
            price=fill_price,
            size=fill_size,
            fee=fee,
            fee_currency=fee_currency,
            liquidity=Liquidity.MAKER,
            trade_id="paper-trade-{0}".format(next(self._trade_id)),
        )

    def _balance(self, currency: str) -> Balance:
        if currency not in self.balances:
            self.balances[currency] = Balance(currency=currency, available=Decimal("0"), frozen=Decimal("0"))
        return self.balances[currency]
