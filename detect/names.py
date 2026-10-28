"""Wikipedia username normalization.

Usernames are case-sensitive except for the first character. Underscores and
spaces are the same character, and the recent-changes stream sometimes injects
bidirectional marks into comments.
"""

from __future__ import annotations

_BIDI = str.maketrans("", "", "\u200e\u200f\u202a\u202b\u202c\u202d\u202e")


def display_user(name: str) -> str:
    text = name.translate(_BIDI).replace("_", " ")
    return " ".join(text.split())


def normalize_user(name: str) -> str:
    text = display_user(name)
    if not text:
        return ""
    return text[0].casefold() + text[1:]
