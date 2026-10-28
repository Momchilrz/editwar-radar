"""Optional per-article history fetch. Not on the hot path."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from urllib.parse import quote

from jsonutil import is_object, loads_lenient_flagged

from ingest.http import PoliteClient

log = logging.getLogger("editwar.history")


@dataclass(frozen=True)
class Revision:
    rev_id: int | None
    timestamp: str
    minor: bool
    size: int | None
    comment: str
    user: str
    delta: int | None


def wiki_lang(server_name: str) -> str | None:
    host = server_name.lower().split(":")[0]
    parts = host.split(".")
    if len(parts) >= 3 and parts[1] == "wikipedia":
        return parts[0]
    return None


def parse_history(payload: object) -> list[Revision]:
    if not is_object(payload):
        return []
    raw = payload.get("revisions")
    if not isinstance(raw, list):
        return []
    revisions: list[Revision] = []
    for item in raw:
        parsed = _revision(item)
        if parsed is not None:
            revisions.append(parsed)
    return revisions


async def fetch_history(
    client: PoliteClient, wiki: str, title: str, *, limit: int = 20
) -> list[Revision]:
    lang = wiki_lang(wiki)
    if lang is None or not title.strip():
        return []
    slug = quote(title.replace(" ", "_"), safe="")
    url = f"https://api.wikimedia.org/core/v1/wikipedia/{lang}/page/{slug}/history?limit={limit}"
    response = await client.get(url)
    if response.status_code == 404:
        return []
    response.raise_for_status()
    try:
        payload, repaired = loads_lenient_flagged(response.text)
    except ValueError:
        log.warning("history response for %s was not JSON", title)
        return []
    if repaired:
        log.warning("history response for %s was truncated; dropped the incomplete tail", title)
    return parse_history(payload)


def _revision(value: object) -> Revision | None:
    if not is_object(value):
        return None
    user = value.get("user")
    name = ""
    if is_object(user):
        raw_name = user.get("name")
        if isinstance(raw_name, str):
            name = raw_name
    comment = value.get("comment")
    timestamp = value.get("timestamp")
    return Revision(
        rev_id=_int(value.get("id")),
        timestamp=timestamp if isinstance(timestamp, str) else "",
        minor=value.get("minor") is True,
        size=_int(value.get("size")),
        comment=comment if isinstance(comment, str) else "",
        user=name,
        delta=_int(value.get("delta")),
    )


def _int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value
