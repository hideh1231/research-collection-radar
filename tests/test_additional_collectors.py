from datetime import date

from radar.collectors.cambridge import CambridgeCollector, next_page_url as next_cambridge_page, parse_listing as parse_cambridge
from radar.collectors.ieee_ras import parse_listing as parse_ieee_ras
from radar.collectors.jmir import parse_listing as parse_jmir
from radar.collectors.nature import parse_listing as parse_nature
from radar.collectors.nature_humanities import parse_listing as parse_nature_humanities
from radar.collectors.taylor_francis import TaylorFrancisCollector, parse_listing as parse_taylor_francis
from radar.config import repo_root


def _source(key: str, **extra: str) -> dict:
    base = {
        "key": key,
        "url": "https://example.org/list",
        "publisher": "Test",
        "journal": "Test Journal",
        "allowed_hosts": ["nature.com", "frontiersin.org", "example.org"],
        "today": date(2026, 9, 12),
    }
    base.update(extra)
    return base


def test_nature_fixture_honors_title_filter() -> None:
    html = (repo_root() / "tests/fixtures/nature_psychology.html").read_text(encoding="utf-8")
    source = _source(
        "nature-filtered", publisher="Nature Portfolio", journal="Communications Engineering"
    )
    source["include_keywords"] = ["human-machine"]
    records = parse_nature(html, source)
    assert records
    assert all("human-machine" in row.title.casefold() for row in records)


def test_nature_humanities_filters_and_merges_sections() -> None:
    html = """
    <h3>Psychology</h3><ul>
      <li><a href="https://www.nature.com/collections/abcdefghij/how-to-submit">Human-technology interactions</a></li>
    </ul>
    <h3>Sociology</h3><ul>
      <li><a href="https://www.nature.com/collections/abcdefghij/how-to-submit">Human-technology interactions</a></li>
    </ul>
    <h3>Economics</h3><ul>
      <li><a href="https://www.nature.com/collections/jihgfedcba/how-to-submit">Unrelated economics topic</a></li>
    </ul>
    """
    source = _source(
        "nature-humanities",
        publisher="Nature Portfolio",
        journal="Humanities and Social Sciences Communications",
    )
    source["include_sections"] = ["Psychology", "Sociology"]
    records = parse_nature_humanities(html, source)
    assert len(records) == 1
    assert records[0].source_section == "Psychology, Sociology"
    assert records[0].status == "open"


def test_jmir_keeps_only_call_announcements() -> None:
    html = """
    <h2><a href="/announcements/999">Call for Papers: Human-AI Collaboration</a></h2>
    <h2><a href="/announcements/998">Journal impact factor update</a></h2>
    """
    records = parse_jmir(
        html,
        _source(
            "jmir-human-factors",
            url="https://humanfactors.jmir.org/announcements",
            publisher="JMIR Publications",
            journal="JMIR Human Factors",
            allowed_hosts=["humanfactors.jmir.org"],
        ),
    )
    assert len(records) == 1
    assert records[0].title == "Human-AI Collaboration"
    assert records[0].status == "unknown"


def test_ieee_ras_parses_calls_and_ignores_policy_links() -> None:
    html = """
    <table><tr><td><a href="/publications/toh/special-issues/human-teleoperation/">Special Issue on Human Teleoperation</a></td>
    <td>Submission Deadline: November 30th, 2026</td></tr></table>
    <p><a href="/policy.pdf">Special Issue Policy</a></p>
    """
    records = parse_ieee_ras(
        html,
        _source(
            "ieee-toh",
            url="https://www.ieee-ras.org/publications/toh/special-issues/",
            publisher="IEEE",
            journal="IEEE Transactions on Haptics",
            allowed_hosts=["www.ieee-ras.org"],
        ),
    )
    assert len(records) == 1
    assert records[0].deadline and records[0].deadline.isoformat() == "2026-11-30"


def test_taylor_francis_parses_special_issue_fields_and_filters() -> None:
    payload = [
        {
            "id": 123,
            "status": "publish",
            "link": "https://think.taylorandfrancis.com/special_issues/visual-cognition/",
            "title": {"rendered": "Fallback title"},
            "meta": {"meta-page-expiry-date": "2027-03-01"},
            "special_issues": {
                "_special_issues_title": ["Visual Cognition and Human Memory"],
                "_special_issues_journal_title": ["Visual Cognition"],
                "_special_issues_deadline": ["15 February 2027"],
                "_special_issues_copy": ["<p>Call <strong>summary</strong>.</p>"],
            },
        },
        {
            "id": 456,
            "status": "publish",
            "link": "https://think.taylorandfrancis.com/special_issues/robot-learning/",
            "title": {"rendered": "Robot learning call"},
            "special_issues": {
                "_special_issues_title": ["Robot learning call"],
                "_special_issues_journal_title": ["Unlisted Journal"],
                "_special_issues_deadline": ["1 January 2025"],
                "_special_issues_copy": ["<p>Autonomous robot learning.</p>"],
            },
        },
        {
            "id": 789,
            "status": "draft",
            "link": "https://think.taylorandfrancis.com/special_issues/draft/",
            "title": {"rendered": "Psychology draft"},
            "special_issues": {
                "_special_issues_journal_title": ["Psychology"],
                "_special_issues_title": ["Psychology draft"],
            },
        },
        {
            "id": 999,
            "status": "publish",
            "link": "https://other.example/special_issues/nope/",
            "title": {"rendered": "Psychology elsewhere"},
            "special_issues": {
                "_special_issues_journal_title": ["Psychology"],
                "_special_issues_title": ["Psychology elsewhere"],
            },
        },
    ]
    source = _source(
        "taylor-francis-test",
        url="https://think.taylorandfrancis.com/wp-json/wp/v2/special_issues",
        publisher="Taylor & Francis",
        journal="Taylor & Francis journals",
        allowed_hosts=["think.taylorandfrancis.com"],
        include_journals=["Visual Cognition"],
        include_domains=["robotics"],
        domain_keywords={"robotics": ["robot", "autonomous"]},
    )
    records = parse_taylor_francis(payload, source)
    assert len(records) == 2
    by_title = {record.title: record for record in records}
    assert by_title["Visual Cognition and Human Memory"].status == "open"
    assert by_title["Visual Cognition and Human Memory"].deadline.isoformat() == "2027-02-15"
    assert by_title["Visual Cognition and Human Memory"].summary == "Call summary."
    assert by_title["Robot learning call"].status == "closed"
    assert by_title["Robot learning call"].extra["publisher_id"] == 456


def test_taylor_francis_uses_wordpress_pagination_header() -> None:
    class Response:
        status_code = 200

        def __init__(self, payload: list[dict], pages: int) -> None:
            self._payload = payload
            self.headers = {"X-WP-TotalPages": str(pages)}

        def json(self) -> list[dict]:
            return self._payload

    class Fetcher:
        def __init__(self) -> None:
            self.urls: list[str] = []

        def get(self, url: str) -> Response:
            self.urls.append(url)
            page = 2 if "page=2" in url else 1
            payload = [{
                "id": page,
                "status": "publish",
                "link": f"https://think.taylorandfrancis.com/special_issues/item-{page}/",
                "title": {"rendered": f"Item {page}"},
                "special_issues": {"_special_issues_journal_title": ["Visual Cognition"]},
            }]
            return Response(payload, 2)

    source = _source(
        "taylor-francis-pagination",
        url="https://think.taylorandfrancis.com/wp-json/wp/v2/special_issues?per_page=100",
        publisher="Taylor & Francis",
        journal="Taylor & Francis journals",
        allowed_hosts=["think.taylorandfrancis.com"],
        max_pages=2,
        page_size=100,
    )
    fetcher = Fetcher()
    result = TaylorFrancisCollector().collect(fetcher, source)
    assert result.ok
    assert result.page_count == 2
    assert result.parsed_count == 2
    assert ["&page=1" in url for url in fetcher.urls] == [True, False]
    assert "&page=2" in fetcher.urls[1]


def test_cambridge_parses_common_cards_and_deadlines() -> None:
    html = """
    <ul class="overview">
      <li class="title"><a href="/core/journals/robotica/announcements/call-for-papers/robot-call">Special issue: Robot Design</a></li>
      <li>01 Mar 2023 Submission Deadline: March 31, 2027</li>
    </ul>
    <ul class="overview">
      <li class="title"><a href="/core/journals/cns-spectrums/announcements/call-for-papers/mental-call">Call for Papers</a></li>
      <li>Psychiatry in the Age of Uncertainties: Brain, Mind, and Society</li>
    </ul>
    <ul class="overview">
      <li class="title"><a href="https://other.example/nope">External card</a></li>
    </ul>
    """
    source = _source(
        "cambridge-test",
        url="https://www.cambridge.org/core/journals/robotica/announcements/call-for-papers",
        publisher="Cambridge University Press",
        journal="Robotica",
        allowed_hosts=["www.cambridge.org", "cambridge.org"],
        today=date(2026, 9, 2),
    )
    records = parse_cambridge(html, source)
    assert len(records) == 2
    by_title = {record.title: record for record in records}
    assert by_title["Special issue: Robot Design"].status == "open"
    assert by_title["Special issue: Robot Design"].deadline.isoformat() == "2027-03-31"
    generic_title = "Psychiatry in the Age of Uncertainties: Brain, Mind, and Society"
    assert by_title[generic_title].title == generic_title
    assert by_title[generic_title].status == "unknown"
    assert by_title["Special issue: Robot Design"].extraction_method == "cambridge_core_html"


def test_cambridge_pagination_and_allow_empty() -> None:
    current = "https://www.cambridge.org/core/journals/robotica/announcements/call-for-papers"
    assert next_cambridge_page('<a rel="next" href="?p=2">next</a>', current, ["cambridge.org"]).endswith("p=2")
    assert next_cambridge_page('<a href="?p=3">3</a>', current, ["cambridge.org"]) is None

    class Fetcher:
        def __init__(self) -> None:
            self.urls: list[str] = []

        def get_html(self, url: str) -> tuple[int, str]:
            self.urls.append(url)
            if "p=2" in url:
                return 200, '<ul class="overview"><li class="title"><a href="/core/journals/robotica/announcements/call-for-papers/two">Second call</a></li></ul>'
            return 200, '<ul class="overview"><li class="title"><a href="/core/journals/robotica/announcements/call-for-papers/one">First call</a></li></ul><a rel="next" href="?p=2">next</a>'

    source = _source(
        "cambridge-pagination",
        url=current,
        publisher="Cambridge University Press",
        journal="Robotica",
        allowed_hosts=["www.cambridge.org", "cambridge.org"],
        max_pages=2,
    )
    fetcher = Fetcher()
    result = CambridgeCollector().collect(fetcher, source)
    assert result.ok
    assert result.page_count == 2
    assert result.parsed_count == 2
    assert len(fetcher.urls) == 4
    assert fetcher.urls[-2].endswith("/call-for-papers/one")
    assert fetcher.urls[-1].endswith("/call-for-papers/two")

    empty_source = {**source, "key": "cambridge-empty", "allow_empty": True}
    empty = CambridgeCollector().collect(
        type("EmptyFetcher", (), {"get_html": lambda self, url: (200, "<html></html>")})(),
        empty_source,
    )
    assert empty.ok and empty.parsed_count == 0
