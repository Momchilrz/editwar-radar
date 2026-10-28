"""Rolling one-minute counter for ingest rate."""

from __future__ import annotations

import time
from collections import deque


class RateMeter:
    def __init__(self) -> None:
        self._marks: deque[float] = deque()

    def mark(self) -> None:
        now = time.monotonic()
        self._marks.append(now)
        self._trim(now)

    def per_minute(self) -> int:
        self._trim(time.monotonic())
        return len(self._marks)

    def _trim(self, now: float) -> None:
        cutoff = now - 60.0
        while self._marks and self._marks[0] < cutoff:
            self._marks.popleft()
