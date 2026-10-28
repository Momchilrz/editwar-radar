from __future__ import annotations

import asyncio
import json
import threading
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from config import Settings

from ingest.consumer import consume_loop, stream_endpoint
from ingest.state import build_state


def test_stream_endpoint_adds_since() -> None:
    assert (
        stream_endpoint("https://stream.example/recentchange", None)
        == "https://stream.example/recentchange"
    )
    url = stream_endpoint("https://stream.example/recentchange", "2026-06-01T00:00:00.000Z")
    assert url.endswith("?since=2026-06-01T00%3A00%3A00.000Z")


def test_consumer_reconnects_and_detects_a_mutual_war(tmp_path: Path) -> None:
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    first = [
        {"type": "log", "server_name": "en.wikipedia.org", "meta": {"id": "log-1", "dt": now}},
        {
            "type": "edit",
            "namespace": 0,
            "title": "Live Article",
            "user": "Someone",
            "bot": False,
            "comment": "fix",
            "server_name": "de.wikipedia.org",
            "meta": {"id": "de-1", "dt": now},
        },
        {
            "type": "edit",
            "namespace": 0,
            "title": "Live Article",
            "user": "ClueBot",
            "bot": True,
            "comment": "Reverted 1 edit by Vandal ([[WP:TW|TW]])",
            "server_name": "en.wikipedia.org",
            "meta": {"id": "bot-1", "dt": now},
        },
        {
            "type": "edit",
            "namespace": 0,
            "title": "Live Article",
            "user": "Alice",
            "bot": False,
            "comment": "Reverted edits by Bob (talk) ([[WP:HG|HG]]) (3.4.12)",
            "server_name": "en.wikipedia.org",
            "meta": {"id": "alice-1", "dt": now},
        },
    ]
    second = [
        {
            "type": "edit",
            "namespace": 0,
            "title": "Live Article",
            "user": "Bob",
            "bot": False,
            "comment": "Reverted 1 edit by Alice ([[WP:TW|TW]])",
            "server_name": "en.wikipedia.org",
            "meta": {"id": "bob-1", "dt": now},
        }
    ]
    server = _SSEServer([first, second])
    thread = threading.Thread(
        target=server.httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
    )
    thread.start()
    settings = Settings(
        _env_file=None,
        wikis="en.wikipedia.org",
        database_url=f"sqlite:///{(tmp_path / 'live.db').as_posix()}",
        ua_contact="radar-tests@example.com",
        disable_ingest=True,
        backfill=False,
        trust_env=False,
        stream_url=server.url,
        stream_connect_timeout=3,
        stream_read_timeout=5,
    )
    state = build_state(settings)
    stop = asyncio.Event()

    async def scenario() -> None:
        task = asyncio.create_task(consume_loop(state, stop))
        try:
            for _ in range(80):
                board = state.engine.leaderboard(datetime.now(UTC))
                if board.total:
                    break
                await asyncio.sleep(0.15)
            else:
                raise AssertionError(
                    "no war "
                    f"reconnects={state.status.reconnects} "
                    f"error={state.status.last_error} "
                    f"connections={server.connections}"
                )
        finally:
            stop.set()
            await asyncio.wait_for(task, timeout=5)

    try:
        asyncio.run(scenario())
    finally:
        server.httpd.shutdown()
        server.httpd.server_close()
        state.store.close()
    board = state.engine.leaderboard(datetime.now(UTC))
    assert server.connections >= 2
    assert board.total == 1
    assert board.wars[0].mutual_war is True
    assert board.wars[0].score == 16
    assert board.wars[0].title == "Live Article"


class _SSEServer:
    def __init__(self, batches: list[list[dict[str, object]]]) -> None:
        self.batches = batches
        self.connections = 0
        handler = self._handler_type()
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}/stream"

    def _handler_type(self) -> type[BaseHTTPRequestHandler]:
        server = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                index = server.connections
                server.connections += 1
                batch = server.batches[min(index, len(server.batches) - 1)]
                body = b"".join(b"data: " + json.dumps(item).encode() + b"\n\n" for item in batch)
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: object) -> None:
                return

        return Handler
