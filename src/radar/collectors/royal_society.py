from __future__ import annotations

from bs4 import BeautifulSoup

from radar.http import Fetcher
from radar.ids import allowed_url, canonicalize_url
from radar.models import RawRecord, SourceResult


class RoyalSocietyCollector:
    key = "royal_society"

    def collect(self, fetcher: Fetcher, source: dict) -> SourceResult:
        status, html = fetcher.get_html(source["url"])
        if status >= 400:
            return SourceResult(key=source["key"], ok=False, records=[], http_status=status, error=f"http {status}")
        if "cf-browser-verification" in html.lower() or "just a moment" in html.lower():
            return SourceResult(key=source["key"], ok=False, records=[], http_status=status, error="bot wall")
        soup = BeautifulSoup(html, "lxml")
        hosts = source.get("allowed_hosts", [])
        found: dict[str, RawRecord] = {}
        for link in soup.find_all("a", href=True):
            href = str(link["href"])
            title = link.get_text(" ", strip=True)
            blob = f"{title} {href}".lower()
            if "collection" not in blob and "special" not in blob:
                continue
            if href.startswith("/"):
                href = "https://royalsocietypublishing.org" + href
            if hosts and not allowed_url(href, hosts):
                continue
            if not title or len(title) < 8:
                continue
            url = canonicalize_url(href)
            found[url] = RawRecord(
                title=title,
                url=url,
                source_url=source["url"],
                publisher=source["publisher"],
                journal=source.get("journal") or "Royal Society Open Science",
                collection_type="special_collection",
                discovered_via=source["key"],
                submission_mode="open_call",
            )
        records = list(found.values())
        if not records:
            return SourceResult(key=source["key"], ok=False, records=[], http_status=status, error="zero records", page_count=1)
        return SourceResult(key=source["key"], ok=True, records=records, http_status=status, parsed_count=len(records), page_count=1)
