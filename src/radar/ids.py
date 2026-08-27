from __future__ import annotations

import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

TRACKING_KEYS = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "fbclid", "gclid"}


def canonicalize_url(url: str) -> str:
    parsed = urlparse(url.strip())
    scheme = parsed.scheme.lower() or "https"
    netloc = parsed.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    path = parsed.path.rstrip("/") or "/"
    query = [
        (k, v)
        for k, v in parse_qsl(parsed.query, keep_blank_values=True)
        if k.lower() not in TRACKING_KEYS
    ]
    query.sort()
    return urlunparse((scheme, netloc, path, "", urlencode(query), ""))


def allowed_url(url: str, hosts: list[str]) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return False
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    allowed = {h.lower().removeprefix("www.") for h in hosts}
    return host in allowed


def stable_id(prefix: str, key: str) -> str:
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:10]
    slug = re.sub(r"[^a-z0-9]+", "-", prefix.lower()).strip("-")
    return f"{slug}-{digest}"


def content_hash(payload: dict[str, object]) -> str:
    blob = "\n".join(f"{k}={payload.get(k, '')}" for k in (
        "title",
        "journal",
        "collection_type",
        "deadline",
        "deadline_status",
        "status",
        "summary",
    ))
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()
