import json
from datetime import date

from radar.collectors.plos import PlosCollector, parse_calendar_deadline, parse_cfp_item
from radar.config import repo_root
from radar.models import SourceResult


SOURCE = {
    "key": "plos-collections",
    "publisher": "PLOS",
    "journal": "PLOS",
    "collection_type": "collection",
    "url": "https://collections.plos.org/calls-for-papers/",
    "api_url": "https://collections.plos.org/wp-json/wp/v2/call_for_papers",
    "allowed_hosts": ["collections.plos.org"],
}


def _item(number: int, deadline: str | None = "July 14, 2027") -> dict:
    deadline_text = f" Submission deadline, {deadline}." if deadline else ""
    return {
        "id": number,
        "slug": f"topic-{number}",
        "link": f"https://collections.plos.org/call-for-papers/topic-{number}/",
        "title": {"rendered": f"Global Mental Health Topic {number}"},
        "excerpt": {"rendered": f"<p>PLOS Mental Health collection.{deadline_text}</p>"},
        "content": {"rendered": "<p>PLOS MENTAL HEALTH</p>"},
    }


class _JsonFetcher:
    def __init__(self, pages: list[tuple[int, object, dict[str, str]]]):
        self.pages = iter(pages)
        self.calls: list[str] = []

    def get_json(self, url: str):
        self.calls.append(url)
        return next(self.pages)


def test_parse_cfp_item_uses_api_fields() -> None:
    record = parse_cfp_item(_item(41), SOURCE, today=date(2026, 8, 27))
    assert record is not None
    assert record.title == "Global Mental Health Topic 41"
    assert record.publisher_id == "41"
    assert record.deadline is not None
    assert record.status == "open"
    assert record.summary and "PLOS Mental Health collection" in record.summary
    assert record.journal == "PLOS Mental Health"
    assert record.image_url is None


def test_parse_cfp_item_uses_content_when_excerpt_is_truncated() -> None:
    item = _item(42, deadline=None)
    item["excerpt"] = {"rendered": "<p>A truncated teaser about climate&hellip;</p>"}
    item["content"] = {"rendered": "<p>PLOS Climate full call text for researchers in the Global South.</p>"}
    item["yoast_head_json"] = {
        "og_image": [{"url": "https://collections.plos.org/wp-content/uploads/cover.jpg"}]
    }
    record = parse_cfp_item(item, SOURCE, today=date(2026, 8, 27))
    assert record is not None
    assert record.status == "open"
    assert record.deadline is None
    assert record.journal == "PLOS Climate"
    assert record.summary == "PLOS Climate full call text for researchers in the Global South."
    assert record.image_url == "https://collections.plos.org/wp-content/uploads/cover.jpg"
    assert record.image_alt == record.title


def test_parse_cfp_item_keeps_excerpt_when_content_is_navigation() -> None:
    item = _item(43, deadline=None)
    item["excerpt"] = {
        "rendered": "<p>PLOS Medicine is calling submissions of research on health systems&hellip;</p>"
    }
    item["content"] = {
        "rendered": "<p>More About Collections</p><ul><li>Collections Home</li><li>Browse Collections</li></ul>"
    }
    record = parse_cfp_item(item, SOURCE, today=date(2026, 8, 27))
    assert record is not None
    assert record.journal == "PLOS Medicine"
    assert "calling submissions" not in record.journal.lower()
    assert record.summary and record.summary.startswith("PLOS Medicine is calling submissions")


def test_parse_calendar_deadline_reads_month_day_year_widget() -> None:
    html = (repo_root() / "tests/fixtures/plos_calendar_cfp.html").read_text(encoding="utf-8")
    assert parse_calendar_deadline(html) == date(2020, 12, 21)


def test_parse_cfp_item_uses_calendar_widget_and_closes_past_calls() -> None:
    html = (repo_root() / "tests/fixtures/plos_calendar_cfp.html").read_text(encoding="utf-8")
    item = _item(151, deadline=None)
    item["slug"] = "cognitive-psychology"
    item["link"] = "https://collections.plos.org/call-for-papers/cognitive-psychology/"
    item["title"] = {"rendered": "Cognitive Psychology Call for Papers"}
    item["excerpt"] = {
        "rendered": "<p>Transparency in reporting and methodological rigor have received increased interest&hellip;</p>"
    }
    item["content"] = {"rendered": html + "<p>PLOS ONE</p>"}
    record = parse_cfp_item(item, SOURCE, today=date(2026, 8, 27))
    assert record is not None
    assert record.deadline == date(2020, 12, 21)
    assert record.status == "closed"
    assert record.journal == "PLOS ONE"


def test_parse_cfp_item_prefers_calendar_widget_over_body_text() -> None:
    html = (
        '<div class="calendar-date calendar-date--right">'
        '<span class="calendar-date__month">Jan</span>'
        '<span class="calendar-date__day">31</span>'
        '<span class="calendar-date__year">2023</span>'
        "</div>"
        "<p>PLOS Sustainability and Transformation. Submission deadline, January 30, 2023.</p>"
    )
    item = _item(99, deadline=None)
    item["content"] = {"rendered": html}
    record = parse_cfp_item(item, SOURCE, today=date(2026, 8, 27))
    assert record is not None
    assert record.deadline == date(2023, 1, 31)
    assert record.status == "closed"


def test_plos_completes_when_total_matches() -> None:
    fetcher = _JsonFetcher(
        [
            (200, [_item(1), _item(2)], {"x-wp-total": "3"}),
            (200, [_item(3)], {"x-wp-total": "3"}),
        ]
    )
    result = PlosCollector().collect(fetcher, SOURCE)
    assert result.ok is True
    assert result.parsed_count == 3
    assert result.page_count == 2


def test_plos_incomplete_total_is_failure() -> None:
    fetcher = _JsonFetcher(
        [
            (200, [_item(1)], {"x-wp-total": "2"}),
            (400, None, {}),
        ]
    )
    result = PlosCollector().collect(fetcher, SOURCE)
    assert result.ok is False
    assert result.records == []
    assert "incomplete listing" in (result.error or "")


def test_plos_missing_title_is_failure() -> None:
    broken = _item(1)
    broken["title"] = {"rendered": ""}
    fetcher = _JsonFetcher([(200, [broken], {"x-wp-total": "1"})])
    result = PlosCollector().collect(fetcher, SOURCE)
    assert result.ok is False
    assert result.error
