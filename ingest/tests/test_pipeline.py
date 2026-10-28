from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from config import Settings
from detect.tests.fixtures import T0, make_edit
from jsonutil import is_object, loads_lenient, loads_lenient_flagged

from ingest.backoff import next_delay
from ingest.history import parse_history
from ingest.http import PoliteClient
from ingest.parse import parse_recentchange
from ingest.store import EventStore
from ingest.views import pageviews_url, parse_top_views


def _settings() -> Settings:
    return Settings(_env_file=None, wikis="en.wikipedia.org", ua_contact="radar-tests@example.com")


def _payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "type": "edit",
        "namespace": 0,
        "title": "Example",
        "comment": "fix typo",
        "user": "Alice",
        "bot": False,
        "minor": False,
        "server_name": "en.wikipedia.org",
        "timestamp": 1717243200,
        "meta": {
            "id": "event-1",
            "dt": "2026-06-01T12:00:00.000Z",
            "domain": "en.wikipedia.org",
        },
    }
    payload.update(overrides)
    return payload


def test_parse_keeps_english_article_edits_and_prefers_meta_dt() -> None:
    edit = parse_recentchange(_payload(timestamp=1), _settings())
    assert edit is not None
    assert edit.wiki == "en.wikipedia.org"
    assert edit.user == "Alice"
    assert edit.timestamp == datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    assert edit.event_id == "event-1"


def test_parse_skips_non_edits_other_wikis_and_namespaces() -> None:
    settings = _settings()
    assert parse_recentchange(_payload(type="log"), settings) is None
    assert parse_recentchange(_payload(type="new"), settings) is None
    assert parse_recentchange(_payload(server_name="de.wikipedia.org"), settings) is None
    assert parse_recentchange(_payload(namespace=1), settings) is None
    assert parse_recentchange(_payload(user=""), settings) is None


def test_parse_passes_bots_and_tags_through() -> None:
    edit = parse_recentchange(_payload(bot=True, tags=["mw-rollback"]), _settings())
    assert edit is not None
    assert edit.bot is True
    assert edit.tags == ("mw-rollback",)


def test_next_delay_doubles_until_the_cap() -> None:
    assert next_delay(0) == 1
    assert next_delay(1) == 2
    assert next_delay(32) == 60
    assert next_delay(60) == 60


def test_lenient_json_drops_a_truncated_tail() -> None:
    raw = '{"revisions":[{"id":1,"comment":"ok","user":{"name":"A"}},{"id":2,"comment":"trunc'
    value, repaired = loads_lenient_flagged(raw)
    assert repaired is True
    assert is_object(value)
    revisions = value["revisions"]
    assert isinstance(revisions, list)
    assert len(revisions) == 1
    parsed = parse_history(value)
    assert len(parsed) == 1
    assert parsed[0].comment == "ok"
    assert parsed[0].user == "A"


def test_lenient_json_leaves_complete_documents_alone() -> None:
    value, repaired = loads_lenient_flagged('{"ok": true}')
    assert repaired is False
    assert value == {"ok": True}


def test_unrecoverable_json_still_raises() -> None:
    try:
        loads_lenient("{")
    except json.JSONDecodeError:
        return
    raise AssertionError("expected JSONDecodeError")


def test_pageviews_parser_normalizes_titles() -> None:
    payload = {
        "items": [
            {
                "articles": [
                    {"article": "Main_Page", "views": 100, "rank": 1},
                    {"article": "Example", "views": 5, "rank": 2},
                ]
            }
        ]
    }
    parsed = parse_top_views("en.wikipedia", payload)
    assert parsed[("en.wikipedia", "Main Page")] == 100
    assert parsed[("en.wikipedia", "Example")] == 5
    assert pageviews_url("en.wikipedia", datetime(2026, 6, 1, tzinfo=UTC).date()).endswith(
        "/en.wikipedia/all-access/2026/06/01"
    )


def test_polite_client_retries_429() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        assert request.headers["User-Agent"].startswith("EditWarRadar/0.1")
        if calls["n"] < 3:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(200, json={"ok": True})

    client = PoliteClient(
        "EditWarRadar/0.1 (contact: test@example.com)",
        min_interval=0,
        transport=httpx.MockTransport(handler),
    )

    async def run() -> int:
        response = await client.get("https://example.test/metrics")
        await client.aclose()
        return response.status_code

    import asyncio

    assert asyncio.run(run()) == 200
    assert calls["n"] == 3


def test_store_roundtrip_and_duplicate_ignore(tmp_path: Path) -> None:
    store = EventStore(f"sqlite:///{(tmp_path / 'events.db').as_posix()}")
    edit = make_edit(
        comment="Reverted 1 edit by OtherUser ([[WP:TW|TW]])", event_id="evt-1", user="Alice"
    )
    store.enqueue(edit, is_revert=True, reverted_user="OtherUser")
    store.flush()
    store.enqueue(edit, is_revert=True, reverted_user="OtherUser")
    store.flush()
    loaded = store.load_recent(T0 - timedelta(minutes=1))
    assert len(loaded) == 1
    assert loaded[0].comment == edit.comment
    assert loaded[0].event_id == "evt-1"
    assert store.latest_ts() == T0
    store.close()
