"""Shareable board. Daily wars, a 4-hour block, and a tape that keeps what it has shown."""

from __future__ import annotations

import asyncio
import os
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import streamlit as st
from config import get_settings, setup_logging
from detect.engine import WarEngine
from detect.models import ArticleScore
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
        if state.status.last_error:
            detail = state.status.last_error
            return f"The Wikipedia stream is disconnected ({detail}). The lists stay up."
        return "The Wikipedia stream is disconnected. The lists stay up."
    if not state.caught_up:
        return "Reading recent edits. The lists fill in as that backlog arrives."
    return "Connected to the English Wikipedia edit stream."


def _article(war: ArticleScore, index: int) -> None:
    st.markdown(f"**{index}.** {war.title}")
    st.caption(_fight(war))
    with st.expander("Revert comments"):
        if not war.timeline:
            st.caption("No revert comments in this block.")
            return
        for item in reversed(war.timeline[-8:]):
            target = item.reverted_user or "an earlier edit"
            when = item.timestamp.astimezone(UTC).strftime("%H:%M UTC")
            st.markdown(f"**{when}** — {item.user} reverted {target}")
            if item.comment:
                st.text(item.comment)


def _section(title: str, note: str, wars: tuple[ArticleScore, ...]) -> None:
    st.subheader(title)
    st.caption(note)
    if not wars:
        st.markdown(
            "Nothing here yet. One or two reverts is ordinary cleanup, so it stays off this list."
        )
        return
    for index, war in enumerate(wars, start=1):
        _article(war, index)


def _tape(items: list[_TapeItem]) -> None:
    st.subheader("Signal tape")
    st.caption(
        "Once an article reaches 4 reverts in the 4-hour block, it stays here until midnight UTC."
    )
    if not items:
        st.markdown("The tape is empty. A line is added when a fight qualifies, and it stays.")
        return
    rows = []
    for item in items:
        seen = item.seen_at.astimezone(UTC).strftime("%H:%M")
        mutual = " Both sides." if item.mutual else ""
        editors = "1 editor" if item.editors == 1 else f"{item.editors} editors"
        rows.append(
            f"<div class='tape-item'><b>{seen} UTC</b> · {item.title}<br>"
            f"{item.reverts} reverts by {editors}.{mutual}</div>"
        )
    st.markdown("<div class='tape'>" + "".join(rows) + "</div>", unsafe_allow_html=True)


def _css() -> None:
    st.markdown(
        """
        <style>
        .stApp { background: #f8f9fa; }
        [data-testid="stAppViewContainer"] > .main { background: #ffffff; }
        h1, h2, h3 { font-family: Georgia, "Times New Roman", serif; font-weight: 400; }
        h1 { border-bottom: 1px solid #a2a9b1; padding-bottom: 0.25rem; }
        .tape {
          max-height: 70vh;
          overflow-y: auto;
          border-left: 1px solid #a2a9b1;
          padding-left: 0.8rem;
        }
        .tape-item { padding: 0.55rem 0; border-bottom: 1px solid #eaecf0; line-height: 1.35; }
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
        st.caption(_status_line(handle.state))
        main, side = st.columns([2.1, 1], gap="large")
        with main:
            _section(
                "Today",
                f"Since {_range_label(day_start, day_end)}. An article is listed only after "
                f"{DAILY_MIN_REVERTS} reverts. Mutual fights are listed first.",
                daily.wars,
            )
            _section(
                "Last four hours",
                f"{_range_label(block_start, block_end)}. This block steps forward once an hour "
                f"(at 20:00 it is 16:00–20:00; at 21:00 it is 17:00–21:00). "
                f"An article needs {FOUR_HOUR_MIN_REVERTS} reverts to be listed.",
                recent.wars,
            )
        with side:
            _tape(tape)
    except Exception as exc:
        st.error("The lists could not refresh. The edit stream is still running in the background.")
        st.caption(str(exc))


def main() -> None:
    _css()
    st.title("Edit-War Radar")
    st.markdown(
        "Articles on English Wikipedia where editors are reverting each other. "
        "A single revert is someone cleaning up vandalism. It is not listed. "
        "A fight is listed only when the reverts keep coming."
    )
    handle = radar()
    if handle.state.settings.placeholder_contact:
        st.caption("Set UA_CONTACT in the Streamlit secrets to a real email address.")
    live_board()


main()
