from __future__ import annotations

import re

from bs4 import BeautifulSoup, Tag

from radar.http import Fetcher
from radar.ids import allowed_url, canonicalize_url
from radar.models import RawRecord, SourceResult

CFP_HEADING_RE = re.compile(r"call for papers?(?:\s+proposals)?", re.I)
PROPOSAL_RE = re.compile(r"proposal", re.I)


def _heading_title(heading: str) -> str | None:
    text = re.sub(r"\s+", " ", heading).strip()
    match = re.search(r"call for paper(?:s)?(?: proposals)?\s*[-–:]\s*(.+)$", text, re.I)
    if match:
        return match.group(1).strip()
    return None


def _journal_from_block(block: Tag, fallback: str) -> str:
    blob = block.get_text(" ", strip=True)
    for name in (
        "Royal Society Open Science",
        "Open Biology",
        "Philosophical Transactions A",
        "Philosophical Transactions B",
        "Interface Focus",
        "Proceedings A",
        "Proceedings B",
    ):
        if name.lower() in blob.lower():
            return name
    return fallback


def parse_listing(html: str, source: dict) -> list[RawRecord]:
    soup = BeautifulSoup(html, "lxml")
    hosts = source.get("allowed_hosts", [])
    fallback = source.get("journal") or "Royal Society"
    source_url = source["url"]
    found: dict[str, RawRecord] = {}

    for heading in soup.find_all(["h2", "h3"]):
        heading_text = heading.get_text(" ", strip=True)
        if not CFP_HEADING_RE.search(heading_text):
            continue
        parts: list[Tag] = []
        for sibling in heading.next_siblings:
            if getattr(sibling, "name", None) in {"h1", "h2", "h3"}:
                break
            if isinstance(sibling, Tag):
                parts.append(sibling)
        block_soup = BeautifulSoup("".join(str(part) for part in parts), "lxml")
        journal = _journal_from_block(block_soup, fallback)
        heading_cfp = _heading_title(heading_text)
        strong_titles = [tag.get_text(" ", strip=True) for tag in block_soup.find_all("strong") if tag.get_text(" ", strip=True)]
        titles = [heading_cfp] if heading_cfp else [title for title in strong_titles if len(title) >= 8]
        if not titles:
            continue
        links = [a for a in block_soup.find_all("a", href=True)]
        summaries = [p.get_text(" ", strip=True) for p in block_soup.find_all("p") if len(p.get_text(" ", strip=True)) > 40]
        proposal = bool(PROPOSAL_RE.search(heading_text))
        for index, title in enumerate(titles):
            link = links[index] if index < len(links) else (links[-1] if links else None)
            href = str(link["href"]) if link is not None else source_url
            if href.startswith("/"):
                href = "https://royalsociety.org" + href
            if hosts and not allowed_url(href, hosts):
                continue
            url = canonicalize_url(href)
            key = f"{url}#{title.lower()}"
            summary = None
            for paragraph in summaries:
                if title.lower() in paragraph.lower() or len(titles) == 1:
                    summary = paragraph[:1000]
                    break
            if summary is None and summaries:
                summary = summaries[min(index, len(summaries) - 1)][:1000]
            publisher_id = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:80]
            found[key] = RawRecord(
                title=title,
                url=url,
                source_url=source_url,
                publisher=source["publisher"],
                journal=journal,
                collection_type="special_collection",
                discovered_via=source["key"],
                summary=summary,
                submission_mode="invited_or_proposal" if proposal else "open_call",
                publisher_id=publisher_id or None,
                extraction_method="listing",
            )
    return list(found.values())


class RoyalSocietyCollector:
    key = "royal_society"

    def collect(self, fetcher: Fetcher, source: dict) -> SourceResult:
        urls = list(source.get("urls") or [source["url"]])
        records: dict[str, RawRecord] = {}
        pages = 0
        last_status = None
        for url in urls:
            page_source = {**source, "url": url}
            status, html = fetcher.get_html(url)
            last_status = status
            pages += 1
            if status >= 400:
                return SourceResult(
                    key=source["key"], ok=False, records=[], http_status=status, error=f"http {status}", page_count=pages
                )
            lowered = html.lower()
            if "cf-browser-verification" in lowered or "just a moment" in lowered or "access blocked" in lowered:
                return SourceResult(
                    key=source["key"], ok=False, records=[], http_status=status, error="bot wall", page_count=pages
                )
            for record in parse_listing(html, page_source):
                records[f"{record.url}#{record.title.lower()}"] = record
        parsed = list(records.values())
        if not parsed:
            return SourceResult(
                key=source["key"],
                ok=False,
                records=[],
                http_status=last_status,
                error="zero records",
                page_count=pages,
            )
        return SourceResult(
            key=source["key"],
            ok=True,
            records=parsed,
            http_status=last_status,
            parsed_count=len(parsed),
            page_count=pages,
        )
