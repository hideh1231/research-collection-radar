from datetime import date
import json

from radar.store import migrate_rows
from radar.views import render_site_collections


def test_viewer_json_contains_only_open_records() -> None:
    rows = [
        {"id": "open", "title": "Open", "status": "open", "journal": "J", "deadline": "2027-01-01", "domains": ["psychology"], "topics": [], "collection_type": "collection"},
        {"id": "closed", "title": "Closed", "status": "closed", "journal": "J", "deadline": "2026-01-01", "domains": [], "topics": [], "collection_type": "collection"},
        {"id": "unknown", "title": "Unknown", "status": "unknown", "journal": "J", "deadline": None, "domains": [], "topics": [], "collection_type": "collection"},
    ]
    payload = render_site_collections(rows)
    assert [row["id"] for row in payload] == ["open"]
    assert all(row["status"] == "open" for row in payload)


def test_migrated_rows_include_viewer_fields() -> None:
    legacy = {
        "id": "frontiers-psychology-12345678",
        "title": "A collection",
        "journal": "Frontiers in Psychology",
        "publisher": "Frontiers",
        "venue_type": "journal",
        "collection_type": "research_topic",
        "url": "https://frontiersin.org/research-topics/12345/a-collection",
        "source_url": "https://frontiersin.org/journals/psychology/research-topics",
        "deadline": None,
        "status": "open",
        "domains": ["psychology"],
        "classification_method": "source_rule",
        "first_seen": "2026-08-01",
        "last_changed": "2026-08-01T00:00:00Z",
        "content_hash": "sha256:legacy",
        "extraction_method": "parser",
        "discovered_via": "frontiers-psychology",
        "submission_mode": "open_call",
    }
    rows, changed = migrate_rows([legacy])
    assert changed is True
    row = rows[0]
    assert row["publisher_id"] == "12345"
    assert row["journals"] == ["Frontiers in Psychology"]
    assert row["source_keys"] == ["frontiers-psychology"]
    assert row["topics_method"] == "none"
    assert row["image_url"] is None
    assert json.dumps(row)


def test_viewer_json_rejects_wide_topic_labels() -> None:
    rows = [
        {
            "id": "open",
            "title": "Open",
            "status": "open",
            "journal": "J",
            "deadline": "2027-01-01",
            "domains": ["psychology"],
            "topics": ["aging", "AI"],
            "collection_type": "collection",
        }
    ]
    payload = render_site_collections(rows)
    assert payload[0]["topics"] == ["aging", "AI"]
    for row in payload:
        assert len(row["topics"]) <= 8
        assert all(len(topic) <= 40 and ";" not in topic for topic in row["topics"])
