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
TOPIC_CHARS_MAX = 60
BATCH_SIZE = 10
ENV_BASE_URL = "RADAR_LLM_BASE_URL"
ENV_API_KEY = "RADAR_LLM_API_KEY"
ENV_MODEL = "RADAR_LLM_MODEL"


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


def normalize_topic_label(value: str, aliases: dict[str, str] | None = None) -> str | None:
    text = re.sub(r"\s+", " ", value).strip()
    if not text:
        return None
    mapped = (aliases or {}).get(text.lower())
    return mapped or text


def normalize_publisher_keywords(values: list[str], aliases: dict[str, str] | None = None) -> list[str]:
    return unique_keep_order(
        [label for value in values if (label := normalize_topic_label(value, aliases))]
    )


def apply_publisher_topics(
    row: dict[str, Any],
    *,
    aliases: dict[str, str] | None = None,
    checked_at: str | None = None,
) -> bool:
    keywords = unique_keep_order(row.get("publisher_keywords") or [])
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


def build_prompt(batch: list[dict[str, Any]]) -> list[dict[str, str]]:
    payload = [topics_input_payload(row) for row in batch]
    return [
        {
            "role": "system",
            "content": (
                "Assign 3 to 6 short English research topic labels to each collection. "
                "Use common names such as HCI, HRI, VR, XR, AI, or LLM when they apply. "
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
) -> dict[str, list[str]]:
    content = client.complete(build_prompt(batch), model)
    return parse_batch_response(content, [str(row["id"]) for row in batch])


def enrich_topics(
    rows: list[dict[str, Any]],
    *,
    client: CompletionsClient,
    model: str,
    limit: int,
    checkpoint: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    targets = select_llm_targets(rows, limit=limit)
    stats = TopicEnrichment(target_count=len(targets), skipped=max(0, 0))
    by_id = {row["id"]: row for row in rows}

    def persist() -> None:
        if checkpoint is not None:
            checkpoint(stats.as_dict())

    for batch in batched(targets, BATCH_SIZE):
        parsed: dict[str, list[str]] | None = None
        try:
            parsed = _complete_batch(client, batch, model)
        except (TopicError, httpx.HTTPError, OSError):
            stats.retried += 1
            try:
                parsed = _complete_batch(client, batch, model)
            except (TopicError, httpx.HTTPError, OSError):
                parsed = None
        if parsed is None:
            for row in batch:
                try:
                    one = _complete_batch(client, [row], model)
                    apply_llm_topics(by_id[row["id"]], one[row["id"]], model=model)
                    stats.checked += 1
                    stats.updated += 1
                    persist()
                except (TopicError, httpx.HTTPError, OSError, KeyError):
                    stats.failed += 1
                    persist()
            continue
        for row in batch:
            apply_llm_topics(by_id[row["id"]], parsed[row["id"]], model=model)
            stats.checked += 1
            stats.updated += 1
        persist()
    return stats.as_dict()
