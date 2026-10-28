"""Map detector state onto API models."""

from __future__ import annotations

from datetime import UTC, datetime

from detect.engine import WarEngine
from detect.models import ArticleScore, FeedNotice
from ingest.history import Revision
from ingest.links import article_url
from ingest.state import AppState
from ingest.views import project_name, title_key

from api.schemas import (
    IgnitionOut,
    MutualOut,
    PairOut,
    ParticipantOut,
    RevisionOut,
    ScorePointOut,
    StatusOut,
    TimelineOut,
    WarDetailOut,
    WarOut,
    WarsResponse,
)


def wars_response(
    state: AppState,
    *,
    limit: int,
    wiki: str | None,
    now: datetime | None = None,
) -> WarsResponse:
    current = now or datetime.now(UTC)
    board = state.engine.leaderboard(current, wiki=wiki, limit=limit)
    articles, _wars = state.engine.counts(current)
    return WarsResponse(
        generated_at=current,
        stream_connected=state.status.connected,
        caught_up=state.caught_up,
        last_event_at=state.status.last_event_at,
        last_error=state.status.last_error,
        reconnects=state.status.reconnects,
        ingested_edits=state.stats.counted_edits,
        reverts_seen=state.stats.reverts,
        edits_per_minute=state.rate.per_minute(),
        articles=articles,
        total=board.total,
        window_hours=state.settings.window_hours,
        refresh_seconds=state.settings.refresh_seconds,
        wikis=sorted(state.settings.wiki_set),
        wars=[war_out(state, score) for score in board.wars],
        ignitions=[ignition_out(notice) for notice in _notices(state, wiki)],
    )


def status_payload(state: AppState) -> dict[str, object]:
    current = datetime.now(UTC)
    articles, wars = state.engine.counts(current)
    payload = StatusOut(
        generated_at=current,
        stream_connected=state.status.connected,
        caught_up=state.caught_up,
        last_event_at=state.status.last_event_at,
        last_error=state.status.last_error,
        reconnects=state.status.reconnects,
        ingested_edits=state.stats.counted_edits,
        reverts_seen=state.stats.reverts,
        edits_per_minute=state.rate.per_minute(),
        articles=articles,
        total=wars,
    )
    return payload.model_dump(mode="json")


def war_detail(
    state: AppState, wiki: str, title: str, now: datetime | None = None
) -> WarDetailOut | None:
    current = now or datetime.now(UTC)
    score = find_article(state.engine, wiki, title, current)
    if score is None:
        return None
    summary = war_out(state, score)
    return WarDetailOut(
        **summary.model_dump(),
        participants=[
            ParticipantOut(
                name=person.name,
                reverts_made=person.reverts_made,
                times_reverted=person.times_reverted,
            )
            for person in score.participants
        ],
        directed_pairs=[
            PairOut(reverter=pair.reverter, reverted=pair.reverted, count=pair.count)
            for pair in score.directed_pairs
        ],
        mutual=[MutualOut(a=pair[0], b=pair[1]) for pair in score.mutual],
        timeline=[
            TimelineOut(
                timestamp=item.timestamp,
                user=item.user,
                reverted_user=item.reverted_user,
                comment=item.comment,
            )
            for item in reversed(score.timeline)
        ],
        score_history=[
            ScorePointOut(timestamp=point.timestamp, score=point.score, reverts=point.reverts)
            for point in state.engine.history(score.wiki, score.title)
        ],
    )


def revision_out(revision: Revision) -> RevisionOut:
    return RevisionOut(
        id=revision.rev_id,
        timestamp=revision.timestamp,
        minor=revision.minor,
        size=revision.size,
        comment=revision.comment,
        user=revision.user,
        delta=revision.delta,
    )


def war_out(state: AppState, score: ArticleScore) -> WarOut:
    return WarOut(
        wiki=score.wiki,
        title=score.title,
        score=score.score,
        edits=score.edits,
        reverts=score.reverts,
        distinct_reverters=score.distinct_reverters,
        mutual_pairs=score.mutual_pairs,
        mutual_war=score.mutual_war,
        reverters=list(score.reverters),
        war_started_at=score.war_started_at,
        last_revert_at=score.last_revert_at,
        views=state.views.get((project_name(score.wiki), title_key(score.title))),
        url=article_url(score.wiki, score.title),
    )


def ignition_out(notice: FeedNotice) -> IgnitionOut:
    return IgnitionOut(
        id=notice.id,
        kind=notice.kind,
        wiki=notice.wiki,
        title=notice.title,
        at=notice.at,
        score=notice.score,
        reverts=notice.reverts,
        mutual=notice.mutual,
        actors=list(notice.actors),
        url=article_url(notice.wiki, notice.title),
    )


def find_article(engine: WarEngine, wiki: str, title: str, now: datetime) -> ArticleScore | None:
    host = wiki.strip().lower()
    for candidate in _title_variants(title):
        found = engine.article(host, candidate, now)
        if found is not None:
            return found
    return None


def _notices(state: AppState, wiki: str | None) -> tuple[FeedNotice, ...]:
    notices = state.engine.feed()
    if not wiki:
        return notices
    host = wiki.strip().lower()
    return tuple(notice for notice in notices if notice.wiki.lower() == host)


def _title_variants(title: str) -> list[str]:
    stripped = title.strip()
    variants: list[str] = []
    for candidate in (stripped, stripped.replace("_", " "), stripped.replace(" ", "_")):
        if candidate and candidate not in variants:
            variants.append(candidate)
    return variants
