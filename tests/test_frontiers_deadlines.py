from datetime import UTC, date, datetime, timedelta
from threading import Event

import pytest

pytest.importorskip("bs4")

from radar.collectors.frontiers import (
    FrontiersCollector,
    enrich_deadlines,
    listing_is_complete,
    next_page_url,
    page_matches_record,
    parse_deadline,
    parse_detail,
    parse_listing,
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


def test_listing_complete_allows_two_topic_hub_drift() -> None:
    assert listing_is_complete(3311, 3312) is True
    assert listing_is_complete(2159, 2161) is True
    assert listing_is_complete(2158, 2161) is False
    assert listing_is_complete(50, 50) is True
    assert listing_is_complete(0, 10) is False


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


def test_remaining_counts_past_daily_limit(monkeypatch) -> None:
    monkeypatch.setattr("radar.collectors.frontiers.utc_now", lambda: "2026-08-26T00:00:00Z")
    rows = [_row(1), _row(2), _row(3)]
    html = '<link rel="canonical" href="https://frontiersin.org/research-topics/1/topic-1"><p>Manuscript Submission Deadline 21 April 2027</p>'
    stats = enrich_deadlines(
        _FakeFetcher([(200, html)]),
        rows,
        _enrichment_source(1),
        backfill=False,
    )
    assert stats["checked"] == 1
    assert stats["remaining"] == 2


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


def _listing(topic: int, next_page: bool = False, total: int = 1, title: str | None = None) -> str:
    suffix = '<a rel="next" href="?page=2">next</a>' if next_page else ""
    heading = f'<h1 class="Hub__total--heading">{total} Research Topics</h1>'
    label = title or f"Topic {topic} title"
    return (
        heading
        + f'<article class="CardResearchTopic">'
        + f'<a class="CardResearchTopic__wrapper" href="/research-topics/{topic}/topic-{topic}">'
        + f'<p class="CardResearchTopic__state">Submission open</p>'
        + f'<h2 class="CardResearchTopic__title">{label}</h2>'
        + f"</a></article>{suffix}"
    )


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
    result = FrontiersCollector().collect(_ListingFetcher([(200, _listing(1, next_page=True, total=2))]), source)
    assert result.ok is False
    assert result.error == "pagination truncated"


def test_frontiers_duplicate_next_page_is_failure() -> None:
    page_one = _listing(1, next_page=True, total=2)
    page_two = _listing(1, total=2) + '<a rel="next" href="?page=3">next</a>'
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


def test_listing_title_ignores_status_editors_and_metrics() -> None:
    html = _listing(9, total=1, title="Clean research title")
    parsed = parse_listing(html, SOURCE)
    assert parsed.records[0].title == "Clean research title"
    assert parsed.records[0].publisher_id == "9"


def test_listing_without_title_is_incomplete() -> None:
    html = (
        '<h1 class="Hub__total--heading">1 Research Topics</h1>'
        '<article class="CardResearchTopic">'
        '<a class="CardResearchTopic__wrapper" href="/research-topics/1/slug">'
        '<p class="CardResearchTopic__state">Submission open</p>'
        "</a></article>"
    )
    parsed = parse_listing(html, SOURCE)
    assert parsed.incomplete is True
    result = FrontiersCollector().collect(_ListingFetcher([(200, html)]), SOURCE)
    assert result.ok is False
    assert "title" in (result.error or "")


def test_complete_listing_matches_advertised_total() -> None:
    page_one = _listing(1, next_page=True, total=2)
    page_two = _listing(2, total=2).replace("?page=2", "?page=1")
    # Keep the second page identifiable as page 2 content without a further next link.
    page_two = (
        '<h1 class="Hub__total--heading">2 Research Topics</h1>'
        '<article class="CardResearchTopic">'
        '<a class="CardResearchTopic__wrapper" href="/research-topics/2/topic-2">'
        '<p class="CardResearchTopic__state">Submission open</p>'
        '<h2 class="CardResearchTopic__title">Topic 2 title</h2>'
        "</a></article>"
    )
    result = FrontiersCollector().collect(_ListingFetcher([(200, page_one), (200, page_two)]), SOURCE)
    assert result.ok is True
    assert result.parsed_count == 2


def test_detail_extracts_summary_keywords_image_and_journals() -> None:
    from radar.config import repo_root

    html = (repo_root() / "tests/fixtures/frontiers_detail.html").read_text(encoding="utf-8")
    detail = parse_detail(html)
    assert "Submission" not in (detail.title or "")
    assert detail.summary and detail.summary.startswith("The rapid growth of digital technologies")
    assert "Article processing charge" not in (detail.summary or "")
    assert "transformin..." not in (detail.summary or "")
    assert detail.image_url.endswith("thumb_400.jpg")
    assert detail.journal == "Frontiers in Psychology"
    assert "Frontiers in Digital Health" in detail.journals
    assert "artificial intelligence" in detail.publisher_keywords
    assert detail.deadline == date(2026, 12, 29)


def test_parse_deadline_reads_manuscript_extension_label() -> None:
    html = (
        "<p>Manuscript Extension Submission Deadline 7 September 2026</p>"
        "<p>Manuscript Submission Deadline 20 April 2026</p>"
    )
    assert parse_deadline(html) == date(2026, 9, 7)


def test_detail_prefers_extension_alert_over_original_deadline() -> None:
    from radar.config import repo_root

    html = (repo_root() / "tests/fixtures/frontiers_detail_extension.html").read_text(encoding="utf-8")
    detail = parse_detail(html)
    assert detail.deadline == date(2026, 9, 7)
    assert detail.deadline_marker is True


def test_not_listed_before_extension_parser_cutoff_is_due() -> None:
    recent = "2026-08-27T06:13:53Z"
    later = "2026-08-29T00:00:00Z"
    now = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)
    due = _row(77470, "not_listed", recent)
    skipped = _row(2, "not_listed", later)
    selected = select_deadline_targets(
        [due, skipped],
        _enrichment_source(2),
        now=now,
    )
    assert [row["id"] for row in selected] == ["frontiers-psychology-77470"]


def test_enrichment_lists_extension_deadline(monkeypatch) -> None:
    monkeypatch.setattr("radar.collectors.frontiers.utc_now", lambda: "2026-08-27T12:00:00Z")
    row = _row(77470)
    html = (
        '<link rel="canonical" href="https://frontiersin.org/research-topics/77470/topic-77470">'
        '<p class="Alert__infoItem__text">Manuscript Extension Submission Deadline 7 September 2026</p>'
    )
    stats = enrich_deadlines(_FakeFetcher([(200, html)]), [row], SOURCE, backfill=True)
    assert stats["listed"] == 1
    assert row["deadline"] == "2026-09-07"
    assert row["deadline_status"] == "listed"


def test_same_topic_id_from_two_sources_keeps_existing_id() -> None:
    from datetime import date

    from radar.ids import stable_id
    from radar.models import RawRecord
    from radar.normalize import to_record
    from radar.pipeline import _assign_raw_id, _publisher_id_index

    existing_id = stable_id("frontiers-psychology", "11111")
    prior = {
        existing_id: {
            "id": existing_id,
            "publisher": "Frontiers",
            "publisher_id": "11111",
            "title": "Adaptive Human-Robot Collaboration in Smart Manufacturing",
            "journal": "Frontiers in Psychology",
            "journals": ["Frontiers in Psychology"],
            "source_keys": ["frontiers-psychology"],
            "discovered_via": "frontiers-psychology",
            "first_seen": "2026-08-01",
            "deadline": None,
            "deadline_status": "not_checked",
            "topics": [],
            "topics_method": "none",
            "content_hash": "old",
        }
    }
    publisher_ids = _publisher_id_index(list(prior.values()))
    raw = RawRecord(
        title="Adaptive Human-Robot Collaboration in Smart Manufacturing",
        url="https://frontiersin.org/research-topics/11111/adaptive-human-robot-collaboration",
        source_url="https://frontiersin.org/journals/robotics-and-ai/research-topics",
        publisher="Frontiers",
        journal="Frontiers in Robotics and AI",
        collection_type="research_topic",
        discovered_via="frontiers-robotics-ai",
        publisher_id="11111",
        journals=["Frontiers in Robotics and AI"],
        source_keys=["frontiers-robotics-ai"],
    )
    _assign_raw_id(raw, publisher_ids)
    row = to_record(
        raw,
        today=date(2026, 8, 27),
        domains=["robotics"],
        domain_scores={"robotics": 0.95},
        topics=[],
        classification_method="source_rule",
        prior=prior,
    )
    assert row["id"] == existing_id
    assert "frontiers-psychology" in row["source_keys"]
    assert "frontiers-robotics-ai" in row["source_keys"]
    assert "Frontiers in Robotics and AI" in row["journals"]


def test_nature_collection_url_reuses_existing_id() -> None:
    from datetime import date

    from radar.models import RawRecord
    from radar.normalize import to_record
    from radar.pipeline import _assign_raw_id, _publisher_id_index

    existing_id = "nature-commsbio-abc123"
    prior = {
        existing_id: {
            "id": existing_id,
            "publisher": "Nature Portfolio",
            "publisher_id": "cbjceedfba",
            "title": "Human-machine interaction in urban settings",
            "journal": "Communications Biology",
            "journals": ["Communications Biology"],
            "source_keys": ["nature-commsbio"],
            "discovered_via": "nature-commsbio",
            "first_seen": "2026-08-01",
            "deadline": "2027-04-21",
            "deadline_status": "listed",
            "topics": [],
            "topics_method": "none",
            "content_hash": "old",
        }
    }
    publisher_ids = _publisher_id_index(list(prior.values()))
    raw = RawRecord(
        title="Human-machine interaction in urban settings",
        url="https://www.nature.com/collections/cbjceedfba",
        source_url="https://www.nature.com/neuro/collections",
        publisher="Nature Portfolio",
        journal="Nature Neuroscience",
        collection_type="collection",
        discovered_via="nature-neuro",
        journals=["Nature Neuroscience"],
        source_keys=["nature-neuro"],
    )
    _assign_raw_id(raw, publisher_ids)
    row = to_record(
        raw,
        today=date(2026, 8, 28),
        domains=["neuroscience"],
        domain_scores={"neuroscience": 0.95},
        topics=[],
        classification_method="source_rule",
        prior=prior,
    )
    assert raw.publisher_id == "cbjceedfba"
    assert row["id"] == existing_id
    assert "Nature Neuroscience" in row["journals"]
    assert row["deadline"] == "2027-04-21"


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
