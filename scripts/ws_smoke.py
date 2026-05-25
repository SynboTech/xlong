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

from mm.common.types import to_jsonable
from mm.config.settings import BitMartCredentials
from mm.exchange.bitmart.smoke import private_ws_smoke, public_ws_smoke


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="BitMart WebSocket smoke check")
    parser.add_argument("--symbol", default="BTC_USDT")
    parser.add_argument("--private", action="store_true")
    parser.add_argument("--network", action="store_true")
    parser.add_argument("--timeout", type=float, default=5.0)
    return parser.parse_args()


async def async_main() -> int:
    args = parse_args()
    if args.private:
        report = await private_ws_smoke(BitMartCredentials.from_env(), dry_run=not args.network, timeout_sec=args.timeout)
    else:
        report = await public_ws_smoke(args.symbol, dry_run=not args.network, timeout_sec=args.timeout)
    print(json.dumps(to_jsonable(report), indent=2, sort_keys=True))
    return 0 if report.passed else 1


def main() -> None:
    raise SystemExit(asyncio.run(async_main()))


if __name__ == "__main__":
    main()

