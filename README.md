# Edit-War Radar

A live radar for Wikipedia edit wars. It watches the public Wikimedia edit stream, tells routine vandalism cleanup apart from a revert battle, and ranks the articles people are fighting over right now.

## Quickstart

From the repo root, with Python 3.12 or newer:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
copy .env.example .env
```

Set `UA_CONTACT` in `.env` to an email Wikimedia can use if a request misbehaves. Then:

```powershell
python -m api.main
```

Open http://127.0.0.1:8000/

If PowerShell blocks the activate script, call the venv interpreter directly:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m api.main
```

No API key is required. Everything uses Wikimedia's public endpoints.

## Share with friends

The Streamlit app is the page you send people. It runs the same detector and ingest.

```powershell
pip install -r requirements.txt
streamlit run streamlit_app.py
```

That opens a local board on port 8501. To put it on the internet for free:

1. This repo is on GitHub.
2. Sign in at https://share.streamlit.io with the same GitHub account.
3. Create an app. Repository: `Momchilrz/editwar-radar`. Branch: `master`. Main file: `streamlit_app.py`.
4. In the app secrets, set a real contact address:

```toml
UA_CONTACT = "you@email"
```

5. Deploy, then send friends the `*.streamlit.app` link.

The Cloud app sleeps when nobody has it open. The next visit reconnects to Wikipedia and rebuilds the 6 hour window, which can take a few minutes before the first war appears.

## What you should see

The page is a dark, single screen. The wordmark sits top left. Top right is a live/replay/down pulse, the edit rate, and when the board was last built.

The main column is the leaderboard. Each row has a rank, a score, a heat bar scaled to the current top score, the article title, revert and editor counts, a Mutual badge when both sides have reverted each other, the names involved, and how long ago the war started. Click a row and the right-hand panel fills with the revert timeline: who reverted whom, the raw comment, and a small score sparkline once a minute of samples exists.

The right column also keeps a **War ignited** feed. A line appears when an article crosses two reverts, and another when a one-sided cleanup turns into a mutual war.

If the Wikipedia stream drops, an amber banner says the board is serving the last window it has. If the browser loses the API stream, a red banner says the dashboard is disconnected and retrying.

## Phases

Run these from the repo root with the venv active.

### Phase 1 — detector

```powershell
python -m pytest detect/tests -q
```

Pure tests, no network. They cover a plain edit, Twinkle, Huggle, undo comments, revert tags, self-reverts, bot edits, mutual pairs, window expiry, and the score formula `3×reverts + 2×editors + 6` when any mutual pair exists.

### Phase 2 — live consumer

```powershell
python -m pytest ingest/tests -q
python -m ingest.consumer
```

The pytest suite includes a local SSE server that drops the connection and reconnects. The CLI connects to the real Wikimedia stream and logs wars to stdout. Stop it with Ctrl+C. It reconnects on its own, with backoff, and resumes with `?since=` set from the last event time.

### Phase 3 — API

```powershell
python -m pytest api/tests -q
python -m api.main
```

In another terminal:

```powershell
curl http://127.0.0.1:8000/wars
curl http://127.0.0.1:8000/wars/en.wikipedia.org/Some_Title
curl -N http://127.0.0.1:8000/stream
```

`GET /wars` takes `limit` (1–100, default 25) and `wiki` (`en.wikipedia.org`). `GET /wars/{wiki}/{title}` returns the revert timeline, participants, mutual pairs, and score history. Add `?deep=1` to also pull the article's recent history from the Wikimedia API; the leaderboard does not need that. `GET /stream` is server-sent events: `hello` on connect, `leaderboard` every refresh interval, `ignition` when a war starts, and `status` about every 10 seconds.

### Phase 4 — radar screen

Leave `python -m api.main` running and open http://127.0.0.1:8000/ . The board updates from `/stream`. Click a row for the timeline. On a phone the ignition feed and detail stack under the leaderboard.

## How it is put together

One Python process. Three asyncio tasks share an in-memory `WarEngine`:

1. **Consumer.** A thread reads `https://stream.wikimedia.org/v2/stream/recentchange` with `sseclient-py`, filters to `type == edit` and the configured `server_name` list, and hands edits to the detector.
2. **Scorer.** Every 60 seconds it recomputes the 6 hour window, writes the leaderboard to the `pages` table, appends `score_history`, and pushes the board to SSE clients.
3. **API.** FastAPI serves `/wars`, `/wars/{wiki}/{title}`, `/stream`, and the static page in `web/`.

SQLite (SQLAlchemy) stores `events`, `pages`, and `score_history`. Types are ordinary strings, integers, booleans, and timestamps so a later move to Postgres is a URL change plus a migration, not a rewrite. On startup the process replays events still inside the window, then resumes the stream from the last stored timestamp (or from `now - window` if the database is empty).

Noise filter, before scoring: bots, self-reverts (the editor matches the reverted user, or the comment is only `self-rv`), and optionally minor edits (`SKIP_MINOR=true`). An article needs at least two reverts in the window to make the leaderboard.

## Validation

Start the app against English Wikipedia and leave it for 30–60 minutes. The leaderboard should show at least one article with `reverts >= 2`, and its detail view should show real revert comments and timestamps from the live stream. If that does not happen, the detector is wrong.

## Limitations

- One process. Restarting replays SQLite and the stream gap; it does not keep a longer archive than the window, plus a few minutes of margin.
- Score history starts when this process is running. A restart keeps the points already written to SQLite.
- Pageview counts show up only when the article is on Wikimedia's daily top list (yesterday, then the day before). Most war articles will not be.
- `?deep=1` is optional and rate-limited. The timeline on the page comes from the stream, not from that call.
- The SSE resume parameter is `since`. EventStreams does not implement `since_date`.
- Large JSON bodies are parsed defensively: a truncated tail is dropped instead of failing the request.

## Not implemented

These are explicitly out of scope:

- Alert bots and newsletters
- Accounts or authentication
- A translated, multi-language interface (the ingest list is configurable, and `/wars?wiki=` filters one wiki)
- A historical backtesting UI
- Deployment pipelines
- The Postgres migration itself

## Checks

```powershell
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
python -m mypy
```
