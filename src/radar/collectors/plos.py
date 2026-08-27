from __future__ import annotations

from datetime import date
from html import unescape
import re
from typing import Any

from radar.http import Fetcher
from radar.ids import allowed_url, canonicalize_url, stable_id
from radar.models import RawRecord, SourceResult
from radar.normalize import parse_date, canonical_plos_journals

API_DEFAULT = "https://collections.plos.org/wp-json/wp/v2/call_for_papers"
DEADLINE_RE = re.compile(
    r"submission deadline[,:]?\s*"
    r"([A-Za-z]+\s+\d{1,2},?\s+\d{4}|\d{1,2}\s+[A-Za-z]+\s+\d{4}|\d{4}-\d{2}-\d{2})",
    re.I,
)
TAG_RE = re.compile(r"<[^>]+>")
TRUNCATED_RE = re.compile(r"(?:\.\.\.|…)\s*$")
NAV_RE = re.compile(r"more about collections|collections home|browse collections", re.I)


def _plain(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("rendered") or ""
    text = TAG_RE.sub(" ", unescape(str(value or "")))
    return re.sub(r"\s+", " ", text).strip()


def parse_summary(item: dict[str, Any]) -> str | None:
    excerpt = _plain(item.get("excerpt"))
    content = _plain(item.get("content"))
    if content and NAV_RE.search(content):
        content = ""
    if excerpt and not TRUNCATED_RE.search(excerpt):
        return excerpt[:1000]
    if content:
        return content[:1000]
    return excerpt[:1000] or None


def parse_image(item: dict[str, Any], title: str) -> tuple[str | None, str | None]:
    yoast = item.get("yoast_head_json")
    if isinstance(yoast, dict):
        og_image = yoast.get("og_image")
        if isinstance(og_image, list) and og_image:
            first = og_image[0]
            url = first.get("url") if isinstance(first, dict) else None
            if url:
                return str(url), title
    embedded = item.get("_embedded")
    if isinstance(embedded, dict):
        media = embedded.get("wp:featuredmedia")
        if isinstance(media, list) and media and isinstance(media[0], dict):
            url = media[0].get("source_url")
            alt = str(media[0].get("alt_text") or "").strip() or title
            if url:
                return str(url), alt
    return None, None


def parse_journals(text: str, fallback: str) -> tuple[str, list[str]]:
    return canonical_plos_journals([text], fallback)


def parse_cfp_item(item: dict[str, Any], source: dict, *, today: date) -> RawRecord | None:
    title = _plain(item.get("title"))
    link = str(item.get("link") or "")
    if not title or not link:
        return None
    hosts = source.get("allowed_hosts") or []
    if hosts and not allowed_url(link, hosts):
        return None
    blob = " ".join(filter(None, [_plain(item.get("excerpt")), _plain(item.get("content"))]))
    deadline = parse_date(DEADLINE_RE.search(blob).group(1) if DEADLINE_RE.search(blob) else None)
    if deadline:
        status = "closed" if deadline < today else "open"
    else:
        status = "open"
    publisher_id = str(item.get("id") or item.get("slug") or "")
    journal, journals = parse_journals(blob, source.get("journal") or "PLOS")
    url = canonicalize_url(link)
    image_url, image_alt = parse_image(item, title)
    return RawRecord(
        title=title,
        url=url,
        source_url=canonicalize_url(source["url"]),
        publisher=source["publisher"],
        journal=journal,
        collection_type=source.get("collection_type") or "collection",
        discovered_via=source["key"],
        status=status,
        deadline=deadline,
        summary=parse_summary(item),
        image_url=image_url,
        image_alt=image_alt,
        submission_mode="open_call",
        publisher_id=publisher_id or None,
        journals=journals,
        source_keys=[source["key"]],
        extra={"id": stable_id(source["key"], publisher_id or url)},
    )


class PlosCollector:
    key = "plos"

    def collect(self, fetcher: Fetcher, source: dict) -> SourceResult:
        api = str(source.get("api_url") or API_DEFAULT).rstrip("/")
        today = date.today()
        records: dict[str, RawRecord] = {}
        last_status: int | None = None
        advertised_total: int | None = None
        page = 1
        pages = 0
        max_pages = int(source.get("max_pages") or 20)
        while page <= max_pages:
            url = f"{api}?per_page=20&page={page}"
            try:
                if hasattr(fetcher, "get_json"):
                    status, payload, headers = fetcher.get_json(url)
                else:
                    status, text = fetcher.get_html(url)
                    import json

                    payload = json.loads(text) if status < 400 else None
                    headers = {}
            except Exception as exc:
                return SourceResult(
                    key=source["key"], ok=False, records=[], http_status=last_status,
                    error=f"fetch failed: {exc}", page_count=pages,
                )
            last_status = status
            pages += 1
            if page > 1 and status == 400:
                break
            if status >= 400:
                return SourceResult(
                    key=source["key"], ok=False, records=[], http_status=status,
                    error=f"http {status}", page_count=pages,
                )
            if not isinstance(payload, list):
                return SourceResult(
                    key=source["key"], ok=False, records=[], http_status=status,
                    error="listing is not a JSON array", page_count=pages,
                )
            if advertised_total is None:
                total_header = headers.get("x-wp-total") if isinstance(headers, dict) else None
                advertised_total = int(total_header) if total_header and str(total_header).isdigit() else None
            if not payload:
                break
            new_on_page = 0
            for item in payload:
                if not isinstance(item, dict):
                    return SourceResult(
                        key=source["key"], ok=False, records=[], http_status=status,
                        error="incomplete listing", page_count=pages,
                    )
                record = parse_cfp_item(item, source, today=today)
                if record is None:
                    return SourceResult(
                        key=source["key"], ok=False, records=[], http_status=status,
                        error="listing item missing title or url", page_count=pages,
                    )
                key = str(record.publisher_id or record.url)
                if key not in records:
                    records[key] = record
                    new_on_page += 1
            if new_on_page == 0:
                return SourceResult(
                    key=source["key"], ok=False, records=[], http_status=status,
                    error="pagination page contained no new records", page_count=pages,
                )
            if advertised_total is not None and len(records) >= advertised_total:
                break
            page += 1
        else:
            return SourceResult(
                key=source["key"], ok=False, records=[], http_status=last_status,
                error="pagination truncated", page_count=pages,
            )
        if not records:
            return SourceResult(
                key=source["key"], ok=False, records=[], http_status=last_status,
                error="zero records", page_count=pages,
            )
        if advertised_total is None:
            return SourceResult(
                key=source["key"], ok=False, records=[], http_status=last_status,
                error="listing total missing", page_count=pages,
            )
        if len(records) != advertised_total:
            return SourceResult(
                key=source["key"], ok=False, records=[], http_status=last_status,
                error=f"incomplete listing: parsed {len(records)} of {advertised_total}",
                page_count=pages,
            )
        return SourceResult(
            key=source["key"],
            ok=True,
            records=list(records.values()),
            http_status=last_status,
            parsed_count=len(records),
            page_count=pages,
        )
