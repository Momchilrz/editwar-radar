"""Background loops and the stdout smoke-test entrypoint."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from config import get_settings, setup_logging

from ingest.consumer import consume_loop
from ingest.state import AppState, build_state, initial_since, replay
from ingest.views import refresh_pageviews

log = logging.getLogger("editwar.score")


async def score_loop(state: AppState, stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=state.settings.refresh_seconds)
            return
        except TimeoutError:
            pass
        try:
            publish_scores(state)
        except Exception:
            log.exception("score refresh failed")


async def status_loop(state: AppState, stop: asyncio.Event) -> None:
    from api.present import status_payload

    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=10)
            return
        except TimeoutError:
            pass
        _note_caught_up(state)
        try:
            state.hub.publish("status", status_payload(state))
        except Exception:
            log.exception("status publish failed")


async def views_loop(state: AppState, stop: asyncio.Event) -> None:
    try:
        await asyncio.wait_for(stop.wait(), timeout=5)
        return
    except TimeoutError:
        pass
    while not stop.is_set():
        try:
            await refresh_pageviews(state)
        except Exception:
            log.exception("pageview refresh failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=3600)
            return
        except TimeoutError:
            continue


def publish_scores(state: AppState) -> None:
    from api.present import wars_response

    now = datetime.now(UTC)
    state.engine.prune(now)
    points = state.engine.record_scores(now)
    state.store.append_scores(points)
    state.store.prune(now - state.engine.window)
    board = state.engine.leaderboard(now)
    state.store.materialize(board.wars, now)
    payload = wars_response(state, limit=50, wiki=None, now=now)
    state.hub.publish("leaderboard", payload.model_dump(mode="json"))
    log.info(
        "leaderboard wars=%s ingested=%s reverts=%s connected=%s",
        board.total,
        state.stats.counted_edits,
        state.stats.reverts,
        state.status.connected,
    )
    for index, war in enumerate(board.wars[:10], start=1):
        log.info(
            "#%s score=%s reverts=%s mutual=%s %s | %s",
            index,
            war.score,
            war.reverts,
            war.mutual_war,
            war.wiki,
            war.title,
        )


def _note_caught_up(state: AppState) -> None:
    if state.caught_up or not state.status.connected or state.status.connected_at is None:
        return
    quiet_for = datetime.now(UTC) - state.status.connected_at
    if quiet_for > timedelta(seconds=20) and state.stats.payloads == 0:
        state.caught_up = True
        log.info("stream connected with no events yet; treating it as live")


async def run_smoke() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)
    if settings.placeholder_contact:
        log.warning("Set UA_CONTACT in .env to a real address before a long run")
    state = build_state(settings)
    replay(state)
    initial_since(state)
    stop = asyncio.Event()
    tasks = [
        asyncio.create_task(consume_loop(state, stop), name="ingest"),
        asyncio.create_task(score_loop(state, stop), name="score"),
    ]
    try:
        await asyncio.gather(*tasks)
    finally:
        stop.set()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        state.store.flush()
        if state.http is not None:
            await state.http.aclose()


def main() -> None:
    try:
        asyncio.run(run_smoke())
    except KeyboardInterrupt:
        logging.getLogger("editwar.ingest").info("stopped")
