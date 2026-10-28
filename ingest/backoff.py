"""Reconnect delay. 1s, 2s, 4s … capped at 60s."""

from __future__ import annotations


def next_delay(current: float, *, cap: float = 60.0) -> float:
    if current < 1:
        return 1.0
    return min(current * 2.0, cap)
