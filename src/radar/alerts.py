from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def new_alert_key(record_id: str) -> str:
    return f"{record_id}:new"


def ledger_keys(rows: list[dict[str, Any]]) -> set[str]:
    return {row["alert_key"] for row in rows}


def new_records(current: list[dict[str, Any]], prior_ids: set[str]) -> list[dict[str, Any]]:
    return [row for row in current if row["id"] not in prior_ids]


def digest_text(records: list[dict[str, Any]], limit: int = 30) -> str:
    shown = records[:limit]
    lines = [f"{len(records)} new collection(s)."]
    for row in shown:
        domains = " · ".join(d.upper() for d in row.get("domains") or [])
        prefix = f"[{domains}] " if domains else ""
        deadline = row.get("deadline") or "no deadline"
        lines.append(f"• {prefix}{row['title']}\n  {row['journal']} · {deadline}\n  {row['url']}")
    if len(records) > limit:
        lines.append(f"… {len(records) - limit} more in OPEN.md")
    return "\n".join(lines)


def ledger_entries(records: list[dict[str, Any]]) -> list[dict[str, str]]:
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return [{"alert_key": new_alert_key(row["id"]), "sent_at": now} for row in records]
