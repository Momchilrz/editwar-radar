"""Shareable board. Daily wars, a 4-hour block, and a tape that keeps what it has shown."""

from __future__ import annotations

import asyncio
import html
import os
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import streamlit as st
from config import get_settings, setup_logging
from detect.engine import WarEngine
from detect.models import ArticleScore, RevertEvent
from detect.plain import plain_comment
from detect.windows import (
    DAILY_MIN_REVERTS,
    FOUR_HOUR_MIN_REVERTS,
    clock_four_hours,
    utc_today,
)
from ingest.runtime import score_loop, status_loop, views_loop
from ingest.state import AppState, build_state, initial_since, replay

_RETAIN = timedelta(hours=26)

st.set_page_config(page_title="Edit-War Radar", layout="wide")


def _export_secrets() -> None:
    try:
        secrets = dict(st.secrets)
    except Exception:
        return
    for key, value in secrets.items():
        if isinstance(value, (str, int, float, bool)):
            os.environ.setdefault(str(key), str(value))


def _ingest(state: AppState) -> None:
    setup_logging(state.settings.log_level)
    replay(state)
    initial_since(state)
    if state.settings.disable_ingest:
        return

    async def _run() -> None:
        from ingest.consumer import consume_loop

        stop = asyncio.Event()
        await asyncio.gather(
            consume_loop(state, stop),
            score_loop(state, stop),
            status_loop(state, stop),
            views_loop(state, stop),
        )

    asyncio.run(_run())


@dataclass
class _TapeItem:
    day: str
    wiki: str
    title: str
    seen_at: datetime
    reverts: int
    editors: int
    mutual: bool


class _Handle:
    def __init__(self, state: AppState) -> None:
        self.state = state
        self.tape: list[_TapeItem] = []
        self._lock = threading.Lock()

    def note(
        self, wars: tuple[ArticleScore, ...] | list[ArticleScore], now: datetime
    ) -> list[_TapeItem]:
        day = now.astimezone(UTC).date().isoformat()
        with self._lock:
            self.tape = [item for item in self.tape if item.day == day]
            known = {(item.wiki, item.title): item for item in self.tape}
            for war in wars:
                current = known.get((war.wiki, war.title))
                if current is not None:
                    current.reverts = war.reverts
                    current.editors = war.distinct_reverters
                    current.mutual = war.mutual_war
                    continue
                item = _TapeItem(
                    day=day,
                    wiki=war.wiki,
                    title=war.title,
                    seen_at=now,
                    reverts=war.reverts,
                    editors=war.distinct_reverters,
                    mutual=war.mutual_war,
                )
                self.tape.insert(0, item)
                known[(war.wiki, war.title)] = item
            return list(self.tape)


@st.cache_resource
def radar() -> _Handle:
    _export_secrets()
    get_settings.cache_clear()
    settings = get_settings()
    engine = WarEngine(
        _RETAIN,
        min_reverts=FOUR_HOUR_MIN_REVERTS,
        skip_minor=settings.skip_minor,
    )
    state = build_state(settings, engine=engine)
    threading.Thread(target=_ingest, args=(state,), name="editwar-streamlit", daemon=True).start()
    return _Handle(state)


def _clock(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%H:%M")


def _range_label(start: datetime, end: datetime) -> str:
    return f"{_clock(start)}–{_clock(end)} UTC"


def _fight(war: ArticleScore) -> str:
    editors = "1 editor" if war.distinct_reverters == 1 else f"{war.distinct_reverters} editors"
    line = f"{war.reverts} reverts by {editors}"
    if war.mutual_war:
        return f"{line}. Both sides have reverted each other."
    return f"{line}. Only one side is reverting so far."


def _status_line(state: AppState) -> str:
    if not state.status.connected:
        return "Wikipedia stream paused. These lists are unchanged."
    if not state.caught_up:
        return "Still reading today's edits."
    return ""


def _safe(text: str) -> str:
    return html.escape(text, quote=True)


def _note_text(item: RevertEvent) -> str:
    cleaned = plain_comment(item.comment)
    lead = f"{item.user} reverted {item.reverted_user}" if item.reverted_user else item.user
    if not cleaned:
        return lead + "."
    if lead.casefold() in cleaned.casefold():
        return cleaned
    return cleaned


def _article(war: ArticleScore, index: int) -> None:
    title = _safe(war.title)
    st.markdown(
        f"<p class='fight-title'>{index}. {title}</p>"
        f"<p class='fight-meta'>{_safe(_fight(war))}</p>",
        unsafe_allow_html=True,
    )
    notes = list(reversed(war.timeline[-6:]))
    if not notes:
        return
    newest = notes[0]
    when = newest.timestamp.astimezone(UTC).strftime("%H:%M")
    st.markdown(
        f"<p class='note'><span class='when'>{when}</span> {_safe(_note_text(newest))}</p>",
        unsafe_allow_html=True,
    )
    older = notes[1:]
    if not older:
        return
    label = "1 earlier edit" if len(older) == 1 else f"{len(older)} earlier edits"
    with st.expander(label):
        for item in older:
            stamp = item.timestamp.astimezone(UTC).strftime("%H:%M")
            st.markdown(
                f"<p class='note'><span class='when'>{stamp}</span> {_safe(_note_text(item))}</p>",
                unsafe_allow_html=True,
            )


def _section(title: str, note: str, wars: tuple[ArticleScore, ...], empty: str) -> None:
    st.markdown(f"<p class='col-title'>{_safe(title)}</p>", unsafe_allow_html=True)
    st.markdown(f"<p class='col-note'>{_safe(note)}</p>", unsafe_allow_html=True)
    if not wars:
        st.markdown(f"<p class='empty'>{_safe(empty)}</p>", unsafe_allow_html=True)
        return
    for index, war in enumerate(wars, start=1):
        _article(war, index)


def _record_row(item: _TapeItem) -> str:
    seen = item.seen_at.astimezone(UTC).strftime("%H:%M")
    sides = " Both sides." if item.mutual else ""
    editors = "1 editor" if item.editors == 1 else f"{item.editors} editors"
    body = f"{item.reverts} reverts by {editors}.{sides}"
    return (
        "<div class='record-item'>"
        f"<span class='when'>{seen}</span> "
        f"<b>{_safe(item.title)}</b>"
        f"<div class='fight-meta'>{_safe(body)}</div>"
        "</div>"
    )


def _record(items: list[_TapeItem]) -> None:
    st.markdown("<p class='col-title'>On the record</p>", unsafe_allow_html=True)
    st.markdown(
        "<p class='col-note'>Fights that reached 4 reverts. They stay until midnight UTC.</p>",
        unsafe_allow_html=True,
    )
    if not items:
        st.markdown(
            "<p class='empty'>Nothing filed yet. A line is added when a fight qualifies.</p>",
            unsafe_allow_html=True,
        )
        return
    rows = "".join(_record_row(item) for item in items)
    seconds = max(48, len(items) * 8)
    st.markdown(
        f"<div class='ticker-window'><div class='ticker-track' style='--crawl:{seconds}s'>"
        f"{rows}{rows}</div></div>",
        unsafe_allow_html=True,
    )


def _css() -> None:
    st.markdown(
        """
        <style>
        header[data-testid="stHeader"], footer, #MainMenu { display: none; }
        .stApp { background: #f3f4f6; }
        [data-testid="stMainBlockContainer"] {
          max-width: 100%;
          padding: 0.85rem 1.1rem 2rem;
        }
        [data-testid="stHeading"] h1 {
          font-family: Georgia, "Times New Roman", serif;
          font-weight: 400;
          font-size: 1.7rem;
          margin: 0;
          padding: 0;
          line-height: 1.15;
        }
        .lede {
          margin: 0.15rem 0 0.55rem;
          color: #202122;
          font-size: 0.95rem;
          line-height: 1.35;
        }
        [data-testid="stHorizontalBlock"] { gap: 0.7rem; }
        [data-testid="stColumn"] {
          background: #ffffff;
          border: 1px solid #a2a9b1;
          padding: 0.7rem 0.85rem 0.8rem;
          max-height: calc(100vh - 7.5rem);
          overflow-y: auto;
        }
        [data-testid="stColumn"]:nth-child(3) { overflow: hidden; }
        .col-title {
          font-family: Georgia, "Times New Roman", serif;
          font-size: 1.25rem;
          margin: 0;
          line-height: 1.2;
        }
        .col-note {
          color: #54595d;
          font-size: 0.82rem;
          line-height: 1.3;
          margin: 0.15rem 0 0.35rem;
          min-height: 2.1rem;
        }
        .ticker-window {
          height: calc(100vh - 14rem);
          overflow: hidden;
          position: relative;
        }
        .ticker-track { animation: crawl var(--crawl, 70s) linear infinite; }
        .ticker-window:hover .ticker-track { animation-play-state: paused; }
        .ticker-window::before, .ticker-window::after {
          content: "";
          position: absolute;
          left: 0;
          right: 0;
          height: 1.4rem;
          z-index: 1;
          pointer-events: none;
        }
        .ticker-window::before {
          top: 0;
          background: linear-gradient(#ffffff, transparent);
        }
        .ticker-window::after {
          bottom: 0;
          background: linear-gradient(transparent, #ffffff);
        }
        @keyframes crawl {
          from { transform: translateY(0); }
          to { transform: translateY(-50%); }
        }
        @media (prefers-reduced-motion: reduce) {
          .ticker-track { animation: none; }
        }
        .fight-title {
          font-family: Georgia, "Times New Roman", serif;
          font-size: 1.05rem;
          margin: 0.85rem 0 0.1rem;
        }
        .fight-meta, .empty { color: #202122; font-size: 0.88rem; margin: 0 0 0.2rem; }
        .note { margin: 0.15rem 0 0.45rem; font-size: 0.9rem; line-height: 1.4; }
        .when { color: #54595d; font-variant-numeric: tabular-nums; }
        .record-item {
          padding: 0.45rem 0;
          border-bottom: 1px solid #eaecf0;
          line-height: 1.35;
        }
        [data-testid="stExpander"] { margin-bottom: 0.2rem; }
        </style>
        """,
        unsafe_allow_html=True,
    )


@st.fragment(run_every=timedelta(seconds=60))
def live_board() -> None:
    try:
        handle = radar()
        now = datetime.now(UTC)
        day_start, day_end = utc_today(now)
        block_start, block_end = clock_four_hours(now)
        daily = handle.state.engine.board(
            day_start, day_end, min_reverts=DAILY_MIN_REVERTS, limit=20
        )
        recent = handle.state.engine.board(
            block_start, block_end, min_reverts=FOUR_HOUR_MIN_REVERTS, limit=20
        )
        tape = handle.note(recent.wars, now)
        notice = _status_line(handle.state)
        if notice:
            st.caption(notice)
        today, recent_col, record = st.columns(3, gap="small")
        with today:
            _section(
                "Today",
                f"Since midnight UTC. Listed after {DAILY_MIN_REVERTS} reverts.",
                daily.wars,
                "No article has been fought over enough times today.",
            )
        with recent_col:
            _section(
                "Last four hours",
                f"{_range_label(block_start, block_end)}. Moves forward on the hour. "
                f"{FOUR_HOUR_MIN_REVERTS} reverts to be listed.",
                recent.wars,
                "No fight has reached 4 reverts in this block.",
            )
        with record:
            _record(tape)
    except Exception as exc:
        st.error("The lists could not refresh. The edit stream is still running in the background.")
        st.caption(str(exc))


def main() -> None:
    _css()
    st.markdown("# Edit-War Radar")
    st.markdown(
        "<p class='lede'>English Wikipedia articles editors keep reverting. "
        "One revert is cleanup. It is not listed.</p>",
        unsafe_allow_html=True,
    )
    radar()
    live_board()


main()
