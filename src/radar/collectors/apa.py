from __future__ import annotations

import re

from bs4 import BeautifulSoup, Tag

from radar.http import Fetcher
from radar.ids import allowed_url, canonicalize_url
from radar.models import RawRecord, SourceResult
from radar.normalize import parse_date

GENERAL_RE = re.compile(
    r"general call for papers|call-for-papers-general|special issue proposals|"
    r"call-for-proposals-special-issues",
    re.I,
)
SKIP_HREF_RE = re.compile(r"covid-19-calls-for-papers|/pubs/journals/resources(?:/|$)", re.I)
DATE_RE = re.compile(
    r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+\d{1,2}\s*,?\s*\d{4}",
    re.I,
)
MANUSCRIPT_LABEL_RE = re.compile(
    r"((?:January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+\d{1,2}\s*,?\s*\d{4})\s*:?\s*"
    r"(?:manuscript submission deadline|full manuscripts? due|full papers submission deadline|"
    r"deadline for manuscript|submission deadline)",
    re.I,
)


def _journal_name(module: Tag) -> str | None:
    title = module.select_one("p.title")
    if title:
        name = title.get_text(" ", strip=True)
        return re.sub(r"\s+", " ", name).strip() or None
    return None


def _deadline(text: str):
    labeled = list(MANUSCRIPT_LABEL_RE.finditer(text))
    if labeled:
        return parse_date(labeled[-1].group(1))
    found = [match.group(0) for match in DATE_RE.finditer(text)]
    if not found:
        return None
    return parse_date(found[-1])


def parse_listing(html: str, source: dict) -> list[RawRecord]:
    soup = BeautifulSoup(html, "lxml")
    hosts = source.get("allowed_hosts", [])
    found: dict[str, RawRecord] = {}
    root = soup.find(id="maincontent") or soup
    for module in root.select(".bodyleft") or [root]:
        journal = _journal_name(module) or source.get("journal") or "APA Journals"
        for item in module.find_all("li"):
            link = item.find("a", href=True)
            if link is None:
                continue
            title = link.get_text(" ", strip=True)
            href = str(link["href"])
            if href.startswith("/"):
                href = "https://www.apa.org" + href
            if SKIP_HREF_RE.search(href):
                continue
            if hosts and not allowed_url(href, hosts):
                continue
            if not title or len(title) < 8:
                continue
            if GENERAL_RE.search(title) or GENERAL_RE.search(href):
                continue
            blob = item.get_text(" ", strip=True)
            url = canonicalize_url(href)
            collection_type = (
                "special_section" if "special section" in title.lower() else "special_issue"
            )
            found[url] = RawRecord(
                title=title,
                url=url,
                source_url=source["url"],
                publisher=source["publisher"],
                journal=journal,
                collection_type=collection_type,
                discovered_via=source["key"],
                deadline=_deadline(blob),
                submission_mode="open_call",
                extraction_method="listing",
            )
    return list(found.values())


class ApaCollector:
    key = "apa"

    def collect(self, fetcher: Fetcher, source: dict) -> SourceResult:
        status, html = fetcher.get_html(source["url"])
        if status >= 400:
            return SourceResult(key=source["key"], ok=False, records=[], http_status=status, error=f"http {status}")
        if "incapsula" in html.lower() or "pardon our interruption" in html.lower():
            return SourceResult(key=source["key"], ok=False, records=[], http_status=status, error="bot wall")
        records = parse_listing(html, source)
        if not records:
            return SourceResult(
                key=source["key"], ok=False, records=[], http_status=status, error="zero records", page_count=1
            )
        return SourceResult(
            key=source["key"], ok=True, records=records, http_status=status, parsed_count=len(records), page_count=1
        )
