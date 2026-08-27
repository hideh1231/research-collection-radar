import json

import httpx
import pytest

from radar.ids import content_hash
from radar.topics import (
    TopicError,
    apply_publisher_topics,
    enrich_topics,
    parse_batch_response,
    select_llm_targets,
    topics_input_hash,
)


def _row(number: int, **updates) -> dict:
    row = {
        "id": f"id-{number}",
        "title": f"Topic {number}",
        "journal": "Frontiers in Psychology",
        "journals": ["Frontiers in Psychology"],
        "summary": "A summary",
        "domains": ["psychology"],
        "status": "open",
        "publisher_keywords": [],
        "topics": [],
        "topics_method": "none",
        "topics_model": None,
        "topics_input_hash": None,
        "first_seen": "2026-08-01",
        "content_hash": "old",
    }
    row.update(updates)
    row["content_hash"] = content_hash(row)
    return row


def test_publisher_keyword_blobs_split_and_reject_sentences() -> None:
    from radar.topics import normalize_topic_list, split_keyword_text

    blob = (
        "Energy-aware multi-robot planning; Fleet-level scheduling and orchestration; "
        "Recharging and battery management; Long-horizon persistent autonomy"
    )
    parts = split_keyword_text(blob)
    assert "Energy-aware multi-robot planning" in parts
    assert "Fleet-level scheduling and orchestration" in parts
    labels = normalize_topic_list([blob, ". Digital Health Technologies", "and neural recovery."])
    assert "Digital Health Technologies" in labels
    assert "neural recovery" in labels
    assert all(";" not in label for label in labels)
    assert all(len(label) <= 40 for label in labels)
    assert split_keyword_text("Orexin/hypocretin") == ["Orexin/hypocretin"]
    assert split_keyword_text("ME/CFS") == ["ME/CFS"]
    assert normalize_topic_list(
        ["Gait variability Dynamic stability Locomotor adaptability Neural control of locomotion"]
    ) == []


def test_publisher_keywords_skip_llm_queue() -> None:
    rows = [
        _row(1, publisher_keywords=["aging", "artificial intelligence"]),
        _row(2),
    ]
    apply_publisher_topics(rows[0])
    selected = select_llm_targets(rows, limit=10)
    assert [row["id"] for row in selected] == ["id-2"]
    assert rows[0]["topics_method"] == "publisher"
    assert "AI" in rows[0]["topics"]


def test_invalid_batch_then_one_by_one(monkeypatch) -> None:
    rows = [_row(1), _row(2)]
    calls: list[int] = []

    class Client:
        def complete(self, messages, model):
            calls.append(len(json.loads(messages[1]["content"])))
            if len(calls) == 1:
                raise TopicError("bad batch")
            if len(calls) == 2:
                raise TopicError("bad batch again")
            payload = json.loads(messages[1]["content"])
            record_id = payload[0]["id"]
            return json.dumps({"topics": {record_id: ["aging", "AI", "well-being"]}})

    stats = enrich_topics(rows, client=Client(), model="deepseek-v4-flash", limit=10)
    assert calls[0] == 2
    assert stats["retried"] == 1
    assert stats["updated"] == 2
    assert rows[0]["topics_method"] == "llm"
    assert rows[0]["topics_model"] == "deepseek-v4-flash"


def test_missing_id_and_duplicates_are_rejected() -> None:
    with pytest.raises(TopicError):
        parse_batch_response('{"topics": {"id-1": ["a", "b", "c"]}}', ["id-1", "id-2"])
    with pytest.raises(TopicError):
        parse_batch_response('{"topics": {"id-1": ["AI", "AI", "aging"]}}', ["id-1"])


def test_http_errors_keep_existing_topics() -> None:
    row = _row(1, topics=["keep-me"], topics_method="llm")
    before = list(row["topics"])

    class Client:
        def complete(self, messages, model):
            raise httpx.HTTPError("network down")

    stats = enrich_topics([row], client=Client(), model="deepseek-v4-flash", limit=10)
    assert stats["failed"] == 1
    assert row["topics"] == before


def test_rate_limit_and_server_error_keep_topics() -> None:
    row = _row(1, topics=["keep-me"], topics_method="llm")

    class Client:
        def __init__(self, code: int):
            self.code = code

        def complete(self, messages, model):
            raise TopicError("rate limited" if self.code == 429 else "server error 503")

    for code in (429, 503):
        row["topics"] = ["keep-me"]
        stats = enrich_topics([row], client=Client(code), model="x", limit=1)
        assert stats["failed"] == 1
        assert row["topics"] == ["keep-me"]


def test_checkpoint_saves_only_successes() -> None:
    rows = [_row(1), _row(2)]
    checkpoints: list[dict] = []

    class Client:
        def complete(self, messages, model):
            payload = json.loads(messages[1]["content"])
            if payload[0]["id"] == "id-2":
                raise TopicError("bad one")
            return json.dumps({"topics": {payload[0]["id"]: ["aging", "AI", "well-being"]}})

    enrich_topics(rows, client=Client(), model="x", limit=10, checkpoint=checkpoints.append)
    assert rows[0]["topics_method"] == "llm"
    assert rows[1]["topics"] == []
    assert checkpoints[-1]["updated"] == 1
    assert checkpoints[-1]["failed"] == 1


def test_unchanged_input_hash_is_not_requeued() -> None:
    row = _row(1, topics=["aging", "AI", "well-being"], topics_method="llm")
    row["topics_input_hash"] = topics_input_hash(row)
    assert select_llm_targets([row], limit=10) == []


def test_catalog_overlay_adds_aliases_and_skips_noise() -> None:
    from radar.topics import apply_catalog_topics, build_prompt, build_topic_catalog, catalog_prompt_labels

    aliases = {
        "artificial intelligence": "AI",
        "human-robot interaction": "HRI",
        "ai": "AI",
    }
    rows = [
        _row(1, title="Aging brains", summary="A study of health and care", topics=["aging"], publisher_keywords=["aging"]),
        _row(2, title="Aging cohorts", summary="Later life", topics=["aging"], publisher_keywords=["aging"]),
        _row(
            3,
            title="Robots and artificial intelligence",
            summary="Human-robot interaction in the clinic",
            topics=["navigation"],
            publisher_keywords=["navigation"],
        ),
        _row(
            4,
            title="One-off fleet phrase",
            summary="Energy-aware multi-robot planning only appears here",
            topics=["Energy-aware multi-robot planning"],
            publisher_keywords=["Energy-aware multi-robot planning"],
        ),
        _row(
            5,
            title="Closed aging",
            summary="Aging and AI",
            status="closed",
            topics=["aging"],
            publisher_keywords=["aging"],
        ),
        _row(
            6,
            title="Full publisher set",
            summary="Artificial intelligence and aging",
            topics=["t1", "t2", "t3", "t4", "t5", "t6", "t7", "t8"],
            publisher_keywords=["t1"],
            topics_method="publisher",
        ),
    ]
    apply_publisher_topics(rows[0], aliases=aliases)
    apply_publisher_topics(rows[1], aliases=aliases)
    apply_publisher_topics(rows[2], aliases=aliases)
    apply_publisher_topics(rows[3], aliases=aliases)
    updated = apply_catalog_topics(rows, aliases=aliases)
    assert updated >= 1
    assert "AI" in rows[2]["topics"]
    assert "HRI" in rows[2]["topics"]
    assert rows[2]["topics_method"] == "publisher"
    assert "health" not in rows[2]["topics"]
    assert "care" not in rows[0]["topics"]
    assert "Energy-aware multi-robot planning" not in rows[2]["topics"]
    assert rows[4]["topics"] == ["aging"]
    assert rows[5]["topics"] == ["t1", "t2", "t3", "t4", "t5", "t6", "t7", "t8"]

    catalog = build_topic_catalog(rows, aliases)
    labels = catalog_prompt_labels(catalog, aliases)
    assert "AI" in labels
    prompt = build_prompt([rows[2]], labels)
    assert "Prefer these existing labels" in prompt[0]["content"]
    assert "AI" in prompt[0]["content"]


def test_llm_result_merges_catalog_matches() -> None:
    aliases = {"artificial intelligence": "AI", "ai": "AI"}
    rows = [
        _row(1, title="Sleep clinic", summary="Circadian work", topics=["sleep"], publisher_keywords=["sleep"]),
        _row(2, title="Sleep lab", summary="Night work", topics=["sleep"], publisher_keywords=["sleep"]),
        _row(3, title="Robots and artificial intelligence", summary="A summary"),
    ]

    class Client:
        def complete(self, messages, model):
            payload = json.loads(messages[1]["content"])
            return json.dumps({"topics": {payload[0]["id"]: ["robotics", "HRI", "caregiving"]}})

    stats = enrich_topics(rows, client=Client(), model="x", limit=10, aliases=aliases)
    assert stats["updated"] == 1
    assert rows[2]["topics_method"] == "llm"
    assert "AI" in rows[2]["topics"]
    assert "robotics" in rows[2]["topics"]
