from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Dict, List


@dataclass(frozen=True)
class ConfigAuditReport:
    path: str
    sha256: str
    trading_mode: str
    exchange: str
    symbols: List[str]
    enabled_strategies: List[str]
    risk_limits: Dict[str, str]


def build_config_audit(path: str) -> ConfigAuditReport:
    with open(path, "rb") as fh:
        raw = fh.read()
    data = json.loads(raw.decode("utf-8"))
    risk = data.get("risk", {})
    return ConfigAuditReport(
        path=path,
        sha256=hashlib.sha256(raw).hexdigest(),
        trading_mode=str(data.get("trading_mode", "")),
        exchange=str(data.get("exchange", "")),
        symbols=[str(symbol) for symbol in data.get("symbols", [])],
        enabled_strategies=[
            str(item.get("id") or "{0}:{1}".format(item.get("name", ""), item.get("symbol", "")))
            for item in data.get("strategies", [])
            if item.get("enabled", True)
        ],
        risk_limits={str(key): str(value) for key, value in risk.items()},
    )
