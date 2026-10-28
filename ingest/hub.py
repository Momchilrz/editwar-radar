"""In-process fan-out for server-sent events."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime


class BroadcastHub:
    def __init__(self) -> None:
        self._subscribers: list[asyncio.Queue[str]] = []

    def subscribe(self) -> asyncio.Queue[str]:
        queue: asyncio.Queue[str] = asyncio.Queue(maxsize=100)
        self._subscribers.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[str]) -> None:
        try:
            self._subscribers.remove(queue)
        except ValueError:
            return

    def publish(self, event: str, data: object) -> None:
        message = format_sse(event, data)
        for queue in list(self._subscribers):
            _offer(queue, message)


def format_sse(event: str, data: object) -> str:
    body = json.dumps(data, separators=(",", ":"), default=_json_default)
    return f"event: {event}\ndata: {body}\n\n"


def _json_default(value: object) -> str:
    if isinstance(value, datetime):
        current = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return current.astimezone(UTC).isoformat()
    raise TypeError(f"not JSON serializable: {type(value)!r}")


def _offer(queue: asyncio.Queue[str], message: str) -> None:
    try:
        queue.put_nowait(message)
    except asyncio.QueueFull:
        try:
            queue.get_nowait()
        except asyncio.QueueEmpty:
            return
        try:
            queue.put_nowait(message)
        except asyncio.QueueFull:
            return
