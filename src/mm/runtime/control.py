from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Dict, Set


@dataclass(frozen=True)
class RuntimeControlSnapshot:
    paused_strategy_keys: Set[str] = field(default_factory=set)
    running_strategy_keys: Set[str] = field(default_factory=set)
    safe_mode: bool = False
    safe_mode_reason: str = ""


class RuntimeControlReader:
    def __init__(self, strategy_state_path: str, risk_state_path: str) -> None:
        self.strategy_state_path = strategy_state_path
        self.risk_state_path = risk_state_path

    def load(self) -> RuntimeControlSnapshot:
        states = self._read_json(self.strategy_state_path, {"states": {}}).get("states", {})
        paused = set()
        running = set()
        for key, value in states.items():
            status = str(value.get("status", "")).lower() if isinstance(value, dict) else ""
            if status == "paused":
                paused.add(str(key))
            elif status == "running":
                running.add(str(key))

        risk = self._read_json(self.risk_state_path, {})
        return RuntimeControlSnapshot(
            paused_strategy_keys=paused,
            running_strategy_keys=running,
            safe_mode=bool(risk.get("safe_mode", False)),
            safe_mode_reason=str(risk.get("reason", "")),
        )

    @staticmethod
    def _read_json(path: str, default: Dict[str, object]) -> Dict[str, object]:
        if not path or not os.path.exists(path):
            return default
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError):
            return default
        return data if isinstance(data, dict) else default
