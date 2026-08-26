from __future__ import annotations

from datetime import date
import re
import time

from bs4 import BeautifulSoup

from radar.http import Fetcher
from radar.ids import allowed_url, canonicalize_url, stable_id
from radar.models import RawRecord, SourceResult
from radar.normalize import normalize_status, parse_date

TOPIC_HREF = re.compile(r"/research-topics/(\d+)(?:/[^/?#]*)?", re.I)
DEADLINE_RE = re.compile(
    r"Manuscript Submission Deadline\s+(\d{1,2}\s+\w+\s+\d{4})",
    re.I,
)
OPEN_RE = re.compile(r"Submission\s+(open|closed)", re.I)


def _topic_id(url: str) -> str | None:
    match = TOPIC_HREF.search(url)
    return match.group(1) if match else None


def parse_listing(html: str, source: dict) -> tuple[list[RawRecord], bool]:
    soup = BeautifulSoup(html, "lxml")
    hosts = source.get("allowed_hosts", ["www.frontiersin.org"])
    found: dict[str, RawRecord] = {}
    for link in soup.find_all("a", href=True):
        href = str(link["href"])
        if not TOPIC_HREF.search(href):
            continue
        if href.startswith("/"):
            href = "https://www.frontiersin.org" + href
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
            source_url=source["url"],
            publisher=source["publisher"],
            journal=source.get("journal") or "Frontiers",
            collection_type="research_topic",
            discovered_via=source["key"],
            status=status,
            submission_mode="open_call",
            extra={"id": stable_id(source["key"], topic or url) if topic else None, "topic_id": topic},
        )
    has_next = soup.find("a", rel="next") is not None or bool(
        soup.find("a", href=re.compile(r"[?&]page=\d+"))
    )
    return list(found.values()), has_next


def parse_deadline(html: str) -> date | None:
    match = DEADLINE_RE.search(html)
    if match:
        return parse_date(match.group(1))
    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text(" ", strip=True)
    match = DEADLINE_RE.search(text)
    return parse_date(match.group(1) if match else None)


class FrontiersCollector:
    key = "frontiers"

    def collect(self, fetcher: Fetcher, source: dict) -> SourceResult:
        base = source["url"]
        records: dict[str, RawRecord] = {}
        last_status = None
        max_pages = int(source.get("max_pages") or 80)
        page = 1
        truncated = False
        while page <= max_pages:
            url = base if page == 1 else f"{base}{'&' if '?' in base else '?'}page={page}"
            status, html = fetcher.get_html(url)
            last_status = status
            if status >= 400:
                if page == 1:
                    return SourceResult(
                        key=source["key"],
                        ok=False,
                        records=[],
                        http_status=status,
                        error=f"http {status}",
                        page_count=page,
                    )
                break
            batch, _has_next = parse_listing(html, {**source, "url": base})
            new_on_page = 0
            for item in batch:
                key = str(item.extra.get("topic_id") or item.url)
                if key not in records:
                    records[key] = item
                    new_on_page += 1
            if new_on_page == 0:
                break
            page += 1
            time.sleep(0.4)
        else:
            truncated = True
        if truncated:
            return SourceResult(
                key=source["key"],
                ok=False,
                records=[],
                http_status=last_status,
                error="pagination truncated",
                page_count=max_pages,
            )
        if not records:
            return SourceResult(
                key=source["key"],
                ok=False,
                records=[],
                http_status=last_status,
                error="zero records",
                page_count=max(page - 1, 1),
            )
        return SourceResult(
            key=source["key"],
            ok=True,
            records=list(records.values()),
            http_status=last_status,
            parsed_count=len(records),
            page_count=max(page - 1, 1),
        )

    def fill_deadlines(
        self,
        fetcher: Fetcher,
        records: list[RawRecord],
        existing_ids: set[str],
        source: dict,
        limit: int = 60,
    ) -> None:
        if not source.get("fetch_deadlines_for_new"):
            return
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
            time.sleep(0.5)
