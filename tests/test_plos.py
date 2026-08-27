import json

from radar.collectors.plos import PlosCollector, parse_cfp_item
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
    from datetime import date

    record = parse_cfp_item(_item(41), SOURCE, today=date(2026, 8, 27))
    assert record is not None
    assert record.title == "Global Mental Health Topic 41"
    assert record.publisher_id == "41"
    assert record.deadline is not None
    assert record.status == "open"
    assert record.summary and "PLOS Mental Health collection" in record.summary
    assert record.image_url is None


def test_parse_cfp_item_uses_content_when_excerpt_is_truncated() -> None:
    from datetime import date

    item = _item(42, deadline=None)
    item["excerpt"] = {"rendered": "<p>A truncated teaser about climate&hellip;</p>"}
    item["content"] = {"rendered": "<p>PLOS Climate full call text for researchers in the Global South.</p>"}
    item["yoast_head_json"] = {
        "og_image": [{"url": "https://collections.plos.org/wp-content/uploads/cover.jpg"}]
    }
    record = parse_cfp_item(item, SOURCE, today=date(2026, 8, 27))
    assert record is not None
    assert record.summary == "PLOS Climate full call text for researchers in the Global South."
    assert record.image_url == "https://collections.plos.org/wp-content/uploads/cover.jpg"
    assert record.image_alt == record.title


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
