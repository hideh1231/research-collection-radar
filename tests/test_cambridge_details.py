from datetime import date

import httpx
import pytest

from radar.collectors.cambridge import CambridgeCollector
from radar.ids import canonicalize_url


LISTING_URL = "https://www.cambridge.org/core/journals/psychological-medicine/announcements/call-for-papers"


def _source() -> dict:
    return {
        "key": "cambridge-psychological-medicine",
        "url": LISTING_URL,
        "publisher": "Cambridge University Press",
        "journal": "Psychological Medicine",
        "today": date(2026, 9, 12),
    }


def _listing(*cards: tuple[str, str, str]) -> str:
    return "".join(
        f'<ul class="overview"><li class="title"><a href="{LISTING_URL}/{slug}">{title}</a></li>'
        f'<li>{description}</li></ul>'
        for slug, title, description in cards
    )


def _detail(slug: str, title: str, content: str) -> str:
    return (
        f'<link rel="canonical" href="{LISTING_URL}/{slug}">'
        '<nav>Submission deadline: 1 January 2020</nav>'
        f'<div id="maincontent"><h1>{title}</h1>{content}</div>'
    )


class Fetcher:
    def __init__(self, pages):
        self.pages = {canonicalize_url(url): value for url, value in pages.items()}
        self.calls = []

    def get_html(self, url):
        self.calls.append(url)
        value = self.pages[canonicalize_url(url)]
        if isinstance(value, Exception):
            raise value
        return value


def test_cambridge_details_supply_exact_manuscript_deadlines() -> None:
    fetcher = Fetcher({
        LISTING_URL: (200, _listing(("proteomics", "Proteomic Insights", ""), ("ai", "AI in Mental Health", ""))),
        LISTING_URL + "/proteomics": (200, _detail("proteomics", "Proteomic Insights", "<p>Submission deadline: 28th February 2027</p>")),
        LISTING_URL + "/ai": (200, _detail("ai", "AI in Mental Health", "<p>Submission deadline: 28 February 2027</p>")),
    })
    result = CambridgeCollector().collect(fetcher, _source())
    assert result.ok
    assert result.error is None
    assert result.parsed_count == 2
    assert {row.deadline for row in result.records} == {date(2027, 2, 28)}
    assert all(row.status == "open" for row in result.records)
    assert all(row.extra["deadline_status"] == "listed" for row in result.records)
    assert len(fetcher.calls) == 3


def test_cambridge_manuscript_deadline_wins_over_invalid_abstract_date() -> None:
    fetcher = Fetcher({
        LISTING_URL: (200, _listing(("polycrisis", "Psychiatry under Polycrisis", ""))),
        LISTING_URL + "/polycrisis": (200, _detail("polycrisis", "Psychiatry under Polycrisis", """
            <p>ABSTRACT SUBMISSION DEADLINE: 31 SEPTEMBER 2026</p>
            <p>FULL MANUSCRIPT SUBMISSION DEADLINE: 30 MARCH 2027</p>
        """)),
    })
    row = CambridgeCollector().collect(fetcher, _source()).records[0]
    assert row.deadline == date(2027, 3, 30)
    assert row.status == "open"


def test_cambridge_month_only_expiry_does_not_invent_a_day() -> None:
    fetcher = Fetcher({
        LISTING_URL: (200, _listing(("autism", "Autism individual differences", ""))),
        LISTING_URL + "/autism": (200, _detail("autism", "Autism individual differences", """
            <p>We welcome submissions. All manuscripts need to be submitted no later than January 2025.</p>
        """)),
    })
    row = CambridgeCollector().collect(fetcher, _source()).records[0]
    assert row.deadline is None
    assert row.status == "closed"
    assert row.extra.get("deadline_status", "not_checked") == "not_checked"


def test_cambridge_extended_deadline_ignores_superseded_date() -> None:
    fetcher = Fetcher({
        LISTING_URL: (200, _listing(("robotics", "Reconfigurable mechanisms", ""))),
        LISTING_URL + "/robotics": (200, _detail("robotics", "Reconfigurable mechanisms", """
            <p>Published 15 December 2021. We welcome submissions.</p>
            <p>Deadline Date Extended: <del>15 February 2022</del> 15 March 2022</p>
        """)),
    })
    row = CambridgeCollector().collect(fetcher, _source()).records[0]
    assert row.deadline == date(2022, 3, 15)
    assert row.status == "closed"


@pytest.mark.parametrize("text, expected", [
    ("31.07.2025", date(2025, 7, 31)),
    ("01.02.2027", date(2027, 2, 1)),
])
def test_cambridge_dotted_deadlines_use_day_month_year(text, expected) -> None:
    fetcher = Fetcher({
        LISTING_URL: (200, _listing(("economics", "Mental health economics", ""))),
        LISTING_URL + "/economics": (200, _detail("economics", "Mental health economics", f"<p>Closing date for submissions: {text}.</p>")),
    })
    row = CambridgeCollector().collect(fetcher, _source()).records[0]
    assert row.deadline == expected


def test_cambridge_unparsed_deadline_does_not_make_old_invitation_open() -> None:
    fetcher = Fetcher({
        LISTING_URL: (200, _listing(("call", "A themed series", ""))),
        LISTING_URL + "/call": (200, _detail("call", "A themed series", """
            <p>We invite submissions. Submission deadline: see attached call.</p>
        """)),
    })
    row = CambridgeCollector().collect(fetcher, _source()).records[0]
    assert row.status == "unknown"
    assert row.deadline is None
    assert "deadline_checked_at" not in row.extra


@pytest.mark.parametrize("content, expected", [
    ("<p>We invite submissions about student mental health.</p>", "open"),
    ("<p>This collection was published in January 2025.</p>", "unknown"),
    ("<p>Submission status: closed</p>", "closed"),
])
def test_cambridge_undated_call_requires_explicit_status(content, expected) -> None:
    fetcher = Fetcher({
        LISTING_URL: (200, _listing(("call", "A themed series", ""))),
        LISTING_URL + "/call": (200, _detail("call", "A themed series", content)),
    })
    row = CambridgeCollector().collect(fetcher, _source()).records[0]
    assert row.status == expected
    assert row.deadline is None
    assert row.extra["deadline_status"] == "not_listed"
    assert row.extra["deadline_checked_at"]


@pytest.mark.parametrize("response", [
    httpx.ReadTimeout("timed out"),
    (403, "Access denied"),
    (200, '<html><h1>Verify you are human</h1></html>'),
    (200, _detail("different-call", "A themed series", "<p>Submission deadline: 1 January 2027</p>")),
    (200, _detail("call", "Different title", "<p>Submission deadline: 1 January 2027</p>")),
])
def test_cambridge_detail_failures_keep_listing_record_unchecked(response) -> None:
    fetcher = Fetcher({
        LISTING_URL: (200, _listing(("call", "A themed series", "Submission status: open"))),
        LISTING_URL + "/call": response,
    })
    result = CambridgeCollector().collect(fetcher, _source())
    assert result.ok
    assert result.parsed_count == 1
    assert result.error == "detail unavailable for 1 calls"
    row = result.records[0]
    assert row.status == "open"
    assert row.deadline is None
    assert "deadline_checked_at" not in row.extra


def test_cambridge_keeps_listing_deadline_without_an_extra_request() -> None:
    fetcher = Fetcher({LISTING_URL: (200, _listing(("call", "A themed series", "Submission deadline: 1 January 2027")))})
    row = CambridgeCollector().collect(fetcher, _source()).records[0]
    assert row.deadline == date(2027, 1, 1)
    assert fetcher.calls == [LISTING_URL]


def test_cambridge_does_not_fetch_outside_the_call_listing() -> None:
    html = '<ul class="overview"><li class="title"><a href="https://www.cambridge.org/login">A themed series</a></li></ul>'
    fetcher = Fetcher({LISTING_URL: (200, html)})
    result = CambridgeCollector().collect(fetcher, _source())
    assert len(result.records) == 1
    assert fetcher.calls == [LISTING_URL]
    assert result.records[0].status == "unknown"


def test_cambridge_fetches_pagination_and_details_on_official_www_host() -> None:
    fetcher = Fetcher({
        LISTING_URL: (200, _listing(("call", "A themed series", "")) + '<a rel="next" href="?p=2">Next</a>'),
        LISTING_URL + "?p=2": (200, "<html>No more calls</html>"),
        LISTING_URL + "/call": (200, _detail("call", "A themed series", "<p>Submission deadline: 1 January 2027</p>")),
    })
    result = CambridgeCollector().collect(fetcher, _source())
    assert result.ok
    assert result.page_count == 2
    assert fetcher.calls == [LISTING_URL, LISTING_URL + "?p=2", LISTING_URL + "/call"]
    assert result.records[0].url.startswith("https://cambridge.org/")
