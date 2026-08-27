from __future__ import annotations

import re

from bs4 import BeautifulSoup, Tag

from radar.http import Fetcher
from radar.ids import allowed_url, canonicalize_url
from radar.models import RawRecord, SourceResult
from radar.normalize import listing_status, parse_date

GENERAL_RE = re.compile(
    r"general call for papers|call-for-papers-general|special issue proposals|"
    r"call-for-proposals-special-issues|proposal guidelines|guidelines for submitting|"
    r"^book and media reviews$",
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
    r"(?:manuscript submission deadline|full manuscripts?(?: submission)? due|"
    r"full papers submission deadline|"
    r"deadline for manuscript|submission deadline|submission of completed manuscripts|"
    r"full invited submissions due|full submission)",
    re.I,
)
PUBLICATION_DATE_RE = re.compile(
    r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
    r"(?:\s+\d{1,2}\s*,?)?\s*\d{4}\s*:?\s*"
    r"(?:anticipated publication|expected publication|publication date|in print|"
    r"issue publication|final decisions? sent)",
    re.I,
)


def _journal_name(module: Tag) -> str | None:
    title = module.select_one("p.title")
    if title:
        name = title.get_text(" ", strip=True)
        return re.sub(r"\s+", " ", name).strip() or None
    return None


def _item_title(item: Tag) -> str:
    parts: list[str] = []
    for child in item.children:
        if isinstance(child, Tag) and child.name == "br":
            break
        text = child.get_text(" ", strip=True) if isinstance(child, Tag) else str(child).strip()
        if text:
            parts.append(text)
    title = re.sub(r"\s+", " ", " ".join(parts)).strip()
    title = re.sub(r"\s*\(no submission deadline\)\s*$", "", title, flags=re.I)
    return title


def _deadline(text: str):
    labeled = list(MANUSCRIPT_LABEL_RE.finditer(text))
    if labeled:
        return parse_date(labeled[-1].group(1))
    cleaned = PUBLICATION_DATE_RE.sub(" ", text)
    found = [match.group(0) for match in DATE_RE.finditer(cleaned)]
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
            publisher_id = None
            if link is None:
                title = _item_title(item)
                href = source["url"]
                publisher_id = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:80] or None
            else:
                title = link.get_text(" ", strip=True)
                href = str(link["href"])
            if href.startswith("/"):
                href = "https://www.apa.org" + href
            if SKIP_HREF_RE.search(href) and link is not None:
                continue
            if hosts and not allowed_url(href, hosts):
                continue
            if not title or len(title) < 8:
                continue
            if GENERAL_RE.search(title) or (link is not None and GENERAL_RE.search(href)):
                continue
            blob = item.get_text(" ", strip=True)
            deadline = _deadline(blob)
            if re.search(r"guidelines for submitting", blob, re.I) and deadline is None:
                continue
            url = canonicalize_url(href)
            collection_type = (
                "special_section" if "special section" in title.lower() else "special_issue"
            )
            key = f"{url}#{publisher_id}" if publisher_id else url
            found[key] = RawRecord(
                title=title,
                url=url,
                source_url=source["url"],
                publisher=source["publisher"],
                journal=journal,
                collection_type=collection_type,
                discovered_via=source["key"],
                deadline=deadline,
                status=listing_status(deadline),
                submission_mode="open_call",
                extraction_method="listing",
                publisher_id=publisher_id,
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
