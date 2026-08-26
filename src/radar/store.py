from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]], key: str = "id") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(rows, key=lambda row: row[key])
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        for row in ordered:
            fh.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def index_by_id(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {row["id"]: row for row in rows}


def load_schema(path: Path) -> Draft202012Validator:
    schema = json.loads(path.read_text(encoding="utf-8"))
    return Draft202012Validator(schema)


def validate_record(row: dict[str, Any], validator: Draft202012Validator) -> list[str]:
    return [f"{'.'.join(str(p) for p in err.path)}: {err.message}" for err in validator.iter_errors(row)]
