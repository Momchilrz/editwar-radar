"""Daily top pageviews, used only as optional context on the leaderboard."""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from urllib.parse import unquote

from jsonutil import is_object, loads_lenient_flagged

from ingest.http import PoliteClient
from ingest.state import AppState

log = logging.getLogger("editwar.views")


def project_name(wiki: str) -> str:
    host = wiki.lower().strip()
    if host.endswith(".org"):
        return host[: -len(".org")]
    return host


def title_key(title: str) -> str:
    return " ".join(unquote(title).replace("_", " ").split())


def pageviews_url(project: str, day: date) -> str:
    stamp = day.strftime("%Y/%m/%d")
    return f"https://wikimedia.org/api/rest_v1/metrics/pageviews/top/{project}/all-access/{stamp}"


def parse_top_views(project: str, payload: object) -> dict[tuple[str, str], int]:
    if not is_object(payload):
        return {}
    items = payload.get("items")
    if not isinstance(items, list):
        return {}
    counts: dict[tuple[str, str], int] = {}
    for item in items:
        if not is_object(item):
            continue
        articles = item.get("articles")
        if not isinstance(articles, list):
            continue
        for article in articles:
            if not is_object(article):
                continue
            name = article.get("article")
            views = article.get("views")
            if not isinstance(name, str) or isinstance(views, bool) or not isinstance(views, int):
                continue
            counts[(project, title_key(name))] = views
    return counts


async def refresh_pageviews(state: AppState) -> None:
    client = state.http
    if client is None:
        return
    counts: dict[tuple[str, str], int] = {}
    errors: list[str] = []
    for wiki in sorted(state.settings.wiki_set):
        project = project_name(wiki)
        try:
            found = await _fetch_project(client, project)
        except Exception as exc:
            log.warning("pageviews failed for %s: %s", project, exc)
            errors.append(f"{project}: {exc}")
            continue
        counts.update(found)
    if counts:
        state.views = counts
        state.views_at = datetime.now(UTC)
    state.views_error = "; ".join(errors) if errors else None


async def _fetch_project(client: PoliteClient, project: str) -> dict[tuple[str, str], int]:
    today = datetime.now(UTC).date()
    for delta in (1, 2):
        response = await client.get(pageviews_url(project, today - timedelta(days=delta)))
        if response.status_code == 404:
            continue
        response.raise_for_status()
        payload, repaired = loads_lenient_flagged(response.content)
        if repaired:
            log.warning(
                "pageviews response for %s was truncated; dropped the incomplete tail", project
            )
        return parse_top_views(project, payload)
    return {}
