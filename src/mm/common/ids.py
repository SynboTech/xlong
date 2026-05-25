from __future__ import annotations

import itertools
import socket
from typing import Optional

from .time import utc_ms


_counter = itertools.count(1)
_host = socket.gethostname().split(".")[0][:8]


def new_client_order_id(strategy: str, symbol: str, side: str, level: Optional[int] = None) -> str:
    cleaned_strategy = "".join(ch for ch in strategy if ch.isalnum())[:5] or "mm"
    cleaned_symbol = "".join(ch for ch in symbol if ch.isalnum())[:8] or "SYM"
    lvl = "0" if level is None else str(level)[:2]
    side_code = side[0].upper()
    counter = str(next(_counter) % 100000).zfill(5)
    ts = str(utc_ms() % 10000000000).zfill(10)
    # BitMart spot client_order_id is limited to 32 alphanumeric characters.
    return "XL{0}{1}{2}{3}{4}{5}".format(
        ts,
        counter,
        side_code,
        lvl,
        cleaned_strategy,
        cleaned_symbol,
    )[:32]


def new_trace_id(prefix: str = "tr") -> str:
    return "{0}-{1}-{2}-{3}".format(prefix, _host, utc_ms(), next(_counter))
