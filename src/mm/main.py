from __future__ import annotations

import argparse
import asyncio
import json
import signal
from dataclasses import asdict

from mm.app import MarketMakerApp
from mm.config.settings import AppSettings
from mm.common.types import to_jsonable


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="XLong market maker")
    parser.add_argument("--config", default="config/paper.json")
    parser.add_argument("--ticks", type=int, default=None, help="number of ticks to run; omit for daemon mode")
    return parser.parse_args()


async def async_main() -> None:
    args = parse_args()
    settings = AppSettings.from_file(args.config)
    app = MarketMakerApp(settings)
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, app.request_stop)
        except NotImplementedError:
            pass
    summary = await app.run(ticks=args.ticks)
    print(json.dumps(to_jsonable(asdict(summary)), indent=2, sort_keys=True))


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
