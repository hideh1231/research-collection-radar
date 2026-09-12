"""Read manuscript deadlines from identified official PDF/DOCX calls."""
from __future__ import annotations

from io import BytesIO
import re
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree
from zipfile import ZipFile

from pypdf import PdfReader

from radar.ids import allowed_url
from radar.models import RawRecord, SourceResult
from radar.normalize import listing_status, parse_date, utc_now

MAX_BYTES = 10_000_000


def document_text(content: bytes, kind: str) -> str:
    if len(content) > MAX_BYTES:
        raise ValueError("call document exceeds size limit")
    if kind == "pdf":
        reader = PdfReader(BytesIO(content))
        if len(reader.pages) > 20:
            raise ValueError("call document exceeds page limit")
        text = " ".join(page.extract_text() for page in reader.pages)
    elif kind == "docx":
        with ZipFile(BytesIO(content)) as archive:
            info = archive.getinfo("word/document.xml")
            if info.file_size > MAX_BYTES:
                raise ValueError("call document XML exceeds size limit")
            root = ElementTree.fromstring(archive.read(info))
        ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        text = " ".join("".join(p.itertext()) for p in root.findall(".//w:p", ns))
    else:
        raise ValueError("unsupported call document format")
    return re.sub(r"\s+", " ", text).strip()


def parse_document(content: bytes, source: dict, final_url: str) -> RawRecord:
    expected, actual = urlsplit(source["url"]), urlsplit(final_url)
    if (actual.scheme != "https" or not allowed_url(final_url, source["allowed_hosts"])
            or actual.hostname != expected.hostname or unquote(actual.path) != unquote(expected.path)):
        raise ValueError("call document redirected to another page")
    text = document_text(content, source["document_format"])
    words = lambda value: set(re.findall(r"\w+", value.casefold()))
    wanted = words(source["title"])
    if not wanted or not wanted <= words(text):
        raise ValueError("call document title does not match")
    match = re.search(source["deadline_pattern"], text, re.I)
    if not match:
        raise ValueError("manuscript deadline label missing")
    value = re.sub(r"(\d)(?:st|nd|rd|th)\b", r"\1", match.group("date"), flags=re.I)
    deadline = parse_date(value)
    if deadline is None:
        raise ValueError("unrecognized manuscript deadline")
    return RawRecord(
        title=source["title"], url=source["url"], source_url=source["url"],
        publisher=source["publisher"], journal=source["journal"],
        collection_type=source.get("collection_type", "special_issue"),
        discovered_via=source["key"], publisher_id=source["key"],
        deadline=deadline, status=listing_status(deadline),
        extra={"deadline_status": "listed", "deadline_checked_at": utc_now()},
    )


class CallDocumentCollector:
    key = "call_document"

    def collect(self, fetcher, source: dict) -> SourceResult:
        response = fetcher.get(source["url"])
        try:
            if response.status_code != 200:
                raise ValueError(f"http {response.status_code}")
            record = parse_document(response.content, source, str(response.url))
        except Exception as exc:
            return SourceResult(key=source["key"], ok=False, records=[],
                                http_status=response.status_code, error=str(exc))
        return SourceResult(key=source["key"], ok=True, records=[record],
                            http_status=200, parsed_count=1, page_count=1)
