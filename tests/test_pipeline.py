import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

pytest.importorskip("bs4")

from radar.pipeline import run
from radar.config import repo_root
from radar.collectors.frontiers import select_deadline_targets
from radar.ids import content_hash
from radar.models import RawRecord, SourceResult
from support import workspace_tempdir


def test_offline_run_writes_migrated_contract_to_temp_root() -> None:
    source_root = repo_root()
    root = Path.cwd() / f".pipeline-test-{uuid4().hex}"
    root.mkdir()
    try:
        (root / "config").mkdir()
        (root / "data").mkdir()
        (root / "schema").mkdir()
        (root / "state").mkdir()
        for relative in ("config/sources.yml", "config/domains.yml", "config/alerts.yml", "schema/collection.schema.json"):
            target = root / relative
            target.write_bytes((source_root / relative).read_bytes())
        (root / "data/collections.jsonl").write_text("", encoding="utf-8")
        (root / "state/notification_ledger.jsonl").write_text("", encoding="utf-8")

        assert run(root, dry_run=True, offline=True) == 0
        assert (root / "data/collections.jsonl").read_text(encoding="utf-8") == ""
        status = json.loads((root / "data/source_status.json").read_text(encoding="utf-8"))
        assert status["sources"]["frontiers-psychology"]["deadline_enrichment"]["remaining"] == 0
        assert (root / "OPEN.md").exists()
        assert (root / "state/notification_ledger.jsonl").read_text(encoding="utf-8") == ""
    finally:
        for path in sorted(root.rglob("*"), reverse=True):
            if path.is_file():
                path.unlink()
            else:
                path.rmdir()
        root.rmdir()


def test_pipeline_passes_only_new_frontiers_ids_to_deadline_queue(monkeypatch) -> None:
    source_root = repo_root()
    with workspace_tempdir("pipeline-existing-frontiers") as root:
        for directory in ("config", "data", "schema", "state"):
            (root / directory).mkdir()
        for relative in (
            "config/sources.yml",
            "config/domains.yml",
            "config/alerts.yml",
            "schema/collection.schema.json",
        ):
            (root / relative).write_bytes((source_root / relative).read_bytes())

        checked_at = (datetime.now(UTC) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        rows = [
            {
                "id": "frontiers-psychology-existing-listed",
                "title": "Existing listed",
                "journal": "Frontiers in Psychology",
                "publisher": "Frontiers",
                "venue_type": "journal",
                "collection_type": "research_topic",
                "url": "https://frontiersin.org/research-topics/101/existing-listed",
                "source_url": "https://frontiersin.org/journals/psychology/research-topics",
                "source_section": None,
                "deadline": "2027-04-21",
                "deadline_status": "listed",
                "deadline_checked_at": checked_at,
                "metadata_checked_at": checked_at,
                "status": "open",
                "summary": None,
                "domains": ["psychology"],
                "domain_scores": {"psychology": 1.0},
                "topics": [],
                "classification_method": "source_rule",
                "first_seen": "2026-08-01",
                "last_changed": "2026-08-01T00:00:00Z",
                "content_hash": "",
                "extraction_method": "parser",
                "discovered_via": "frontiers-psychology",
                "submission_mode": "open_call",
            },
            {
                "id": "frontiers-psychology-existing-not-listed",
                "title": "Existing not listed",
                "journal": "Frontiers in Psychology",
                "publisher": "Frontiers",
                "venue_type": "journal",
                "collection_type": "research_topic",
                "url": "https://frontiersin.org/research-topics/102/existing-not-listed",
                "source_url": "https://frontiersin.org/journals/psychology/research-topics",
                "source_section": None,
                "deadline": None,
                "deadline_status": "not_listed",
                "deadline_checked_at": checked_at,
                "metadata_checked_at": checked_at,
                "status": "open",
                "summary": None,
                "domains": ["psychology"],
                "domain_scores": {"psychology": 1.0},
                "topics": [],
                "classification_method": "source_rule",
                "first_seen": "2026-08-01",
                "last_changed": "2026-08-01T00:00:00Z",
                "content_hash": "",
                "extraction_method": "parser",
                "discovered_via": "frontiers-psychology",
                "submission_mode": "open_call",
            },
        ]
        for row in rows:
            row["content_hash"] = content_hash(row)
        (root / "data/collections.jsonl").write_text(
            "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows),
            encoding="utf-8",
        )
        (root / "state/notification_ledger.jsonl").write_text("", encoding="utf-8")

        def fake_run_source(_fetcher, source):
            if source["key"] != "frontiers-psychology":
                return SourceResult(key=source["key"], ok=True, records=[])
            return SourceResult(
                key=source["key"],
                ok=True,
                records=[
                    RawRecord(
                        title="Existing listed",
                        url=rows[0]["url"],
                        source_url=rows[0]["source_url"],
                        publisher="Frontiers",
                        journal="Frontiers in Psychology",
                        collection_type="research_topic",
                        discovered_via="frontiers-psychology",
                        status="open",
                        extra={"id": rows[0]["id"]},
                    ),
                    RawRecord(
                        title="Existing not listed",
                        url=rows[1]["url"],
                        source_url=rows[1]["source_url"],
                        publisher="Frontiers",
                        journal="Frontiers in Psychology",
                        collection_type="research_topic",
                        discovered_via="frontiers-psychology",
                        status="open",
                        extra={"id": rows[1]["id"]},
                    ),
                ],
                parsed_count=2,
                page_count=1,
            )

        class _ClosedFetcher:
            def __init__(self, *_args, **_kwargs):
                self.min_interval_seconds = 0

            def close(self):
                pass

        enrichment_calls: list[set[str]] = []

        def fake_enrich(_fetcher, current_rows, source, **kwargs):
            incoming_ids = set(kwargs.get("incoming_ids") or set())
            enrichment_calls.append(incoming_ids)
            assert not incoming_ids
            assert all(row["deadline_status"] in {"listed", "not_listed"} for row in current_rows)
            assert select_deadline_targets(
                current_rows,
                source,
                incoming_ids=incoming_ids,
                now=datetime.now(UTC),
            ) == []
            return {
                "target_count": 0,
                "checked": 0,
                "listed": 0,
                "with_deadline": 0,
                "not_listed": 0,
                "failed": 0,
                "rate_limited": 0,
                "parse_errors": 0,
                "forbidden": 0,
                "remaining": 0,
            }

        monkeypatch.setattr("radar.pipeline.run_source", fake_run_source)
        monkeypatch.setattr("radar.pipeline.Fetcher", _ClosedFetcher)
        monkeypatch.setattr("radar.pipeline.enrich_deadlines", fake_enrich)

        assert run(root, dry_run=True) == 0
        assert enrichment_calls == [set()]


def test_only_preserves_other_source_status(monkeypatch) -> None:
    source_root = repo_root()
    with workspace_tempdir("pipeline-only-status") as root:
        for directory in ("config", "data", "schema", "state"):
            (root / directory).mkdir()
        for relative in (
            "config/sources.yml",
            "config/domains.yml",
            "config/alerts.yml",
            "schema/collection.schema.json",
        ):
            (root / relative).write_bytes((source_root / relative).read_bytes())
        (root / "data/collections.jsonl").write_text("", encoding="utf-8")
        (root / "state/notification_ledger.jsonl").write_text("", encoding="utf-8")
        (root / "data/source_status.json").write_text(
            json.dumps(
                {
                    "checked_at": "2026-08-01T00:00:00Z",
                    "sources": {
                        "nature-psychology": {
                            "enabled": True,
                            "ok": True,
                            "http_status": 200,
                            "parsed": 55,
                            "pages": 6,
                            "error": None,
                        }
                    },
                }
            )
            + "\n",
            encoding="utf-8",
        )

        called: list[str] = []

        def fake_run_source(_fetcher, source):
            called.append(source["key"])
            return SourceResult(key=source["key"], ok=True, records=[], parsed_count=0, page_count=1)

        class _ClosedFetcher:
            def __init__(self, *_args, **_kwargs):
                self.min_interval_seconds = 0

            def close(self):
                pass

        monkeypatch.setattr("radar.pipeline.run_source", fake_run_source)
        monkeypatch.setattr("radar.pipeline.Fetcher", _ClosedFetcher)
        monkeypatch.setattr(
            "radar.pipeline.enrich_deadlines",
            lambda *_args, **_kwargs: {
                "target_count": 0,
                "checked": 0,
                "listed": 0,
                "with_deadline": 0,
                "not_listed": 0,
                "failed": 0,
                "rate_limited": 0,
                "parse_errors": 0,
                "forbidden": 0,
                "remaining": 0,
            },
        )

        assert run(root, dry_run=True, only={"frontiers-psychology"}) == 0
        assert called == ["frontiers-psychology"]
        status = json.loads((root / "data/source_status.json").read_text(encoding="utf-8"))
        assert status["sources"]["nature-psychology"]["parsed"] == 55
        assert status["sources"]["frontiers-psychology"]["ok"] is True


def test_cli_keeps_limit_and_only(monkeypatch) -> None:
    from radar.pipeline import main

    captured: dict[str, object] = {}

    monkeypatch.setattr("radar.pipeline.run", lambda _root, **kwargs: captured.update(kwargs) or 0)
    monkeypatch.setattr(
        "radar.pipeline.run_topic_enrichment",
        lambda _root, **kwargs: captured.update({"enrich_limit": kwargs.get("limit")}) or 0,
    )

    assert main(["--only", "frontiers-psychology", "--only", "frontiers-neurology"]) == 0
    assert captured["only"] == {"frontiers-psychology", "frontiers-neurology"}

    captured.clear()
    assert main(["--enrich-topics", "--limit", "50"]) == 0
    assert captured["enrich_limit"] == 50
