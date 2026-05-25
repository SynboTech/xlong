from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Dict

from mm.common.types import FillEvent, MarketSnapshot, Side


@dataclass
class SymbolPnl:
    symbol: str
    position: Decimal = Decimal("0")
    avg_cost: Decimal = Decimal("0")
    realized_pnl: Decimal = Decimal("0")
    fees: Decimal = Decimal("0")

    def apply_fill(self, fill: FillEvent) -> None:
        if fill.side == Side.BUY:
            self._apply_buy(fill.price, fill.size)
        else:
            self._apply_sell(fill.price, fill.size)
        self.fees += fill.fee

    def unrealized(self, mark_price: Decimal) -> Decimal:
        return (mark_price - self.avg_cost) * self.position

    def total(self, mark_price: Decimal) -> Decimal:
        return self.realized_pnl + self.unrealized(mark_price) - self.fees

    def _apply_buy(self, price: Decimal, size: Decimal) -> None:
        if size <= 0:
            return
        new_position = self.position + size
        if new_position <= 0:
            self.position = new_position
            return
        self.avg_cost = ((self.avg_cost * self.position) + (price * size)) / new_position
        self.position = new_position

    def _apply_sell(self, price: Decimal, size: Decimal) -> None:
        if size <= 0:
            return
        close_size = min(size, self.position)
        self.realized_pnl += (price - self.avg_cost) * close_size
        self.position -= close_size
        if self.position <= 0:
            self.position = Decimal("0")
            self.avg_cost = Decimal("0")


class PnlTracker:
    def __init__(self) -> None:
        self.symbols: Dict[str, SymbolPnl] = {}

    def apply_fill(self, fill: FillEvent) -> None:
        self.for_symbol(fill.symbol).apply_fill(fill)

    def for_symbol(self, symbol: str) -> SymbolPnl:
        if symbol not in self.symbols:
            self.symbols[symbol] = SymbolPnl(symbol=symbol)
        return self.symbols[symbol]

    def total_pnl(self, markets: Dict[str, MarketSnapshot]) -> Decimal:
        total = Decimal("0")
        for symbol, state in self.symbols.items():
            market = markets.get(symbol)
            if market is not None:
                total += state.total(market.mid)
            else:
                total += state.realized_pnl - state.fees
        return total

    def snapshot(self, markets: Dict[str, MarketSnapshot]) -> Dict[str, Dict[str, str]]:
        rows: Dict[str, Dict[str, str]] = {}
        for symbol, state in self.symbols.items():
            mark = markets[symbol].mid if symbol in markets else state.avg_cost
            rows[symbol] = {
                "position": str(state.position),
                "avg_cost": str(state.avg_cost),
                "realized_pnl": str(state.realized_pnl),
                "unrealized_pnl": str(state.unrealized(mark)),
                "fees": str(state.fees),
                "total_pnl": str(state.total(mark)),
            }
        return rows

