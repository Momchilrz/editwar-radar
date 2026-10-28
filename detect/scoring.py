"""Sliding-window war score for a single article.

score = 3 × reverts + 2 × distinct_reverters + 6 × (mutual_pairs > 0)

The mutual term is a flag: extra pairs do not add another 6 points.
"""

from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta

from detect.models import (
    ArticleScore,
    IncomingEdit,
    Participant,
    RevertEvent,
)
from detect.mutual import PairGraph
from detect.names import display_user, normalize_user
from detect.signatures import extract_reverted_user, is_revert, is_self_revert


def war_score(*, reverts: int, distinct_reverters: int, mutual_pairs: int) -> int:
    mutual_bonus = 6 if mutual_pairs > 0 else 0
    return 3 * reverts + 2 * distinct_reverters + mutual_bonus


class ArticleWindow:
    """Edits and reverts for one article inside a sliding window."""

    def __init__(self, wiki: str, title: str, window: timedelta) -> None:
        self.wiki = wiki
        self.title = title
        self._window = window
        self._edit_times: deque[datetime] = deque()
        self._reverts: deque[RevertEvent] = deque()
        self._pairs = PairGraph()

    @property
    def revert_count(self) -> int:
        return len(self._reverts)

    @property
    def edit_count(self) -> int:
        return len(self._edit_times)

    def has_mutual(self) -> bool:
        return bool(self._pairs.mutual_pairs())

    def expire(self, now: datetime) -> None:
        cutoff = now - self._window
        self._edit_times = deque(ts for ts in self._edit_times if ts >= cutoff)
        self._reverts = deque(rev for rev in self._reverts if rev.timestamp >= cutoff)
        self._pairs.expire(cutoff)

    def add_edit(self, edit: IncomingEdit) -> None:
        self._edit_times.append(edit.timestamp)

    def add_revert(self, edit: IncomingEdit, reverted_user: str | None) -> RevertEvent:
        record = RevertEvent(
            timestamp=edit.timestamp,
            user=display_user(edit.user),
            reverted_user=display_user(reverted_user) if reverted_user else None,
            comment=edit.comment,
        )
        self._reverts.append(record)
        self._edit_times.append(edit.timestamp)
        if record.reverted_user is not None:
            self._pairs.add(record.user, record.reverted_user, record.timestamp)
        return record

    def snapshot(self, now: datetime) -> ArticleScore:
        self.expire(now)
        return self.score_slice(now - self._window)

    def score_slice(self, start: datetime, end: datetime | None = None) -> ArticleScore:
        """Score one clock range without deleting reverts stored outside it."""
        timeline = tuple(
            sorted(
                (rev for rev in self._reverts if _in_range(rev.timestamp, start, end)),
                key=lambda rev: rev.timestamp,
            )
        )
        edits = sum(1 for ts in self._edit_times if _in_range(ts, start, end))
        pairs = PairGraph()
        for revert in timeline:
            if revert.reverted_user is not None:
                pairs.add(revert.user, revert.reverted_user, revert.timestamp)
        reverters = _reverter_names(timeline)
        mutual = tuple(pairs.mutual_pairs())
        reverts = len(timeline)
        distinct = len(reverters)
        mutual_count = len(mutual)
        return ArticleScore(
            wiki=self.wiki,
            title=self.title,
            score=war_score(
                reverts=reverts,
                distinct_reverters=distinct,
                mutual_pairs=mutual_count,
            ),
            edits=edits,
            reverts=reverts,
            distinct_reverters=distinct,
            mutual_pairs=mutual_count,
            mutual_war=mutual_count > 0,
            reverters=reverters,
            war_started_at=timeline[0].timestamp if timeline else None,
            last_revert_at=timeline[-1].timestamp if timeline else None,
            timeline=timeline,
            directed_pairs=tuple(pairs.directed_counts()),
            mutual=mutual,
            participants=tuple(_participants(timeline)),
        )


def _in_range(moment: datetime, start: datetime, end: datetime | None) -> bool:
    if moment < start:
        return False
    return end is None or moment <= end


def classify_revert(edit: IncomingEdit) -> tuple[bool, str | None, bool]:
    """Return ``(is_revert, reverted_user, is_self)``."""
    if not is_revert(edit.comment, edit.tags):
        return False, None, False
    reverted = extract_reverted_user(edit.comment)
    return True, reverted, is_self_revert(edit.user, reverted, edit.comment)


def _reverter_names(timeline: tuple[RevertEvent, ...]) -> tuple[str, ...]:
    display: dict[str, str] = {}
    counts: dict[str, int] = {}
    for revert in timeline:
        key = normalize_user(revert.user)
        if not key:
            continue
        display.setdefault(key, revert.user)
        counts[key] = counts.get(key, 0) + 1
    ordered = sorted(display, key=lambda key: (-counts[key], display[key].casefold()))
    return tuple(display[key] for key in ordered)


def _participants(timeline: tuple[RevertEvent, ...]) -> list[Participant]:
    made: dict[str, int] = {}
    hit: dict[str, int] = {}
    display: dict[str, str] = {}
    for revert in timeline:
        actor = normalize_user(revert.user)
        if actor:
            display.setdefault(actor, revert.user)
            made[actor] = made.get(actor, 0) + 1
        if revert.reverted_user:
            target = normalize_user(revert.reverted_user)
            if target:
                display.setdefault(target, revert.reverted_user)
                hit[target] = hit.get(target, 0) + 1
    keys = set(made) | set(hit)
    rows = [
        Participant(
            name=display[key], reverts_made=made.get(key, 0), times_reverted=hit.get(key, 0)
        )
        for key in keys
    ]
    rows.sort(key=lambda row: (-row.reverts_made, -row.times_reverted, row.name.casefold()))
    return rows
