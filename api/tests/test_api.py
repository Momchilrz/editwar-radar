from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from config import Settings
from detect.engine import WarEngine
from detect.models import IncomingEdit
from fastapi.testclient import TestClient
from ingest.state import build_state

from api.main import create_app


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        wikis="en.wikipedia.org",
        database_url=f"sqlite:///{(tmp_path / 'api.db').as_posix()}",
        ua_contact="radar-tests@example.com",
        disable_ingest=True,
        backfill=False,
        trust_env=False,
    )


def _client(tmp_path: Path, engine: WarEngine | None = None) -> TestClient:
    state = build_state(_settings(tmp_path), engine=engine)
    return TestClient(create_app(state))


def test_wars_empty(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.get("/wars")
    assert response.status_code == 200
    body = response.json()
    assert body["wars"] == []
    assert body["total"] == 0
    assert body["stream_connected"] is False
    assert body["window_hours"] == 6


def test_wars_are_ranked_and_detail_shows_the_timeline(tmp_path: Path) -> None:
    now = datetime.now(UTC) - timedelta(minutes=5)
    engine = WarEngine(timedelta(hours=6))
    engine.observe(
        IncomingEdit(
            wiki="en.wikipedia.org",
            title="Some Page",
            user="Alice",
            comment="Reverted edits by Bob (talk) ([[WP:HG|HG]]) (3.4.12)",
            timestamp=now,
            event_id="a",
        ),
        now=now,
    )
    engine.observe(
        IncomingEdit(
            wiki="en.wikipedia.org",
            title="Some Page",
            user="Bob",
            comment="Reverted 1 edit by Alice ([[WP:TW|TW]])",
            timestamp=now + timedelta(minutes=1),
            event_id="b",
        ),
        now=now,
    )
    engine.observe(
        IncomingEdit(
            wiki="en.wikipedia.org",
            title="Quieter",
            user="Cara",
            comment="Reverted 1 edit by Dana ([[WP:TW|TW]])",
            timestamp=now,
            event_id="c",
        ),
        now=now,
    )
    engine.observe(
        IncomingEdit(
            wiki="en.wikipedia.org",
            title="Quieter",
            user="Cara",
            comment="Reverted 1 edit by Dana ([[WP:TW|TW]])",
            timestamp=now + timedelta(seconds=30),
            event_id="d",
        ),
        now=now,
    )
    with _client(tmp_path, engine) as client:
        listed = client.get("/wars?limit=1")
        assert listed.status_code == 200
        payload = listed.json()
        assert payload["total"] == 2
        assert len(payload["wars"]) == 1
        assert payload["wars"][0]["title"] == "Some Page"
        assert payload["wars"][0]["score"] == 16
        assert payload["wars"][0]["mutual_war"] is True
        detail = client.get("/wars/en.wikipedia.org/Some_Page")
        spaced = client.get("/wars/en.wikipedia.org/Some%20Page")
        missing = client.get("/wars/en.wikipedia.org/Missing")
        with client.stream("GET", "/stream") as stream:
            assert stream.status_code == 200
            assert "text/event-stream" in stream.headers["content-type"]
            chunk = ""
            for line in stream.iter_lines():
                chunk += line + "\n"
                if line.startswith("data:"):
                    break
    assert detail.status_code == 200
    assert spaced.status_code == 200
    body = detail.json()
    assert body["reverts"] == 2
    assert "Bob" in body["timeline"][0]["comment"] or "Alice" in body["timeline"][0]["comment"]
    assert len(body["timeline"]) == 2
    assert missing.status_code == 404
    assert "event: hello" in chunk
    assert "Some Page" in chunk
