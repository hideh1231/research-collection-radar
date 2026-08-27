from datetime import UTC, datetime, timedelta
from threading import Event

import pytest

pytest.importorskip("bs4")

from radar.collectors.frontiers import (
    FrontiersCollector,
    enrich_deadlines,
    next_page_url,
    page_matches_record,
    select_deadline_targets,
)
from radar.ids import content_hash


SOURCE = {
    "key": "frontiers-psychology",
    "url": "https://www.frontiersin.org/journals/psychology/research-topics",
    "publisher": "Frontiers",
    "journal": "Frontiers in Psychology",
    "collection_type": "research_topic",
    "allowed_hosts": ["www.frontiersin.org", "frontiersin.org"],
    "deadline_enrichment": {
        "daily_limit": 2,
        "min_interval_seconds": 1,
        "listed_recheck_days": 7,
        "not_listed_recheck_days": 30,
        "checkpoint_size": 25,
    },
}


def _row(number: int, state: str = "not_checked", checked_at: str | None = None) -> dict:
    row = {
        "id": f"frontiers-psychology-{number}",
        "title": f"Topic {number}",
        "journal": "Frontiers in Psychology",
        "collection_type": "research_topic",
        "deadline": "2027-04-21" if state == "listed" else None,
        "deadline_status": state,
        "deadline_checked_at": checked_at,
        "status": "open",
        "summary": None,
        "discovered_via": "frontiers-psychology",
        "url": f"https://frontiersin.org/research-topics/{number}/topic-{number}",
        "content_hash": "",
        "last_changed": "2026-08-01T00:00:00Z",
    }
    row["content_hash"] = content_hash(row)
    return row


def test_next_page_requires_immediate_next_number() -> None:
    current = SOURCE["url"]
    assert next_page_url('<a href="?page=2">2</a>', current, ["frontiersin.org"]).endswith("page=2")
    assert next_page_url('<a href="?page=3">3</a>', current, ["frontiersin.org"]) is None


def test_page_identity_accepts_canonical_and_open_graph_metadata() -> None:
    row = _row(1)
    canonical = '<link rel="canonical" href="https://frontiersin.org/research-topics/1/topic-1">'
    open_graph = '<meta property="og:url" content="https://frontiersin.org/research-topics/1/topic-1">'
    assert page_matches_record(canonical, row)
    assert page_matches_record(open_graph, row)


def test_page_identity_rejects_anchor_only_related_page() -> None:
    row = _row(1)
    html = '<main><a href="https://frontiersin.org/research-topics/1/topic-1">Related topic</a></main>'
    assert not page_matches_record(html, row)


def test_selection_prioritizes_new_then_state_and_budget() -> None:
    old = (datetime.now(UTC) - timedelta(days=8)).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = [_row(1, "listed", old), _row(2, "not_listed", old), _row(3), _row(4, "listed", old)]
    selected = select_deadline_targets(rows, SOURCE, incoming_ids={"frontiers-psychology-4"})
    assert [row["id"] for row in selected] == [
        "frontiers-psychology-4",
        "frontiers-psychology-3",
    ]


class _FakeFetcher:
    min_interval_seconds = 0

    def __init__(self, responses):
        self.responses = iter(responses)

    def get_html(self, url, **kwargs):
        return next(self.responses)


def test_enrichment_updates_state_and_keeps_known_deadline(monkeypatch) -> None:
    monkeypatch.setattr("radar.collectors.frontiers.utc_now", lambda: "2026-08-26T00:00:00Z")
    rows = [_row(1), _row(2, "listed")]
    html = '<link rel="canonical" href="https://frontiersin.org/research-topics/1/topic-1"><p>Manuscript Submission Deadline 21 April 2027</p>'
    no_date = '<link rel="canonical" href="https://frontiersin.org/research-topics/2/topic-2"><p>Submission open</p>'
    stats = enrich_deadlines(_FakeFetcher([(200, html), (200, no_date)]), rows, SOURCE, backfill=False)
    assert stats["checked"] == 2
    assert rows[0]["deadline"] == "2027-04-21"
    assert rows[0]["deadline_status"] == "listed"
    assert rows[1]["deadline"] == "2027-04-21"
    assert rows[1]["deadline_status"] == "listed"
    assert stats["remaining"] == 0


def test_forbidden_stops_without_changing_row() -> None:
    row = _row(1)
    before = dict(row)
    stats = enrich_deadlines(_FakeFetcher([(403, "")]), [row], SOURCE, backfill=True)
    assert stats["stop_reason"] == "forbidden"
    assert stats["remaining"] == 1
    assert row == before


class _ListingFetcher:
    def __init__(self, responses):
        self.responses = iter(responses)

    def get_html(self, url):
        return next(self.responses)


def _listing(topic: int, next_page: bool = False) -> str:
    suffix = '<a rel="next" href="?page=2">next</a>' if next_page else ""
    return f'<a href="/research-topics/{topic}/topic-{topic}">Topic {topic} title</a>{suffix}'


def test_frontiers_http_failure_is_not_partial_success() -> None:
    result = FrontiersCollector().collect(_ListingFetcher([(500, "")]), SOURCE)
    assert result.ok is False
    assert result.records == []


def test_frontiers_zero_records_is_failure() -> None:
    result = FrontiersCollector().collect(_ListingFetcher([(200, "<html></html>")]), SOURCE)
    assert result.ok is False
    assert result.error == "zero records"


def test_frontiers_max_pages_is_failure() -> None:
    source = {**SOURCE, "max_pages": 1}
    result = FrontiersCollector().collect(_ListingFetcher([(200, _listing(1, next_page=True))]), source)
    assert result.ok is False
    assert result.error == "pagination truncated"


def test_frontiers_duplicate_next_page_is_failure() -> None:
    page_one = _listing(1, next_page=True)
    page_two = '<a href="/research-topics/1/topic-1">Topic 1 title</a><a rel="next" href="?page=3">next</a>'
    result = FrontiersCollector().collect(_ListingFetcher([(200, page_one), (200, page_two)]), SOURCE)
    assert result.ok is False
    assert result.records == []
    assert result.error == "pagination page contained no new records"


def _enrichment_source(limit: int) -> dict:
    return {
        **SOURCE,
        "deadline_enrichment": {**SOURCE["deadline_enrichment"], "daily_limit": limit},
    }


def test_checkpoint_persists_final_batch_smaller_than_25(monkeypatch) -> None:
    monkeypatch.setattr("radar.collectors.frontiers.utc_now", lambda: "2026-08-26T00:00:00Z")
    rows = [_row(1)]
    html = '<link rel="canonical" href="https://frontiersin.org/research-topics/1/topic-1"><p>Manuscript Submission Deadline 21 April 2027</p>'
    checkpoints: list[dict] = []
    stats = enrich_deadlines(
        _FakeFetcher([(200, html)]),
        rows,
        _enrichment_source(1),
        backfill=True,
        checkpoint=checkpoints.append,
    )
    assert stats["checked"] == 1
    assert len(checkpoints) == 1
    assert checkpoints[0]["remaining"] == 0


def test_checkpoint_persists_immediate_forbidden_after_success(monkeypatch) -> None:
    monkeypatch.setattr("radar.collectors.frontiers.utc_now", lambda: "2026-08-26T00:00:00Z")
    rows = [_row(1), _row(2)]
    html = '<link rel="canonical" href="https://frontiersin.org/research-topics/1/topic-1"><p>Manuscript Submission Deadline 21 April 2027</p>'
    checkpoints: list[dict] = []
    stats = enrich_deadlines(
        _FakeFetcher([(200, html), (403, "")]),
        rows,
        _enrichment_source(2),
        backfill=True,
        checkpoint=checkpoints.append,
    )
    assert stats["stop_reason"] == "forbidden"
    assert len(checkpoints) == 1
    assert checkpoints[-1]["stop_reason"] == "forbidden"
    assert checkpoints[-1]["checked"] == 1


def test_checkpoint_persists_three_exhausted_rate_limits() -> None:
    rows = [_row(1), _row(2), _row(3)]
    checkpoints: list[dict] = []
    stats = enrich_deadlines(
        _FakeFetcher([(429, ""), (429, ""), (429, "")]),
        rows,
        _enrichment_source(3),
        backfill=True,
        checkpoint=checkpoints.append,
    )
    assert stats["stop_reason"] == "consecutive_rate_limits"
    assert stats["rate_limited"] == 3
    assert len(checkpoints) == 1
    assert checkpoints[-1]["remaining"] == 3


def test_checkpoint_persists_five_exhausted_other_failures() -> None:
    rows = [_row(i) for i in range(1, 6)]
    checkpoints: list[dict] = []
    stats = enrich_deadlines(
        _FakeFetcher([(503, "")] * 5),
        rows,
        _enrichment_source(5),
        backfill=True,
        checkpoint=checkpoints.append,
    )
    assert stats["stop_reason"] == "consecutive_failures"
    assert stats["failed"] == 5
    assert len(checkpoints) == 1


def test_checkpoint_persists_signal_stop_before_request() -> None:
    rows = [_row(1)]
    checkpoints: list[dict] = []
    event = Event()
    event.set()
    stats = enrich_deadlines(
        _FakeFetcher([]),
        rows,
        _enrichment_source(1),
        backfill=True,
        checkpoint=checkpoints.append,
        stop_event=event,
    )
    assert stats["stop_reason"] == "signal"
    assert len(checkpoints) == 1
    assert checkpoints[-1]["remaining"] == 1


def test_checkpoint_occurs_once_at_exact_25_boundary() -> None:
    rows = [_row(i) for i in range(1, 26)]
    target_order = sorted(range(1, 26), key=str)
    htmls = [
        (200, f'<link rel="canonical" href="https://frontiersin.org/research-topics/{i}/topic-{i}"><p>Submission open</p>')
        for i in target_order
    ]
    checkpoints: list[dict] = []
    stats = enrich_deadlines(
        _FakeFetcher(htmls),
        rows,
        _enrichment_source(25),
        backfill=True,
        checkpoint=checkpoints.append,
    )
    assert stats["checked"] == 25
    assert stats["remaining"] == 0
    assert len(checkpoints) == 1
