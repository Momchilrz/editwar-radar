"""Turn revert comments into sentences a person can read."""

from __future__ import annotations

import re

from detect.names import display_user

_TALK = re.compile(
    r"\s*\(\[\[User(?: talk)?:[^\[\]|]+\|[^\[\]]*\]\]\)",
    re.IGNORECASE,
)
_TOOL = re.compile(
    r"\s*\(\[\[WP:(?:TW|HG|CSD|AWB|ROLLBACK)\s*\|[^\[\]]*\]\]\)(?:\s*\([^)]*\))?",
    re.IGNORECASE,
)
_DIFF = re.compile(r"\[\[Special:Diff/[^\[\]|]+\|[^\[\]]*\]\]", re.IGNORECASE)
_CONTRIB = re.compile(
    r"\[\[Special:Contributions/([^\[\]|]+)\|[^\[\]]*\]\]",
    re.IGNORECASE,
)
_PIPED = re.compile(r"\[\[([^\[\]|]+)\|([^\[\]]*)\]\]")
_BARE = re.compile(r"\[\[([^\[\]]+)\]\]")
_TEMPLATE = re.compile(r"\{\{[^{}]*\}\}")
_HTML = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"[ \t]+")
_SPACE_BEFORE_PUNCT = re.compile(r"\s+([,.;:)])")


def plain_comment(comment: str) -> str:
    """Drop wiki links, tool tags, and talk-page links. Keep the editor's note."""
    text = comment.replace("\u200e", "").replace("\u200f", "")
    text = _TALK.sub("", text)
    text = _TOOL.sub("", text)
    text = _DIFF.sub("", text)
    text = _CONTRIB.sub(lambda match: display_user(match.group(1)), text)
    text = _PIPED.sub(lambda match: _readable(match.group(2) or match.group(1)), text)
    text = _BARE.sub(lambda match: _readable(match.group(1)), text)
    text = _TEMPLATE.sub("", text)
    text = _HTML.sub("", text)
    text = text.replace("'''", "").replace("''", "")
    text = _SPACE.sub(" ", text)
    text = _SPACE_BEFORE_PUNCT.sub(r"\1", text)
    text = text.strip(" \n\t-–—")
    text = re.sub(r"\bUndid revision\s+by\b", "Undid an edit by", text, flags=re.IGNORECASE)
    text = re.sub(
        r"\bto last revision by\b", "back to the last version by", text, flags=re.IGNORECASE
    )
    text = re.sub(r"\bReverted 1 edit by\b", "Reverted an edit by", text, flags=re.IGNORECASE)
    text = re.sub(
        r"(Undid an edit by \S+(?: \S+)?)(\s+)(?=[A-Z])",
        r"\1. ",
        text,
        count=1,
    )
    text = re.sub(r"\s{2,}", " ", text).strip()
    if text and text[-1] not in ".!?":
        text += "."
    return text


def _readable(raw: str) -> str:
    text = raw.strip()
    if ":" in text:
        text = text.split(":")[-1]
    text = display_user(text)
    text = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", text)
    return text
