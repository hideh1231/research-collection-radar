from __future__ import annotations

from datetime import UTC, datetime, date
import re

from dateutil import parser as date_parser

from radar.ids import canonicalize_url, content_hash, stable_id
from radar.models import RawRecord


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    text = re.sub(r"\s+", " ", value).strip()
    text = re.sub(r"^(deadline|submission deadline|manuscript submission deadline)\s*:?\s*", "", text, flags=re.I)
    if not text:
        return None
    try:
        return date_parser.parse(text, fuzzy=True, default=datetime(2099, 1, 1)).date()
    except (ValueError, OverflowError, TypeError):
        return None


def normalize_status(value: str | None) -> str:
    if not value:
        return "unknown"
    text = value.strip().lower()
    if "open" in text or "accepting" in text or "ready to submit" in text:
        return "open"
    if "closed" in text or "completed" in text:
        return "closed"
    return "unknown"


def normalize_title(title: str) -> str:
    return re.sub(r"\s+", " ", title).strip()


def to_record(
    raw: RawRecord,
    *,
    today: date,
    domains: list[str],
    domain_scores: dict[str, float],
    topics: list[str],
    classification_method: str,
    prior: dict[str, dict] | None = None,
) -> dict:
    url = canonicalize_url(raw.url)
    record_id = raw.extra.get("id") or stable_id(raw.discovered_via, url)
    deadline = raw.deadline.isoformat() if raw.deadline else None
    status = normalize_status(raw.status)
    payload = {
        "id": record_id,
        "title": normalize_title(raw.title),
        "journal": raw.journal,
        "publisher": raw.publisher,
        "venue_type": raw.venue_type,
        "collection_type": raw.collection_type,
        "url": url,
        "source_url": canonicalize_url(raw.source_url),
        "source_section": raw.source_section,
        "deadline": deadline,
        "status": status,
        "summary": raw.summary,
        "domains": domains,
        "domain_scores": domain_scores,
        "topics": topics,
        "classification_method": classification_method,
        "extraction_method": raw.extraction_method,
        "discovered_via": raw.discovered_via,
        "submission_mode": raw.submission_mode,
    }
    payload["content_hash"] = content_hash(payload)
    previous = (prior or {}).get(record_id)
    if previous:
        payload["first_seen"] = previous["first_seen"]
        if previous.get("content_hash") == payload["content_hash"]:
            payload["last_changed"] = previous["last_changed"]
        else:
            payload["last_changed"] = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    else:
        payload["first_seen"] = today.isoformat()
        payload["last_changed"] = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return payload
