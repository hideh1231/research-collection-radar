from __future__ import annotations

import re

from bs4 import BeautifulSoup

from radar.http import Fetcher
from radar.ids import allowed_url, canonicalize_url
from radar.models import RawRecord, SourceResult
from radar.normalize import parse_date

SPECIAL_HREF = re.compile(r"/special-issue/|/call-for-papers|calls-for-papers", re.I)
DEADLINE_RE = re.compile(r"Submission deadline:\s*(\d{1,2}\s+\w+\s+\d{4}|\d{4}-\d{2}-\d{2})", re.I)


def parse_listing(html: str, source: dict) -> list[RawRecord]:
    soup = BeautifulSoup(html, "lxml")
    hosts = source.get("allowed_hosts", [])
    found: dict[str, RawRecord] = {}
    for link in soup.find_all("a", href=True):
        href = str(link["href"])
        if not SPECIAL_HREF.search(href):
            continue
        if href.startswith("/"):
            href = "https://www.sciencedirect.com" + href
        if hosts and not allowed_url(href, hosts):
            continue
        title = link.get_text(" ", strip=True)
        if not title or len(title) < 8:
            continue
        parent = link.find_parent(["li", "article", "div"]) or link
        text = parent.get_text(" ", strip=True)
        deadline = parse_date(m.group(1) if (m := DEADLINE_RE.search(text)) else None)
        url = canonicalize_url(href)
        found[url] = RawRecord(
            title=title,
            url=url,
            source_url=source["url"],
            publisher=source["publisher"],
            journal=source.get("journal") or "ScienceDirect",
            collection_type="special_issue",
            discovered_via=source["key"],
            deadline=deadline,
            submission_mode="open_call",
        )
    return list(found.values())


class ScienceDirectCollector:
    key = "sciencedirect"

    def collect(self, fetcher: Fetcher, source: dict) -> SourceResult:
        status, html = fetcher.get_html(source["url"])
        if status >= 400:
            return SourceResult(key=source["key"], ok=False, records=[], http_status=status, error=f"http {status}")
        lowered = html.lower()
        if "cloudflare" in lowered and "cf-browser-verification" in lowered:
            return SourceResult(key=source["key"], ok=False, records=[], http_status=status, error="bot wall")
        records = parse_listing(html, source)
        if not records:
            return SourceResult(key=source["key"], ok=False, records=[], http_status=status, error="zero records", page_count=1)
        return SourceResult(key=source["key"], ok=True, records=records, http_status=status, parsed_count=len(records), page_count=1)
