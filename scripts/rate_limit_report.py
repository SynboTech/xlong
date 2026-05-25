#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from mm.common.types import to_jsonable
from mm.config.settings import BitMartCredentials
from mm.exchange.bitmart.rest import BitMartRestGateway


def main() -> int:
    gateway = BitMartRestGateway(BitMartCredentials.from_env())
    print(json.dumps(to_jsonable(gateway.rate_limit_report()), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

