from __future__ import annotations

from datetime import date
import json
from pathlib import Path
from typing import Any, Mapping


DEFAULT_COLLECTION_TYPE_LABELS = {
    "collection": "Collection",
    "special_issue": "Special Issue",
    "research_topic": "Research Topic",
    "special_section": "Special Section",
    "special_collection": "Special Collection",
    "theme_issue": "Theme Issue",
    "article_collection": "Article Collection",
    "pacmhci_track": "PACMHCI Track",
}
DEFAULT_DOMAIN_LABELS = {
    "psychology": "Psychology",
    "hci": "HCI",
    "neuroscience": "Neuroscience",
    "robotics": "Robotics",
    "hri": "HRI",
}


def _cell(value: object) -> str:
    return str(value or "").replace("|", "/").replace("\r", " ").replace("\n", " ")


def render_open_md(
    rows: list[dict[str, Any]],
    today: date,
    domain_labels: Mapping[str, str] | None = None,
    type_labels: Mapping[str, str] | None = None,
) -> str:
    """Render only open rows whose deadline is a concrete date."""
    labels = {**DEFAULT_DOMAIN_LABELS, **(domain_labels or {})}
    collection_labels = {**DEFAULT_COLLECTION_TYPE_LABELS, **(type_labels or {})}
    dated = [row for row in rows if row.get("status") == "open" and row.get("deadline")]
    dated.sort(key=lambda row: (_cell(row.get("deadline")), _cell(row.get("title"))))
    lines = [
        "# Open calls",
        "",
        f"Generated {today.isoformat()}. Sorted by deadline.",
        "",
        "| Deadline | Title | Journal | Fields | Type | URL |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in dated:
        fields = ", ".join(labels.get(str(domain), str(domain)) for domain in row.get("domains") or [])
        collection_type = collection_labels.get(
            str(row.get("collection_type")), str(row.get("collection_type") or "")
        )
        lines.append(
            "| "
            + " | ".join(
                (
                    _cell(row.get("deadline")),
                    _cell(row.get("title")),
                    _cell(row.get("journal")),
                    _cell(fields),
                    _cell(collection_type),
                    _cell(row.get("url")),
                )
            )
            + " |"
        )
    lines.append("")
    return "\n".join(lines)


VIEWER_FIELDS = (
    "id",
    "title",
    "summary",
    "journal",
    "journals",
    "domains",
    "topics",
    "collection_type",
    "deadline",
    "deadline_status",
    "url",
    "image_url",
    "image_alt",
    "first_seen",
    "publisher",
    "status",
)


def open_records(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if row.get("status") == "open"]


def viewer_record(row: dict[str, Any]) -> dict[str, Any]:
    return {key: row.get(key) for key in VIEWER_FIELDS}


def render_site_collections(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return open records only, sorted for a stable public JSON file."""
    selected = [viewer_record(row) for row in open_records(rows)]
    selected.sort(key=lambda row: (str(row.get("deadline") or "9999-99-99"), str(row.get("title") or ""), str(row.get("id") or "")))
    return selected


def write_site_collections(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(render_site_collections(rows), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def write_open_md(
    path: Path,
    rows: list[dict[str, Any]],
    today: date,
    domain_labels: Mapping[str, str] | None = None,
    type_labels: Mapping[str, str] | None = None,
) -> None:
    path.write_text(
        render_open_md(rows, today, domain_labels=domain_labels, type_labels=type_labels),
        encoding="utf-8",
    )
