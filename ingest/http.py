"""One-at-a-time HTTP client with exponential backoff."""

from __future__ import annotations

import asyncio
import time

import httpx


class PoliteClient:
    """Serialize outbound API calls. The long-lived SSE stream does not use this."""

    def __init__(
        self,
        user_agent: str,
        *,
        min_interval: float = 0.25,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._min_interval = min_interval
        self._last = 0.0
        self._lock = asyncio.Lock()
        self._client = httpx.AsyncClient(
            headers={"User-Agent": user_agent, "Accept": "application/json"},
            timeout=httpx.Timeout(30.0),
            follow_redirects=True,
            transport=transport,
        )

    async def get(self, url: str) -> httpx.Response:
        async with self._lock:
            delay = 1.0
            last_error: Exception | None = None
            for _attempt in range(6):
                await self._gap()
                try:
                    response = await self._client.get(url)
                except httpx.HTTPError as exc:
                    last_error = exc
                    await asyncio.sleep(delay)
                    delay = min(delay * 2.0, 60.0)
                    continue
                if response.status_code == 429 or response.status_code >= 500:
                    retry_after = response.headers.get("Retry-After", "")
                    sleep_for = delay
                    if retry_after.isdigit():
                        sleep_for = min(float(retry_after), 120.0)
                    last_error = httpx.HTTPStatusError(
                        f"HTTP {response.status_code} for {url}",
                        request=response.request,
                        response=response,
                    )
                    await asyncio.sleep(sleep_for)
                    delay = min(max(delay, 1.0) * 2.0, 60.0)
                    continue
                return response
            if last_error is None:
                raise RuntimeError(f"no response for {url}")
            raise last_error

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _gap(self) -> None:
        if self._min_interval <= 0:
            return
        now = time.monotonic()
        wait = self._min_interval - (now - self._last)
        if wait > 0:
            self._last = now + wait
            await asyncio.sleep(wait)
            return
        self._last = now
