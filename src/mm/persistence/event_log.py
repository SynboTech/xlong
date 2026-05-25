from __future__ import annotations

import json
import os
from typing import Any, Dict

from mm.common.time import utc_ms
from mm.common.types import to_jsonable


class JsonlEventLog:
    def __init__(self, path: str) -> None:
        self.path = path
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)

    def append(self, event_type: str, payload: Any) -> None:
        row: Dict[str, Any] = {
            "ts": utc_ms(),
            "type": event_type,
            "payload": to_jsonable(payload),
        }
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, separators=(",", ":"), sort_keys=True) + "\n")

