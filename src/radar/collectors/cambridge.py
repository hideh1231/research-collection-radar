from __future__ import annotations

from datetime import date
import re
from urllib.parse import parse_qsl, urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from radar.http import Fetcher
from radar.ids import allowed_url, canonicalize_url, stable_id
from radar.models import RawRecord, SourceResult
from radar.normalize import normalize_status, parse_date, utc_now


DEFAULT_HOSTS = ["www.cambridge.org", "cambridge.org"]
TITLE_SELECTOR = "li.title a[href]"
DEADLINE_LABEL = (
    r"(?:(?:full\s+)?manuscript\s+submission\s+deadline|submission\s+deadline|"
    r"deadline\s+for\s+submissions?|closing\s+date\s+for\s+submissions?|"
    r"submitted\s+no\s+later\s+than|deadline(?:\s+date)?(?:\s+extended)?)\s*:?\s*"
)
DEADLINE_RE = re.compile(
    DEADLINE_LABEL +
    r"(?P<date>\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+\s+\d{4}|"
    r"[A-Za-z]+\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4}|"
    r"\d{4}-\d{2}-\d{2}|\d{1,2}\.\d{1,2}\.\d{4})",
    re.I,
)
MONTH_DEADLINE_RE = re.compile(DEADLINE_LABEL + r"(?P<month>[A-Za-z]+)\s+(?P<year>\d{4})\b", re.I)
STATUS_RE = re.compile(
    r"(?:submission|call)\s+(?:status|is)\s*:?\s*(?P<status>open|closed)", re.I
)
GENERIC_TITLE_RE = re.compile(r"^(?:call\s+for\s+papers?|special\s+issue\s+call\s+for\s+papers?)$", re.I)
OPEN_RE = re.compile(
    r"\b(?:we\s+(?:invite|welcome)|(?:currently\s+)?accepting)\s+"
    r"(?:unsolicited\s+)?(?:submissions?|manuscripts?|papers?)\b|"
    r"\bsubmissions?\s+(?:are\s+)?open\b", re.I,
)


def _overview(link: Tag) -> Tag | None:
    for parent in link.parents:
        if not isinstance(parent, Tag):
            continue
        classes = parent.get("class") or []
        if parent.name == "ul" and "overview" in classes:
            return parent
        if parent.name in {"article", "main"}:
            break
    return None


def _card_text(link: Tag) -> str:
    overview = _overview(link)
    if overview is not None:
        return overview.get_text(" ", strip=True)
    parent = link.find_parent(["li", "article", "div", "p"])
    return parent.get_text(" ", strip=True) if parent else link.get_text(" ", strip=True)


def _summary(block: str, anchor_title: str) -> str | None:
    text = re.sub(rf"^{re.escape(anchor_title)}\s*", "", block, flags=re.I).strip()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    return text[:1200] or None


def _deadline(text: str) -> date | None:
    candidates: list[tuple[int, date]] = []
    for match in DEADLINE_RE.finditer(text):
        prefix = text[max(0, match.start() - 30):match.start()]
        if re.search(r"abstract\s*$", prefix, re.I):
            continue
        date_text = match.group("date")
        if re.fullmatch(r"\d{1,2}\.\d{1,2}\.\d{4}", date_text):
            day, month, year = map(int, date_text.split("."))
            try:
                value = date(year, month, day)
            except ValueError:
                value = None
        else:
            value = parse_date(date_text)
        if value is not None:
            label = match.group(0).casefold()
            priority = 0 if "manuscript" in label or "extended" in label else 1
            candidates.append((priority, value))
    return min(candidates, key=lambda item: item[0])[1] if candidates else None


def _status(deadline: date | None, text: str, source: dict) -> str:
    today = source.get("today")
    if not isinstance(today, date):
        today = date.today()
    match = STATUS_RE.search(text)
    if match and normalize_status(match.group("status")) == "closed":
        return "closed"
    if deadline:
        return "open" if deadline >= today else "closed"
    if match:
        return normalize_status(match.group("status"))
    return "unknown"


def _detail_body(html: str, record: RawRecord) -> Tag | None:
    soup = BeautifulSoup(html, "lxml")
    body = soup.select_one("#maincontent")
    if body is None:
        return None
    canonical = soup.select_one('link[rel="canonical"][href]')
    if canonical is not None:
        identity = canonicalize_url(urljoin(record.url, str(canonical["href"])))
        if identity != canonicalize_url(record.url):
            return None
    for element in body.select("script, style, nav, header, footer, del, s, strike"):
        element.decompose()
    # A valid response must still describe this call, not a sign-in or wall page.
    title = re.sub(r"\s+", " ", record.title).strip().casefold()
    text = re.sub(r"\s+", " ", body.get_text(" ", strip=True)).casefold()
    if not title or title not in text:
        return None
    return body


def _request_url(url: str, source: dict) -> str:
    """Keep stable identities separate from Cambridge's working www origin."""
    parsed = urlparse(url)
    official = urlparse(source["url"])
    if (parsed.hostname or "").removeprefix("www.") == (official.hostname or "").removeprefix("www."):
        return parsed._replace(scheme=official.scheme, netloc=official.netloc).geturl()
    return url


def _enrich_detail(fetcher: Fetcher, record: RawRecord, source: dict) -> bool:
    hosts = source.get("allowed_hosts", DEFAULT_HOSTS)
    listing_path = urlparse(source["url"]).path.rstrip("/")
    if (
        not allowed_url(record.url, hosts)
        or not urlparse(record.url).path.startswith(listing_path + "/")
    ):
        return False
    try:
        status, html = fetcher.get_html(_request_url(record.url, source))
    except Exception:
        return False
    if status >= 400:
        return False
    body = _detail_body(html, record)
    if body is None:
        return False
    text = body.get_text(" ", strip=True)
    deadline = _deadline(text)
    status = _status(deadline, text, source)
    if deadline is not None:
        record.deadline = deadline
        record.extra.update(deadline_status="listed", deadline_checked_at=utc_now())
    else:
        today = source.get("today")
        if not isinstance(today, date):
            today = date.today()
        # Month-only dates can establish expiry without inventing a day.
        for match in MONTH_DEADLINE_RE.finditer(text):
            month = parse_date(f"1 {match.group('month')} {match.group('year')}")
            if month and (month.year, month.month) < (today.year, today.month):
                status = "closed"
                break
        has_deadline_label = re.search(DEADLINE_LABEL, text, re.I)
        if status == "unknown" and not has_deadline_label and OPEN_RE.search(text):
            status = "open"
        if not has_deadline_label:
            record.extra.update(deadline_status="not_listed", deadline_checked_at=utc_now())
    if status != "unknown":
        record.status = status
    return True


def parse_listing(html: str, source: dict) -> list[RawRecord]:
    """Parse Cambridge Core journal call-for-papers listing HTML."""
    soup = BeautifulSoup(html, "lxml")
    hosts = source.get("allowed_hosts", DEFAULT_HOSTS)
    include_keywords = [
        str(value).casefold().strip()
        for value in source.get("include_keywords", [])
        if str(value).strip()
    ]
    found: dict[str, RawRecord] = {}
    for link in soup.select(TITLE_SELECTOR):
        anchor_title = link.get_text(" ", strip=True)
        if not anchor_title:
            continue
        href = urljoin(source["url"], str(link["href"]))
        if not allowed_url(href, hosts):
            continue
        block = _card_text(link)
        title = anchor_title
        if GENERIC_TITLE_RE.fullmatch(anchor_title):
            remainder = re.sub(rf"^{re.escape(anchor_title)}\s*", "", block, flags=re.I).strip()
            if remainder:
                title = remainder
        summary = _summary(block, anchor_title)
        haystack = " ".join(filter(None, (title, summary))).casefold()
        if include_keywords and not any(keyword in haystack for keyword in include_keywords):
            continue
        url = canonicalize_url(href)
        deadline = _deadline(block)
        found[url] = RawRecord(
            title=title,
            url=url,
            source_url=canonicalize_url(source["url"]),
            publisher=source["publisher"],
            journal=source["journal"],
            collection_type=source.get("collection_type") or "special_issue",
            discovered_via=source["key"],
            status=_status(deadline, block, source),
            deadline=deadline,
            summary=summary,
            submission_mode="open_call",
            extraction_method="cambridge_core_html",
            extra={"id": stable_id(source["key"], url)},
        )
    return list(found.values())


def _page_number(url: str) -> int:
    for key, value in parse_qsl(urlparse(url).query, keep_blank_values=True):
        if key in {"p", "page"} and value.isdigit():
            return int(value)
    return 1


def next_page_url(html: str, current: str, hosts: list[str] | None = None) -> str | None:
    """Return an explicit or immediately following Cambridge ``p`` link."""
    soup = BeautifulSoup(html, "lxml")
    allowed_hosts = hosts or DEFAULT_HOSTS
    current_path = urlparse(current).path.rstrip("/")
    for link in soup.find_all("a", href=True):
        label = link.get_text(" ", strip=True).casefold()
        rel = link.get("rel") or []
        if isinstance(rel, str):
            rel = [rel]
        if "next" not in [str(value).casefold() for value in rel] and label not in {"next", "next page", ">"}:
            continue
        candidate = urljoin(current, str(link["href"]))
        parsed = urlparse(candidate)
        if (
            allowed_url(candidate, allowed_hosts)
            and parsed.path.rstrip("/") == current_path
            and _page_number(candidate) > _page_number(current)
        ):
            return canonicalize_url(candidate)
    wanted = _page_number(current) + 1
    for link in soup.find_all("a", href=True):
        candidate = urljoin(current, str(link["href"]))
        if not allowed_url(candidate, allowed_hosts):
            continue
        parsed = urlparse(candidate)
        if parsed.path.rstrip("/") != current_path or _page_number(candidate) != wanted:
            continue
        return canonicalize_url(candidate)
    return None


class CambridgeCollector:
    key = "cambridge"

    def collect(self, fetcher: Fetcher, source: dict) -> SourceResult:
        current = source["url"]
        seen: set[str] = set()
        records: dict[str, RawRecord] = {}
        max_pages = max(1, int(source.get("max_pages") or 10))
        pages = 0
        last_status: int | None = None
        while current and pages < max_pages:
            if current in seen:
                return SourceResult(
                    key=source["key"], ok=False, records=[], http_status=last_status,
                    error="pagination cycle", page_count=pages,
                )
            seen.add(current)
            pages += 1
            try:
                status, html = fetcher.get_html(_request_url(current, source))
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
            for record in parse_listing(html, {**source, "url": current}):
                records[record.url] = record
            current = next_page_url(html, current, source.get("allowed_hosts"))

        if current:
            return SourceResult(
                key=source["key"], ok=False, records=[], http_status=last_status,
                error="pagination truncated", page_count=pages,
            )
        if not records and not source.get("allow_empty"):
            return SourceResult(
                key=source["key"], ok=False, records=[], http_status=last_status,
                error="zero records", page_count=pages,
            )
        detail_failures = 0
        for record in records.values():
            if record.deadline is None and not _enrich_detail(fetcher, record, source):
                detail_failures += 1
        return SourceResult(
            key=source["key"], ok=True, records=list(records.values()), http_status=last_status,
            parsed_count=len(records), page_count=pages,
            error=f"detail unavailable for {detail_failures} calls" if detail_failures else None,
        )
