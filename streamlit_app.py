"""Shareable Streamlit board. One process ingests Wikipedia and renders the wars."""

from __future__ import annotations

import asyncio
import os
import threading
from datetime import UTC, datetime, timedelta

import streamlit as st
from api.present import war_detail, wars_response
from api.schemas import WarDetailOut, WarsResponse
from config import get_settings, setup_logging
from ingest.runtime import score_loop, status_loop, views_loop
from ingest.state import AppState, build_state, initial_since, replay

st.set_page_config(
    page_title="Edit-War Radar",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="expanded",
)


def _export_secrets() -> None:
    """Streamlit Cloud secrets become env vars before settings are read."""
    try:
        secrets = st.secrets
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


@st.cache_resource
def radar() -> AppState:
    _export_secrets()
    get_settings.cache_clear()
    state = build_state(get_settings())
    threading.Thread(target=_ingest, args=(state,), name="editwar-streamlit", daemon=True).start()
    return state


def _ago(moment: datetime | None) -> str:
    if moment is None:
        return ""
    current = moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)
    seconds = int((datetime.now(UTC) - current.astimezone(UTC)).total_seconds())
    if seconds < 60:
        return "just now"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours, rem = divmod(minutes, 60)
    if hours < 36:
        return f"{hours}h {rem}m ago" if rem else f"{hours}h ago"
    return f"{hours // 24}d ago"


def _status(board: WarsResponse) -> None:
    if not board.stream_connected:
        message = "Wikipedia stream disconnected. Showing the last window we have."
        if board.last_error:
            message = f"{message} ({board.last_error})"
        st.warning(message)
        return
    if not board.caught_up:
        st.info("Replaying recent edits into the 6 hour window.")
        return
    st.success(
        f"Live · {board.edits_per_minute} edits/min · {board.reverts_seen} reverts kept · "
        f"{board.total} wars"
    )


def _detail(state: AppState, wiki: str, title: str) -> None:
    detail: WarDetailOut | None = war_detail(state, wiki, title)
    if detail is None:
        st.caption("That article has fallen out of the window.")
        return
    st.subheader(detail.title)
    bits = [
        f"score {detail.score}",
        f"{detail.reverts} reverts",
        f"{detail.distinct_reverters} editors",
    ]
    if detail.mutual_war:
        bits.append("mutual")
    st.caption(" · ".join(bits))
    if detail.url:
        st.link_button("Open on Wikipedia", detail.url)
    if detail.mutual:
        st.write(" · ".join(f"{pair.a} ⇄ {pair.b}" for pair in detail.mutual))
    for person in detail.participants:
        st.caption(f"{person.name} · {person.reverts_made} sent / {person.times_reverted} received")
    for item in detail.timeline:
        who = item.reverted_user or "an unnamed edit"
        st.markdown(f"**{_ago(item.timestamp)}** {item.user} reverted {who}")
        if item.comment:
            st.text(item.comment)


@st.fragment(run_every=timedelta(seconds=15))
def live_board() -> None:
    state = radar()
    board = wars_response(state, limit=25, wiki=None)
    _status(board)
    left, right = st.columns([1.4, 1], gap="large")
    with left:
        st.header("On the radar")
        if not board.wars:
            st.caption(
                "Listening. English Wikipedia usually puts at least one article "
                "over two reverts within an hour."
            )
        else:
            top = max(war.score for war in board.wars)
            for index, war in enumerate(board.wars, start=1):
                label = f"{index:02d}   {war.score}   {war.title}"
                if st.button(label, key=f"war-{war.wiki}-{war.title}", use_container_width=True):
                    st.session_state["selected"] = (war.wiki, war.title)
                meta = (
                    f"{war.reverts} reverts · {war.distinct_reverters} editors · "
                    f"{_ago(war.war_started_at)}"
                )
                if war.mutual_war:
                    meta = f"{meta} · mutual"
                if war.reverters:
                    meta = f"{meta} · {', '.join(war.reverters[:4])}"
                st.caption(meta)
                st.progress(war.score / top)
    with right:
        st.header("War ignited")
        if not board.ignitions:
            st.caption("No ignition yet. An article joins this list at the second revert.")
        for notice in board.ignitions[:12]:
            kind = "Mutual" if notice.kind == "mutual" else "War ignited"
            if st.button(
                f"{kind} · {notice.title}",
                key=f"feed-{notice.id}",
                use_container_width=True,
            ):
                st.session_state["selected"] = (notice.wiki, notice.title)
            st.caption(f"{_ago(notice.at)} · {notice.reverts} reverts")
        selected = st.session_state.get("selected")
        if isinstance(selected, tuple) and len(selected) == 2:
            st.divider()
            _detail(state, str(selected[0]), str(selected[1]))


def main() -> None:
    st.title("Edit-War Radar")
    st.caption("Revert battles on English Wikipedia, before they harden into news.")
    state = radar()
    if state.settings.placeholder_contact:
        st.sidebar.warning("Set UA_CONTACT in Streamlit secrets to a real email address.")
    st.sidebar.caption(
        "Score = 3×reverts + 2×editors + 6 if both sides revert each other. "
        "Two reverts inside 6 hours is a war."
    )
    live_board()


main()
