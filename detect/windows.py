"""Clock windows for the boards people actually read.

The 4-hour block starts on an hour boundary and only steps forward when the
hour changes. At 20:30 UTC the block is 16:00–20:30. At 21:00 it becomes
17:00–21:00. The daily board is the current UTC day.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

FOUR_HOUR_MIN_REVERTS = 4
DAILY_MIN_REVERTS = 6


def clock_four_hours(now: datetime) -> tuple[datetime, datetime]:
    current = now.astimezone(UTC)
    hour = current.replace(minute=0, second=0, microsecond=0)
    return hour - timedelta(hours=4), current


def utc_today(now: datetime) -> tuple[datetime, datetime]:
    current = now.astimezone(UTC)
    start = current.replace(hour=0, minute=0, second=0, microsecond=0)
    return start, current
