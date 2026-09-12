from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

import httpx

SNAPSHOT_HOSTS = frozenset(
    {
        "raw.githubusercontent.com",
        "gist.githubusercontent.com",
        "objects.githubusercontent.com",
    }
)
SNAPSHOT_MAX_BYTES = 15 * 1024 * 1024


class SnapshotError(ValueError):
    """Raised when a listing snapshot URL is refused or cannot be downloaded."""


def snapshot_url_allowed(url: str) -> bool:
    try:
        parsed = urlparse(url.strip())
        port = parsed.port
    except ValueError:
        return False
    if parsed.scheme != "https" or port not in (None, 443) or parsed.username or parsed.password:
        return False
    host = (parsed.hostname or "").lower()
    return host in SNAPSHOT_HOSTS


def _check_snapshot_request(request: httpx.Request) -> None:
    # Redirects must obey the same host restriction as the original URL.
    if not snapshot_url_allowed(str(request.url)):
        raise SnapshotError(f"listing snapshot host is not allowed: {request.url}")


def download_snapshot(url: str, dest: Path, *, timeout_seconds: float = 60.0) -> Path:
    if not snapshot_url_allowed(url):
        raise SnapshotError(f"listing snapshot host is not allowed: {url}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        with httpx.Client(
            follow_redirects=True,
            timeout=timeout_seconds,
            event_hooks={"request": [_check_snapshot_request]},
        ) as client:
            with client.stream("GET", url) as response:
                if response.status_code >= 400:
                    raise SnapshotError(f"listing snapshot HTTP {response.status_code}: {url}")
                chunks = []
                size = 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > SNAPSHOT_MAX_BYTES:
                        raise SnapshotError(f"listing snapshot exceeds {SNAPSHOT_MAX_BYTES} bytes")
                    chunks.append(chunk)
                dest.write_bytes(b"".join(chunks))
    except httpx.HTTPError as exc:
        raise SnapshotError(f"listing snapshot download failed: {url}: {exc}") from exc
    return dest
