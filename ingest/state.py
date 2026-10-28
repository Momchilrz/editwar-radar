"""Process-wide state shared by the consumer, scorer, and API."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from config import Settings
from detect.engine import WarEngine
from detect.models import ScorePoint

from ingest.http import PoliteClient
from ingest.hub import BroadcastHub
from ingest.rate import RateMeter
from ingest.store import EventStore

log = logging.getLogger("editwar.ingest")


@dataclass
class StreamStatus:
    connected: bool = False
    connected_at: datetime | None = None
    last_event_at: datetime | None = None
    last_error: str | None = None
    reconnects: int = 0


@dataclass
class IngestStats:
    payloads: int = 0
    seen: int = 0
    counted_edits: int = 0
    reverts: int = 0
    bots_skipped: int = 0
    self_skipped: int = 0
    duplicates: int = 0
    ignored: int = 0


@dataclass
class AppState:
    settings: Settings
    engine: WarEngine
    store: EventStore
    status: StreamStatus = field(default_factory=StreamStatus)
    stats: IngestStats = field(default_factory=IngestStats)
    rate: RateMeter = field(default_factory=RateMeter)
    views: dict[tuple[str, str], int] = field(default_factory=dict)
    views_at: datetime | None = None
    views_error: str | None = None
    hub: BroadcastHub = field(default_factory=BroadcastHub)
    http: PoliteClient | None = None
    live_after: datetime = field(default_factory=lambda: datetime.now(UTC))
    caught_up: bool = False
    since: str | None = None

    def __post_init__(self) -> None:
        if self.http is None:
            self.http = PoliteClient(
                self.settings.user_agent,
                min_interval=self.settings.http_min_interval,
            )


def build_state(settings: Settings, engine: WarEngine | None = None) -> AppState:
    window = timedelta(hours=settings.window_hours)
    radar = engine or WarEngine(
        window,
        min_reverts=settings.leaderboard_min_reverts,
        skip_minor=settings.skip_minor,
    )
    store = EventStore(settings.database_url)
    live_after = datetime.now(UTC) - timedelta(seconds=15)
    return AppState(settings=settings, engine=radar, store=store, live_after=live_after)


def replay(state: AppState) -> None:
    now = datetime.now(UTC)
    cutoff = now - state.engine.window - timedelta(minutes=10)
    events = state.store.load_recent(cutoff)
    for event in events:
        state.engine.observe(event, now=now)
    seeded: dict[tuple[str, str], list[ScorePoint]] = {}
    for wiki, title, point in state.store.load_history(cutoff):
        seeded.setdefault((wiki, title), []).append(point)
    for (wiki, title), points in seeded.items():
        state.engine.seed_history(wiki, title, points)
    log.info("replayed %s edits from sqlite", len(events))


def initial_since(state: AppState) -> None:
    now = datetime.now(UTC)
    window_start = now - state.engine.window
    last = state.store.latest_ts()
    if last is None:
        state.since = iso_z(window_start) if state.settings.backfill else None
        return
    state.since = iso_z(max(last - timedelta(seconds=2), window_start))


def iso_z(value: datetime) -> str:
    current = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return current.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
