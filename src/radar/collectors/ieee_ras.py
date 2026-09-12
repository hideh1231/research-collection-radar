from __future__ import annotations

from datetime import date
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from radar.http import Fetcher
from radar.ids import allowed_url, canonicalize_url
from radar.models import RawRecord, SourceResult
from radar.normalize import parse_date

CALL_RE = re.compile(r"(?:cfp\s*:\s*)?special\s+(?:issue|collection|section)", re.I)
DEADLINE_RE = re.compile(
    r"(?:submission|submissions?)\s+(?:deadline|close|closes)\s*:\s*"
    r"([A-Za-z]+\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4}|\d{1,2}\s+[A-Za-z]+\s+\d{4})",
    re.I,
)


def _status(deadline: date | None) -> str:
    if deadline is None:
        return "unknown"
    return "open" if deadline >= date.today() else "closed"


def parse_listing(html: str, source: dict) -> list[RawRecord]:
    soup = BeautifulSoup(html, "lxml")
    hosts = source.get("allowed_hosts", ["www.ieee-ras.org", "ieee-ras.org"])
    found: dict[str, RawRecord] = {}
    for link in soup.find_all("a", href=True):
        title = link.get_text(" ", strip=True)
        if not CALL_RE.search(title):
            continue
        lowered = title.casefold()
        if any(word in lowered for word in ("policy", "proposal", "submission procedures")):
            continue
        href = urljoin(source["url"], str(link["href"]))
        if hosts and not allowed_url(href, hosts):
            continue
        parent = link.find_parent(["tr", "li", "p", "article", "div"]) or link
        text = parent.get_text(" ", strip=True)
        match = DEADLINE_RE.search(text)
        deadline = parse_date(match.group(1) if match else None)
        url = canonicalize_url(href)
        found[url] = RawRecord(
            title=title.removeprefix("CFP:").strip(),
            url=url,
            source_url=source["url"],
            publisher=source["publisher"],
            journal=source["journal"],
            collection_type=source.get("collection_type") or "special_issue",
            discovered_via=source["key"],
            status=_status(deadline),
            deadline=deadline,
            submission_mode="open_call",
        )
    return list(found.values())


class IeeeRasCollector:
    key = "ieee_ras"

    def collect(self, fetcher: Fetcher, source: dict) -> SourceResult:
        status, html = fetcher.get_html(source["url"])
        lowered = html.casefold()
        if status >= 400:
            return SourceResult(
                key=source["key"], ok=False, records=[], http_status=status,
                error=f"http {status}", page_count=1,
            )
        if "just a moment" in lowered or "cf-browser-verification" in lowered:
            return SourceResult(
                key=source["key"], ok=False, records=[], http_status=status,
                error="bot wall", page_count=1,
            )
        records = parse_listing(html, source)
        if not records and not source.get("allow_empty"):
            return SourceResult(
                key=source["key"], ok=False, records=[], http_status=status,
                error="zero records", page_count=1,
            )
        return SourceResult(
            key=source["key"], ok=True, records=records, http_status=status,
            parsed_count=len(records), page_count=1,
        )
