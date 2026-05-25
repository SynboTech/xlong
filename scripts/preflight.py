#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from mm.config.settings import AppSettings
from mm.exchange.bitmart.preflight import BitMartPreflight
from mm.exchange.bitmart.rest import BitMartRestGateway
from mm.common.types import to_jsonable


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="BitMart preflight checks")
    parser.add_argument("--config", default="config/live_read_only.example.json")
    parser.add_argument("--network", action="store_true")
    return parser.parse_args()


async def async_main() -> int:
    args = parse_args()
    settings = AppSettings.from_file(args.config)
    gateway = BitMartRestGateway(settings.bitmart)
    report = await BitMartPreflight(settings, gateway).run(network=args.network)
    print(json.dumps(to_jsonable(report.as_dict()), indent=2, sort_keys=True))
    return 0 if report.passed else 1


def main() -> None:
    raise SystemExit(asyncio.run(async_main()))


if __name__ == "__main__":
    main()

