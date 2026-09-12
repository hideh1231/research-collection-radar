from datetime import date
import json

import httpx
import pytest

from radar.config import repo_root
from radar.http import FetchError
from radar.models import RawRecord, SourceResult
from radar.normalize import to_record
from radar.pipeline import main, run
from radar.store import load_jsonl, write_jsonl
from support import copy_radar_config, workspace_tempdir


SOURCES = [
    {"key": "failed", "collector": "html_listing", "enabled": True},
    {"key": "healthy", "collector": "html_listing", "enabled": True},
]


def _raw(key: str, **changes) -> RawRecord:
    values = {
        "title": f"Psychology collection from {key}",
        "url": f"https://example.org/{key}",
        "source_url": "https://example.org/calls",
        "publisher": "Example Publisher",
        "journal": "Example Journal",
        "collection_type": "collection",
        "discovered_via": key,
        "extra": {"id": f"collection-{key}"},
    }
    values.update(changes)
    return RawRecord(**values)


def _record(key: str, **changes) -> dict:
    return to_record(
        _raw(key, **changes), today=date(2026, 8, 1), domains=["psychology"],
        domain_scores={"psychology": 0.8}, topics=[], classification_method="keyword",
    )


@pytest.fixture
def isolated_root(monkeypatch):
    class ClosedFetcher:
        def __init__(self, *_args, **_kwargs):
            pass

        def close(self):
            pass

    monkeypatch.setattr("radar.pipeline.Fetcher", ClosedFetcher)
    monkeypatch.setattr("radar.pipeline.load_sources", lambda _root: {"sources": SOURCES})
    monkeypatch.setattr("radar.pipeline.commit_if_actions", lambda *_args: None)
    monkeypatch.setattr("radar.pipeline.credentials", lambda: (None, None))
    with workspace_tempdir("pipeline-resilience") as root:
        copy_radar_config(repo_root(), root)
        yield root


@pytest.mark.parametrize("error", [
    FetchError("https://www.jske.org/", httpx.ConnectTimeout("timed out")),
    ValueError("unexpected publisher markup"),
    None,
])
def test_source_failure_keeps_old_data_and_finishes_healthy_source(isolated_root, monkeypatch, error):
    original = _record("failed")
    write_jsonl(isolated_root / "data/collections.jsonl", [original])
    called = []

    def collect(_fetcher, source):
        called.append(source["key"])
        if source["key"] == "failed":
            if error is not None:
                raise error
            return SourceResult(key="failed", ok=False, records=[], error="bot wall", http_status=403)
        return SourceResult(key="healthy", ok=True, records=[_raw("healthy")], parsed_count=1)

    monkeypatch.setattr("radar.pipeline.run_source", collect)
    assert run(isolated_root, dry_run=True) == 1
    assert called == ["failed", "healthy"]
    rows = {row["id"]: row for row in load_jsonl(isolated_root / "data/collections.jsonl")}
    assert set(rows) == {"collection-failed", "collection-healthy"}
    assert rows[original["id"]] == original
    status = json.loads((isolated_root / "data/source_status.json").read_text(encoding="utf-8"))
    assert status["sources"]["failed"]["ok"] is False
    assert status["sources"]["healthy"]["ok"] is True
    assert (isolated_root / "OPEN.md").exists()
    assert (isolated_root / "site/data/collections.json").exists()


@pytest.mark.parametrize("ingest", [False, True])
def test_selected_success_ignores_prior_unselected_failure(isolated_root, monkeypatch, ingest):
    status_path = isolated_root / "data/source_status.json"
    status_path.parent.mkdir(parents=True)
    old = {"enabled": True, "ok": False, "error": "pagination truncated"}
    status_path.write_text(json.dumps({"sources": {"nature-psychology": old}}), encoding="utf-8")
    monkeypatch.setattr("radar.pipeline.load_sources", lambda _root: {
        "sources": [{**SOURCES[0], "key": "nature-psychology"}, SOURCES[1]],
    })
    monkeypatch.setattr("radar.pipeline.run_source", lambda _f, _s: SourceResult(
        key="healthy", ok=True, records=[_raw("healthy")], parsed_count=1,
    ))
    monkeypatch.setattr("radar.pipeline.parse_listing_html", lambda _s, _html: [_raw("healthy")])
    kwargs = {"only": {"healthy"}}
    if ingest:
        path = isolated_root / "listing.html"
        path.write_text("<html></html>", encoding="utf-8")
        kwargs = {"ingest_html": {"healthy": path}}
    assert run(isolated_root, dry_run=True, **kwargs) == 0
    saved = json.loads(status_path.read_text(encoding="utf-8"))
    assert saved["sources"]["nature-psychology"] == old
    assert saved["sources"]["healthy"]["ok"] is True


@pytest.mark.parametrize("initial_failure", ["send", "credentials"])
def test_unsent_records_retry_after_the_data_was_saved(isolated_root, monkeypatch, initial_failure):
    ledger_path = isolated_root / "state/notification_ledger.jsonl"
    baseline = [{"alert_key": "baseline:new", "sent_at": "2026-08-01T00:00:00Z"}]
    write_jsonl(ledger_path, baseline, key="alert_key")
    monkeypatch.setattr("radar.pipeline.run_source", lambda _f, _s: SourceResult(
        key="healthy", ok=True, records=[_raw("healthy")], parsed_count=1,
    ))
    credentials = [("token", "channel") if initial_failure == "send" else (None, None)]
    monkeypatch.setattr("radar.pipeline.credentials", lambda: credentials[0])
    sent = []
    success = [False]
    monkeypatch.setattr("radar.pipeline.post_message", lambda text, *_args: sent.append(text) or success[0])
    assert run(isolated_root, only={"healthy"}) == (1 if initial_failure == "send" else 0)
    assert len(load_jsonl(isolated_root / "data/collections.jsonl")) == 1
    assert load_jsonl(ledger_path) == baseline
    credentials[0] = ("token", "channel")
    success[0] = True
    assert run(isolated_root, only={"healthy"}) == 0
    delivered_count = len(sent)
    assert "Psychology collection from healthy" in sent[-1]
    assert len(load_jsonl(ledger_path)) == 2
    assert run(isolated_root, only={"healthy"}) == 0
    assert len(sent) == delivered_count


def test_initial_ledger_covers_existing_open_records_without_sending(isolated_root, monkeypatch):
    write_jsonl(isolated_root / "data/collections.jsonl", [_record("healthy")])
    monkeypatch.setattr("radar.pipeline.post_message", lambda *_args: pytest.fail("initial run must not send"))
    assert run(isolated_root, offline=True) == 0
    ledger = load_jsonl(isolated_root / "state/notification_ledger.jsonl")
    assert [row["alert_key"] for row in ledger] == ["collection-healthy:new"]


def test_cross_listed_collection_has_one_merged_notification(isolated_root, monkeypatch):
    ledger_path = isolated_root / "state/notification_ledger.jsonl"
    write_jsonl(ledger_path, [{"alert_key": "baseline:new", "sent_at": "2026-08-01T00:00:00Z"}], key="alert_key")
    monkeypatch.setattr("radar.pipeline.credentials", lambda: ("fake-token", "fake-channel"))
    monkeypatch.setattr("radar.pipeline.run_source", lambda _f, source: SourceResult(
        key=source["key"], ok=True, records=[_raw(source["key"], publisher_id="same-opportunity")], parsed_count=1,
    ))
    sent = []
    monkeypatch.setattr("radar.pipeline.post_message", lambda text, *_args: sent.append(text) or True)
    assert run(isolated_root) == 0
    assert len(sent) == 1
    assert sent[0].startswith("1 new collection(s).")
    rows = load_jsonl(isolated_root / "data/collections.jsonl")
    assert len(rows) == 1
    assert rows[0]["source_keys"] == ["failed", "healthy"]
    assert len(load_jsonl(ledger_path)) == 2


def test_complete_listing_keeps_healthy_records_despite_optional_detail_warning(isolated_root, monkeypatch):
    previous = _record("known", status="open", deadline=date(2027, 1, 1))
    write_jsonl(isolated_root / "data/collections.jsonl", [previous])
    monkeypatch.setattr("radar.pipeline.run_source", lambda _f, _s: SourceResult(
        key="healthy", ok=True, parsed_count=3, error="optional detail unavailable",
        records=[
            _raw("known", status="unknown"),
            _raw("new", status="open", deadline=date(2027, 2, 1)),
            _raw("unknown", status="unknown"),
        ],
    ))
    assert run(isolated_root, dry_run=True, only={"healthy"}) == 0
    rows = {row["id"]: row for row in load_jsonl(isolated_root / "data/collections.jsonl")}
    assert rows["collection-known"]["status"] == "open"
    assert rows["collection-known"]["deadline"] == "2027-01-01"
    assert rows["collection-new"]["deadline"] == "2027-02-01"
    assert rows["collection-unknown"]["status"] == "unknown"
    assert rows["collection-unknown"]["deadline_status"] == "not_checked"
    status = json.loads((isolated_root / "data/source_status.json").read_text(encoding="utf-8"))
    assert status["sources"]["healthy"]["error"] == "optional detail unavailable"


def test_empty_rendered_batch_does_not_skip_explicit_listing(monkeypatch):
    captured = {}
    monkeypatch.setattr("radar.pipeline.run", lambda _root, **kwargs: captured.update(kwargs) or 0)
    with workspace_tempdir("pipeline-rendered-fallback") as root:
        (root / "status.json").write_text('{"pages":{"blocked":{"ok":false}}}', encoding="utf-8")
        html = root / "listing.html"
        html.write_text("<html></html>", encoding="utf-8")
        assert main(["--ingest-rendered", str(root), "--ingest-html", f"healthy={html}"]) == 0
        assert captured["ingest_html"] == {"healthy": html}


@pytest.mark.parametrize("mode", ["only", "ingest"])
def test_unknown_source_keys_fail_before_fetching_or_writing(isolated_root, monkeypatch, capsys, mode):
    monkeypatch.setattr("radar.pipeline.run_source", lambda *_args: pytest.fail("must not fetch invalid selection"))
    kwargs = {"only": {"typo", "healthy"}} if mode == "only" else {
        "ingest_html": {"typo": isolated_root / "does-not-exist.html"},
    }
    assert run(isolated_root, dry_run=True, **kwargs) == 1
    assert "unknown source key(s): typo" in capsys.readouterr().err
    assert not (isolated_root / "data").exists()
    assert not (isolated_root / "OPEN.md").exists()
