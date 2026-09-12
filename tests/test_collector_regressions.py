from datetime import date
from urllib.parse import parse_qs, urlparse

import pytest

from radar.collectors.html_listing import parse_ipsj, parse_jske
from radar.collectors.jmir import JmirCollector, parse_detail
from radar.collectors.nature import NatureCollector, next_page_url
from radar.collectors.springer import parse_listing as parse_springer
from radar.collectors.taylor_francis import TaylorFrancisCollector
from radar.models import RawRecord


JMIR = {
    "key": "jmir-human-factors", "url": "https://humanfactors.jmir.org/announcements",
    "allowed_hosts": ["humanfactors.jmir.org"], "publisher": "JMIR Publications",
    "journal": "JMIR Human Factors", "journal_id": 6, "api_max_pages": 2,
    "today": date(2026, 9, 12),
}


class Response:
    status_code = 200
    headers = {}

    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


def _announcement(number, journal_id=6):
    return {"announcement_id": number, "journal_id": journal_id,
            "title": f"Call for Papers: Human Factors {number}", "description_short": "<p>Research.</p>"}


def _detail(number, deadline="January 31, 2027"):
    return f'<h1>Call for Papers: Human Factors {number}</h1><main id="main-content"><p>Submission Deadline: {deadline}</p></main>'


class ApiFetcher:
    def __init__(self, pages):
        self.pages = iter(pages)
        self.requests = []
        self.details = []

    def get(self, url, *, headers):
        assert headers["X-JOURNAL-ID"] == "6"
        self.requests.append(url)
        return Response(next(self.pages))

    def get_html(self, url):
        self.details.append(url)
        return 200, _detail(url.rsplit("/", 1)[1])


def test_jmir_collects_calls_from_every_api_page_and_checks_details():
    fetcher = ApiFetcher([
        {"data": [_announcement(571)], "pagination": {"lastPage": 2}},
        {"data": [_announcement(223)], "pagination": {"lastPage": 2}},
    ])
    result = JmirCollector().collect(fetcher, JMIR)
    assert result.ok and result.page_count == 2 and result.parsed_count == 2
    assert "page=2&" in fetcher.requests[1]
    assert {row.publisher_id for row in result.records} == {"571", "223"}
    assert all(row.status == "open" and row.deadline == date(2027, 1, 31) for row in result.records)


def test_jmir_rejects_api_response_from_other_journal():
    fetcher = ApiFetcher([{"data": [_announcement(726, journal_id=16)], "pagination": {"lastPage": 1}}])
    result = JmirCollector().collect(fetcher, JMIR)
    assert not result.ok and result.records == []
    assert result.error == "API journal filter mismatch"
    assert fetcher.details == []


def test_jmir_api_truncation_and_duplicate_page_are_failures():
    first = {"data": [_announcement(571)], "pagination": {"lastPage": 2}}
    result = JmirCollector().collect(ApiFetcher([first]), {**JMIR, "api_max_pages": 1})
    assert not result.ok and result.error == "pagination truncated"
    result = JmirCollector().collect(ApiFetcher([first, first]), JMIR)
    assert not result.ok and result.error == "pagination page contained no new records"


def _record():
    return RawRecord(title="Human Factors 571", url="https://humanfactors.jmir.org/announcements/571",
                     source_url=JMIR["url"], publisher=JMIR["publisher"], journal=JMIR["journal"],
                     collection_type="theme_issue", discovered_via=JMIR["key"], status="unknown")


@pytest.mark.parametrize(("deadline", "status", "expected"), [
    ("Open call", "open", None),
    ("Open call for submissions", "open", None),
    ("January 31, 2025", "closed", date(2025, 1, 31)),
    ("January 31, 2027", "open", date(2027, 1, 31)),
])
def test_jmir_detail_reads_explicit_deadlines(deadline, status, expected):
    record = _record()
    assert parse_detail(_detail(571, deadline), record, JMIR)
    assert record.status == status and record.deadline == expected
    assert record.extra["deadline_status"] == ("listed" if expected else "not_listed")
    assert record.extra["deadline_checked_at"]


def test_jmir_detail_mismatch_or_invalid_date_does_not_confirm_a_deadline():
    record = _record()
    assert not parse_detail(_detail(999), record, JMIR)
    assert not parse_detail(_detail(571, "31 February 2027"), record, JMIR)
    assert record.status == "unknown" and not record.extra


def test_jmir_detail_failure_is_reported_with_listing_preserved():
    fetcher = ApiFetcher([{"data": [_announcement(571)], "pagination": {"lastPage": 1}}])
    fetcher.get_html = lambda url: (403, "Forbidden")
    result = JmirCollector().collect(fetcher, JMIR)
    assert result.ok and result.error == "1 detail checks failed"
    assert len(result.records) == 1 and result.records[0].status == "unknown"


@pytest.mark.parametrize("text", [
    "The deadline for submission is March 31st, 2018",
    "Full paper due: *EXTENDED* March 31, 2018",
    "Authors are invited to submit a full-length manuscript by March 31, 2018",
])
def test_jmir_reads_prose_and_schedule_manuscript_deadlines(text):
    record = _record()
    html = f'<h1>Call for Papers: Human Factors 571</h1><main id="main-content"><p>{text}</p></main>'
    assert parse_detail(html, record, JMIR)
    assert record.deadline == date(2018, 3, 31) and record.status == "closed"


def test_nature_pagination_preserves_subject_and_rejects_external_or_other_listing():
    current = "https://www.nature.com/srep/calls-for-papers?subject=Psychology"
    following = next_page_url('<a rel="next" href="?page=2">Next</a>', current)
    assert following is not None
    assert parse_qs(urlparse(following).query) == {"page": ["2"], "subject": ["Psychology"]}
    assert next_page_url('<a rel="next" href="https://other.example/srep/calls-for-papers?page=2">Next</a>', current) is None
    assert next_page_url('<a rel="next" href="/ncomms/calls-for-papers?page=2">Next</a>', current) is None


def test_nature_pagination_cycle_is_failure():
    source = {"key": "nature-test", "url": "https://www.nature.com/srep/calls-for-papers",
              "allowed_hosts": ["nature.com"], "publisher": "Nature Portfolio", "allow_empty": True}
    fetcher = type("Fetcher", (), {"get_html": lambda self, url: (200, '<a rel="next" href="?">Next</a>')})()
    result = NatureCollector().collect(fetcher, source)
    assert not result.ok and result.error == "pagination cycle"


def test_taylor_francis_no_header_full_last_page_is_truncated():
    item = {"id": 1, "status": "publish", "link": "https://think.taylorandfrancis.com/special_issues/hci", "title": {"rendered": "Human Factors"}}
    fetcher = type("Fetcher", (), {"get": lambda self, url: Response([item])})()
    source = {"key": "tf", "url": "https://think.taylorandfrancis.com/wp-json/wp/v2/special_issues", "publisher": "Taylor & Francis", "page_size": 1, "max_pages": 1}
    result = TaylorFrancisCollector().collect(fetcher, source)
    assert not result.ok and result.error == "pagination truncated"


def test_springer_does_not_invent_deadline_from_summary_date():
    html = '<article class="app-card-collection"><a class="app-card-collection__heading-link" href="/collection/topic">Human Psychology</a><p class="app-card-collection__text">A symposium on 1 January 2027.</p></article>'
    records = parse_springer(html, {"key": "bmc", "url": "https://example.org/collections", "publisher": "Springer"})
    assert len(records) == 1 and records[0].deadline is None


def test_jske_only_journal_calls_and_explicit_deadline():
    html = '''<a href="/cfp/">Call for Papers</a>
      <a class="post_list" href="/cfp/isase2026"><span>2026/01/05</span><p class="post_title">ISASE2026 Call For Papers / Paper submission Deadline Extended until January 15, 2026</p></a>
      <a class="post_list" href="/cfp/special-2026"><span>2026/04/15</span><p class="post_title">IJAE: Special Issue: Call for Extended Papers of ISASE 2026</p></a>
      <a class="post_list" href="/cfp/special-2025"><p class="post_title">IJAE: Special Issue of Kansei Research</p><p>Paper submission Deadline Extended until January 15, 2025</p></a>'''
    source = {"key": "jske", "url": "https://www.jske.org/cfp/", "publisher": "JSKE", "journal": "IJAE", "allowed_hosts": ["jske.org"]}
    records = parse_jske(html, source)
    assert len(records) == 2
    assert records[0].status == "unknown" and records[0].deadline is None
    assert records[1].status == "closed" and records[1].deadline == date(2025, 1, 15)


def test_ipsj_skips_generic_index_heading():
    html = '<h2>特集論文募集（一覧）</h2><h3>特集：人と計算機</h3><p>投稿締切：2027年1月31日</p>'
    source = {"key": "ipsj", "url": "https://ipsj.or.jp/journal/cfp/cfp_list.html", "publisher": "IPSJ"}
    records = parse_ipsj(html, source)
    assert len(records) == 1 and records[0].title == "特集：人と計算機"
