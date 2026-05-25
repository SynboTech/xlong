from __future__ import annotations

import time


def utc_ms() -> int:
    return int(time.time() * 1000)


def mono_ms() -> int:
    return int(time.monotonic() * 1000)

