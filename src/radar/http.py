from __future__ import annotations

import time
from typing import Any

import httpx

DEFAULT_RETRIES = 3


class Fetcher:
    def __init__(self, user_agent: str, timeout_seconds: float, retries: int = DEFAULT_RETRIES) -> None:
        self.user_agent = user_agent
        self.timeout_seconds = timeout_seconds
        self.retries = retries
        self._client = httpx.Client(
            headers={"User-Agent": user_agent, "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8"},
            timeout=timeout_seconds,
            follow_redirects=True,
        )

    def close(self) -> None:
        self._client.close()

    def get(self, url: str) -> httpx.Response:
        last_error: Exception | None = None
        for attempt in range(self.retries):
            try:
                response = self._client.get(url)
                return response
            except httpx.HTTPError as exc:
                last_error = exc
                time.sleep(1.5 * (attempt + 1))
        raise last_error or RuntimeError(f"GET failed: {url}")

    def get_html(self, url: str) -> tuple[int, str]:
        response = self.get(url)
        return response.status_code, response.text
