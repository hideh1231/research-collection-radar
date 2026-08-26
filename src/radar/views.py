from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any


def render_open_md(rows: list[dict[str, Any]], today: date) -> str:
    open_rows = [row for row in rows if row.get("status") == "open"]
    dated = [row for row in open_rows if row.get("deadline")]
    undated = [row for row in open_rows if not row.get("deadline")]
    dated.sort(key=lambda row: (row["deadline"], row["title"]))
    undated.sort(key=lambda row: row["title"])
    lines = [
        "# Open calls",
        "",
        f"Generated {today.isoformat()}. Sorted by deadline. Rows without a deadline are at the end.",
        "",
        "| Deadline | Title | Journal | Domains | URL |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in dated + undated:
        domains = ", ".join(row.get("domains") or [])
        title = row["title"].replace("|", "/")
        lines.append(
            f"| {row.get('deadline') or ''} | {title} | {row['journal']} | {domains} | {row['url']} |"
        )
    lines.append("")
    return "\n".join(lines)


def write_open_md(path: Path, rows: list[dict[str, Any]], today: date) -> None:
    path.write_text(render_open_md(rows, today), encoding="utf-8")
