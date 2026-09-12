from __future__ import annotations

from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from radar.http import Fetcher
from radar.ids import allowed_url, canonicalize_url
from radar.models import RawRecord, SourceResult


def parse_listing(html: str, source: dict) -> list[RawRecord]:
    soup = BeautifulSoup(html, "lxml")
    hosts = source.get("allowed_hosts", ["www.nature.com", "nature.com"])
    included = {str(section).casefold() for section in source.get("include_sections", [])}
    found: dict[str, RawRecord] = {}

    for heading in soup.find_all("h3"):
        section = heading.get_text(" ", strip=True)
        if included and section.casefold() not in included:
            continue
        sibling = heading.find_next_sibling()
        while sibling is not None and not (
            isinstance(sibling, Tag) and sibling.name in {"h2", "h3"}
        ):
            if isinstance(sibling, Tag):
                for link in sibling.find_all("a", href=True):
                    href = urljoin(source["url"], str(link["href"]))
                    if "/collections/" not in href or not allowed_url(href, hosts):
                        continue
                    title = link.get_text(" ", strip=True)
                    if len(title) < 8:
                        continue
                    url = canonicalize_url(href)
                    previous = found.get(url)
                    if previous:
                        sections = set((previous.source_section or "").split(", "))
                        sections.add(section)
                        previous.source_section = ", ".join(sorted(filter(None, sections)))
                        continue
                    found[url] = RawRecord(
                        title=title,
                        url=url,
                        source_url=source["url"],
                        publisher=source["publisher"],
                        journal=source["journal"],
                        collection_type=source.get("collection_type") or "collection",
                        discovered_via=source["key"],
                        source_section=section,
                        status="open",
                        submission_mode="open_call",
                    )
            sibling = sibling.find_next_sibling()
    return list(found.values())


class NatureHumanitiesCollector:
    key = "nature_humanities"

    def collect(self, fetcher: Fetcher, source: dict) -> SourceResult:
        status, html = fetcher.get_html(source["url"])
        if status >= 400:
            return SourceResult(
                key=source["key"], ok=False, records=[], http_status=status,
                error=f"http {status}", page_count=1,
            )
        records = parse_listing(html, source)
        if not records:
            return SourceResult(
                key=source["key"], ok=False, records=[], http_status=status,
                error="zero records", page_count=1,
            )
        return SourceResult(
            key=source["key"], ok=True, records=records, http_status=status,
            parsed_count=len(records), page_count=1,
        )
