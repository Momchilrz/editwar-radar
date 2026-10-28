"""API response models."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class WarOut(BaseModel):
    wiki: str
    title: str
    score: int
    edits: int
    reverts: int
    distinct_reverters: int
    mutual_pairs: int
    mutual_war: bool
    reverters: list[str]
    war_started_at: datetime | None
    last_revert_at: datetime | None
    views: int | None = None
    url: str


class IgnitionOut(BaseModel):
    id: str
    kind: str
    wiki: str
    title: str
    at: datetime
    score: int
    reverts: int
    mutual: bool
    actors: list[str]
    url: str


class WarsResponse(BaseModel):
    generated_at: datetime
    stream_connected: bool
    caught_up: bool
    last_event_at: datetime | None
    last_error: str | None
    reconnects: int
    ingested_edits: int
    reverts_seen: int
    edits_per_minute: int
    articles: int
    total: int
    window_hours: float
    refresh_seconds: int
    wikis: list[str]
    wars: list[WarOut]
    ignitions: list[IgnitionOut]


class StatusOut(BaseModel):
    generated_at: datetime
    stream_connected: bool
    caught_up: bool
    last_event_at: datetime | None
    last_error: str | None
    reconnects: int
    ingested_edits: int
    reverts_seen: int
    edits_per_minute: int
    articles: int
    total: int


class ParticipantOut(BaseModel):
    name: str
    reverts_made: int
    times_reverted: int


class PairOut(BaseModel):
    reverter: str
    reverted: str
    count: int


class MutualOut(BaseModel):
    a: str
    b: str


class TimelineOut(BaseModel):
    timestamp: datetime
    user: str
    reverted_user: str | None
    comment: str


class ScorePointOut(BaseModel):
    timestamp: datetime
    score: int
    reverts: int


class RevisionOut(BaseModel):
    id: int | None
    timestamp: str
    minor: bool
    size: int | None
    comment: str
    user: str
    delta: int | None


class WarDetailOut(WarOut):
    participants: list[ParticipantOut]
    directed_pairs: list[PairOut]
    mutual: list[MutualOut]
    timeline: list[TimelineOut]
    score_history: list[ScorePointOut]
    recent_history: list[RevisionOut] | None = Field(default=None)
