from __future__ import annotations

import re

from bs4 import BeautifulSoup, Tag

from radar.http import Fetcher
from radar.ids import allowed_url, canonicalize_url
from radar.models import RawRecord, SourceResult
from radar.normalize import parse_date

SPECIAL_HREF = re.compile(r"/special-issue/(\d+)", re.I)
DEADLINE_RE = re.compile(
    r"Submission deadline:\s*(\d{1,2}\s+\w+\s+\d{4}|\d{4}-\d{2}-\d{2})",
    re.I,
)


def _journal_name(card: Tag, fallback: str) -> str:
    block = card.select_one("p.publication-text")
    if block is None:
        return fallback
    text = block.get_text(" ", strip=True)
    name = re.split(r"\s*[•·]\s*", text, maxsplit=1)[0]
    name = re.sub(r"\s+", " ", name).strip()
    return name or fallback


def parse_listing(html: str, source: dict) -> list[RawRecord]:
    soup = BeautifulSoup(html, "lxml")
    hosts = source.get("allowed_hosts", [])
    fallback = source.get("journal") or "ScienceDirect"
    found: dict[str, RawRecord] = {}
    cards = soup.select("li.publication, li.js-publication")
    nodes = cards or soup.find_all("a", href=True)
    for node in nodes:
        if node.name == "a":
            card = node.find_parent(["li", "article", "div"]) or node
            link = node
        else:
            card = node
            link = card.find("a", href=True)
        if link is None:
            continue
        href = str(link["href"])
        match = SPECIAL_HREF.search(href)
        if not match:
            continue
        if href.startswith("/"):
            href = "https://www.sciencedirect.com" + href
        if hosts and not allowed_url(href, hosts):
            continue
        title = link.get_text(" ", strip=True)
        if not title or len(title) < 8:
            continue
        text = card.get_text(" ", strip=True)
        deadline = parse_date(m.group(1) if (m := DEADLINE_RE.search(text)) else None)
        url = canonicalize_url(href)
        journal = _journal_name(card, fallback)
        found[url] = RawRecord(
            title=title,
            url=url,
            source_url=source["url"],
            publisher=source["publisher"],
            journal=journal,
            collection_type="special_issue",
            discovered_via=source["key"],
            deadline=deadline,
            submission_mode="open_call",
            publisher_id=match.group(1),
            extraction_method="listing",
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
        if "there was a problem providing the content you requested" in lowered:
            return SourceResult(key=source["key"], ok=False, records=[], http_status=status, error="bot wall")
        records = parse_listing(html, source)
        if not records:
            return SourceResult(
                key=source["key"], ok=False, records=[], http_status=status, error="zero records", page_count=1
            )
        return SourceResult(
            key=source["key"], ok=True, records=records, http_status=status, parsed_count=len(records), page_count=1
        )
