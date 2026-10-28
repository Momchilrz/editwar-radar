"""Wikimedia recentchange SSE consumer."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import threading
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from typing import cast
from urllib.parse import quote

import requests
import sseclient
from config import Settings
from detect.models import FeedNotice
from detect.signatures import extract_reverted_user
from jsonutil import is_object, loads_lenient_flagged, object_list

from ingest.links import article_url
from ingest.parse import event_time, parse_recentchange
from ingest.state import AppState, iso_z

log = logging.getLogger("editwar.ingest")

_active_close: list[threading.Event] = []
_active_responses: list[requests.Response] = []


def stream_endpoint(base: str, since: str | None) -> str:
    """EventStreams resumes with ``since`` (ISO-8601). ``since_date`` is not a parameter."""
    if not since:
        return base
    separator = "&" if "?" in base else "?"
    return f"{base}{separator}since={quote(since, safe='')}"


def close_active_stream() -> None:
    while _active_close:
        _active_close.pop().set()
    while _active_responses:
        response = _active_responses.pop()
        try:
            response.close()
        except Exception:
            log.debug("closing stream failed", exc_info=True)


async def consume_loop(state: AppState, stop: asyncio.Event) -> None:
    from ingest.backoff import next_delay

    delay = 0.0
    since = state.since
    try:
        while not stop.is_set():
            got_event = False
            try:
                state.status.connected = True
                state.status.connected_at = datetime.now(UTC)
                state.status.last_error = None
                async for raw in iter_sse_data(state.settings, since, stop):
                    got_event = True
                    delay = 0.0
                    handle_raw(state, raw)
                    since = state.since
                    if stop.is_set():
                        break
            except Exception as exc:
                if stop.is_set():
                    break
                state.status.last_error = str(exc)
                log.warning("stream interrupted: %s", exc)
            finally:
                state.status.connected = False
                state.status.connected_at = None
                state.store.flush()
            if stop.is_set():
                break
            if got_event:
                delay = 0.0
            delay = next_delay(delay)
            state.status.reconnects += 1
            log.info("reconnecting in %.0fs (attempt %s)", delay, state.status.reconnects)
            try:
                await asyncio.wait_for(stop.wait(), timeout=delay)
                break
            except TimeoutError:
                continue
    finally:
        close_active_stream()
        state.store.flush()


def handle_raw(state: AppState, raw: str) -> None:
    try:
        payload, repaired = loads_lenient_flagged(raw)
    except ValueError:
        log.debug("dropping unparseable stream event")
        return
    if repaired:
        log.warning("stream event was truncated; dropped the incomplete tail")
    for item in object_list(payload):
        handle_payload(state, item)


def handle_payload(state: AppState, payload: dict[str, object]) -> None:
    state.stats.payloads += 1
    when = event_time(payload)
    if when is not None:
        state.status.last_event_at = when
        state.since = iso_z(when - timedelta(seconds=2))
        if datetime.now(UTC) - when < timedelta(seconds=45):
            if not state.caught_up:
                log.info("caught up to the live stream")
            state.caught_up = True
    if not is_object(payload):
        return
    edit = parse_recentchange(payload, state.settings)
    if edit is None:
        state.stats.ignored += 1
        _maybe_log_rate(state)
        return
    state.stats.seen += 1
    result = state.engine.observe(edit)
    if result.reason == "counted":
        state.stats.counted_edits += 1
        state.rate.mark()
        reverted = extract_reverted_user(edit.comment) if result.is_revert else None
        if result.is_revert:
            state.stats.reverts += 1
        state.store.enqueue(edit, is_revert=result.is_revert, reverted_user=reverted)
        if result.notice is not None and edit.timestamp >= state.live_after:
            log.info(
                "WAR %s %s | %s score=%s reverts=%s mutual=%s",
                result.notice.kind,
                result.notice.wiki,
                result.notice.title,
                result.notice.score,
                result.notice.reverts,
                result.notice.mutual,
            )
            state.hub.publish("ignition", ignition_dict(result.notice))
    elif result.reason == "bot":
        state.stats.bots_skipped += 1
    elif result.reason == "self_revert":
        state.stats.self_skipped += 1
    elif result.reason == "duplicate":
        state.stats.duplicates += 1
    _maybe_log_rate(state)


def ignition_dict(notice: FeedNotice) -> dict[str, object]:
    return {
        "id": notice.id,
        "kind": notice.kind,
        "wiki": notice.wiki,
        "title": notice.title,
        "at": notice.at.isoformat(),
        "score": notice.score,
        "reverts": notice.reverts,
        "mutual": notice.mutual,
        "actors": list(notice.actors),
        "url": article_url(notice.wiki, notice.title),
    }


def _maybe_log_rate(state: AppState) -> None:
    if state.stats.payloads % 1000 != 0:
        return
    articles, wars = state.engine.counts(datetime.now(UTC))
    log.info(
        "ingest payloads=%s edits=%s reverts=%s bots=%s wars=%s articles=%s connected=%s",
        state.stats.payloads,
        state.stats.counted_edits,
        state.stats.reverts,
        state.stats.bots_skipped,
        wars,
        articles,
        state.status.connected,
    )


async def iter_sse_data(
    settings: Settings, since: str | None, stop: asyncio.Event
) -> AsyncIterator[str]:
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[tuple[str, object]] = asyncio.Queue()
    cancelled = threading.Event()
    _active_close.append(cancelled)

    def emit(kind: str, payload: object) -> None:
        try:
            loop.call_soon_threadsafe(queue.put_nowait, (kind, payload))
        except RuntimeError:
            return

    def worker() -> None:
        response: requests.Response | None = None
        try:
            session = requests.Session()
            session.trust_env = settings.trust_env
            session.headers["User-Agent"] = settings.user_agent
            session.headers["Accept"] = "text/event-stream"
            url = stream_endpoint(settings.stream_url, since)
            response = session.get(
                url,
                stream=True,
                timeout=(settings.stream_connect_timeout, settings.stream_read_timeout),
            )
            response.raise_for_status()
            _active_responses.append(response)
            client = sseclient.SSEClient(cast(Iterator[bytes], response))
            for event in client.events():
                if stop.is_set() or cancelled.is_set():
                    break
                data = getattr(event, "data", "")
                if isinstance(data, bytes):
                    data = data.decode("utf-8", errors="replace")
                if isinstance(data, str) and data.strip():
                    emit("data", data)
            emit("end", None)
        except Exception as exc:
            emit("error", exc)
        finally:
            if response is not None:
                with contextlib.suppress(ValueError):
                    _active_responses.remove(response)
                response.close()

    thread = threading.Thread(target=worker, name="editwar-sse", daemon=True)
    thread.start()
    try:
        while not stop.is_set() and not cancelled.is_set():
            try:
                kind, payload = await asyncio.wait_for(queue.get(), timeout=0.2)
            except TimeoutError:
                continue
            if kind == "data" and isinstance(payload, str):
                yield payload
            elif kind == "end":
                break
            elif kind == "error":
                if isinstance(payload, Exception):
                    raise payload
                raise RuntimeError("stream failed")
    finally:
        cancelled.set()
        thread.join(timeout=2)


def main() -> None:
    from ingest.runtime import main as run_smoke

    run_smoke()


if __name__ == "__main__":
    main()
