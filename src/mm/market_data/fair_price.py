from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, Iterable, List, Optional

from mm.common.types import MarketSnapshot


@dataclass(frozen=True)
class FairPriceSource:
    exchange: str
    weight: Decimal
    snapshot: MarketSnapshot


@dataclass(frozen=True)
class FairPrice:
    symbol: str
    price: Decimal
    sources: List[str]
    max_age_ms: int


class FairPriceEngine:
    def __init__(self, stale_ms: int) -> None:
        self.stale_ms = stale_ms

    def compute(self, symbol: str, sources: Iterable[FairPriceSource]) -> Optional[FairPrice]:
        active: List[FairPriceSource] = [
            source
            for source in sources
            if source.snapshot.symbol == symbol and source.weight > 0 and source.snapshot.age_ms <= self.stale_ms
        ]
        if not active:
            return None
        total_weight = sum((source.weight for source in active), Decimal("0"))
        if total_weight <= 0:
            return None
        weighted = sum((source.snapshot.mid * source.weight for source in active), Decimal("0")) / total_weight
        max_age = max(source.snapshot.age_ms for source in active)
        return FairPrice(
            symbol=symbol,
            price=weighted,
            sources=[source.exchange for source in active],
            max_age_ms=max_age,
        )

