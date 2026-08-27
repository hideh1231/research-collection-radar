from __future__ import annotations

import time
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any, Callable

import httpx

DEFAULT_RETRIES = 3


class FetchError(httpx.HTTPError):
    """A network error raised after the request retry budget is exhausted."""

    def __init__(self, url: str, cause: Exception) -> None:
        super().__init__(f"GET failed after retries: {url}: {cause}")
        self.url = url
        self.cause = cause


class Fetcher:
    def __init__(
        self,
        user_agent: str,
        timeout_seconds: float,
        retries: int = DEFAULT_RETRIES,
        min_interval_seconds: float = 0.0,
    ) -> None:
        self.user_agent = user_agent
        self.timeout_seconds = timeout_seconds
        self.retries = max(1, int(retries))
        self.min_interval_seconds = max(0.0, float(min_interval_seconds))
        self._last_request_started: float | None = None
        self._client = httpx.Client(
            headers={"User-Agent": user_agent, "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8"},
            timeout=timeout_seconds,
            follow_redirects=True,
        )

    def close(self) -> None:
        self._client.close()

    def _wait_for_interval(self) -> None:
        if self._last_request_started is None:
            return
        wait = self.min_interval_seconds - (time.monotonic() - self._last_request_started)
        if wait > 0:
            time.sleep(wait)

    @staticmethod
    def retry_after(response: httpx.Response, attempt: int) -> float:
        """Return a bounded Retry-After delay, with the specified fallback."""
        value = response.headers.get("Retry-After")
        if value:
            try:
                return min(120.0, max(0.0, float(value)))
            except ValueError:
                try:
                    target = parsedate_to_datetime(value)
                    if target.tzinfo is None:
                        target = target.replace(tzinfo=UTC)
                    return min(120.0, max(0.0, (target - datetime.now(UTC)).total_seconds()))
                except (TypeError, ValueError, OverflowError):
                    pass
        return (5.0, 15.0)[attempt] if attempt < 2 else 15.0

    @staticmethod
    def retry_delay(attempt: int) -> float:
        return 1.5 * (attempt + 1)

    def get(
        self,
        url: str,
        *,
        validator: Callable[[str], bool] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        last_error: Exception | None = None
        for attempt in range(self.retries):
            try:
                self._wait_for_interval()
                self._last_request_started = time.monotonic()
                response = self._client.get(url, headers=headers)
                if response.status_code == 403:
                    return response
                if response.status_code == 429 and attempt + 1 < self.retries:
                    time.sleep(self.retry_after(response, attempt))
                    continue
                if 500 <= response.status_code <= 599 and attempt + 1 < self.retries:
                    time.sleep(self.retry_delay(attempt))
                    continue
                if validator is not None and response.status_code < 400:
                    try:
                        valid = validator(response.text)
                    except Exception:
                        valid = False
                    if not valid and attempt + 1 < self.retries:
                        time.sleep(self.retry_delay(attempt))
                        continue
                return response
            except Exception as exc:
                last_error = exc
                if attempt + 1 < self.retries:
                    time.sleep(self.retry_delay(attempt))
        raise FetchError(url, last_error or RuntimeError(f"GET failed: {url}"))

    def get_html(
        self,
        url: str,
        *,
        validator: Callable[[str], bool] | None = None,
    ) -> tuple[int, str]:
        response = self.get(url, validator=validator)
        return response.status_code, response.text

    def get_json(self, url: str) -> tuple[int, Any, dict[str, str]]:
        response = self.get(url, headers={"Accept": "application/json"})
        headers = {key.lower(): value for key, value in response.headers.items()}
        if response.status_code >= 400:
            return response.status_code, None, headers
        try:
            return response.status_code, response.json(), headers
        except ValueError:
            return response.status_code, None, headers
