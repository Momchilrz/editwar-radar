"""Revert signatures.

An edit is a revert when its comment matches the revert regex or it carries a
revert change-tag. Self-reverts are identified separately and dropped before
scoring.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from detect.names import display_user, normalize_user

# Spec: /(undid revision|reverted|revert|huggle|twinkle|\brv\b|\brv:|vandalism|rollback)/i
REVERT_RE = re.compile(
    r"undid revision|reverted|revert|huggle|twinkle|\brv\b|\brv:|vandalism|rollback",
    re.IGNORECASE,
)

REVERT_TAGS = frozenset(
    {
        "mw-rollback",
        "mw-undo",
        "mw-manual-revert",
        "mw-reverted",
    }
)

_SELF_RV_RE = re.compile(r"\bself[-\s]?rv\b", re.IGNORECASE)
_CONTRIB_RE = re.compile(r"\[\[Special:Contributions/([^|\]]+)", re.IGNORECASE)
_TWINKLE_RE = re.compile(
    r"Reverted\s+\d+\s+edits?\s+by\s+(.+?)(?:\s*\(|\s*\[\[|$)",
    re.IGNORECASE,
)
_HUGGLE_RE = re.compile(
    r"Reverted\s+edits\s+by\s+(.+?)(?:\s*\(|\s*\[\[|$)",
    re.IGNORECASE,
)


def is_revert(comment: str, tags: Iterable[str] = ()) -> bool:
    if has_revert_tag(tags):
        return True
    return REVERT_RE.search(comment) is not None


def has_revert_tag(tags: Iterable[str]) -> bool:
    return any(tag.lower() in REVERT_TAGS for tag in tags)


def extract_reverted_user(comment: str) -> str | None:
    """Pull the reverted username out of undo, Twinkle, and Huggle comments."""
    contrib = _CONTRIB_RE.search(comment)
    if contrib is not None:
        return _clean_name(contrib.group(1))
    twinkle = _TWINKLE_RE.search(comment)
    if twinkle is not None:
        return _clean_name(twinkle.group(1))
    huggle = _HUGGLE_RE.search(comment)
    if huggle is not None:
        return _clean_name(huggle.group(1))
    return None


def is_self_revert(editor: str, reverted: str | None, comment: str) -> bool:
    """True when the editor reverted their own edit.

    A named target that is someone else wins over a stray ``self-rv`` token.
    Comments that only say ``self-rv`` (no extracted target) are self-reverts.
    """
    editor_key = normalize_user(editor)
    if reverted is not None:
        reverted_key = normalize_user(reverted)
        if editor_key and editor_key == reverted_key:
            return True
        if reverted_key and editor_key != reverted_key:
            return False
    return _SELF_RV_RE.search(comment) is not None


def _clean_name(raw: str) -> str | None:
    text = display_user(raw).strip(" .,:;")
    if not text:
        return None
    return text
