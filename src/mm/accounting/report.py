from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict

from mm.common.decimal import D
from mm.persistence.replay import EventLogReplay


@dataclass(frozen=True)
class DailyPnlReport:
    event_log_path: str
    fills: int
    total_fees: Decimal
    symbols: Dict[str, Dict[str, str]] = field(default_factory=dict)


class DailyPnlReporter:
    def __init__(self, event_log_path: str) -> None:
        self.event_log_path = event_log_path

    def build(self) -> DailyPnlReport:
        fills = 0
        total_fees = Decimal("0")
        latest_symbols: Dict[str, Dict[str, str]] = {}
        replay = EventLogReplay(self.event_log_path)
        for event in replay.events():
            if event.event_type == "order.fill":
                fills += 1
                total_fees += D(event.payload.get("fee", "0"))
            elif event.event_type == "account.pnl":
                latest_symbols = {
                    str(symbol): {str(key): str(value) for key, value in row.items()}
                    for symbol, row in event.payload.items()
                    if isinstance(row, dict)
                }
        return DailyPnlReport(
            event_log_path=self.event_log_path,
            fills=fills,
            total_fees=total_fees,
            symbols=latest_symbols,
        )

