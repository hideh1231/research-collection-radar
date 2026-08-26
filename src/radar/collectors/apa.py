from __future__ import annotations

from bs4 import BeautifulSoup

from radar.http import Fetcher
from radar.ids import allowed_url, canonicalize_url
from radar.models import RawRecord, SourceResult
from radar.normalize import parse_date

SPECIAL_HINTS = ("special issue", "special section", "themed issue", "special section")


class ApaCollector:
    key = "apa"

    def collect(self, fetcher: Fetcher, source: dict) -> SourceResult:
        status, html = fetcher.get_html(source["url"])
        if status >= 400:
            return SourceResult(key=source["key"], ok=False, records=[], http_status=status, error=f"http {status}")
        if "incapsula" in html.lower() or "pardon our interruption" in html.lower():
            return SourceResult(key=source["key"], ok=False, records=[], http_status=status, error="bot wall")
        soup = BeautifulSoup(html, "lxml")
        hosts = source.get("allowed_hosts", [])
        found: dict[str, RawRecord] = {}
        for link in soup.find_all("a", href=True):
            title = link.get_text(" ", strip=True)
            href = str(link["href"])
            blob = f"{title} {href}".lower()
            if "call" not in blob and "special" not in blob:
                continue
            if href.startswith("/"):
                href = "https://www.apa.org" + href
            if hosts and not allowed_url(href, hosts):
                continue
            if not title or len(title) < 8:
                continue
            if "general call for papers" in title.lower():
                continue
            parent = link.find_parent(["li", "p", "div", "article"]) or link
            text = parent.get_text(" ", strip=True)
            url = canonicalize_url(href)
            found[url] = RawRecord(
                title=title,
                url=url,
                source_url=source["url"],
                publisher=source["publisher"],
                journal=source.get("journal") or "APA Journals",
                collection_type="special_issue",
                discovered_via=source["key"],
                deadline=parse_date(text),
                submission_mode="open_call",
            )
        records = list(found.values())
        if not records:
            return SourceResult(key=source["key"], ok=False, records=[], http_status=status, error="zero records", page_count=1)
        return SourceResult(key=source["key"], ok=True, records=records, http_status=status, parsed_count=len(records), page_count=1)
