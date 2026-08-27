from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
import re
from threading import Event
from typing import Any, Callable, Iterable
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from radar.http import Fetcher
from radar.ids import allowed_url, canonicalize_url, content_hash, stable_id
from radar.models import RawRecord, SourceResult
from radar.normalize import normalize_status, parse_date, utc_now

TOPIC_HREF = re.compile(r"/research-topics/(\d+)(?:/[^/?#]*)?", re.I)
DEADLINE_RE = re.compile(
    r"Manuscript\s+Submission\s+Deadline\s*:?[\s\u00a0]*"
    r"(?P<date>\d{1,2}\s+[A-Za-z]+\s+\d{4}|[A-Za-z]+\s+\d{1,2},?\s+\d{4}|\d{4}-\d{2}-\d{2})",
    re.I,
)
DEADLINE_MARKER_RE = re.compile(r"Manuscript\s+Submission\s+Deadline", re.I)
OPEN_RE = re.compile(r"Submission\s+(open|closed)", re.I)
PAGE_RE = re.compile(r"(?:^|[?&])page=(\d+)(?:&|$)", re.I)


def _topic_id(url: str) -> str | None:
    match = TOPIC_HREF.search(url)
    return match.group(1) if match else None


def _page_number(url: str) -> int:
    match = PAGE_RE.search(urlparse(url).query)
    return int(match.group(1)) if match else 1


def _absolute_href(href: str, current: str) -> str:
    return urljoin(current, href.replace("&#x3D;", "="))


def next_page_url(html: str, current: str, hosts: Iterable[str] | None = None) -> str | None:
    """Return only an explicit next link or the immediately following page."""
    soup = BeautifulSoup(html, "lxml")
    allowed_hosts = list(hosts or [])
    rel_next = soup.find("a", rel=lambda value: value and "next" in value)
    if rel_next and rel_next.get("href"):
        candidate = _absolute_href(str(rel_next["href"]), current)
        if not allowed_hosts or allowed_url(candidate, allowed_hosts):
            return canonicalize_url(candidate)

    current_page = _page_number(current)
    wanted = current_page + 1
    current_path = urlparse(current).path.rstrip("/")
    for link in soup.find_all("a", href=True):
        candidate = _absolute_href(str(link["href"]), current)
        if allowed_hosts and not allowed_url(candidate, allowed_hosts):
            continue
        parsed = urlparse(candidate)
        if parsed.path.rstrip("/") != current_path:
            continue
        if _page_number(candidate) == wanted and PAGE_RE.search(parsed.query):
            return canonicalize_url(candidate)
    return None


def parse_listing(html: str, source: dict) -> tuple[list[RawRecord], bool]:
    soup = BeautifulSoup(html, "lxml")
    hosts = source.get("allowed_hosts", ["www.frontiersin.org"])
    found: dict[str, RawRecord] = {}
    for link in soup.find_all("a", href=True):
        href = str(link["href"])
        if not TOPIC_HREF.search(href):
            continue
        href = _absolute_href(href, source.get("url", "https://www.frontiersin.org"))
        if not allowed_url(href, hosts):
            continue
        title = link.get_text(" ", strip=True)
        if not title or len(title) < 8:
            heading = link.find_parent(["h2", "h3", "h4"])
            if heading:
                title = heading.get_text(" ", strip=True)
        if not title or len(title) < 8:
            continue
        parent = link
        block = ""
        for _ in range(6):
            if parent.parent is None:
                break
            parent = parent.parent
            block = parent.get_text(" ", strip=True)
            if OPEN_RE.search(block):
                break
        status_match = OPEN_RE.search(block)
        status = normalize_status(status_match.group(0) if status_match else "unknown")
        url = canonicalize_url(href)
        topic = _topic_id(url)
        found[topic or url] = RawRecord(
            title=title,
            url=url,
            source_url=canonicalize_url(source["url"]),
            publisher=source["publisher"],
            journal=source.get("journal") or "Frontiers",
            collection_type=source.get("collection_type") or "research_topic",
            discovered_via=source["key"],
            status=status,
            submission_mode="open_call",
            extra={"id": stable_id(source["key"], topic or url) if topic else None, "topic_id": topic},
        )
    return list(found.values()), next_page_url(html, source.get("url", ""), hosts) is not None


def _deadline_details(html: str) -> tuple[date | None, bool]:
    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text(" ", strip=True)
    match = DEADLINE_RE.search(text)
    if not match:
        return None, bool(DEADLINE_MARKER_RE.search(text))
    return parse_date(match.group("date")), True


def parse_deadline(html: str) -> date | None:
    return _deadline_details(html)[0]


def page_matches_record(html: str, record: dict[str, Any] | RawRecord) -> bool:
    """Require canonical identity metadata in the fetched detail page.

    Body links are not evidence of page identity: listing and related-content
    pages commonly link to many topics, including the topic being checked.
    """
    expected_url = record["url"] if isinstance(record, dict) else record.url
    expected_topic = _topic_id(expected_url)
    soup = BeautifulSoup(html, "lxml")
    candidates: list[str] = []
    for tag in soup.find_all(["link", "meta"]):
        rel = tag.get("rel") or []
        if isinstance(rel, str):
            rel = [rel]
        prop = (tag.get("property") or tag.get("name") or "").lower()
        value = tag.get("href") or tag.get("content")
        if value and (any(str(item).lower() == "canonical" for item in rel) or prop in {"og:url", "twitter:url"}):
            candidates.append(_absolute_href(str(value), expected_url))
    if expected_topic and any(_topic_id(candidate) == expected_topic for candidate in candidates):
        return True
    expected_canonical = canonicalize_url(expected_url)
    return any(canonicalize_url(candidate) == expected_canonical for candidate in candidates)


@dataclass(slots=True)
class DeadlineEnrichment:
    target_count: int = 0
    checked: int = 0
    listed: int = 0
    not_listed: int = 0
    failed: int = 0
    rate_limited: int = 0
    parse_errors: int = 0
    forbidden: int = 0
    remaining: int = 0
    stop_reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        value = {
            "target_count": self.target_count,
            "checked": self.checked,
            "listed": self.listed,
            "with_deadline": self.listed,
            "not_listed": self.not_listed,
            "failed": self.failed,
            "rate_limited": self.rate_limited,
            "parse_errors": self.parse_errors,
            "forbidden": self.forbidden,
            "remaining": self.remaining,
        }
        if self.stop_reason:
            value["stop_reason"] = self.stop_reason
        return value


def _settings(source: dict[str, Any]) -> dict[str, int | float]:
    configured = source.get("deadline_enrichment") or {}
    return {
        "daily_limit": int(configured.get("daily_limit", 100)),
        "min_interval_seconds": float(configured.get("min_interval_seconds", 1)),
        "listed_recheck_days": int(configured.get("listed_recheck_days", 7)),
        "not_listed_recheck_days": int(configured.get("not_listed_recheck_days", 30)),
        "checkpoint_size": int(configured.get("checkpoint_size", 25)),
    }


def _checked_at(row: dict[str, Any]) -> datetime | None:
    value = row.get("deadline_checked_at")
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _due(row: dict[str, Any], now: datetime, settings: dict[str, int | float]) -> bool:
    status = row.get("deadline_status")
    checked = _checked_at(row)
    if status == "not_checked":
        return True
    if status == "listed":
        return checked is None or now - checked >= timedelta(days=int(settings["listed_recheck_days"]))
    if status == "not_listed":
        return checked is None or now - checked >= timedelta(days=int(settings["not_listed_recheck_days"]))
    return row.get("deadline") is None


def _is_frontiers_open(row: dict[str, Any], source_key: str) -> bool:
    return row.get("discovered_via") == source_key and row.get("status") == "open"


def select_deadline_targets(
    rows: list[dict[str, Any]],
    source: dict[str, Any],
    *,
    incoming_ids: set[str] | None = None,
    now: datetime | None = None,
    backfill: bool = False,
) -> list[dict[str, Any]]:
    """Select merged rows in new, unconfirmed, and stale-state priority order."""
    now = now or datetime.now(UTC)
    incoming_ids = incoming_ids or set()
    settings = _settings(source)
    candidates = [row for row in rows if _is_frontiers_open(row, source["key"])]
    if backfill:
        selected = [row for row in candidates if row.get("deadline_status") == "not_checked"]
        selected.sort(key=lambda row: (row.get("first_seen", ""), row.get("id", "")))
        return selected

    new = [row for row in candidates if row.get("id") in incoming_ids]
    unconfirmed = [row for row in candidates if row.get("deadline_status") == "not_checked" and row not in new]
    listed = [
        row for row in candidates
        if row.get("deadline_status") == "listed" and row not in new and _due(row, now, settings)
    ]
    not_listed = [
        row for row in candidates
        if row.get("deadline_status") == "not_listed" and row not in new and _due(row, now, settings)
    ]
    ordered: list[dict[str, Any]] = []
    seen: set[str] = set()
    for group in (new, unconfirmed, listed, not_listed):
        for row in sorted(group, key=lambda item: (item.get("first_seen", ""), item.get("id", ""))):
            if row.get("id") not in seen:
                ordered.append(row)
                seen.add(str(row.get("id")))
    return ordered[: int(settings["daily_limit"])]


def _set_deadline(row: dict[str, Any], deadline: str | None, state: str, checked_at: str) -> bool:
    before_hash = row.get("content_hash")
    row["deadline"] = deadline
    row["deadline_status"] = state
    row["deadline_checked_at"] = checked_at
    row["content_hash"] = content_hash(row)
    if row["content_hash"] != before_hash:
        row["last_changed"] = checked_at
        return True
    return False


def _get_html_with_identity(fetcher: Fetcher, row: dict[str, Any]) -> tuple[int, str]:
    validator = lambda html: page_matches_record(html, row)
    try:
        return fetcher.get_html(row["url"], validator=validator)
    except TypeError as exc:
        # Small test doubles often expose only the original get_html(url) API.
        if "validator" not in str(exc):
            raise
        return fetcher.get_html(row["url"])


def _eligible_for_remaining(
    rows: list[dict[str, Any]], source: dict[str, Any], *, backfill: bool
) -> list[dict[str, Any]]:
    if backfill:
        return [
            row for row in rows
            if _is_frontiers_open(row, source["key"]) and row.get("deadline_status") == "not_checked"
        ]
    return select_deadline_targets(rows, source, incoming_ids=set(), backfill=False)


def enrich_deadlines(
    fetcher: Fetcher,
    rows: list[dict[str, Any]],
    source: dict[str, Any],
    *,
    incoming_ids: set[str] | None = None,
    backfill: bool = False,
    now: datetime | None = None,
    checkpoint: Callable[[dict[str, Any]], None] | None = None,
    stop_event: Event | None = None,
) -> dict[str, Any]:
    settings = _settings(source)
    if hasattr(fetcher, "min_interval_seconds"):
        fetcher.min_interval_seconds = max(
            float(getattr(fetcher, "min_interval_seconds", 0)),
            float(settings["min_interval_seconds"]),
        )
    targets = select_deadline_targets(
        rows, source, incoming_ids=incoming_ids, now=now, backfill=backfill
    )
    stats = DeadlineEnrichment(target_count=len(targets))
    consecutive_429 = 0
    consecutive_failures = 0
    checkpoint_size = max(1, int(settings["checkpoint_size"]))

    for row in targets:
        if stop_event is not None and stop_event.is_set():
            stats.stop_reason = "signal"
            break
        try:
            status, html = _get_html_with_identity(fetcher, row)
        except Exception:
            stats.failed += 1
            consecutive_failures += 1
            consecutive_429 = 0
            if consecutive_failures >= 5:
                stats.stop_reason = "consecutive_failures"
                break
            continue
        if status == 403:
            stats.failed += 1
            stats.forbidden += 1
            stats.stop_reason = "forbidden"
            break
        if status == 429:
            stats.failed += 1
            stats.rate_limited += 1
            consecutive_429 += 1
            consecutive_failures = 0
            if consecutive_429 >= 3:
                stats.stop_reason = "consecutive_rate_limits"
                break
            continue
        if status >= 400:
            stats.failed += 1
            consecutive_failures += 1
            consecutive_429 = 0
            if consecutive_failures >= 5:
                stats.stop_reason = "consecutive_failures"
                break
            continue
        if not page_matches_record(html, row):
            stats.failed += 1
            stats.parse_errors += 1
            consecutive_failures += 1
            consecutive_429 = 0
            if consecutive_failures >= 5:
                stats.stop_reason = "consecutive_failures"
                break
            continue

        consecutive_429 = 0
        consecutive_failures = 0
        found_deadline, marker_found = _deadline_details(html)
        checked_at = utc_now()
        previous_deadline = row.get("deadline")
        if found_deadline:
            _set_deadline(row, found_deadline.isoformat(), "listed", checked_at)
            stats.listed += 1
        elif previous_deadline:
            # A known date is never erased by an absent or malformed detail.
            _set_deadline(row, previous_deadline, "listed", checked_at)
            stats.parse_errors += 1
        elif marker_found:
            _set_deadline(row, None, "not_listed", checked_at)
            stats.not_listed += 1
            stats.parse_errors += 1
        else:
            _set_deadline(row, None, "not_listed", checked_at)
            stats.not_listed += 1
        stats.checked += 1
        if checkpoint is not None and stats.checked % checkpoint_size == 0:
            checkpoint(stats.as_dict())

    stats.remaining = len(_eligible_for_remaining(rows, source, backfill=backfill))
    if checkpoint is not None and (stats.checked % checkpoint_size or stats.stop_reason):
        checkpoint(stats.as_dict())
    return stats.as_dict()


class FrontiersCollector:
    key = "frontiers"

    def collect(self, fetcher: Fetcher, source: dict) -> SourceResult:
        base = source["url"]
        current_url = base
        records: dict[str, RawRecord] = {}
        seen_pages: set[str] = set()
        last_status: int | None = None
        max_pages = int(source.get("max_pages") or 80)
        pages = 0
        while current_url and current_url not in seen_pages:
            if pages >= max_pages:
                return SourceResult(
                    key=source["key"], ok=False, records=[], http_status=last_status,
                    error="pagination truncated", page_count=pages,
                )
            seen_pages.add(current_url)
            pages += 1
            try:
                status, html = fetcher.get_html(current_url)
            except Exception as exc:
                return SourceResult(
                    key=source["key"], ok=False, records=[], http_status=last_status,
                    error=f"fetch failed: {exc}", page_count=pages,
                )
            last_status = status
            if status >= 400:
                return SourceResult(
                    key=source["key"], ok=False, records=[], http_status=status,
                    error=f"http {status}", page_count=pages,
                )
            batch, _has_next = parse_listing(html, {**source, "url": current_url})
            new_on_page = 0
            for item in batch:
                item_key = str(item.extra.get("topic_id") or item.url)
                if item_key not in records:
                    records[item_key] = item
                    new_on_page += 1
            next_url = next_page_url(html, current_url, source.get("allowed_hosts"))
            if next_url is not None and new_on_page == 0:
                return SourceResult(
                    key=source["key"], ok=False, records=[], http_status=last_status,
                    error="pagination page contained no new records", page_count=pages,
                )
            if next_url in seen_pages:
                return SourceResult(
                    key=source["key"], ok=False, records=[], http_status=last_status,
                    error="pagination cycle", page_count=pages,
                )
            current_url = next_url

        if not records:
            return SourceResult(
                key=source["key"], ok=False, records=[], http_status=last_status,
                error="zero records", page_count=pages,
            )
        return SourceResult(
            key=source["key"], ok=True, records=list(records.values()),
            http_status=last_status, parsed_count=len(records), page_count=pages,
        )

    def fill_deadlines(
        self,
        fetcher: Fetcher,
        records: list[RawRecord],
        existing_ids: set[str],
        source: dict,
        limit: int = 60,
    ) -> None:
        """Compatibility helper for callers that still enrich RawRecord objects."""
        fetched = 0
        for record in records:
            if fetched >= limit:
                break
            record_id = record.extra.get("id")
            if record_id and record_id in existing_ids:
                continue
            if record.deadline or record.status != "open":
                continue
            try:
                status, html = fetcher.get_html(record.url)
            except Exception:
                continue
            if status >= 400:
                continue
            record.deadline = parse_deadline(html)
            fetched += 1
