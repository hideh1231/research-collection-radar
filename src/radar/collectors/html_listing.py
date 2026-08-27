from __future__ import annotations

from datetime import date
import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from radar.http import Fetcher
from radar.ids import allowed_url, canonicalize_url
from radar.models import RawRecord, SourceResult
from radar.normalize import listing_status, parse_date

DEADLINE_RE = re.compile(
    r"(?:manuscript |paper |submission |論文)?(?:deadline|締切|必着)"
    r"(?:\s+for\s+submissions?)?\s*[:：]?\s*"
    r"(\d{1,2}(?:st|nd|rd|th)?\s+\w+\s+\d{4}|\w+\s+\d{1,2},?\s+\d{4}|\d{4}-\d{2}-\d{2}|"
    r"\d{4}年\d{1,2}月\d{1,2}日)",
    re.I,
)
ISO_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
CLOSED_RE = re.compile(r"\bclosed\b|受付終了|募集は終了|論文募集は終了", re.I)
SKIP_TITLE_RE = re.compile(
    r"regular papers?|開発報告|always welcome|call for papers$|filter call|"
    r"login|sign in|cookie|privacy",
    re.I,
)


def _source_urls(source: dict) -> list[str]:
    urls: list[str] = []
    for item in [source.get("url"), *(source.get("urls") or [])]:
        text = str(item or "").strip()
        if text and text not in urls:
            urls.append(text)
    return urls


def _absolute(href: str, base: str) -> str:
    if href.startswith("//"):
        return "https:" + href
    return urljoin(base, href)


def _deadline(text: str) -> date | None:
    jp = re.search(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日", text or "")
    if jp:
        try:
            return date(int(jp.group(1)), int(jp.group(2)), int(jp.group(3)))
        except ValueError:
            pass
    matches = list(DEADLINE_RE.finditer(text or ""))
    for match in reversed(matches):
        parsed = parse_date(match.group(1))
        if parsed:
            return parsed
    iso = ISO_RE.search(text or "")
    return parse_date(iso.group(0) if iso else None)


def _clean_title(title: str) -> str:
    text = re.sub(r"\s+", " ", title or "").strip(" :-–—")
    stripped = re.sub(r"^(?:for a special issue on|special issue(?: on)?)\s+", "", text, flags=re.I)
    if len(stripped) >= 8:
        text = stripped
    text = re.sub(r"^call for papers:\s*", "", text, flags=re.I)
    return text.strip(" “”\"'")


def _skip_title(title: str) -> bool:
    if not title:
        return True
    if len(title) < 4:
        return True
    if len(title) < 8 and not re.search(r"[一-龯ぁ-んァ-ン]", title):
        return True
    return bool(SKIP_TITLE_RE.search(title))


def _make(
    source: dict,
    *,
    title: str,
    url: str,
    journal: str | None = None,
    deadline: date | None = None,
    status: str | None = None,
    summary: str | None = None,
    publisher_id: str | None = None,
) -> RawRecord | None:
    title = _clean_title(title)
    if _skip_title(title):
        return None
    hosts = source.get("allowed_hosts") or []
    if hosts and not allowed_url(url, hosts):
        return None
    closed = status == "closed" or bool(CLOSED_RE.search(title))
    record_status = "closed" if closed else (status or listing_status(deadline))
    canon = canonicalize_url(url)
    listing = canonicalize_url(str(source.get("url") or ""))
    fragment = urlparse(url).fragment.strip()
    if not publisher_id:
        if fragment:
            publisher_id = fragment[:80]
        elif listing and canon == listing:
            title_slug = re.sub(r"[^a-z0-9一-龯ぁ-んァ-ン]+", "-", title.lower()).strip("-")[:50]
            publisher_id = title_slug or canon.rsplit("/", 1)[-1][:80]
        else:
            publisher_id = canon.rsplit("/", 1)[-1][:80]
    return RawRecord(
        title=title,
        url=canon,
        source_url=source["url"],
        publisher=source["publisher"],
        journal=journal or source.get("journal") or source["publisher"],
        collection_type=source.get("collection_type") or "special_issue",
        discovered_via=source["key"],
        deadline=deadline,
        summary=(summary or None) and summary[:1000],
        submission_mode="open_call",
        extraction_method="listing",
        publisher_id=publisher_id,
        status=record_status,
    )


def _heading_blocks(soup: BeautifulSoup, names: tuple[str, ...] = ("h2", "h3")):
    for heading in soup.find_all(names):
        parts: list[Tag] = []
        for sibling in heading.next_siblings:
            if getattr(sibling, "name", None) in {"h1", "h2", "h3"}:
                break
            if isinstance(sibling, Tag):
                parts.append(sibling)
        yield heading, parts


def parse_aps(html: str, source: dict) -> list[RawRecord]:
    soup = BeautifulSoup(html, "lxml")
    found: dict[str, RawRecord] = {}
    current_journal = source.get("journal") or "Journal of Neurophysiology"
    for heading, parts in _heading_blocks(soup, ("h2", "h3")):
        heading_text = heading.get_text(" ", strip=True)
        if not heading_text:
            continue
        if re.search(r"journal of neurophysiology|american journal of physiology|physiological", heading_text, re.I):
            current_journal = heading_text.replace("*", "").strip()
        for part in parts:
            for item in part.find_all("li"):
                link = item.find("a", href=True)
                title = (link.get_text(" ", strip=True) if link else item.get_text(" ", strip=True))
                href = _absolute(str(link["href"]), source["url"]) if link else source["url"]
                text = item.get_text(" ", strip=True)
                anytime = bool(re.search(r"submit anytime|no deadline", text, re.I))
                record = _make(
                    source,
                    title=title,
                    url=href,
                    journal=current_journal,
                    deadline=None if anytime else _deadline(text),
                    status="open" if anytime or not CLOSED_RE.search(text) else "closed",
                )
                if record:
                    found[f"{record.url}#{record.title.lower()}"] = record
    return list(found.values())


def parse_science_robotics(html: str, source: dict) -> list[RawRecord]:
    soup = BeautifulSoup(html, "lxml")
    found: dict[str, RawRecord] = {}
    for heading, parts in _heading_blocks(soup, ("h2", "h3")):
        heading_text = heading.get_text(" ", strip=True)
        if not re.search(r"special issue", heading_text, re.I):
            continue
        blob = " ".join(part.get_text(" ", strip=True) for part in parts)
        link = None
        for part in parts:
            link = part.find("a", href=True) or link
        href = _absolute(str(link["href"]), source["url"]) if link else source["url"]
        record = _make(source, title=heading_text, url=href, deadline=_deadline(blob), summary=blob[:1000])
        if record:
            found[record.title.lower()] = record
    return list(found.values())


def parse_tandf(html: str, source: dict) -> list[RawRecord]:
    soup = BeautifulSoup(html, "lxml")
    found: dict[str, RawRecord] = {}
    hosts = source.get("allowed_hosts") or []
    for card in soup.select("article, .cfp-item, .call-for-papers, li.result, div.card"):
        link = card.find("a", href=True)
        if link is None:
            continue
        href = _absolute(str(link["href"]), source["url"])
        if hosts and not allowed_url(href, hosts):
            continue
        heading = card.find(["h2", "h3", "h4"])
        title = (heading.get_text(" ", strip=True) if heading is not None else "") or link.get_text(" ", strip=True)
        journal_el = card.select_one(".journal, .journal-title, [data-journal]")
        journal = journal_el.get_text(" ", strip=True) if journal_el else source.get("journal")
        if not journal or journal == "Taylor & Francis":
            strong = card.find("strong")
            if strong:
                journal = strong.get_text(" ", strip=True)
        record = _make(
            source,
            title=title,
            url=href,
            journal=journal,
            deadline=_deadline(card.get_text(" ", strip=True)),
            summary=card.get_text(" ", strip=True)[:1000],
        )
        if record:
            found[record.url] = record
    return list(found.values())


def parse_sage(html: str, source: dict) -> list[RawRecord]:
    soup = BeautifulSoup(html, "lxml")
    found: dict[str, RawRecord] = {}
    current_journal = source.get("journal") or "SAGE"
    for node in soup.find_all(["h2", "h3", "h4", "p", "li", "article"]):
        text = node.get_text(" ", strip=True)
        if node.name in {"h2", "h3"} and not re.search(r"deadline|call for", text, re.I):
            if 8 <= len(text) <= 120 and "sage" not in text.lower():
                current_journal = text
            continue
        if not re.search(r"submission deadline|manuscript deadline|deadline:", text, re.I):
            continue
        link = node.find("a", href=True)
        href = _absolute(str(link["href"]), source["url"]) if link else source["url"] + "#" + text[:40]
        title = (link.get_text(" ", strip=True) if link else re.split(r"submission deadline", text, maxsplit=1, flags=re.I)[0])
        record = _make(
            source,
            title=title,
            url=href,
            journal=current_journal,
            deadline=_deadline(text),
        )
        if record:
            found[f"{record.url}#{record.title.lower()}"] = record
    return list(found.values())


def parse_pnas(html: str, source: dict) -> list[RawRecord]:
    soup = BeautifulSoup(html, "lxml")
    found: dict[str, RawRecord] = {}
    for heading, parts in _heading_blocks(soup, ("h2", "h3")):
        heading_text = heading.get_text(" ", strip=True)
        if not re.search(r"call for papers", heading_text, re.I):
            continue
        if heading_text.lower() in {"call for papers", "recent calls for papers:"}:
            for part in parts:
                for link in part.find_all("a", href=True):
                    title = link.get_text(" ", strip=True)
                    href = _absolute(str(link["href"]), source["url"])
                    blob = (link.find_parent(["article", "li", "div"]) or part).get_text(" ", strip=True)
                    record = _make(source, title=title, url=href, deadline=_deadline(blob), journal="PNAS")
                    if record:
                        found[record.url] = record
            continue
        link = None
        blob_parts = []
        for part in parts:
            blob_parts.append(part.get_text(" ", strip=True))
            link = part.find("a", href=True) or link
        href = _absolute(str(link["href"]), source["url"]) if link else source["url"]
        record = _make(source, title=heading_text, url=href, deadline=_deadline(" ".join(blob_parts)), journal="PNAS")
        if record:
            found[record.url] = record
    return list(found.values())


def parse_pnas_nexus(html: str, source: dict) -> list[RawRecord]:
    soup = BeautifulSoup(html, "lxml")
    found: dict[str, RawRecord] = {}
    for link in soup.find_all("a", href=True):
        href = str(link["href"])
        if "call-for-papers" not in href.lower() and "call for papers" not in link.get_text(" ", strip=True).lower():
            continue
        abs_url = _absolute(href, source["url"])
        title = link.get_text(" ", strip=True)
        parent = link.find_parent(["article", "section", "li", "div", "p"]) or link
        record = _make(
            source,
            title=title,
            url=abs_url,
            deadline=_deadline(parent.get_text(" ", strip=True)),
            journal="PNAS Nexus",
        )
        if record:
            found[record.url] = record
    for heading, parts in _heading_blocks(soup, ("h1", "h2")):
        heading_text = heading.get_text(" ", strip=True)
        if not re.search(r"call for papers", heading_text, re.I):
            continue
        blob = " ".join(part.get_text(" ", strip=True) for part in parts)
        record = _make(source, title=heading_text, url=source["url"], deadline=_deadline(blob), journal="PNAS Nexus")
        if record:
            found.setdefault(record.title.lower(), record)
    return list(found.values())


def parse_wiley(html: str, source: dict) -> list[RawRecord]:
    soup = BeautifulSoup(html, "lxml")
    found: dict[str, RawRecord] = {}
    journal = source.get("journal") or "Wiley"
    for heading, parts in _heading_blocks(soup, ("h2", "h3")):
        heading_text = heading.get_text(" ", strip=True)
        if heading_text.lower() in {"call for papers", "calls for papers", "special issues"}:
            continue
        blob = " ".join(part.get_text(" ", strip=True) for part in parts)
        if not re.search(r"deadline|special issue|call for", blob + " " + heading_text, re.I):
            continue
        link = None
        for part in parts:
            link = part.find("a", href=True) or link
        href = _absolute(str(link["href"]), source["url"]) if link else source["url"]
        record = _make(source, title=heading_text, url=href, journal=journal, deadline=_deadline(blob + " " + heading_text))
        if record:
            found[record.title.lower()] = record
    return list(found.values())


def parse_josa(html: str, source: dict) -> list[RawRecord]:
    soup = BeautifulSoup(html, "lxml")
    found: dict[str, RawRecord] = {}
    for heading, parts in _heading_blocks(soup, ("h2", "h3", "h4")):
        heading_text = heading.get_text(" ", strip=True)
        blob = " ".join(part.get_text(" ", strip=True) for part in parts)
        if not re.search(r"submission deadline|submissions open|feature issue", (heading_text + " " + blob), re.I):
            continue
        link = None
        for part in parts:
            link = part.find("a", href=True) or link
        href = _absolute(str(link["href"]), source["url"]) if link else source["url"]
        record = _make(source, title=heading_text, url=href, deadline=_deadline(blob))
        if record:
            found[record.title.lower()] = record
    return list(found.values())


def parse_fujipress(html: str, source: dict) -> list[RawRecord]:
    soup = BeautifulSoup(html, "lxml")
    found: dict[str, RawRecord] = {}
    for heading in soup.find_all(["h3", "h2"]):
        heading_text = heading.get_text(" ", strip=True)
        if "special issue" not in heading_text.lower() and "特集" not in heading_text:
            continue
        blob_parts: list[str] = []
        href = source["url"]
        for sibling in heading.next_siblings:
            if getattr(sibling, "name", None) in {"h2", "h3"}:
                break
            if not isinstance(sibling, Tag):
                continue
            blob_parts.append(sibling.get_text(" ", strip=True))
            link = sibling.find("a", href=True)
            if link and "/cfp/" in str(link.get("href") or ""):
                href = _absolute(str(link["href"]), source["url"])
        blob = " ".join(blob_parts)
        closed = bool(re.search(r"受付終了|\bclosed\b", blob, re.I))
        if re.search(r"regular papers|開発報告募集$|always welcome", heading_text, re.I):
            continue
        record = _make(
            source,
            title=heading_text,
            url=href,
            deadline=_deadline(blob),
            status="closed" if closed else None,
            summary=blob[:1000],
        )
        if record:
            found[record.title.lower()] = record
    return list(found.values())


def parse_vrsj(html: str, source: dict) -> list[RawRecord]:
    soup = BeautifulSoup(html, "lxml")
    found: dict[str, RawRecord] = {}
    for heading in soup.find_all(["h2", "h3", "strong", "b"]):
        heading_text = heading.get_text(" ", strip=True)
        match = re.search(r"【([^】]+)】", heading_text)
        if not match:
            continue
        title = match.group(1)
        parent = heading.find_parent(["table", "section", "div", "article"]) or heading.parent
        blob = parent.get_text(" ", strip=True) if parent else heading_text
        deadline = _deadline(blob)
        record = _make(source, title=title, url=source["url"] + "#" + title, deadline=deadline, summary=blob[:1000])
        if record:
            found[title] = record
    return list(found.values())


def parse_ipsj(html: str, source: dict) -> list[RawRecord]:
    soup = BeautifulSoup(html, "lxml")
    found: dict[str, RawRecord] = {}
    for heading in soup.find_all(["h3", "h2"]):
        heading_text = heading.get_text(" ", strip=True)
        if "特集" not in heading_text:
            continue
        blob_parts: list[str] = []
        href = source["url"]
        for sibling in heading.next_siblings:
            if getattr(sibling, "name", None) in {"h2", "h3"}:
                break
            if not isinstance(sibling, Tag):
                continue
            blob_parts.append(sibling.get_text(" ", strip=True))
            link = sibling.find("a", href=True)
            if link:
                href = _absolute(str(link["href"]), source["url"])
        blob = " ".join(blob_parts)
        closed = bool(re.search(r"募集は終了", blob))
        record = _make(
            source,
            title=heading_text,
            url=href,
            deadline=_deadline(blob),
            status="closed" if closed else None,
        )
        if record:
            found[record.title.lower()] = record
    return list(found.values())


def parse_jske(html: str, source: dict) -> list[RawRecord]:
    soup = BeautifulSoup(html, "lxml")
    found: dict[str, RawRecord] = {}
    for link in soup.find_all("a", href=True):
        title = link.get_text(" ", strip=True)
        if "call for papers" not in title.lower() and "/cfp/" not in str(link["href"]).lower():
            continue
        parent = link.find_parent(["li", "p", "div", "article"]) or link
        href = _absolute(str(link["href"]), source["url"])
        record = _make(source, title=title, url=href, deadline=_deadline(parent.get_text(" ", strip=True)))
        if record:
            found[record.url] = record
    return list(found.values())


PARSERS = {
    "aps": parse_aps,
    "science_robotics": parse_science_robotics,
    "tandf": parse_tandf,
    "sage": parse_sage,
    "pnas": parse_pnas,
    "pnas_nexus": parse_pnas_nexus,
    "wiley": parse_wiley,
    "josa": parse_josa,
    "fujipress": parse_fujipress,
    "vrsj": parse_vrsj,
    "ipsj": parse_ipsj,
    "jske": parse_jske,
}


def parse_listing(html: str, source: dict) -> list[RawRecord]:
    kind = str(source.get("listing_kind") or "")
    parser = PARSERS.get(kind)
    if parser is None:
        raise KeyError(f"unknown listing_kind {kind}")
    return parser(html, source)


class HtmlListingCollector:
    key = "html_listing"

    def collect(self, fetcher: Fetcher, source: dict) -> SourceResult:
        records: list[RawRecord] = []
        last_status = None
        pages = 0
        error = None
        for url in _source_urls(source):
            pages += 1
            status, html = fetcher.get_html(url)
            last_status = status
            lowered = html.lower()
            if status >= 400:
                error = f"http {status}"
                break
            if "cf-browser-verification" in lowered or "pardon our interruption" in lowered:
                error = "bot wall"
                break
            if "captcha page" in lowered and "optica" in lowered:
                error = "bot wall"
                break
            page_source = dict(source)
            page_source["url"] = url
            records.extend(parse_listing(html, page_source))
        unique: dict[str, RawRecord] = {}
        for row in records:
            unique[f"{row.url}#{row.title.lower()}"] = row
        if error:
            return SourceResult(
                key=source["key"],
                ok=False,
                records=[],
                http_status=last_status,
                error=error,
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
