from __future__ import annotations

from decimal import Decimal
from typing import Iterable, Tuple

from mm.common.types import MarketSnapshot


def depth_vwap(levels: Iterable[Tuple[Decimal, Decimal]]) -> Tuple[Decimal, Decimal]:
    total_size = Decimal("0")
    total_notional = Decimal("0")
    for price, size in levels:
        if size <= 0:
            continue
        total_size += size
        total_notional += price * size
    if total_size <= 0:
        return Decimal("0"), Decimal("0")
    return total_notional / total_size, total_size


def microprice(snapshot: MarketSnapshot, depth_levels: int = 1) -> Decimal:
    bid_vwap, bid_size = depth_vwap(snapshot.bid_levels(depth_levels))
    ask_vwap, ask_size = depth_vwap(snapshot.ask_levels(depth_levels))
    total_size = bid_size + ask_size
    if total_size <= 0:
        return snapshot.mid
    if bid_vwap <= 0:
        bid_vwap = snapshot.bid
    if ask_vwap <= 0:
        ask_vwap = snapshot.ask
    return ((ask_vwap * bid_size) + (bid_vwap * ask_size)) / total_size


def order_book_imbalance(snapshot: MarketSnapshot, depth_levels: int = 1) -> Decimal:
    bid_size, ask_size = snapshot.depth_sizes(depth_levels)
    total_size = bid_size + ask_size
    if total_size <= 0:
        return Decimal("0")
    return max(Decimal("-1"), min(Decimal("1"), (bid_size - ask_size) / total_size))
