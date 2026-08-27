from __future__ import annotations

from datetime import date
import re
import time

from bs4 import BeautifulSoup, Tag

from radar.http import Fetcher
from radar.ids import allowed_url, canonicalize_url
from radar.models import RawRecord, SourceResult
from radar.normalize import normalize_status, parse_date
from urllib.parse import urljoin

COLLECTION_HREF = re.compile(r"/collections/[a-z0-9]+", re.I)
STATUS_RE = re.compile(r"Submission status:\s*(Open|Closed)", re.I)
DEADLINE_RE = re.compile(r"Deadline:\s*([0-9]{1,2}\s+[A-Za-z]+\s+[0-9]{4})", re.I)


def _container_text(node: Tag) -> str:
    parent = node
    for _ in range(4):
        if parent.parent is None:
            break
        parent = parent.parent
        text = parent.get_text(" ", strip=True)
        if "Submission status" in text or "Deadline" in text:
            return text
    return node.parent.get_text(" ", strip=True) if node.parent else node.get_text(" ", strip=True)


def parse_listing(html: str, source: dict) -> list[RawRecord]:
    soup = BeautifulSoup(html, "lxml")
    hosts = source.get("allowed_hosts", ["www.nature.com"])
    found: dict[str, RawRecord] = {}
    cards = soup.select("article.c-card") or soup.find_all("article")
    for article in cards:
        link = article.find("a", href=COLLECTION_HREF)
        if link is None:
            continue
        href = str(link["href"])
        if href.startswith("/"):
            href = "https://www.nature.com" + href
        if not allowed_url(href, hosts):
            continue
        title = link.get_text(" ", strip=True)
        if not title or len(title) < 8:
            continue
        block = article.get_text(" ", strip=True)
        status_el = article.find(attrs={"data-test": "status"})
        date_el = article.find(attrs={"data-test": "end-date"})
        status = normalize_status(status_el.get_text(" ", strip=True) if status_el else block)
        deadline_text = date_el.get_text(" ", strip=True) if date_el else None
        summary_el = article.find(attrs={"data-test": "description"}) or article.select_one(".c-card__summary")
        summary = summary_el.get_text(" ", strip=True)[:1000] if summary_el else None
        img = article.select_one(".c-card__image img, img")
        src = str(img.get("src") or img.get("data-src") or "").strip() if img is not None else ""
        image_url = urljoin("https://www.nature.com", src) if src and not src.startswith("data:") else None
        image_alt = (str(img.get("alt") or "").strip() or title) if img is not None and image_url else None
        url = canonicalize_url(href)
        found[url] = RawRecord(
            title=title,
            url=url,
            source_url=source["url"],
            publisher=source["publisher"],
            journal=source.get("journal") or "Scientific Reports",
            collection_type=source.get("collection_type") or "collection",
            discovered_via=source["key"],
            status=status,
            deadline=parse_date(deadline_text) or parse_date(
                DEADLINE_RE.search(block).group(1) if DEADLINE_RE.search(block) else None
            ),
            summary=summary or None,
            image_url=image_url,
            image_alt=image_alt,
            submission_mode="open_call",
        )
    return list(found.values())


def next_page_url(html: str, current: str) -> str | None:
    soup = BeautifulSoup(html, "lxml")
    nxt = soup.find(attrs={"data-test": "page-next"})
    if nxt:
        link = nxt.find("a", href=True) if nxt.name != "a" else nxt
        if link and link.get("href"):
            href = str(link["href"]).replace("&#x3D;", "=")
            if href.startswith("/"):
                href = "https://www.nature.com" + href
            return href
    link = soup.find("a", rel="next")
    if link and link.get("href"):
        href = str(link["href"])
        if href.startswith("/"):
            href = "https://www.nature.com" + href
        return href
    return None


class NatureCollector:
    key = "nature"

    def collect(self, fetcher: Fetcher, source: dict) -> SourceResult:
        url = source["url"]
        records: list[RawRecord] = []
        seen_pages: set[str] = set()
        last_status = None
        max_pages = int(source.get("max_pages") or 40)
        pages = 0
        while url and url not in seen_pages and pages < max_pages:
            seen_pages.add(url)
            pages += 1
            status, html = fetcher.get_html(url)
            last_status = status
            if status >= 400:
                return SourceResult(
                    key=source["key"],
                    ok=False,
                    records=[],
                    http_status=status,
                    error=f"http {status}",
                    page_count=pages,
                )
            batch = parse_listing(html, source)
            records.extend(batch)
            nxt = next_page_url(html, url)
            if nxt == url:
                break
            url = nxt
            if url:
                time.sleep(0.4)
        unique: dict[str, RawRecord] = {row.url: row for row in records}
        if pages >= max_pages and url:
            return SourceResult(
                key=source["key"],
                ok=False,
                records=[],
                http_status=last_status,
                error="pagination truncated",
                page_count=pages,
            )
        if not unique:
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
            records=list(unique.values()),
            http_status=last_status,
            parsed_count=len(unique),
            page_count=pages,
        )
