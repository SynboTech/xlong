#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from mm.backtest.runner import EventLogBacktestRunner
from mm.common.types import to_jsonable
from mm.config.settings import AppSettings


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Replay event log through strategy and quote engine")
    parser.add_argument("--config", default="config/paper.json")
    parser.add_argument("--events", default="runtime/events.jsonl")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    settings = AppSettings.from_file(args.config)
    summary = EventLogBacktestRunner(settings, args.events).run_sync()
    print(json.dumps(to_jsonable(asdict(summary)), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

