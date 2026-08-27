from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import re
from typing import Any

from radar.config import load_yaml, repo_root

_AND_RE = re.compile(r"[&＋]")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
_SPACE_RE = re.compile(r"\s+")
_THE_RE = re.compile(r"^the\s+")


def normalize_journal_name(name: str) -> str:
    text = (name or "").lower().replace("’", "'").replace("–", "-").replace("—", "-")
    text = _AND_RE.sub(" and ", text)
    text = _NON_ALNUM_RE.sub(" ", text)
    text = _SPACE_RE.sub(" ", text).strip()
    return _THE_RE.sub("", text)


def load_journals(root: Path | None = None) -> dict[str, Any]:
    root = root or repo_root()
    path = root / "config" / "journals.yml"
    if not path.exists():
        return {"journals": []}
    data = load_yaml(path) or {}
    data.setdefault("journals", [])
    return data


@lru_cache(maxsize=1)
def _alias_index(root_key: str) -> tuple[tuple[str, str, tuple[str, ...], str], ...]:
    root = Path(root_key)
    rows = []
    for item in load_journals(root).get("journals") or []:
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        aliases = tuple(str(alias).strip() for alias in (item.get("aliases") or []) if str(alias).strip())
        publisher = str(item.get("publisher") or "")
        rows.append((name, normalize_journal_name(name), aliases, publisher))
    return tuple(rows)


def watched_journal_names(root: Path | None = None) -> list[str]:
    root = root or repo_root()
    return [name for name, _norm, _aliases, _pub in _alias_index(str(root.resolve()))]


def match_watched_journal(name: str, root: Path | None = None, *, publisher: str | None = None) -> str | None:
    """Return the canonical watched journal name if `name` matches the allowlist."""
    extracted = normalize_journal_name(name)
    if not extracted:
        return None
    root = root or repo_root()
    wanted_pub = normalize_journal_name(publisher or "")
    for canonical, canonical_norm, aliases, item_publisher in _alias_index(str(root.resolve())):
        if wanted_pub and item_publisher:
            item_norm = normalize_journal_name(item_publisher)
            if item_norm and item_norm not in wanted_pub and wanted_pub not in item_norm:
                continue
        candidates = [canonical_norm, *(normalize_journal_name(alias) for alias in aliases)]
        for candidate in candidates:
            if not candidate:
                continue
            if extracted == candidate:
                return canonical
            words = candidate.split()
            if len(words) < 2:
                continue
            if extracted.startswith(candidate + " ") or candidate.startswith(extracted + " "):
                return canonical
    return None


def journal_is_watched(name: str, root: Path | None = None, *, publisher: str | None = None) -> bool:
    return match_watched_journal(name, root, publisher=publisher) is not None


def clear_journal_cache() -> None:
    _alias_index.cache_clear()
