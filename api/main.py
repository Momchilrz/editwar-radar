"""Edit-War Radar API and dashboard."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from config import get_settings, setup_logging
from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from ingest.consumer import close_active_stream, consume_loop
from ingest.history import fetch_history
from ingest.hub import format_sse
from ingest.runtime import score_loop, status_loop, views_loop
from ingest.state import AppState, build_state, initial_since, replay

from api.present import revision_out, war_detail, wars_response
from api.schemas import WarDetailOut, WarsResponse

log = logging.getLogger("editwar.api")
WEB = Path(__file__).resolve().parents[1] / "web"


def create_app(state: AppState | None = None) -> FastAPI:
    radar = state if state is not None else build_state(get_settings())
    app = FastAPI(title="Edit-War Radar", version="0.1.0", lifespan=lifespan)
    app.state.radar = radar

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(WEB / "index.html", headers={"Cache-Control": "no-cache"})

    @app.get("/assets/{name:path}")
    async def assets(name: str) -> FileResponse:
        return FileResponse(_asset_path(name), headers={"Cache-Control": "no-cache"})

    @app.get("/wars", response_model=WarsResponse)
    async def list_wars(
        request: Request,
        response: Response,
        limit: int = Query(default=25, ge=1, le=100),
        wiki: str | None = None,
    ) -> WarsResponse:
        response.headers["Cache-Control"] = "no-store"
        return wars_response(_radar(request), limit=limit, wiki=wiki)

    @app.get("/wars/{wiki}/{title:path}", response_model=WarDetailOut)
    async def read_war(
        wiki: str,
        title: str,
        request: Request,
        response: Response,
        deep: bool = False,
    ) -> WarDetailOut:
        response.headers["Cache-Control"] = "no-store"
        radar_state = _radar(request)
        detail = war_detail(radar_state, wiki, title)
        if detail is None:
            raise HTTPException(
                status_code=404, detail="no edits for this article in the current window"
            )
        if not deep or radar_state.http is None:
            return detail
        try:
            revisions = await fetch_history(radar_state.http, detail.wiki, detail.title)
        except Exception as exc:
            log.warning("history fetch failed for %s: %s", detail.title, exc)
            revisions = []
        return detail.model_copy(
            update={"recent_history": [revision_out(item) for item in revisions]}
        )

    @app.get("/stream")
    async def stream(request: Request) -> StreamingResponse:
        radar_state = _radar(request)
        queue = radar_state.hub.subscribe()

        async def generate() -> AsyncIterator[str]:
            try:
                opening = wars_response(radar_state, limit=50, wiki=None)
                yield format_sse("hello", opening.model_dump(mode="json"))
                while not await request.is_disconnected():
                    try:
                        message = await asyncio.wait_for(queue.get(), timeout=15)
                    except TimeoutError:
                        yield ": keepalive\n\n"
                        continue
                    yield message
            finally:
                radar_state.hub.unsubscribe(queue)

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    return app


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    radar: AppState = app.state.radar
    setup_logging(radar.settings.log_level)
    if radar.settings.placeholder_contact and not radar.settings.disable_ingest:
        log.warning("Set UA_CONTACT in .env to a real address before a long run")
    replay(radar)
    initial_since(radar)
    log.info(
        "radar window=%sh refresh=%ss wikis=%s",
        radar.settings.window_hours,
        radar.settings.refresh_seconds,
        ",".join(sorted(radar.settings.wiki_set)),
    )
    if radar.settings.disable_ingest:
        try:
            yield
        finally:
            await _shutdown(radar, None)
        return
    stop = asyncio.Event()
    tasks = [
        asyncio.create_task(consume_loop(radar, stop), name="ingest"),
        asyncio.create_task(score_loop(radar, stop), name="score"),
        asyncio.create_task(status_loop(radar, stop), name="status"),
        asyncio.create_task(views_loop(radar, stop), name="views"),
    ]
    try:
        yield
    finally:
        stop.set()
        close_active_stream()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await _shutdown(radar, stop)


async def _shutdown(radar: AppState, _stop: asyncio.Event | None) -> None:
    radar.store.close()
    if radar.http is not None:
        await radar.http.aclose()


def _radar(request: Request) -> AppState:
    radar = getattr(request.app.state, "radar", None)
    if not isinstance(radar, AppState):
        raise RuntimeError("radar is not initialized")
    return radar


def _asset_path(name: str) -> Path:
    root = WEB.resolve()
    target = (root / name).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        raise HTTPException(status_code=404, detail="not found")
    return target


app = create_app()


def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)
    uvicorn.run(app, host=settings.host, port=settings.port, log_level=settings.log_level.lower())


if __name__ == "__main__":
    main()
