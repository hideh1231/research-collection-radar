from __future__ import annotations

from datetime import UTC, datetime, date
import re
from typing import Any

from dateutil import parser as date_parser

from radar.ids import canonicalize_url, content_hash, stable_id
from radar.models import DEADLINE_STATUSES, RawRecord


def utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def deadline_state(deadline: str | None, status: str | None) -> str:
    """Return a valid deadline state while keeping legacy rows readable."""
    if deadline:
        return "listed"
    if status in DEADLINE_STATUSES:
        return str(status)
    return "not_checked"


def migrate_record(row: dict[str, Any]) -> dict[str, Any]:
    """Add deadline fields to a legacy row without changing its timestamps."""
    migrated = dict(row)
    migrated["deadline_status"] = deadline_state(
        migrated.get("deadline"), migrated.get("deadline_status")
    )
    checked_at = migrated.get("deadline_checked_at")
    if isinstance(checked_at, str):
        try:
            parsed = datetime.fromisoformat(checked_at.replace("Z", "+00:00"))
            migrated["deadline_checked_at"] = parsed.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        except (TypeError, ValueError, OverflowError):
            migrated["deadline_checked_at"] = None
    else:
        migrated["deadline_checked_at"] = None
    migrated["content_hash"] = content_hash(migrated)
    return migrated


def migrate_records(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [migrate_record(row) for row in rows]


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
    previous = (prior or {}).get(record_id)
    incoming_deadline = raw.deadline.isoformat() if raw.deadline else None
    # A source listing often omits a deadline.  That omission must not erase a
    # date confirmed by an earlier run.
    if incoming_deadline is None and previous and previous.get("deadline"):
        deadline = previous["deadline"]
    else:
        deadline = incoming_deadline
    status = normalize_status(raw.status)
    if deadline:
        if previous and previous.get("deadline") == deadline:
            deadline_status = deadline_state(deadline, previous.get("deadline_status"))
            deadline_checked_at = previous.get("deadline_checked_at")
        else:
            deadline_status = "listed"
            deadline_checked_at = utc_now()
    elif previous:
        deadline_status = deadline_state(None, previous.get("deadline_status"))
        deadline_checked_at = previous.get("deadline_checked_at")
    else:
        deadline_status = "not_checked"
        deadline_checked_at = None
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
        "deadline_status": deadline_status,
        "deadline_checked_at": deadline_checked_at,
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
