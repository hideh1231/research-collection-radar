from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from html import unescape
import re
from threading import Event
from typing import Any, Callable, Iterable
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup, Tag

from radar.http import Fetcher
from radar.ids import allowed_url, canonicalize_url, content_hash, stable_id
from radar.models import RawRecord, SourceResult
from radar.normalize import normalize_status, parse_date, unique_keep_order, utc_now

TOPIC_HREF = re.compile(r"/research-topics/(\d+)(?:/[^/?#]*)?", re.I)
DEADLINE_DATE = (
    r"(?P<date>\d{1,2}\s+[A-Za-z]+\s+\d{4}|[A-Za-z]+\s+\d{1,2},?\s+\d{4}|\d{4}-\d{2}-\d{2})"
)
DEADLINE_RE = re.compile(
    r"Manuscript(?:\s+(?P<kind>Extension))?\s+Submission\s+Deadline\s*:?[\s\u00a0]*"
    + DEADLINE_DATE,
    re.I,
)
DEADLINE_MARKER_RE = re.compile(r"Manuscript(?:\s+Extension)?\s+Submission\s+Deadline", re.I)
OPEN_RE = re.compile(r"Submission\s+(open|closed)", re.I)
PAGE_RE = re.compile(r"(?:^|[?&])page=(\d+)(?:&|$)", re.I)
TOTAL_RE = re.compile(r"([\d,]+)\s+Research Topics", re.I)
SKIP_SUMMARY_RE = re.compile(
    r"article processing charge|\bAPC\b|submission fee|topic editors?|"
    r"manuscript(?:\s+extension)?\s+submission deadline|important note:",
    re.I,
)
# not_listed rows checked before this used a parser that skipped extension labels.
NOT_LISTED_PARSER_CUTOFF = datetime(2026, 8, 28, tzinfo=UTC)
KEYWORD_LABEL_RE = re.compile(r"^keywords:\s*", re.I)
TRUNCATED_RE = re.compile(r"(?:\.\.\.|…)\s*$")


def _topic_id(url: str) -> str | None:
    match = TOPIC_HREF.search(url)
    return match.group(1) if match else None


def _page_number(url: str) -> int:
    match = PAGE_RE.search(urlparse(url).query)
    return int(match.group(1)) if match else 1


def _absolute_href(href: str, current: str) -> str:
    return urljoin(current, href.replace("&#x3D;", "="))


def _with_page(url: str, page: int) -> str:
    parsed = urlparse(url)
    query = [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True) if key.lower() != "page"]
    if page > 1:
        query.append(("page", str(page)))
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, urlencode(query), ""))


def parse_advertised_total(html: str) -> int | None:
    soup = BeautifulSoup(html, "lxml")
    heading = soup.select_one("h1.Hub__total--heading") or soup.select_one(".Hub__total")
    if heading is None:
        return None
    match = TOTAL_RE.search(heading.get_text(" ", strip=True))
    if not match:
        return None
    return int(match.group(1).replace(",", ""))


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


def listing_next_page(
    html: str,
    current: str,
    hosts: Iterable[str] | None,
    *,
    card_count: int,
    page_size: int | None,
    advertised_total: int | None,
    collected_count: int,
) -> str | None:
    if advertised_total is not None and collected_count >= advertised_total:
        return None
    if page_size and card_count < page_size:
        return None
    if card_count == 0:
        return None
    explicit = next_page_url(html, current, hosts)
    if explicit:
        return explicit
    if advertised_total is None and not page_size:
        return None
    return canonicalize_url(_with_page(current, _page_number(current) + 1))


def listing_is_complete(collected: int, advertised: int) -> bool:
    """Hub totals can drift by one or two topics from the paginated cards."""
    if collected <= 0 or advertised <= 0:
        return False
    if collected >= advertised:
        return True
    return advertised - collected <= 2


@dataclass(slots=True)
class ListingParse:
    records: list[RawRecord]
    next_url: str | None = None
    advertised_total: int | None = None
    card_count: int = 0
    incomplete: bool = False
    error: str | None = None


def _card_title(card: Tag) -> str | None:
    heading = card.select_one("h2.CardResearchTopic__title")
    if heading is None:
        return None
    title = heading.get_text(" ", strip=True)
    return title or None


def _card_image(card: Tag, title: str, base: str) -> tuple[str | None, str | None]:
    if card.select_one(".CardResearchTopic__magazine--noImage"):
        return None, None
    img = card.select_one("figure.CardResearchTopic__mask img, img.is-inside-mask, img")
    if img is None:
        return None, None
    src = str(img.get("src") or img.get("data-src") or "").strip()
    if not src or src.startswith("data:"):
        return None, None
    alt = str(img.get("alt") or "").strip() or title
    return urljoin(base, src), alt


def parse_listing(html: str, source: dict) -> ListingParse:
    soup = BeautifulSoup(html, "lxml")
    hosts = source.get("allowed_hosts", ["www.frontiersin.org"])
    base = source.get("url", "https://www.frontiersin.org")
    advertised_total = parse_advertised_total(html)
    cards = soup.select("article.CardResearchTopic")
    found: dict[str, RawRecord] = {}
    for card in cards:
        title = _card_title(card)
        if not title:
            return ListingParse(
                records=[],
                advertised_total=advertised_total,
                card_count=len(cards),
                incomplete=True,
                error="listing card missing title",
            )
        link = card.select_one("a.CardResearchTopic__wrapper[href], a[href*='/research-topics/']")
        if link is None or not link.get("href"):
            return ListingParse(
                records=[],
                advertised_total=advertised_total,
                card_count=len(cards),
                incomplete=True,
                error="listing card missing url",
            )
        href = _absolute_href(str(link["href"]), base)
        if not allowed_url(href, hosts):
            continue
        if href.rstrip("/").endswith("/magazine"):
            href = href[: href.rstrip("/").rfind("/")]
        url = canonicalize_url(href)
        topic = _topic_id(url)
        if not topic:
            return ListingParse(
                records=[],
                advertised_total=advertised_total,
                card_count=len(cards),
                incomplete=True,
                error="listing card missing topic id",
            )
        state_el = card.select_one(".CardResearchTopic__state")
        status = normalize_status(state_el.get_text(" ", strip=True) if state_el else "")
        image_url, image_alt = _card_image(card, title, base)
        found[topic] = RawRecord(
            title=title,
            url=url,
            source_url=canonicalize_url(source["url"]),
            publisher=source["publisher"],
            journal=source.get("journal") or "Frontiers",
            collection_type=source.get("collection_type") or "research_topic",
            discovered_via=source["key"],
            status=status,
            submission_mode="open_call",
            publisher_id=topic,
            journals=[source.get("journal") or "Frontiers"],
            source_keys=[source["key"]],
            image_url=image_url,
            image_alt=image_alt,
            extra={"id": None, "topic_id": topic},
        )
    records = list(found.values())
    next_url = listing_next_page(
        html,
        source.get("url", ""),
        hosts,
        card_count=len(cards),
        page_size=len(cards) or None,
        advertised_total=advertised_total,
        collected_count=len(records),
    )
    return ListingParse(
        records=records,
        next_url=next_url,
        advertised_total=advertised_total,
        card_count=len(cards),
    )


def _meta_content(soup: BeautifulSoup, prop: str) -> str | None:
    tag = soup.find("meta", property=prop) or soup.find("meta", attrs={"name": prop})
    if tag is None:
        return None
    value = tag.get("content")
    if not value:
        return None
    return unescape(str(value)).strip()


def is_truncated_description(text: str | None) -> bool:
    if not text:
        return True
    return bool(TRUNCATED_RE.search(text.strip()))


def _clean_paragraph(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _paragraphs_from_about(node: Tag) -> list[str]:
    paragraphs: list[str] = []
    for child in node.find_all("p"):
        if child.find_parent(class_="RTOverviewBackground__keywords"):
            continue
        html = str(child)
        chunks = re.split(r"<br\s*/?>\s*<br\s*/?>", html, flags=re.I)
        for chunk in chunks:
            text = _clean_paragraph(BeautifulSoup(chunk, "lxml").get_text(" ", strip=True))
            if text:
                paragraphs.append(text)
    if paragraphs:
        return paragraphs
    text = _clean_paragraph(node.get_text(" ", strip=True))
    return [text] if text else []


def parse_summary(soup: BeautifulSoup) -> str | None:
    root = soup.select_one(".RTOverviewBackground__expandable") or soup.select_one(
        ".content-Overview .RTOverviewBackground"
    )
    if root is None:
        return None
    for paragraph in _paragraphs_from_about(root):
        if SKIP_SUMMARY_RE.search(paragraph):
            continue
        if KEYWORD_LABEL_RE.match(paragraph):
            continue
        lowered = paragraph.lower()
        if lowered.startswith("about this research topic"):
            continue
        if "topic editor" in lowered or "navigation" in lowered:
            continue
        return paragraph[:1000]
    return None


def parse_publisher_keywords(soup: BeautifulSoup) -> list[str]:
    from radar.topics import split_keyword_text

    found: list[str] = []
    for node in soup.select(".RTOverviewBackground__keywords p"):
        text = _clean_paragraph(node.get_text(" ", strip=True))
        if not KEYWORD_LABEL_RE.match(text):
            continue
        text = KEYWORD_LABEL_RE.sub("", text)
        found.extend(split_keyword_text(text))
    return unique_keep_order(found)


def parse_journals(soup: BeautifulSoup) -> tuple[str | None, list[str]]:
    main = None
    title = soup.select_one(".CardJournal__Title--journal") or soup.select_one("h2.CardJournal__Title")
    if title is not None:
        main = _clean_paragraph(title.get_text(" ", strip=True)) or None
    participating = [
        _clean_paragraph(node.get_text(" ", strip=True))
        for node in soup.select(".RtSidePanel__Section__OtherParticipatingJournals h3.journalTitle")
    ]
    journals = unique_keep_order(([main] if main else []) + participating)
    return main, journals


@dataclass(slots=True)
class DetailParse:
    title: str | None = None
    summary: str | None = None
    publisher_keywords: list[str] = field(default_factory=list)
    image_url: str | None = None
    image_alt: str | None = None
    journal: str | None = None
    journals: list[str] = field(default_factory=list)
    deadline: date | None = None
    deadline_marker: bool = False


def parse_detail(html: str) -> DetailParse:
    soup = BeautifulSoup(html, "lxml")
    heading = soup.select_one("h1.MainHeader__title") or soup.select_one("h1")
    title = _clean_paragraph(heading.get_text(" ", strip=True)) if heading else None
    summary = parse_summary(soup)
    if summary is None:
        og_description = _meta_content(soup, "og:description")
        if og_description and not is_truncated_description(og_description):
            summary = og_description[:1000]
    image_url = _meta_content(soup, "og:image")
    image_alt = title
    journal, journals = parse_journals(soup)
    deadline, marker = _deadline_details_from_soup(soup)
    return DetailParse(
        title=title or None,
        summary=summary,
        publisher_keywords=parse_publisher_keywords(soup),
        image_url=image_url,
        image_alt=image_alt,
        journal=journal,
        journals=journals,
        deadline=deadline,
        deadline_marker=marker,
    )


def _alert_deadline_text(soup: BeautifulSoup) -> str:
    chunks = []
    for node in soup.select(".Alert__infoItem__text"):
        text = _clean_paragraph(node.get_text(" ", strip=True))
        if text:
            chunks.append(text)
    return " ".join(chunks)


def _deadline_details_from_text(text: str) -> tuple[date | None, bool]:
    matches = list(DEADLINE_RE.finditer(text or ""))
    marker = bool(matches or DEADLINE_MARKER_RE.search(text or ""))
    parsed: list[tuple[bool, date]] = []
    for match in matches:
        value = parse_date(match.group("date"))
        if value is None:
            continue
        parsed.append((bool(match.group("kind")), value))
    if not parsed:
        return None, marker
    extended = [value for is_extension, value in parsed if is_extension]
    if extended:
        return max(extended), True
    return max(value for _, value in parsed), True


def _deadline_details_from_soup(soup: BeautifulSoup) -> tuple[date | None, bool]:
    alert_deadline, alert_marker = _deadline_details_from_text(_alert_deadline_text(soup))
    if alert_deadline is not None:
        return alert_deadline, True
    page_deadline, page_marker = _deadline_details_from_text(soup.get_text(" ", strip=True))
    return page_deadline, alert_marker or page_marker


def _deadline_details(html: str) -> tuple[date | None, bool]:
    return _deadline_details_from_soup(BeautifulSoup(html, "lxml"))


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
    return any(canonicalize_url(candidate.removesuffix("undefined")) == expected_canonical for candidate in candidates)


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
    metadata_updated: int = 0
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
            "metadata_updated": self.metadata_updated,
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


def _checked_at(row: dict[str, Any], field_name: str = "deadline_checked_at") -> datetime | None:
    value = row.get(field_name)
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
        if checked is None or checked < NOT_LISTED_PARSER_CUTOFF:
            return True
        return now - checked >= timedelta(days=int(settings["not_listed_recheck_days"]))
    return row.get("deadline") is None


def _is_frontiers_open(row: dict[str, Any], source: dict[str, Any] | None = None) -> bool:
    if row.get("status") != "open":
        return False
    if row.get("publisher") == "Frontiers":
        return True
    if source is not None and row.get("discovered_via") == source.get("key"):
        return True
    return False


def _deadline_queue(
    rows: list[dict[str, Any]],
    source: dict[str, Any],
    *,
    incoming_ids: set[str] | None = None,
    now: datetime | None = None,
    backfill: bool = False,
) -> list[dict[str, Any]]:
    now = now or datetime.now(UTC)
    incoming_ids = incoming_ids or set()
    settings = _settings(source)
    candidates = [row for row in rows if _is_frontiers_open(row, source)]
    if backfill:
        selected = [
            row
            for row in candidates
            if row.get("deadline_status") in {"not_checked", "not_listed"}
            or not row.get("metadata_checked_at")
        ]
        selected.sort(key=lambda row: (row.get("first_seen", ""), row.get("id", "")))
        return selected

    new = [row for row in candidates if row.get("id") in incoming_ids]
    unconfirmed = [row for row in candidates if row.get("deadline_status") == "not_checked" and row not in new]
    missing_metadata = [
        row
        for row in candidates
        if not row.get("metadata_checked_at") and row not in new and row not in unconfirmed
    ]
    listed = [
        row
        for row in candidates
        if row.get("deadline_status") == "listed" and row not in new and _due(row, now, settings)
    ]
    not_listed = [
        row
        for row in candidates
        if row.get("deadline_status") == "not_listed" and row not in new and _due(row, now, settings)
    ]
    ordered: list[dict[str, Any]] = []
    seen: set[str] = set()
    for group in (new, unconfirmed, missing_metadata, listed, not_listed):
        for row in sorted(group, key=lambda item: (item.get("first_seen", ""), item.get("id", ""))):
            if row.get("id") not in seen:
                ordered.append(row)
                seen.add(str(row.get("id")))
    return ordered


def select_deadline_targets(
    rows: list[dict[str, Any]],
    source: dict[str, Any],
    *,
    incoming_ids: set[str] | None = None,
    now: datetime | None = None,
    backfill: bool = False,
) -> list[dict[str, Any]]:
    """Select merged rows in new, unconfirmed, metadata, and stale-state order."""
    ordered = _deadline_queue(rows, source, incoming_ids=incoming_ids, now=now, backfill=backfill)
    if backfill:
        return ordered
    return ordered[: int(_settings(source)["daily_limit"])]


def _touch_hash(row: dict[str, Any], checked_at: str) -> bool:
    before_hash = row.get("content_hash")
    row["content_hash"] = content_hash(row)
    if row["content_hash"] != before_hash:
        row["last_changed"] = checked_at
        return True
    return False


def _set_deadline(row: dict[str, Any], deadline: str | None, state: str, checked_at: str) -> bool:
    row["deadline"] = deadline
    row["deadline_status"] = state
    row["deadline_checked_at"] = checked_at
    return _touch_hash(row, checked_at)


def apply_detail_metadata(row: dict[str, Any], detail: DetailParse, checked_at: str) -> bool:
    if detail.title:
        row["title"] = detail.title
    if detail.summary:
        row["summary"] = detail.summary
    if detail.publisher_keywords:
        row["publisher_keywords"] = unique_keep_order(detail.publisher_keywords)
        from radar.topics import apply_publisher_topics

        apply_publisher_topics(row, checked_at=checked_at)
    if detail.image_url:
        row["image_url"] = detail.image_url
        row["image_alt"] = detail.image_alt or row.get("title")
    if detail.journal:
        row["journal"] = detail.journal
    if detail.journals:
        row["journals"] = unique_keep_order([detail.journal or row.get("journal") or "", *detail.journals])
    row["metadata_checked_at"] = checked_at
    return _touch_hash(row, checked_at)


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
    return _deadline_queue(rows, source, incoming_ids=set(), backfill=backfill)


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
        detail = parse_detail(html)
        found_deadline = detail.deadline
        marker_found = detail.deadline_marker
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
        if apply_detail_metadata(row, detail, checked_at):
            stats.metadata_updated += 1
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
        max_pages = int(source.get("max_pages") or 200)
        pages = 0
        advertised_total: int | None = None
        page_size: int | None = None
        while current_url and current_url not in seen_pages:
            if pages >= max_pages:
                return SourceResult(
                    key=source["key"],
                    ok=False,
                    records=[],
                    http_status=last_status,
                    error="pagination truncated",
                    page_count=pages,
                )
            seen_pages.add(current_url)
            pages += 1
            try:
                status, html = fetcher.get_html(current_url)
            except Exception as exc:
                return SourceResult(
                    key=source["key"],
                    ok=False,
                    records=[],
                    http_status=last_status,
                    error=f"fetch failed: {exc}",
                    page_count=pages,
                )
            last_status = status
            if status == 404 and pages > 1:
                break
            if status >= 400:
                return SourceResult(
                    key=source["key"],
                    ok=False,
                    records=[],
                    http_status=status,
                    error=f"http {status}",
                    page_count=pages,
                )
            parsed = parse_listing(html, {**source, "url": current_url})
            if parsed.incomplete:
                return SourceResult(
                    key=source["key"],
                    ok=False,
                    records=[],
                    http_status=last_status,
                    error=parsed.error or "incomplete listing",
                    page_count=pages,
                )
            if advertised_total is None:
                advertised_total = parsed.advertised_total
            if page_size is None and parsed.card_count:
                page_size = parsed.card_count
            new_on_page = 0
            for item in parsed.records:
                item_key = str(item.publisher_id or item.extra.get("topic_id") or item.url)
                if item_key not in records:
                    records[item_key] = item
                    new_on_page += 1
            next_url = listing_next_page(
                html,
                current_url,
                source.get("allowed_hosts"),
                card_count=parsed.card_count,
                page_size=page_size,
                advertised_total=advertised_total,
                collected_count=len(records),
            )
            if next_url is not None and new_on_page == 0:
                return SourceResult(
                    key=source["key"],
                    ok=False,
                    records=[],
                    http_status=last_status,
                    error="pagination page contained no new records",
                    page_count=pages,
                )
            if next_url in seen_pages:
                return SourceResult(
                    key=source["key"],
                    ok=False,
                    records=[],
                    http_status=last_status,
                    error="pagination cycle",
                    page_count=pages,
                )
            current_url = next_url

        if not records:
            return SourceResult(
                key=source["key"],
                ok=False,
                records=[],
                http_status=last_status,
                error="zero records",
                page_count=pages,
            )
        if advertised_total is None:
            return SourceResult(
                key=source["key"],
                ok=False,
                records=[],
                http_status=last_status,
                error="listing total missing",
                page_count=pages,
            )
        if not listing_is_complete(len(records), advertised_total):
            return SourceResult(
                key=source["key"],
                ok=False,
                records=[],
                http_status=last_status,
                error=f"incomplete listing: parsed {len(records)} of {advertised_total}",
                page_count=pages,
            )
        return SourceResult(
            key=source["key"],
            ok=True,
            records=list(records.values()),
            http_status=last_status,
            parsed_count=len(records),
            page_count=pages,
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
