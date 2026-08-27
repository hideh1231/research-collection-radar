from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from typing import Any

from jsonschema import Draft202012Validator

from radar.normalize import migrate_record


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


def stage_jsonl(path: Path, rows: list[dict[str, Any]], key: str = "id") -> Path:
    """Write JSONL beside its destination and return the closed temp path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            for row in sorted(rows, key=lambda item: item[key]):
                fh.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return temporary


def replace_staged(staged: Path, destination: Path) -> None:
    """Atomically replace a destination with a same-directory staged file."""
    os.replace(staged, destination)


def write_jsonl_atomic(path: Path, rows: list[dict[str, Any]], key: str = "id") -> None:
    staged = stage_jsonl(path, rows, key=key)
    try:
        replace_staged(staged, path)
    except Exception:
        staged.unlink(missing_ok=True)
        raise


def index_by_id(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {row["id"]: row for row in rows}


def migrate_rows(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], bool]:
    """Migrate legacy rows and report whether their serialized content changed."""
    migrated = [migrate_record(row) for row in rows]
    return migrated, migrated != rows


def load_schema(path: Path) -> Draft202012Validator:
    schema = json.loads(path.read_text(encoding="utf-8"))
    return Draft202012Validator(schema)


def validate_record(row: dict[str, Any], validator: Draft202012Validator) -> list[str]:
    return [f"{'.'.join(str(p) for p in err.path)}: {err.message}" for err in validator.iter_errors(row)]
