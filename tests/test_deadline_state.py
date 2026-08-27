from datetime import date
import json

from radar.ids import content_hash
from radar.models import RawRecord
from radar.normalize import migrate_record, to_record
from radar.store import replace_staged, stage_jsonl
from support import workspace_tempdir


def _legacy_row(deadline: str | None) -> dict:
    return {
        "id": "frontiers-psychology-12345678",
        "title": "A collection",
        "journal": "Frontiers in Psychology",
        "publisher": "Frontiers",
        "venue_type": "journal",
        "collection_type": "research_topic",
        "url": "https://frontiersin.org/research-topics/12345/a-collection",
        "source_url": "https://frontiersin.org/journals/psychology/research-topics",
        "source_section": None,
        "deadline": deadline,
        "status": "open",
        "summary": None,
        "domains": ["psychology"],
        "domain_scores": {"psychology": 1.0},
        "topics": [],
        "classification_method": "source_rule",
        "first_seen": "2026-08-01",
        "last_changed": "2026-08-01T00:00:00Z",
        "content_hash": "sha256:legacy",
        "extraction_method": "parser",
        "discovered_via": "frontiers-psychology",
        "submission_mode": "open_call",
    }


def test_migration_adds_state_without_touching_last_changed() -> None:
    row = migrate_record(_legacy_row("2027-04-21"))
    assert row["deadline_status"] == "listed"
    assert row["deadline_checked_at"] is None
    assert row["last_changed"] == "2026-08-01T00:00:00Z"
    assert row["content_hash"] == content_hash(row)

    undated = migrate_record(_legacy_row(None))
    assert undated["deadline_status"] == "not_checked"
    assert undated["deadline_checked_at"] is None


def test_to_record_preserves_only_prior_deadline_fields() -> None:
    previous = migrate_record(_legacy_row("2027-04-21"))
    raw = RawRecord(
        title="Updated title",
        url=previous["url"],
        source_url=previous["source_url"],
        publisher="Frontiers",
        journal=previous["journal"],
        collection_type="research_topic",
        discovered_via="frontiers-psychology",
        status="closed",
        deadline=None,
        extra={"id": previous["id"]},
    )
    current = to_record(
        raw,
        today=date(2026, 8, 26),
        domains=["psychology"],
        domain_scores={"psychology": 1.0},
        topics=[],
        classification_method="source_rule",
        prior={previous["id"]: previous},
    )
    assert current["title"] == "Updated title"
    assert current["status"] == "closed"
    assert current["deadline"] == "2027-04-21"
    assert current["deadline_status"] == "listed"
    assert current["deadline_checked_at"] is None


def test_stage_jsonl_does_not_replace_until_committed() -> None:
    with workspace_tempdir("store-test") as directory:
        path = directory / "collections.jsonl"
        path.write_text('{"id":"old"}\n', encoding="utf-8")
        staged = stage_jsonl(path, [{"id": "new", "value": 1}])
        assert json.loads(path.read_text(encoding="utf-8"))["id"] == "old"
        replace_staged(staged, path)
        assert json.loads(path.read_text(encoding="utf-8"))["id"] == "new"
