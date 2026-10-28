"""In-memory war radar. Pure: no I/O, no logging. One instance per process."""

from __future__ import annotations

import threading
from collections import OrderedDict, deque
from datetime import UTC, datetime, timedelta

from detect.models import (
    ArticleScore,
    FeedNotice,
    IncomingEdit,
    Leaderboard,
    ObserveResult,
    ScorePoint,
)
from detect.names import display_user
from detect.scoring import ArticleWindow, classify_revert


class WarEngine:
    """Track every article that has been edited inside the scoring window."""

    def __init__(
        self,
        window: timedelta,
        *,
        min_reverts: int = 2,
        skip_minor: bool = False,
    ) -> None:
        if min_reverts < 1:
            raise ValueError("min_reverts must be >= 1")
        self.window = window
        self.min_reverts = min_reverts
        self.skip_minor = skip_minor
        self._articles: dict[tuple[str, str], ArticleWindow] = {}
        self._seen: OrderedDict[str, datetime] = OrderedDict()
        self._feed: deque[FeedNotice] = deque(maxlen=40)
        self._history: dict[tuple[str, str], deque[ScorePoint]] = {}
        self._lock = threading.RLock()

    def observe(self, edit: IncomingEdit, *, now: datetime | None = None) -> ObserveResult:
        with self._lock:
            return self._observe(edit, now=now)

    def _observe(self, edit: IncomingEdit, *, now: datetime | None = None) -> ObserveResult:
        current = _require_aware(now) if now is not None else datetime.now(UTC)
        timestamp = _require_aware(edit.timestamp)
        if edit.event_id:
            if edit.event_id in self._seen:
                return ObserveResult("duplicate", False, None, None)
            self._remember(edit.event_id, timestamp)
        if not edit.user.strip() or not edit.title.strip():
            return ObserveResult("empty", False, None, None)
        if timestamp < current - self.window:
            return ObserveResult("too_old", False, None, None)
        if edit.bot:
            return ObserveResult("bot", False, None, None)
        if self.skip_minor and edit.minor:
            return ObserveResult("minor", False, None, None)

        revert, reverted_user, self_revert = classify_revert(edit)
        if self_revert:
            return ObserveResult("self_revert", False, None, None)

        key = (edit.wiki, edit.title)
        window = self._articles.get(key)
        if window is None:
            window = ArticleWindow(edit.wiki, edit.title, self.window)
            self._articles[key] = window
        window.expire(current)
        was_qualifying = window.revert_count >= self.min_reverts
        was_mutual = window.has_mutual() if was_qualifying else False
        if revert:
            window.add_revert(
                IncomingEdit(
                    wiki=edit.wiki,
                    title=edit.title,
                    user=display_user(edit.user),
                    comment=edit.comment,
                    timestamp=timestamp,
                    bot=edit.bot,
                    minor=edit.minor,
                    tags=edit.tags,
                    event_id=edit.event_id,
                ),
                display_user(reverted_user) if reverted_user else None,
            )
        else:
            window.add_edit(edit)

        score = window.snapshot(current)
        notice = self._notice(
            score, edit_at=timestamp, was_qualifying=was_qualifying, was_mutual=was_mutual
        )
        if notice is not None:
            self._feed.append(notice)
        return ObserveResult("counted", revert, notice, score)

    def leaderboard(
        self,
        now: datetime,
        *,
        wiki: str | None = None,
        limit: int | None = None,
    ) -> Leaderboard:
        with self._lock:
            return self._stored_board(now, wiki=wiki, limit=limit)

    def _stored_board(
        self,
        now: datetime,
        *,
        wiki: str | None,
        limit: int | None,
    ) -> Leaderboard:
        current = _require_aware(now)
        wiki_key = wiki.lower() if wiki else None
        rows: list[ArticleScore] = []
        for window in self._articles.values():
            window.expire(current)
            if wiki_key is not None and window.wiki.lower() != wiki_key:
                continue
            if window.revert_count < self.min_reverts:
                continue
            rows.append(window.snapshot(current))
        rows.sort(key=lambda row: (-row.score, -row.reverts, row.title.casefold(), row.wiki))
        total = len(rows)
        if limit is not None:
            rows = rows[:limit]
        return Leaderboard(wars=tuple(rows), total=total)

    def board(
        self,
        start: datetime,
        end: datetime,
        *,
        min_reverts: int,
        wiki: str | None = None,
        limit: int | None = None,
    ) -> Leaderboard:
        """Rank articles inside an explicit clock range. Does not change what is stored."""
        with self._lock:
            opened = _require_aware(start)
            closed = _require_aware(end)
            wiki_key = wiki.lower() if wiki else None
            rows: list[ArticleScore] = []
            for window in self._articles.values():
                window.expire(closed)
                if wiki_key is not None and window.wiki.lower() != wiki_key:
                    continue
                score = window.score_slice(opened, closed)
                if score.reverts < min_reverts:
                    continue
                rows.append(score)
            rows.sort(
                key=lambda row: (
                    not row.mutual_war,
                    -row.reverts,
                    -row.distinct_reverters,
                    row.title.casefold(),
                    row.wiki,
                )
            )
            total = len(rows)
            if limit is not None:
                rows = rows[:limit]
            return Leaderboard(wars=tuple(rows), total=total)

    def article(self, wiki: str, title: str, now: datetime) -> ArticleScore | None:
        with self._lock:
            window = self._articles.get((wiki, title))
            if window is None:
                return None
            score = window.snapshot(_require_aware(now))
            if score.edits == 0 and score.reverts == 0:
                return None
            return score

    def feed(self) -> tuple[FeedNotice, ...]:
        with self._lock:
            return tuple(reversed(self._feed))

    def history(self, wiki: str, title: str) -> tuple[ScorePoint, ...]:
        points = self._history.get((wiki, title))
        if points is None:
            return ()
        return tuple(points)

    def record_scores(self, now: datetime) -> list[tuple[str, str, ScorePoint]]:
        """Append one score point for every article that is, or was, a war."""
        with self._lock:
            return self._record_scores(now)

    def _record_scores(self, now: datetime) -> list[tuple[str, str, ScorePoint]]:
        current = _require_aware(now)
        saved: list[tuple[str, str, ScorePoint]] = []
        for key, window in list(self._articles.items()):
            window.expire(current)
            tracked = key in self._history
            if window.revert_count < self.min_reverts and not (tracked and window.revert_count > 0):
                continue
            score = window.snapshot(current)
            point = ScorePoint(timestamp=current, score=score.score, reverts=score.reverts)
            self._history.setdefault(key, deque(maxlen=400)).append(point)
            saved.append((key[0], key[1], point))
        return saved

    def seed_history(self, wiki: str, title: str, points: list[ScorePoint]) -> None:
        if not points:
            return
        bucket = self._history.setdefault((wiki, title), deque(maxlen=400))
        for point in points:
            bucket.append(point)

    def counts(self, now: datetime) -> tuple[int, int]:
        """Return ``(articles_in_window, wars)``."""
        with self._lock:
            return self._counts(now)

    def _counts(self, now: datetime) -> tuple[int, int]:
        current = _require_aware(now)
        articles = 0
        wars = 0
        for window in self._articles.values():
            window.expire(current)
            if window.edit_count == 0 and window.revert_count == 0:
                continue
            articles += 1
            if window.revert_count >= self.min_reverts:
                wars += 1
        return articles, wars

    def prune(self, now: datetime) -> None:
        with self._lock:
            self._prune(now)

    def _prune(self, now: datetime) -> None:
        current = _require_aware(now)
        cutoff = current - self.window
        empty: list[tuple[str, str]] = []
        for key, window in self._articles.items():
            window.expire(current)
            if window.edit_count == 0 and window.revert_count == 0:
                empty.append(key)
        for article_key in empty:
            del self._articles[article_key]
            self._history.pop(article_key, None)
        stale_ids = [event_id for event_id, seen_at in self._seen.items() if seen_at < cutoff]
        for event_id in stale_ids:
            del self._seen[event_id]
        for key in list(self._history):
            if key not in self._articles:
                self._history.pop(key, None)

    def _notice(
        self,
        score: ArticleScore,
        *,
        edit_at: datetime,
        was_qualifying: bool,
        was_mutual: bool,
    ) -> FeedNotice | None:
        qualifying = score.reverts >= self.min_reverts
        if qualifying and not was_qualifying:
            actors: tuple[str, ...] = score.mutual[0] if score.mutual else score.reverters
            return FeedNotice(
                kind="ignited",
                wiki=score.wiki,
                title=score.title,
                at=edit_at,
                score=score.score,
                reverts=score.reverts,
                mutual=score.mutual_war,
                actors=actors,
            )
        if qualifying and score.mutual_war and not was_mutual:
            actors = score.mutual[0] if score.mutual else score.reverters
            return FeedNotice(
                kind="mutual",
                wiki=score.wiki,
                title=score.title,
                at=edit_at,
                score=score.score,
                reverts=score.reverts,
                mutual=True,
                actors=actors,
            )
        return None

    def _remember(self, event_id: str, timestamp: datetime) -> None:
        self._seen[event_id] = timestamp
        self._seen.move_to_end(event_id)
        while len(self._seen) > 200_000:
            self._seen.popitem(last=False)


def _require_aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError("timestamps must be timezone-aware UTC")
    return value
