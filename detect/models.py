"""Datatypes shared by the detector. The consumer and API depend on these."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

Reason = Literal["counted", "bot", "minor", "self_revert", "duplicate", "too_old", "empty"]
NoticeKind = Literal["ignited", "mutual"]


@dataclass(frozen=True)
class IncomingEdit:
    wiki: str
    title: str
    user: str
    comment: str
    timestamp: datetime
    bot: bool = False
    minor: bool = False
    tags: tuple[str, ...] = ()
    event_id: str | None = None


@dataclass(frozen=True)
class RevertEvent:
    timestamp: datetime
    user: str
    reverted_user: str | None
    comment: str


@dataclass(frozen=True)
class Participant:
    name: str
    reverts_made: int
    times_reverted: int


@dataclass(frozen=True)
class DirectedCount:
    reverter: str
    reverted: str
    count: int


@dataclass(frozen=True)
class ScorePoint:
    timestamp: datetime
    score: int
    reverts: int


@dataclass(frozen=True)
class ArticleScore:
    wiki: str
    title: str
    score: int
    edits: int
    reverts: int
    distinct_reverters: int
    mutual_pairs: int
    mutual_war: bool
    reverters: tuple[str, ...]
    war_started_at: datetime | None
    last_revert_at: datetime | None
    timeline: tuple[RevertEvent, ...]
    directed_pairs: tuple[DirectedCount, ...]
    mutual: tuple[tuple[str, str], ...]
    participants: tuple[Participant, ...]


@dataclass(frozen=True)
class FeedNotice:
    kind: NoticeKind
    wiki: str
    title: str
    at: datetime
    score: int
    reverts: int
    mutual: bool
    actors: tuple[str, ...]

    @property
    def id(self) -> str:
        return f"{self.kind}|{self.wiki}|{self.title}|{self.at.isoformat()}"


@dataclass(frozen=True)
class ObserveResult:
    reason: Reason
    is_revert: bool
    notice: FeedNotice | None
    score: ArticleScore | None


@dataclass(frozen=True)
class Leaderboard:
    wars: tuple[ArticleScore, ...]
    total: int
