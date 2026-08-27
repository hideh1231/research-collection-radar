from __future__ import annotations

from datetime import UTC, datetime, date
import re
from typing import Any

from dateutil import parser as date_parser

from radar.ids import canonicalize_url, content_hash, stable_id
from radar.models import DEADLINE_STATUSES, TOPICS_METHODS, RawRecord

FRONTIERS_TOPIC_RE = re.compile(r"/research-topics/(\d+)(?:/|$)", re.I)
NATURE_COLLECTION_RE = re.compile(r"/collections/([a-z0-9]+)", re.I)
PLOS_CFP_RE = re.compile(r"/call-for-papers/([^/?#]+)", re.I)
ELSEVIER_SI_RE = re.compile(r"/special-issue/(\d+)(?:/|$)", re.I)
APA_CFP_RE = re.compile(r"/pubs/journals/([a-z0-9]+)/([a-z0-9-]+)/?$", re.I)
PLOS_JOURNALS = (
    "PLOS Sustainability and Transformation",
    "PLOS Neglected Tropical Diseases",
    "PLOS Global Public Health",
    "PLOS Computational Biology",
    "PLOS Complex Systems",
    "PLOS Digital Health",
    "PLOS Mental Health",
    "PLOS Genetics",
    "PLOS Pathogens",
    "PLOS Medicine",
    "PLOS Biology",
    "PLOS Climate",
    "PLOS Water",
    "PLOS ONE",
)


def unique_keep_order(values: list[str] | None) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values or []:
        text = re.sub(r"\s+", " ", str(value)).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        ordered.append(text)
    return ordered


def canonical_plos_journals(values: list[str] | None, fallback: str = "PLOS") -> tuple[str, list[str]]:
    blob = " ".join(unique_keep_order(list(values or []))).lower()
    found: list[str] = []
    for name in PLOS_JOURNALS:
        needle = "plos one" if name == "PLOS ONE" else name.lower()
        if needle in blob:
            found.append(name)
    journals = unique_keep_order(found)
    if not journals:
        return fallback, [fallback]
    return journals[0], journals


def publisher_id_from_url(url: str, publisher: str | None = None) -> str | None:
    text = url or ""
    match = FRONTIERS_TOPIC_RE.search(text)
    if match:
        return match.group(1)
    if publisher == "Nature Portfolio" or "nature.com" in text:
        match = NATURE_COLLECTION_RE.search(text)
        if match:
            return match.group(1)
    match = PLOS_CFP_RE.search(text)
    if match:
        return match.group(1)
    match = ELSEVIER_SI_RE.search(text)
    if match:
        return match.group(1)
    match = APA_CFP_RE.search(text)
    if match and match.group(2) not in {"call-for-papers-general", "resources"}:
        return match.group(2)
    return None


def utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def deadline_state(deadline: str | None, status: str | None) -> str:
    """Return a valid deadline state while keeping legacy rows readable."""
    if deadline:
        return "listed"
    if status in DEADLINE_STATUSES:
        return str(status)
    return "not_checked"


def _as_utc_timestamp(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError, OverflowError):
        return None


def migrate_record(row: dict[str, Any]) -> dict[str, Any]:
    """Add deadline and viewer fields to a legacy row without changing timestamps."""
    migrated = dict(row)
    migrated["deadline_status"] = deadline_state(
        migrated.get("deadline"), migrated.get("deadline_status")
    )
    migrated["deadline_checked_at"] = _as_utc_timestamp(migrated.get("deadline_checked_at"))
    migrated["metadata_checked_at"] = _as_utc_timestamp(migrated.get("metadata_checked_at"))
    journal = str(migrated.get("journal") or "").strip()
    migrated["journals"] = unique_keep_order(migrated.get("journals") or ([journal] if journal else []))
    if migrated.get("publisher") == "PLOS" or migrated.get("discovered_via") == "plos-collections":
        journal, journals = canonical_plos_journals(
            [journal, *list(migrated.get("journals") or [])],
            "PLOS",
        )
        migrated["journal"] = journal
        migrated["journals"] = journals
    discovered = str(migrated.get("discovered_via") or "").strip()
    migrated["source_keys"] = unique_keep_order(migrated.get("source_keys") or ([discovered] if discovered else []))
    migrated["publisher_id"] = migrated.get("publisher_id") or publisher_id_from_url(
        str(migrated.get("url") or ""), str(migrated.get("publisher") or "")
    )
    migrated["image_url"] = migrated.get("image_url") or None
    migrated["image_alt"] = migrated.get("image_alt") or None
    from radar.topics import load_aliases, normalize_topic_list, split_publisher_keywords

    aliases = load_aliases()
    keywords = split_publisher_keywords(migrated.get("publisher_keywords") or [])
    migrated["publisher_keywords"] = keywords
    method = migrated.get("topics_method")
    if keywords:
        migrated["topics"] = normalize_topic_list(keywords, aliases)
        method = "publisher"
    else:
        migrated["topics"] = normalize_topic_list(migrated.get("topics") or [], aliases)
        if method not in TOPICS_METHODS:
            method = "llm" if migrated["topics"] else "none"
    migrated["topics_method"] = method
    migrated["topics_model"] = migrated.get("topics_model") or None
    migrated["topics_input_hash"] = migrated.get("topics_input_hash") or None
    migrated["topics_updated_at"] = _as_utc_timestamp(migrated.get("topics_updated_at"))
    migrated["content_hash"] = content_hash(migrated)
    return migrated


def migrate_records(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [migrate_record(row) for row in rows]


def listing_status(deadline: date | None, today: date | None = None) -> str:
    if deadline is None:
        return "open"
    return "closed" if deadline < (today or date.today()) else "open"


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    text = re.sub(r"\s+", " ", value).strip()
    text = re.sub(
        r"^(deadline|submission deadline|manuscript(?: extension)? submission deadline)\s*:?\s*",
        "",
        text,
        flags=re.I,
    )
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
    incoming_journals = unique_keep_order(raw.journals or ([raw.journal] if raw.journal else []))
    incoming_keys = unique_keep_order(raw.source_keys or ([raw.discovered_via] if raw.discovered_via else []))
    previous_journals = unique_keep_order(previous.get("journals") if previous else [])
    previous_keys = unique_keep_order(previous.get("source_keys") if previous else [])
    if previous and previous.get("metadata_checked_at"):
        journal = str(previous.get("journal") or raw.journal)
        journals = unique_keep_order([journal, *previous_journals, *incoming_journals])
    else:
        journal = raw.journal
        journals = unique_keep_order([journal, *incoming_journals, *previous_journals])
    source_keys = unique_keep_order([*previous_keys, *incoming_keys])
    publisher_keywords = unique_keep_order(
        raw.publisher_keywords or (previous.get("publisher_keywords") if previous else [])
    )
    publisher_id = raw.publisher_id or (previous.get("publisher_id") if previous else None) or publisher_id_from_url(
        url, raw.publisher
    )
    incoming_topics = unique_keep_order(topics)
    if publisher_keywords:
        topics_method = "publisher"
        stored_topics = incoming_topics or unique_keep_order(previous.get("topics") if previous else [])
    elif previous and (previous.get("topics") or previous.get("topics_method") in TOPICS_METHODS):
        topics_method = previous.get("topics_method") if previous.get("topics_method") in TOPICS_METHODS else "none"
        stored_topics = unique_keep_order(previous.get("topics") or incoming_topics)
    elif incoming_topics:
        topics_method = "none"
        stored_topics = incoming_topics
    else:
        topics_method = "none"
        stored_topics = []
    payload = {
        "id": record_id,
        "title": normalize_title(raw.title),
        "journal": journal,
        "journals": journals,
        "publisher": raw.publisher,
        "publisher_id": publisher_id,
        "venue_type": raw.venue_type,
        "collection_type": raw.collection_type,
        "url": url,
        "source_url": canonicalize_url(raw.source_url),
        "source_section": raw.source_section,
        "source_keys": source_keys,
        "deadline": deadline,
        "deadline_status": deadline_status,
        "deadline_checked_at": deadline_checked_at,
        "metadata_checked_at": previous.get("metadata_checked_at") if previous else None,
        "status": status,
        "summary": raw.summary if raw.summary is not None else (previous.get("summary") if previous else None),
        "image_url": raw.image_url if raw.image_url is not None else (previous.get("image_url") if previous else None),
        "image_alt": raw.image_alt if raw.image_alt is not None else (previous.get("image_alt") if previous else None),
        "publisher_keywords": publisher_keywords,
        "domains": unique_keep_order(list(domains) + list(previous.get("domains") or []) if previous else domains),
        "domain_scores": {**(previous.get("domain_scores") or {} if previous else {}), **domain_scores},
        "topics": stored_topics,
        "topics_method": topics_method,
        "topics_model": previous.get("topics_model") if previous else None,
        "topics_input_hash": previous.get("topics_input_hash") if previous else None,
        "topics_updated_at": previous.get("topics_updated_at") if previous else None,
        "classification_method": classification_method,
        "extraction_method": raw.extraction_method,
        "discovered_via": previous["discovered_via"] if previous else raw.discovered_via,
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


def merge_collection_rows(current: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    """Combine two listings of the same opportunity without dropping source keys."""
    merged = dict(incoming)
    merged["source_keys"] = unique_keep_order(
        list(current.get("source_keys") or []) + list(incoming.get("source_keys") or [])
    )
    merged["journals"] = unique_keep_order(
        [current.get("journal") or "", incoming.get("journal") or ""]
        + list(current.get("journals") or [])
        + list(incoming.get("journals") or [])
    )
    if current.get("metadata_checked_at") and not incoming.get("metadata_checked_at"):
        merged["journal"] = current.get("journal") or incoming.get("journal")
        merged["journals"] = unique_keep_order(
            [merged["journal"] or "", *list(current.get("journals") or []), *merged["journals"]]
        )
        merged["summary"] = current.get("summary")
        merged["image_url"] = current.get("image_url")
        merged["image_alt"] = current.get("image_alt")
        merged["publisher_keywords"] = unique_keep_order(current.get("publisher_keywords") or [])
        merged["metadata_checked_at"] = current.get("metadata_checked_at")
        merged["topics"] = unique_keep_order(current.get("topics") or incoming.get("topics") or [])
        merged["topics_method"] = current.get("topics_method") or incoming.get("topics_method")
        merged["topics_model"] = current.get("topics_model")
        merged["topics_input_hash"] = current.get("topics_input_hash")
        merged["topics_updated_at"] = current.get("topics_updated_at")
    merged["domains"] = unique_keep_order(list(current.get("domains") or []) + list(incoming.get("domains") or []))
    merged["domain_scores"] = {**(current.get("domain_scores") or {}), **(incoming.get("domain_scores") or {})}
    merged["discovered_via"] = current.get("discovered_via") or incoming.get("discovered_via")
    merged["first_seen"] = min(filter(None, [current.get("first_seen"), incoming.get("first_seen")]))
    if current.get("deadline") and not incoming.get("deadline"):
        merged["deadline"] = current["deadline"]
        merged["deadline_status"] = current.get("deadline_status", "listed")
        merged["deadline_checked_at"] = current.get("deadline_checked_at")
    if merged.get("publisher") == "PLOS" or merged.get("discovered_via") == "plos-collections":
        journal, journals = canonical_plos_journals(
            [merged.get("journal") or "", *list(merged.get("journals") or [])],
            merged.get("journal") or "PLOS",
        )
        merged["journal"] = journal
        merged["journals"] = journals
    merged["content_hash"] = content_hash(merged)
    if merged["content_hash"] == current.get("content_hash"):
        merged["last_changed"] = current.get("last_changed")
    return merged
