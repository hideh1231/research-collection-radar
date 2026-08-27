from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Callable, Protocol
from urllib.parse import urljoin

import httpx
import yaml

from radar.ids import content_hash
from radar.normalize import unique_keep_order, utc_now

TOPIC_COUNT_MIN = 3
TOPIC_COUNT_MAX = 6
TOPIC_CHARS_MAX = 40
TOPIC_WORDS_MAX = 6
PUBLISHER_TOPIC_MAX = 8
BATCH_SIZE = 10
CATALOG_MIN_COUNT = 2
CATALOG_MIN_CHARS = 3
CATALOG_PROMPT_LIMIT = 80
CATALOG_STOPWORDS = frozenset({"research", "study", "health", "care", "review"})
ENV_BASE_URL = "RADAR_LLM_BASE_URL"
ENV_API_KEY = "RADAR_LLM_API_KEY"
ENV_MODEL = "RADAR_LLM_MODEL"
SPLIT_RE = re.compile(r"[,;|·•\n]+")
COLON_SPLIT_RE = re.compile(r"\s*:\s*")
LEADING_NOISE_RE = re.compile(r"^(?:[^\w]+|\d+[.)]\s+)+", re.UNICODE)
TRAILING_NOISE_RE = re.compile(r"[\s.;,:\-–—/&|]+$")
PREFIX_RE = re.compile(r"^(?:and|or|the|a|an)\s+", re.I)
WORD_RE = re.compile(r"\S+")


class TopicError(ValueError):
    """Raised when an LLM topic batch is structurally invalid."""


class CompletionsClient(Protocol):
    def complete(self, messages: list[dict[str, str]], model: str) -> str: ...


def load_aliases(root: Path | None = None) -> dict[str, str]:
    from radar.config import repo_root

    root = root or repo_root()
    path = root / "config" / "topic_aliases.yml"
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    aliases = data.get("aliases") or {}
    return {str(key).strip().lower(): str(value).strip() for key, value in aliases.items() if key and value}


def split_keyword_text(value: str) -> list[str]:
    """Split a publisher keyword line without breaking compound terms such as ME/CFS."""
    text = str(value or "").replace("\u2019", "'")
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    parts = COLON_SPLIT_RE.split(text) if text.count(":") >= 2 else [text]
    found: list[str] = []
    for part in parts:
        found.extend(piece.strip() for piece in SPLIT_RE.split(part) if piece.strip())
    return found or [text]


def normalize_topic_label(value: str, aliases: dict[str, str] | None = None) -> str | None:
    text = str(value or "").replace("\u2019", "'")
    text = re.sub(r"\s+", " ", text).strip()
    text = LEADING_NOISE_RE.sub("", text)
    text = TRAILING_NOISE_RE.sub("", text)
    text = PREFIX_RE.sub("", text).strip()
    if not text:
        return None
    mapped = (aliases or {}).get(text.lower())
    label = mapped or text
    if len(label) > TOPIC_CHARS_MAX:
        return None
    if len(WORD_RE.findall(label)) > TOPIC_WORDS_MAX:
        return None
    return label


def normalize_topic_list(
    values: list[str] | None,
    aliases: dict[str, str] | None = None,
    *,
    max_items: int = PUBLISHER_TOPIC_MAX,
) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        for part in split_keyword_text(str(value)):
            label = normalize_topic_label(part, aliases)
            if not label:
                continue
            key = label.lower()
            if key in seen:
                continue
            seen.add(key)
            found.append(label)
            if len(found) >= max_items:
                return found
    return found


def normalize_publisher_keywords(values: list[str], aliases: dict[str, str] | None = None) -> list[str]:
    return normalize_topic_list(values, aliases, max_items=PUBLISHER_TOPIC_MAX)


def split_publisher_keywords(values: list[str] | None) -> list[str]:
    return unique_keep_order([part for value in values or [] for part in split_keyword_text(str(value))])


def apply_publisher_topics(
    row: dict[str, Any],
    *,
    aliases: dict[str, str] | None = None,
    checked_at: str | None = None,
) -> bool:
    keywords = split_publisher_keywords(row.get("publisher_keywords") or [])
    if not keywords:
        return False
    topics = normalize_publisher_keywords(keywords, aliases or load_aliases())
    before = (row.get("topics"), row.get("topics_method"))
    row["publisher_keywords"] = keywords
    row["topics"] = topics
    row["topics_method"] = "publisher"
    row["topics_model"] = None
    row["topics_input_hash"] = None
    row["topics_updated_at"] = checked_at or utc_now()
    row["content_hash"] = content_hash(row)
    return (row.get("topics"), row.get("topics_method")) != before


@dataclass(slots=True)
class CatalogTerm:
    label: str
    count: int
    patterns: tuple[re.Pattern[str], ...]


def _boundary_pattern(term: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![a-z0-9]){re.escape(term.lower())}(?![a-z0-9])")


def _alias_targets(aliases: dict[str, str]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for source, target in aliases.items():
        label = str(target).strip()
        if not label:
            continue
        grouped.setdefault(label, [])
        key = str(source).strip()
        if key and key.lower() != label.lower():
            grouped[label].append(key)
    return grouped


def _allowed_short_labels(aliases: dict[str, str]) -> set[str]:
    return {str(value).strip() for value in aliases.values() if str(value).strip()}


def catalog_label_allowed(label: str, aliases: dict[str, str] | None = None) -> bool:
    text = str(label or "").strip()
    if not text:
        return False
    if text.lower() in CATALOG_STOPWORDS:
        return False
    if len(text) < CATALOG_MIN_CHARS and text not in _allowed_short_labels(aliases or {}):
        return False
    return True


def build_topic_catalog(
    rows: list[dict[str, Any]],
    aliases: dict[str, str] | None = None,
    *,
    open_only: bool = True,
) -> list[CatalogTerm]:
    aliases = aliases or {}
    counts: dict[str, int] = {}
    casing: dict[str, str] = {}
    for row in rows:
        if open_only and row.get("status") != "open":
            continue
        for topic in row.get("topics") or []:
            label = str(topic).strip()
            if not label:
                continue
            key = label.lower()
            counts[key] = counts.get(key, 0) + 1
            casing.setdefault(key, label)

    alias_groups = _alias_targets(aliases)
    terms: dict[str, CatalogTerm] = {}

    def add_term(label: str, count: int) -> None:
        if not catalog_label_allowed(label, aliases):
            return
        key = label.lower()
        needles = [casing.get(key, label), *alias_groups.get(casing.get(key, label), []), *alias_groups.get(label, [])]
        for source, target in aliases.items():
            if str(target).strip().lower() == key:
                needles.append(source)
                needles.append(target)
        seen: set[str] = set()
        patterns: list[re.Pattern[str]] = []
        for needle in needles:
            folded = str(needle).strip().lower()
            if not folded or folded in seen:
                continue
            seen.add(folded)
            patterns.append(_boundary_pattern(folded))
        if not patterns:
            return
        display = casing.get(key, label)
        current = terms.get(key)
        if current is None or count > current.count:
            terms[key] = CatalogTerm(label=display, count=count, patterns=tuple(patterns))

    for key, count in counts.items():
        if count >= CATALOG_MIN_COUNT:
            add_term(casing[key], count)

    for label in alias_groups:
        add_term(label, counts.get(label.lower(), 0))

    return sorted(terms.values(), key=lambda item: (-item.count, item.label.lower()))


def catalog_prompt_labels(catalog: list[CatalogTerm], aliases: dict[str, str] | None = None) -> list[str]:
    aliases = aliases or {}
    preferred = unique_keep_order([str(value).strip() for value in aliases.values() if str(value).strip()])
    rest = [term.label for term in catalog if term.label not in preferred]
    return unique_keep_order([*preferred, *rest])[:CATALOG_PROMPT_LIMIT]


def match_catalog_labels(text: str, catalog: list[CatalogTerm]) -> list[str]:
    haystack = str(text or "").lower()
    if not haystack:
        return []
    found: list[str] = []
    seen: set[str] = set()
    for term in catalog:
        if not any(pattern.search(haystack) for pattern in term.patterns):
            continue
        key = term.label.lower()
        if key in seen:
            continue
        seen.add(key)
        found.append(term.label)
    return found


def overlay_catalog_topics(
    row: dict[str, Any],
    catalog: list[CatalogTerm],
    *,
    checked_at: str | None = None,
) -> bool:
    if row.get("status") != "open":
        return False
    current = [str(item) for item in (row.get("topics") or []) if str(item).strip()]
    if len(current) >= PUBLISHER_TOPIC_MAX:
        return False
    haystack = " ".join(part for part in (row.get("title"), row.get("summary")) if part)
    matches = match_catalog_labels(haystack, catalog)
    if not matches:
        return False
    merged = unique_keep_order([*current, *matches])[:PUBLISHER_TOPIC_MAX]
    if merged == current:
        return False
    row["topics"] = merged
    row["topics_updated_at"] = checked_at or utc_now()
    row["content_hash"] = content_hash(row)
    return True


def apply_catalog_topics(
    rows: list[dict[str, Any]],
    *,
    aliases: dict[str, str] | None = None,
    root: Path | None = None,
    open_only: bool = True,
    checked_at: str | None = None,
) -> int:
    alias_map = aliases if aliases is not None else load_aliases(root)
    catalog = build_topic_catalog(rows, alias_map, open_only=open_only)
    updated = 0
    for row in rows:
        if overlay_catalog_topics(row, catalog, checked_at=checked_at):
            updated += 1
    return updated


def llm_configured(env: dict[str, str] | None = None) -> bool:
    values = env or os.environ
    return bool(values.get(ENV_BASE_URL) and values.get(ENV_API_KEY) and values.get(ENV_MODEL))


def llm_settings(env: dict[str, str] | None = None) -> dict[str, str] | None:
    values = env or os.environ
    if not llm_configured(values):
        return None
    return {
        "base_url": values[ENV_BASE_URL].rstrip("/"),
        "api_key": values[ENV_API_KEY],
        "model": values[ENV_MODEL],
    }


def topics_input_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "title": row.get("title"),
        "journal": row.get("journal"),
        "journals": list(row.get("journals") or []),
        "summary": row.get("summary"),
        "domains": list(row.get("domains") or []),
    }


def topics_input_hash(row: dict[str, Any]) -> str:
    blob = json.dumps(topics_input_payload(row), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


def select_llm_targets(
    rows: list[dict[str, Any]],
    *,
    limit: int,
    open_only: bool = True,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for row in sorted(rows, key=lambda item: (item.get("first_seen", ""), item.get("id", ""))):
        if open_only and row.get("status") != "open":
            continue
        if row.get("publisher_keywords"):
            continue
        if row.get("topics_method") == "publisher":
            continue
        current_hash = topics_input_hash(row)
        if row.get("topics_method") == "llm" and row.get("topics") and row.get("topics_input_hash") == current_hash:
            continue
        selected.append(row)
        if len(selected) >= limit:
            break
    return selected


def batched(items: list[dict[str, Any]], size: int = BATCH_SIZE) -> list[list[dict[str, Any]]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


def _validate_topic_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        raise TopicError("topics must be a list")
    labels: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            raise TopicError("topic values must be strings")
        label = normalize_topic_label(item, load_aliases())
        if not label:
            raise TopicError("topic values must be non-empty")
        if len(label) > TOPIC_CHARS_MAX:
            raise TopicError("topic exceeds character limit")
        key = label.lower()
        if key in seen:
            raise TopicError("duplicate topic")
        seen.add(key)
        labels.append(label)
    if not (TOPIC_COUNT_MIN <= len(labels) <= TOPIC_COUNT_MAX):
        raise TopicError("topic count out of range")
    return labels


def parse_batch_response(text: str, expected_ids: list[str]) -> dict[str, list[str]]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise TopicError("response is not JSON") from exc
    if isinstance(payload, dict) and "topics" in payload and len(payload) == 1:
        payload = payload["topics"]
    if isinstance(payload, dict) and all(key in expected_ids for key in payload):
        items = payload
    elif isinstance(payload, list):
        items = {}
        for entry in payload:
            if not isinstance(entry, dict) or "id" not in entry:
                raise TopicError("batch item missing id")
            items[str(entry["id"])] = entry.get("topics")
    else:
        raise TopicError("batch response has unexpected shape")
    if set(items) != set(expected_ids):
        raise TopicError("batch ids do not match")
    if len(items) != len(expected_ids):
        raise TopicError("batch count does not match")
    parsed: dict[str, list[str]] = {}
    for record_id in expected_ids:
        parsed[record_id] = _validate_topic_list(items[record_id])
    return parsed


def build_prompt(batch: list[dict[str, Any]], catalog_labels: list[str] | None = None) -> list[dict[str, str]]:
    payload = [topics_input_payload(row) for row in batch]
    catalog_note = ""
    if catalog_labels:
        catalog_note = (
            " Prefer these existing labels when they apply: "
            + json.dumps(catalog_labels, ensure_ascii=False)
            + "."
        )
    return [
        {
            "role": "system",
            "content": (
                "Assign 3 to 6 short English research topic labels to each collection. "
                "Use common names such as HCI, HRI, VR, XR, AI, or LLM when they apply."
                f"{catalog_note} "
                "Do not invent publisher keywords. Reply with JSON: "
                '{"topics": {"<id>": ["label", ...]}}.'
            ),
        },
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]


@dataclass(slots=True)
class HttpCompletionsClient:
    base_url: str
    api_key: str
    timeout_seconds: float = 40.0

    def complete(self, messages: list[dict[str, str]], model: str) -> str:
        url = urljoin(self.base_url.rstrip("/") + "/", "chat/completions")
        response = httpx.post(
            url,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={"model": model, "messages": messages, "temperature": 0},
            timeout=self.timeout_seconds,
        )
        if response.status_code == 429:
            raise TopicError("rate limited")
        if response.status_code >= 500:
            raise TopicError(f"server error {response.status_code}")
        if response.status_code >= 400:
            raise TopicError(f"http {response.status_code}")
        data = response.json()
        try:
            return str(data["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError) as exc:
            raise TopicError("completion missing content") from exc


def apply_llm_topics(
    row: dict[str, Any],
    topics: list[str],
    *,
    model: str,
    checked_at: str | None = None,
) -> None:
    previous_topics = list(row.get("topics") or [])
    try:
        row["topics"] = unique_keep_order(topics)
        row["topics_method"] = "llm"
        row["topics_model"] = model
        row["topics_input_hash"] = topics_input_hash(row)
        row["topics_updated_at"] = checked_at or utc_now()
        row["content_hash"] = content_hash(row)
        row["last_changed"] = row["topics_updated_at"]
    except Exception:
        row["topics"] = previous_topics
        raise


@dataclass(slots=True)
class TopicEnrichment:
    target_count: int = 0
    checked: int = 0
    updated: int = 0
    failed: int = 0
    skipped: int = 0
    retried: int = 0
    stop_reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        value = {
            "target_count": self.target_count,
            "checked": self.checked,
            "updated": self.updated,
            "failed": self.failed,
            "skipped": self.skipped,
            "retried": self.retried,
        }
        if self.stop_reason:
            value["stop_reason"] = self.stop_reason
        return value


def _complete_batch(
    client: CompletionsClient,
    batch: list[dict[str, Any]],
    model: str,
    catalog_labels: list[str] | None = None,
) -> dict[str, list[str]]:
    content = client.complete(build_prompt(batch, catalog_labels), model)
    return parse_batch_response(content, [str(row["id"]) for row in batch])


def enrich_topics(
    rows: list[dict[str, Any]],
    *,
    client: CompletionsClient,
    model: str,
    limit: int,
    checkpoint: Callable[[dict[str, Any]], None] | None = None,
    aliases: dict[str, str] | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    alias_map = aliases if aliases is not None else load_aliases(root)
    apply_catalog_topics(rows, aliases=alias_map)
    catalog = build_topic_catalog(rows, alias_map)
    catalog_labels = catalog_prompt_labels(catalog, alias_map)
    targets = select_llm_targets(rows, limit=limit)
    stats = TopicEnrichment(target_count=len(targets), skipped=max(0, 0))
    by_id = {row["id"]: row for row in rows}

    def persist() -> None:
        if checkpoint is not None:
            checkpoint(stats.as_dict())

    for batch in batched(targets, BATCH_SIZE):
        parsed: dict[str, list[str]] | None = None
        try:
            parsed = _complete_batch(client, batch, model, catalog_labels)
        except (TopicError, httpx.HTTPError, OSError):
            stats.retried += 1
            try:
                parsed = _complete_batch(client, batch, model, catalog_labels)
            except (TopicError, httpx.HTTPError, OSError):
                parsed = None
        if parsed is None:
            for row in batch:
                try:
                    one = _complete_batch(client, [row], model, catalog_labels)
                    apply_llm_topics(by_id[row["id"]], one[row["id"]], model=model)
                    overlay_catalog_topics(by_id[row["id"]], catalog)
                    stats.checked += 1
                    stats.updated += 1
                    persist()
                except (TopicError, httpx.HTTPError, OSError, KeyError):
                    stats.failed += 1
                    persist()
            continue
        for row in batch:
            apply_llm_topics(by_id[row["id"]], parsed[row["id"]], model=model)
            overlay_catalog_topics(by_id[row["id"]], catalog)
            stats.checked += 1
            stats.updated += 1
        persist()
    apply_catalog_topics(rows, aliases=alias_map)
    return stats.as_dict()
