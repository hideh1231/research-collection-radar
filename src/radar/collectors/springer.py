from __future__ import annotations

from bs4 import BeautifulSoup

from radar.http import Fetcher
from radar.ids import allowed_url, canonicalize_url
from radar.models import RawRecord, SourceResult
from radar.normalize import normalize_status, parse_date


def _definition(article, label: str) -> str | None:
    for block in article.select("dl.app-card-collection__description-list"):
        term = block.find("dt")
        if term is None or term.get_text(" ", strip=True).lower() != label.lower():
            continue
        detail = block.find("dd")
        if detail is None:
            return None
        value = detail.get_text(" ", strip=True)
        return value or None
    return None


def parse_listing(html: str, source: dict) -> list[RawRecord]:
    soup = BeautifulSoup(html, "lxml")
    hosts = source.get("allowed_hosts", [])
    found: dict[str, RawRecord] = {}
    for article in soup.select("article.app-card-collection"):
        link = article.select_one("a.app-card-collection__heading-link[href]")
        if link is None:
            continue
        href = str(link["href"])
        if href.startswith("/"):
            href = f"{source['url'].split('/')[0]}//{source['url'].split('/')[2]}{href}"
        if hosts and not allowed_url(href, hosts):
            continue
        title = link.get_text(" ", strip=True)
        if not title or len(title) < 8:
            continue
        teaser = article.select_one(".app-card-collection__text")
        summary = teaser.get_text(" ", strip=True)[:1000] if teaser is not None else None
        status_text = _definition(article, "Submission status") or article.get_text(" ", strip=True)
        deadline_text = _definition(article, "Submission deadline")
        url = canonicalize_url(href)
        found[url] = RawRecord(
            title=title,
            url=url,
            source_url=source["url"],
            publisher=source["publisher"],
            journal=source.get("journal") or "Springer",
            collection_type=source.get("collection_type") or "collection",
            discovered_via=source["key"],
            status=normalize_status(status_text),
            deadline=parse_date(deadline_text) or parse_date(article.get_text(" ", strip=True)),
            summary=summary or None,
            submission_mode="open_call",
        )
    return list(found.values())


class SpringerCollector:
    key = "springer"

    def collect(self, fetcher: Fetcher, source: dict) -> SourceResult:
        status, html = fetcher.get_html(source["url"])
        if status >= 400:
            return SourceResult(key=source["key"], ok=False, records=[], http_status=status, error=f"http {status}")
        records = parse_listing(html, source)
        if not records:
            return SourceResult(key=source["key"], ok=False, records=[], http_status=status, error="zero records", page_count=1)
        return SourceResult(key=source["key"], ok=True, records=records, http_status=status, parsed_count=len(records), page_count=1)
