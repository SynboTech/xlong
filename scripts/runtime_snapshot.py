#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import asdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from mm.app import MarketMakerApp
from mm.common.types import to_jsonable
from mm.config.settings import AppSettings


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate runtime snapshot after a short paper run")
    parser.add_argument("--config", default="config/paper.json")
    parser.add_argument("--ticks", type=int, default=3)
    return parser.parse_args()


async def async_main() -> int:
    args = parse_args()
    settings = AppSettings.from_file(args.config)
    app = MarketMakerApp(settings)
    await app.run(ticks=args.ticks)
    print(json.dumps(to_jsonable(asdict(app.runtime_snapshot())), indent=2, sort_keys=True))
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(async_main()))


if __name__ == "__main__":
    main()

