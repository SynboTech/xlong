from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Dict, Iterator, Optional


@dataclass(frozen=True)
class ReplayEvent:
    ts: int
    event_type: str
    payload: Dict[str, object]


class EventLogReplay:
    def __init__(self, path: str) -> None:
        self.path = path

    def events(self, event_type: Optional[str] = None) -> Iterator[ReplayEvent]:
        with open(self.path, "r", encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                row = json.loads(line)
                if event_type is not None and row.get("type") != event_type:
                    continue
                payload = row.get("payload", {})
                if not isinstance(payload, dict):
                    payload = {"value": payload}
                yield ReplayEvent(
                    ts=int(row["ts"]),
                    event_type=str(row["type"]),
                    payload=payload,
                )

    def count_by_type(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for event in self.events():
            counts[event.event_type] = counts.get(event.event_type, 0) + 1
        return counts

