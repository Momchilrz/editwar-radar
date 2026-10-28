"""Article links shared by the API and the live ignition events."""

from __future__ import annotations

import re
from urllib.parse import quote

_HOST = re.compile(r"[a-z0-9.-]+")


def article_url(wiki: str, title: str) -> str:
    host = wiki.strip().lower()
    if _HOST.fullmatch(host) is None or host.startswith(".") or host.endswith(".") or ".." in host:
        return ""
    slug = quote(title.replace(" ", "_"), safe="/")
    return f"https://{host}/wiki/{slug}"
