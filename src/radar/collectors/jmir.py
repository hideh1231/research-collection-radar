from __future__ import annotations

from datetime import date
import re
from urllib.parse import urlencode, urljoin

from bs4 import BeautifulSoup

from radar.http import Fetcher
from radar.ids import allowed_url, canonicalize_url
from radar.models import RawRecord, SourceResult
from radar.normalize import parse_date, utc_now

DATE_TEXT = r"(?:\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]+\s+\d{4}|[A-Za-z]+\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4}|\d{4}-\d{2}-\d{2})"
DEADLINE_LABEL = r"(?:manuscript\s+)?submission\s+deadline|deadline\s+for\s+(?:full\s+)?(?:manuscripts?|papers?|submissions?)|full\s+paper\s+due|submit\s+(?:a\s+)?full-length\s+manuscript\s+by"
DEADLINE_RE = re.compile(rf"(?:{DEADLINE_LABEL})\s*:?\s*(?:is\s+)?(?:\*?extended\*?\s*(?:(?:to|until)\s+)?)?({DATE_TEXT})", re.I)
OPEN_DEADLINE_RE = re.compile(rf"(?:{DEADLINE_LABEL})\s*:?\s*(?:open\s+call|rolling|none|no\s+deadline)", re.I)
CLOSED_RE = re.compile(r"(?:submissions?|call)(?:\s+(?:is|are))?\s+(?:now\s+)?closed|no\s+longer\s+accepting\s+submissions", re.I)


def _clean_title(title: str) -> str:
    return re.sub(r"^call\s+for\s+papers\s*[:–—-]?\s*(?:theme\s+issue\s*:\s*)?", "", title, flags=re.I).strip()


def parse_detail(html: str, record: RawRecord, source: dict) -> bool:
    """Apply metadata only when the announcement heading matches the listing."""
    soup = BeautifulSoup(html, "lxml")
    heading = soup.find("h1")
    if heading is None or _clean_title(heading.get_text(" ", strip=True)).casefold() != record.title.casefold():
        return False
    main = soup.select_one("main#main-content") or soup.find("main") or soup.find("article")
    if main is None:
        return False
    canonical = soup.find("link", rel="canonical")
    if canonical and canonical.get("href") and canonicalize_url(urljoin(record.url, str(canonical["href"]))) != record.url:
        return False
    text = main.get_text(" ", strip=True)
    dates = [parse_date(match.group(1)) for match in DEADLINE_RE.finditer(text)]
    deadline = max((value for value in dates if value is not None), default=None)
    if re.search(DEADLINE_LABEL, text, re.I) and deadline is None and not OPEN_DEADLINE_RE.search(text):
        return False
    today = source.get("today") or date.today()
    if CLOSED_RE.search(text):
        record.status = "closed"
    elif deadline:
        record.status = "open" if deadline >= today else "closed"
    elif OPEN_DEADLINE_RE.search(text):
        record.status = "open"
    record.deadline = deadline
    record.extra["deadline_checked_at"] = utc_now()
    record.extra["deadline_status"] = "listed" if deadline else "not_listed"
    record.extraction_method = "jmir_announcement_detail"
    return True


def parse_listing(html: str, source: dict) -> list[RawRecord]:
    soup = BeautifulSoup(html, "lxml")
    hosts = source.get("allowed_hosts", [])
    found: dict[str, RawRecord] = {}
    for heading in soup.find_all(["h2", "h3"]):
        link = heading.find("a", href=True)
        if link is None:
            continue
        title = link.get_text(" ", strip=True)
        if "call for papers" not in title.casefold():
            continue
        href = urljoin(source["url"], str(link["href"]))
        if hosts and not allowed_url(href, hosts):
            continue
        url = canonicalize_url(href)
        cleaned = _clean_title(title)
        found[url] = RawRecord(
            title=cleaned,
            url=url,
            source_url=source["url"],
            publisher=source["publisher"],
            journal=source["journal"],
            collection_type=source.get("collection_type") or "theme_issue",
            discovered_via=source["key"],
            status="unknown",
            submission_mode="open_call",
        )
    return list(found.values())


def _api_records(payload: list[dict], source: dict) -> list[RawRecord]:
    records = []
    for item in payload:
        if not isinstance(item, dict) or str(item.get("journal_id")) != str(source["journal_id"]):
            continue
        title = str(item.get("title") or "")
        number = item.get("announcement_id")
        if "call for papers" not in title.casefold() or not str(number).isdigit():
            continue
        if _clean_title(title).casefold() == str(source["journal"]).casefold():
            continue
        records.append(RawRecord(
            title=_clean_title(title),
            url=canonicalize_url(urljoin(source["url"], f"/announcements/{number}")),
            source_url=source["url"], publisher=source["publisher"], journal=source["journal"],
            collection_type=source.get("collection_type") or "theme_issue",
            discovered_via=source["key"], status="unknown", publisher_id=str(number),
            summary=BeautifulSoup(str(item.get("description_short") or ""), "lxml").get_text(" ", strip=True)[:1000] or None,
            extraction_method="jmir_announcements_api",
        ))
    return records


class JmirCollector:
    key = "jmir"

    def collect(self, fetcher: Fetcher, source: dict) -> SourceResult:
        if source.get("journal_id"):
            return self._collect_api(fetcher, source)
        status, html = fetcher.get_html(source["url"])
        if status >= 400:
            return SourceResult(
                key=source["key"], ok=False, records=[], http_status=status,
                error=f"http {status}", page_count=1,
            )
        records = parse_listing(html, source)
        if not records and not source.get("allow_empty"):
            return SourceResult(
                key=source["key"], ok=False, records=[], http_status=status,
                error="zero records", page_count=1,
            )
        return self._details(fetcher, source, records, status, 1)

    def _collect_api(self, fetcher: Fetcher, source: dict) -> SourceResult:
        base = source.get("api_url") or urljoin(source["url"], "/v1/announcements")
        if not allowed_url(base, source.get("allowed_hosts") or []):
            return SourceResult(key=source["key"], ok=False, records=[], error="API host not allowed")
        max_pages = max(1, int(source.get("api_max_pages") or source.get("max_pages") or 40))
        records: dict[str, RawRecord] = {}
        seen: set[str] = set()
        for page in range(1, max_pages + 1):
            query = urlencode({"page": page, "perPage": 10, "sortField": "announcement_id", "sortOrder": "DESC"})
            response = fetcher.get(base + "?" + query, headers={"X-JOURNAL-ID": str(source["journal_id"]), "Accept": "application/json"})
            if response.status_code >= 400:
                return SourceResult(key=source["key"], ok=False, records=[], http_status=response.status_code, error=f"http {response.status_code}", page_count=page)
            try:
                payload = response.json()
                items = payload["data"]
                last_page = max(1, int(payload["pagination"]["lastPage"]))
                if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
                    raise ValueError("unexpected API items")
            except (ValueError, TypeError, KeyError):
                return SourceResult(key=source["key"], ok=False, records=[], http_status=response.status_code, error="unexpected JSON shape", page_count=page)
            if any(str(item.get("journal_id")) != str(source["journal_id"]) for item in items):
                return SourceResult(key=source["key"], ok=False, records=[], http_status=response.status_code, error="API journal filter mismatch", page_count=page)
            item_ids = {str(item.get("announcement_id")) for item in items}
            if page > 1 and not item_ids - seen:
                return SourceResult(key=source["key"], ok=False, records=[], http_status=response.status_code, error="pagination page contained no new records", page_count=page)
            seen.update(item_ids)
            for record in _api_records(items, source):
                records[record.url] = record
            if page >= last_page:
                return self._details(fetcher, source, list(records.values()), response.status_code, page)
        return SourceResult(key=source["key"], ok=False, records=[], http_status=200, error="pagination truncated", page_count=max_pages)

    def _details(self, fetcher: Fetcher, source: dict, records: list[RawRecord], status: int, pages: int) -> SourceResult:
        if not records and not source.get("allow_empty"):
            return SourceResult(key=source["key"], ok=False, records=[], http_status=status, error="zero records", page_count=pages)
        errors = 0
        for record in records:
            try:
                detail_status, html = fetcher.get_html(record.url)
                valid = detail_status < 400 and parse_detail(html, record, source)
            except Exception:
                valid = False
            if not valid:
                errors += 1
        return SourceResult(
            key=source["key"], ok=True, records=records, http_status=status,
            error=f"{errors} detail checks failed" if errors else None,
            parsed_count=len(records), page_count=pages,
        )
