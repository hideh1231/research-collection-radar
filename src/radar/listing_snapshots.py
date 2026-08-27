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
    parsed = urlparse(url.strip())
    if parsed.scheme != "https":
        return False
    host = (parsed.hostname or "").lower()
    return host in SNAPSHOT_HOSTS


def download_snapshot(url: str, dest: Path, *, timeout_seconds: float = 60.0) -> Path:
    if not snapshot_url_allowed(url):
        raise SnapshotError(f"listing snapshot host is not allowed: {url}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    with httpx.Client(follow_redirects=True, timeout=timeout_seconds) as client:
        response = client.get(url)
        if response.status_code >= 400:
            raise SnapshotError(f"listing snapshot HTTP {response.status_code}: {url}")
        if len(response.content) > SNAPSHOT_MAX_BYTES:
            raise SnapshotError(f"listing snapshot exceeds {SNAPSHOT_MAX_BYTES} bytes")
        dest.write_bytes(response.content)
    return dest
