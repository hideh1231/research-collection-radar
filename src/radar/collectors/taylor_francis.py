from __future__ import annotations

from datetime import date
import json
import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from bs4 import BeautifulSoup

from radar.http import Fetcher
from radar.ids import allowed_url, canonicalize_url, stable_id
from radar.models import RawRecord, SourceResult
from radar.normalize import normalize_status, parse_date


DEFAULT_HOSTS = ["think.taylorandfrancis.com"]
PAGE_HEADER = "X-WP-TotalPages"


def _first_value(value: Any) -> str:
    """Return the first usable scalar from a WordPress custom-field value."""
    if isinstance(value, (list, tuple)):
        for item in value:
            text = _first_value(item)
            if text:
                return text
        return ""
    if isinstance(value, dict):
        for key in ("rendered", "value", "raw"):
            if key in value:
                return _first_value(value[key])
        return ""
    if value is None:
        return ""
    return str(value).strip()


def _normalise_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("\u00a0", " ")).strip().casefold()


def _clean_html(value: str, limit: int = 2000) -> str | None:
    if not value:
        return None
    text = BeautifulSoup(value, "lxml").get_text(" ", strip=True)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    return text[:limit] or None


def _date_from_fields(fields: dict[str, Any]) -> date | None:
    for key in ("_special_issues_deadline", "_special_issues_deadline2"):
        value = _first_value(fields.get(key))
        parsed = parse_date(value)
        if parsed:
            return parsed
    return None


def _expiry_from_item(item: dict[str, Any], fields: dict[str, Any]) -> date | None:
    meta = item.get("meta")
    if not isinstance(meta, dict):
        meta = {}
    for value in (
        fields.get("meta-page-expiry-date"),
        fields.get("_special_issues_page_expiry_date"),
        meta.get("meta-page-expiry-date"),
    ):
        parsed = parse_date(_first_value(value))
        if parsed:
            return parsed
    return None


def _domain_groups(source: dict[str, Any]) -> tuple[list[str], dict[str, list[str]]]:
    selected = source.get("include_domains") or []
    configured = source.get("domain_keywords") or {}
    if isinstance(selected, dict):
        configured = selected
        selected = list(selected)
    if not isinstance(selected, (list, tuple, set)):
        selected = [selected]
    groups: dict[str, list[str]] = {}
    if isinstance(configured, dict):
        for name, words in configured.items():
            if isinstance(words, str):
                words = [words]
            if isinstance(words, (list, tuple, set)):
                groups[str(name)] = [str(word) for word in words if str(word).strip()]
    return [str(name) for name in selected], groups


def _matches_filter(journal: str, title: str, summary: str | None, source: dict[str, Any]) -> tuple[bool, list[str]]:
    include_journals = {
        _normalise_text(str(value)) for value in source.get("include_journals", []) if str(value).strip()
    }
    journal_match = _normalise_text(journal) in include_journals if include_journals else False
    # The journal and title identify the call's subject.  Summaries often mention
    # broad background terms such as “learning” or “behavior” and would admit
    # unrelated calls if they were used for the filter.
    haystack = _normalise_text(" ".join(filter(None, (journal, title))))
    keywords = [str(value).casefold().strip() for value in source.get("include_keywords", []) if str(value).strip()]
    keyword_match = any(keyword in haystack for keyword in keywords)

    selected_domains, groups = _domain_groups(source)
    matched_domains = [
        domain
        for domain in selected_domains
        if any(_normalise_text(keyword) in haystack for keyword in groups.get(domain, []))
    ]
    has_filter = bool(include_journals or keywords or selected_domains)
    return (not has_filter or journal_match or keyword_match or bool(matched_domains)), matched_domains


def _status(deadline: date | None, expiry: date | None, raw_status: str, *, today: date | None = None) -> str:
    today = today or date.today()
    if deadline:
        return "open" if deadline >= today else "closed"
    normalized = normalize_status(raw_status)
    if normalized in {"open", "closed"}:
        return normalized
    if expiry and expiry < today:
        return "closed"
    return "unknown"


def _records_from_payload(payload: Any, source: dict[str, Any]) -> list[RawRecord]:
    if isinstance(payload, dict):
        items = payload.get("records") or payload.get("items") or []
    else:
        items = payload
    if not isinstance(items, list):
        return []

    hosts = source.get("allowed_hosts", DEFAULT_HOSTS)
    found: dict[str, RawRecord] = {}
    for item in items:
        if not isinstance(item, dict) or item.get("status") not in {None, "publish"}:
            continue
        fields = item.get("special_issues")
        if not isinstance(fields, dict):
            fields = {}
        title = _first_value(fields.get("_special_issues_title"))
        if not title:
            title = _first_value(item.get("title"))
        journal = _first_value(fields.get("_special_issues_journal_title")) or str(
            source.get("journal") or "Taylor & Francis"
        )
        summary = _clean_html(_first_value(fields.get("_special_issues_copy")))
        accepted, matched_domains = _matches_filter(journal, title, summary, source)
        if not accepted or not title:
            continue
        href = _first_value(item.get("link"))
        if not href or not allowed_url(href, hosts):
            continue
        url = canonicalize_url(href)
        deadline = _date_from_fields(fields)
        expiry = _expiry_from_item(item, fields)
        configured_today = source.get("today")
        if not isinstance(configured_today, date):
            configured_today = None
        record = RawRecord(
            title=title,
            url=url,
            source_url=canonicalize_url(source["url"]),
            publisher=source["publisher"],
            journal=journal,
            collection_type=source.get("collection_type") or "special_issue",
            discovered_via=source["key"],
            status=_status(deadline, expiry, _first_value(item.get("status")), today=configured_today),
            deadline=deadline,
            summary=summary,
            submission_mode="open_call",
            extraction_method="taylor_francis_rest_api",
            publisher_id=str(item["id"]) if item.get("id") is not None else None,
            extra={
                "id": stable_id(source["key"], url),
                "publisher_id": item.get("id"),
                "page_expiry": expiry.isoformat() if expiry else None,
                "matched_domains": matched_domains,
            },
        )
        found[url] = record
    return list(found.values())


def parse_listing(payload: str | bytes | list[dict[str, Any]] | dict[str, Any], source: dict[str, Any]) -> list[RawRecord]:
    """Parse the public WordPress ``special_issues`` JSON response."""
    if isinstance(payload, (str, bytes)):
        try:
            payload = json.loads(payload)
        except (TypeError, ValueError):
            return []
    return _records_from_payload(payload, source)


def _page_url(base: str, page: int) -> str:
    parsed = urlparse(base)
    query = [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True) if key != "page"]
    query.append(("page", str(page)))
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, urlencode(query), parsed.fragment))


def _header_int(response: Any, name: str) -> int | None:
    try:
        value = response.headers.get(name)
    except AttributeError:
        return None
    try:
        return int(str(value)) if value is not None else None
    except (TypeError, ValueError):
        return None


class TaylorFrancisCollector:
    key = "taylor_francis"

    def collect(self, fetcher: Fetcher, source: dict[str, Any]) -> SourceResult:
        records: dict[str, RawRecord] = {}
        max_pages = max(1, int(source.get("max_pages") or 40))
        page_size = max(1, int(source.get("page_size") or 100))
        current_page = 1
        total_pages: int | None = None
        last_status: int | None = None

        while current_page <= max_pages:
            url = _page_url(source["url"], current_page)
            try:
                response = fetcher.get(url)
            except Exception as exc:
                return SourceResult(
                    key=source["key"], ok=False, records=[], http_status=last_status,
                    error=f"fetch failed: {exc}", page_count=current_page,
                )
            last_status = response.status_code
            if response.status_code >= 400:
                return SourceResult(
                    key=source["key"], ok=False, records=[], http_status=response.status_code,
                    error=f"http {response.status_code}", page_count=current_page,
                )
            try:
                payload = response.json()
            except (TypeError, ValueError):
                return SourceResult(
                    key=source["key"], ok=False, records=[], http_status=response.status_code,
                    error="invalid json", page_count=current_page,
                )
            if not isinstance(payload, list):
                return SourceResult(
                    key=source["key"], ok=False, records=[], http_status=response.status_code,
                    error="unexpected json shape", page_count=current_page,
                )
            for record in parse_listing(payload, {**source, "url": source["url"]}):
                records[record.url] = record
            header_pages = _header_int(response, PAGE_HEADER)
            if header_pages is not None:
                total_pages = header_pages
            if total_pages is not None and current_page >= total_pages:
                break
            if total_pages is None and len(payload) < page_size:
                break
            current_page += 1

        pages = min(current_page, max_pages)
        if current_page > max_pages or (total_pages is not None and total_pages > max_pages):
            return SourceResult(
                key=source["key"], ok=False, records=[], http_status=last_status,
                error="pagination truncated", page_count=pages,
            )
        if not records and not source.get("allow_empty"):
            return SourceResult(
                key=source["key"], ok=False, records=[], http_status=last_status,
                error="zero records", page_count=pages,
            )
        return SourceResult(
            key=source["key"], ok=True, records=list(records.values()), http_status=last_status,
            parsed_count=len(records), page_count=pages,
        )
