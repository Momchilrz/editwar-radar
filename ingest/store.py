"""SQLite persistence. Schema uses portable types so Postgres is a later swap."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from detect.models import ArticleScore, IncomingEdit, ScorePoint
from sqlalchemy import DateTime, Integer, String, Text, create_engine, delete, event, select
from sqlalchemy.engine import Dialect, Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column
from sqlalchemy.pool import StaticPool
from sqlalchemy.types import TypeDecorator

_SQLITE_PREFIX = "sqlite:///"


class UTCDateTime(TypeDecorator[datetime]):
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        del dialect
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        del dialect
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class Base(DeclarativeBase):
    pass


class EventRow(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dedup_key: Mapped[str] = mapped_column(String(160), unique=True)
    wiki: Mapped[str] = mapped_column(String(128), index=True)
    title: Mapped[str] = mapped_column(Text)
    user_name: Mapped[str] = mapped_column(Text)
    bot: Mapped[bool] = mapped_column()
    minor: Mapped[bool] = mapped_column()
    comment: Mapped[str] = mapped_column(Text)
    tags: Mapped[str] = mapped_column(Text)
    ts: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    is_revert: Mapped[bool] = mapped_column()
    reverted_user: Mapped[str | None] = mapped_column(Text, nullable=True)


class PageRow(Base):
    __tablename__ = "pages"

    wiki: Mapped[str] = mapped_column(String(128), primary_key=True)
    title: Mapped[str] = mapped_column(Text, primary_key=True)
    score: Mapped[int] = mapped_column(Integer)
    edits: Mapped[int] = mapped_column(Integer)
    reverts: Mapped[int] = mapped_column(Integer)
    distinct_reverters: Mapped[int] = mapped_column(Integer)
    mutual_pairs: Mapped[int] = mapped_column(Integer)
    mutual_war: Mapped[bool] = mapped_column()
    reverters: Mapped[str] = mapped_column(Text)
    war_started_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)


class ScoreHistoryRow(Base):
    __tablename__ = "score_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    wiki: Mapped[str] = mapped_column(String(128), index=True)
    title: Mapped[str] = mapped_column(Text)
    score: Mapped[int] = mapped_column(Integer)
    reverts: Mapped[int] = mapped_column(Integer)
    recorded_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)


@dataclass
class _Pending:
    edit: IncomingEdit
    is_revert: bool
    reverted_user: str | None


class EventStore:
    def __init__(self, url: str) -> None:
        resolved = resolve_sqlite_url(url)
        self.engine = _make_engine(resolved)
        Base.metadata.create_all(self.engine)
        self._pending: list[_Pending] = []

    def enqueue(self, edit: IncomingEdit, *, is_revert: bool, reverted_user: str | None) -> None:
        if not edit.event_id:
            return
        self._pending.append(_Pending(edit, is_revert, reverted_user))
        if len(self._pending) >= 50:
            self.flush()

    def flush(self) -> None:
        if not self._pending:
            return
        batch = self._pending
        self._pending = []
        with Session(self.engine) as session:
            session.add_all(_rows(batch))
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                for item in batch:
                    session.add(_row(item))
                    try:
                        session.commit()
                    except IntegrityError:
                        session.rollback()

    def load_recent(self, since: datetime) -> list[IncomingEdit]:
        with Session(self.engine) as session:
            rows = session.scalars(
                select(EventRow).where(EventRow.ts >= since).order_by(EventRow.ts.asc())
            ).all()
            return [_to_edit(row) for row in rows]

    def latest_ts(self) -> datetime | None:
        with Session(self.engine) as session:
            row = session.scalar(select(EventRow).order_by(EventRow.ts.desc()).limit(1))
            if row is None:
                return None
            return _aware(row.ts)

    def materialize(
        self, wars: tuple[ArticleScore, ...] | list[ArticleScore], now: datetime
    ) -> None:
        with Session(self.engine) as session:
            session.execute(delete(PageRow))
            for war in wars:
                session.add(
                    PageRow(
                        wiki=war.wiki,
                        title=war.title,
                        score=war.score,
                        edits=war.edits,
                        reverts=war.reverts,
                        distinct_reverters=war.distinct_reverters,
                        mutual_pairs=war.mutual_pairs,
                        mutual_war=war.mutual_war,
                        reverters=json.dumps(list(war.reverters)),
                        war_started_at=war.war_started_at,
                        updated_at=now,
                    )
                )
            session.commit()

    def append_scores(self, points: list[tuple[str, str, ScorePoint]]) -> None:
        if not points:
            return
        with Session(self.engine) as session:
            for wiki, title, point in points:
                session.add(
                    ScoreHistoryRow(
                        wiki=wiki,
                        title=title,
                        score=point.score,
                        reverts=point.reverts,
                        recorded_at=point.timestamp,
                    )
                )
            session.commit()

    def load_history(self, since: datetime) -> list[tuple[str, str, ScorePoint]]:
        with Session(self.engine) as session:
            rows = session.scalars(
                select(ScoreHistoryRow)
                .where(ScoreHistoryRow.recorded_at >= since)
                .order_by(ScoreHistoryRow.recorded_at.asc())
            ).all()
            return [
                (
                    row.wiki,
                    row.title,
                    ScorePoint(
                        timestamp=_aware(row.recorded_at), score=row.score, reverts=row.reverts
                    ),
                )
                for row in rows
            ]

    def prune(self, cutoff: datetime) -> None:
        margin = cutoff - timedelta(minutes=10)
        with Session(self.engine) as session:
            session.execute(delete(EventRow).where(EventRow.ts < margin))
            session.execute(delete(ScoreHistoryRow).where(ScoreHistoryRow.recorded_at < margin))
            session.commit()

    def close(self) -> None:
        self.flush()
        self.engine.dispose()


def resolve_sqlite_url(url: str) -> str:
    if not url.startswith(_SQLITE_PREFIX):
        return url
    path = url[len(_SQLITE_PREFIX) :]
    if path in {"", ":memory:"} or path.startswith("file:"):
        return url
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    candidate.parent.mkdir(parents=True, exist_ok=True)
    return _SQLITE_PREFIX + candidate.as_posix()


def _make_engine(url: str) -> Engine:
    if url in {"sqlite://", "sqlite:///:memory:"}:
        engine = create_engine(
            url,
            poolclass=StaticPool,
            connect_args={"check_same_thread": False},
        )
    elif url.startswith("sqlite"):
        engine = create_engine(url, connect_args={"check_same_thread": False})
    else:
        engine = create_engine(url)

    @event.listens_for(engine, "connect")
    def _pragmas(dbapi_connection: object, _connection_record: object) -> None:
        if not isinstance(dbapi_connection, sqlite3.Connection):
            return
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
        except sqlite3.Error:
            return
        finally:
            cursor.close()

    return engine


def _rows(batch: list[_Pending]) -> list[EventRow]:
    return [_row(item) for item in batch]


def _row(item: _Pending) -> EventRow:
    edit = item.edit
    return EventRow(
        dedup_key=edit.event_id or "",
        wiki=edit.wiki,
        title=edit.title,
        user_name=edit.user,
        bot=edit.bot,
        minor=edit.minor,
        comment=edit.comment,
        tags=json.dumps(list(edit.tags)),
        ts=edit.timestamp,
        is_revert=item.is_revert,
        reverted_user=item.reverted_user,
    )


def _to_edit(row: EventRow) -> IncomingEdit:
    try:
        parsed = json.loads(row.tags)
    except json.JSONDecodeError:
        parsed = []
    tags = tuple(tag for tag in parsed if isinstance(tag, str)) if isinstance(parsed, list) else ()
    return IncomingEdit(
        wiki=row.wiki,
        title=row.title,
        user=row.user_name,
        comment=row.comment,
        timestamp=_aware(row.ts),
        bot=row.bot,
        minor=row.minor,
        tags=tags,
        event_id=row.dedup_key,
    )


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
