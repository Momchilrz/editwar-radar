"""Turn a recentchange payload into an IncomingEdit, or drop it."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from config import Settings
from detect.models import IncomingEdit
from jsonutil import is_object


def event_time(payload: dict[str, object]) -> datetime | None:
    meta = payload.get("meta")
    if is_object(meta):
        raw_dt = meta.get("dt")
        if isinstance(raw_dt, str):
            parsed = _parse_iso(raw_dt)
            if parsed is not None:
                return parsed
    raw_ts = payload.get("timestamp")
    if isinstance(raw_ts, bool):
        return None
    if isinstance(raw_ts, (int, float)):
        return datetime.fromtimestamp(float(raw_ts), tz=UTC)
    if isinstance(raw_ts, str) and raw_ts.isdigit():
        return datetime.fromtimestamp(int(raw_ts), tz=UTC)
    return None


def parse_recentchange(payload: dict[str, object], settings: Settings) -> IncomingEdit | None:
    """Keep edits on configured wikis. Noise filtering happens in the detector."""
    if payload.get("type") != "edit":
        return None
    wiki = _wiki(payload)
    if wiki is None or wiki not in settings.wiki_set:
        return None
    if settings.main_namespace_only and _namespace(payload) not in {None, 0}:
        return None
    title = _text(payload.get("title"))
    user = _text(payload.get("user"))
    if title is None or user is None:
        return None
    timestamp = event_time(payload)
    if timestamp is None:
        return None
    comment = payload.get("comment")
    comment_text = comment if isinstance(comment, str) else ""
    return IncomingEdit(
        wiki=wiki,
        title=title,
        user=user,
        comment=comment_text,
        timestamp=timestamp,
        bot=payload.get("bot") is True,
        minor=payload.get("minor") is True,
        tags=_tags(payload),
        event_id=_event_id(payload, wiki, title, user, comment_text, timestamp),
    )


def _wiki(payload: dict[str, object]) -> str | None:
    server = _text(payload.get("server_name"))
    if server is not None:
        return server.lower()
    meta = payload.get("meta")
    if is_object(meta):
        domain = _text(meta.get("domain"))
        if domain is not None:
            return domain.lower()
    return None


def _namespace(payload: dict[str, object]) -> int | None:
    raw = payload.get("namespace")
    if isinstance(raw, bool) or not isinstance(raw, int):
        return None
    return raw


def _tags(payload: dict[str, object]) -> tuple[str, ...]:
    raw = payload.get("tags")
    if not isinstance(raw, list):
        return ()
    return tuple(tag for tag in raw if isinstance(tag, str))


def _text(value: object) -> str | None:
    if isinstance(value, str):
        stripped = value.strip()
        if stripped:
            return stripped
    return None


def _event_id(
    payload: dict[str, object],
    wiki: str,
    title: str,
    user: str,
    comment: str,
    timestamp: datetime,
) -> str:
    meta = payload.get("meta")
    if is_object(meta):
        meta_id = _text(meta.get("id"))
        if meta_id is not None:
            return meta_id
    raw_id = payload.get("id")
    if isinstance(raw_id, int) and not isinstance(raw_id, bool):
        return f"{wiki}:{raw_id}"
    digest = hashlib.sha1(
        f"{wiki}|{title}|{user}|{timestamp.isoformat()}|{comment}".encode()
    ).hexdigest()
    return digest


def _parse_iso(value: str) -> datetime | None:
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
