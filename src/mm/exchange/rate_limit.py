from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Deque


@dataclass(frozen=True)
class RateLimitSnapshot:
    max_calls: int
    window_seconds: float
    used: int
    remaining: int
    reset_after_seconds: float


class SlidingWindowRateLimiter:
    def __init__(self, max_calls: int, window_seconds: float) -> None:
        if max_calls <= 0:
            raise ValueError("max_calls must be positive")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        self.max_calls = max_calls
        self.window_seconds = window_seconds
        self._calls: Deque[float] = deque()
        self._lock = threading.Lock()

    def allow(self) -> bool:
        with self._lock:
            now = time.monotonic()
            self._prune(now)
            if len(self._calls) >= self.max_calls:
                return False
            self._calls.append(now)
            return True

    def wait(self) -> None:
        while True:
            with self._lock:
                now = time.monotonic()
                self._prune(now)
                if len(self._calls) < self.max_calls:
                    self._calls.append(now)
                    return
                sleep_for = self.window_seconds - (now - self._calls[0])
            if sleep_for > 0:
                time.sleep(min(sleep_for, self.window_seconds))

    def snapshot(self) -> RateLimitSnapshot:
        with self._lock:
            now = time.monotonic()
            self._prune(now)
            reset_after = 0.0
            if self._calls:
                reset_after = max(0.0, self.window_seconds - (now - self._calls[0]))
            used = len(self._calls)
            return RateLimitSnapshot(
                max_calls=self.max_calls,
                window_seconds=self.window_seconds,
                used=used,
                remaining=max(0, self.max_calls - used),
                reset_after_seconds=reset_after,
            )

    def _prune(self, now: float) -> None:
        while self._calls and now - self._calls[0] >= self.window_seconds:
            self._calls.popleft()
