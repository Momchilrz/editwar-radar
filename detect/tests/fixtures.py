"""Realistic edit events for detector tests."""

from __future__ import annotations

from datetime import UTC, datetime

from detect.models import IncomingEdit

T0 = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)

UNDO_SOMEUSER = (
    "Undid revision [[Special:Diff/123|123]] by "
    "[[Special:Contributions/SomeUser|SomeUser]] ([[User talk:SomeUser|talk]])"
)
HUGGLE_IP = "Reverted edits by 1.2.3.4 (talk) ([[WP:HG|HG]]) (3.4.12)"
TWINKLE_OTHER = "Reverted 1 edit by OtherUser ([[WP:TW|TW]])"


def make_edit(
    *,
    wiki: str = "en.wikipedia.org",
    title: str = "Example",
    user: str = "Patroller",
    comment: str = "fix typo",
    timestamp: datetime | None = None,
    bot: bool = False,
    minor: bool = False,
    tags: tuple[str, ...] = (),
    event_id: str | None = None,
) -> IncomingEdit:
    return IncomingEdit(
        wiki=wiki,
        title=title,
        user=user,
        comment=comment,
        timestamp=T0 if timestamp is None else timestamp,
        bot=bot,
        minor=minor,
        tags=tags,
        event_id=event_id,
    )
