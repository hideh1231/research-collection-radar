from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any


CONTENT_HASH_FIELDS = (
    "title",
    "journal",
    "collection_type",
    "deadline",
    "deadline_status",
    "status",
    "summary",
)

DEADLINE_STATUSES = ("listed", "not_listed", "not_checked")


@dataclass(slots=True)
class RawRecord:
    title: str
    url: str
    source_url: str
    publisher: str
    journal: str
    collection_type: str
    discovered_via: str
    status: str = "open"
    deadline: date | None = None
    summary: str | None = None
    source_section: str | None = None
    submission_mode: str = "open_call"
    venue_type: str = "journal"
    extraction_method: str = "parser"
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SourceResult:
    key: str
    ok: bool
    records: list[RawRecord]
    http_status: int | None = None
    error: str | None = None
    parsed_count: int = 0
    page_count: int = 0
