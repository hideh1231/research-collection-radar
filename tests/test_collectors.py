from pathlib import Path

from radar.collectors.frontiers import parse_listing
from radar.collectors.nature import parse_listing as parse_nature
from radar.collectors.springer import parse_listing as parse_springer
from radar.config import repo_root
from radar.store import write_jsonl, load_jsonl
from radar.views import render_open_md
from datetime import date
from support import workspace_tempdir


def _source(key: str, **extra: str) -> dict:
    base = {
        "key": key,
        "url": "https://example.org/list",
        "publisher": "Test",
        "journal": "Test Journal",
        "allowed_hosts": ["nature.com", "frontiersin.org", "example.org"],
    }
    base.update(extra)
    return base


def test_nature_fixture() -> None:
    html = (repo_root() / "tests/fixtures/nature_psychology.html").read_text(encoding="utf-8")
    records = parse_nature(html, _source("nature-psychology", publisher="Nature Portfolio", journal="Scientific Reports"))
    titles = {row.title for row in records}
    assert any("Human-machine" in title for title in titles)
    open_rows = [row for row in records if row.status == "open"]
    assert any(row.deadline and row.deadline.year == 2027 for row in open_rows)
    assert any(row.deadline and row.deadline.year == 2026 for row in open_rows)
    human = next(row for row in records if "Human-machine" in row.title)
    assert human.summary and "streets" in human.summary
    assert human.image_url and human.image_url.endswith("human-machine.jpg")
    assert human.publisher_id == "cbjceedfba"
    assert human.journals == ["Scientific Reports"]
    closed = next(row for row in records if "already closed" in row.title)
    from radar.collectors.nature import finalize_records

    kept = finalize_records(records, {**_source("nature-neuro"), "require_open_status": True, "journal": "Nature Neuroscience"})
    assert closed not in kept
    assert all(row.status == "open" for row in kept)


def test_frontiers_fixture() -> None:
    html = (repo_root() / "tests/fixtures/frontiers_psychology.html").read_text(encoding="utf-8")
    parsed = parse_listing(html, _source("frontiers-psychology", publisher="Frontiers", journal="Frontiers in Psychology"))
    records = parsed.records
    assert parsed.advertised_total == 2
    assert len(records) == 2
    statuses = {row.title: row.status for row in records}
    assert statuses["Adaptive Human-Robot Collaboration in Smart Manufacturing"] == "open"
    assert statuses["An old closed topic"] == "closed"
    for row in records:
        assert "Submission" not in row.title
        assert "views" not in row.title
        assert "Editor" not in row.title
        assert "articles" not in row.title
    images = {row.title: row.image_url for row in records}
    assert images["Adaptive Human-Robot Collaboration in Smart Manufacturing"] == "https://www.frontiersin.org/image/researchtopic/11111"
    assert images["An old closed topic"] is None


def test_jsonl_stable_sort() -> None:
    with workspace_tempdir("collector-test") as directory:
        path = directory / "x.jsonl"
        write_jsonl(path, [{"id": "b", "title": "b"}, {"id": "a", "title": "a"}])
        rows = load_jsonl(path)
        assert [row["id"] for row in rows] == ["a", "b"]


def test_open_md_orders_deadline() -> None:
    text = render_open_md(
        [
            {"title": "Later", "journal": "J", "url": "https://a", "status": "open", "deadline": "2027-05-01", "domains": ["psychology"], "collection_type": "collection"},
            {"title": "Soon", "journal": "J", "url": "https://b", "status": "open", "deadline": "2026-09-01", "domains": ["hci"], "collection_type": "special_issue"},
            {"title": "Closed", "journal": "J", "url": "https://c", "status": "closed", "deadline": "2026-01-01", "domains": [], "collection_type": "collection"},
            {"title": "No date", "journal": "J", "url": "https://d", "status": "open", "deadline": None, "domains": [], "collection_type": "collection"},
        ],
        date(2026, 8, 26),
    )
    assert text.index("Soon") < text.index("Later")
    assert "Closed" not in text
    assert "No date" not in text
    assert "| Deadline | Title | Journal | Fields | Type | URL |" in text
    assert "Psychology" in text
    assert "Special Issue" in text


def test_springer_fixture_uses_collection_cards() -> None:
    html = (repo_root() / "tests/fixtures/springer_bmc.html").read_text(encoding="utf-8")
    records = parse_springer(
        html,
        _source(
            "springer-bmc-psychology",
            publisher="Springer Nature",
            journal="BMC Psychology",
            url="https://bmcpsychology.biomedcentral.com/articles/collections",
            allowed_hosts=["bmcpsychology.biomedcentral.com", "www.biomedcentral.com"],
        ),
    )
    titles = {row.title for row in records}
    assert "Beyond WEIRD: positive psychology in underrepresented contexts" in titles
    assert "An already closed methods collection" in titles
    assert all("Sign in" not in row.title for row in records)
    open_row = next(row for row in records if row.status == "open")
    assert open_row.deadline and open_row.deadline.isoformat() == "2027-05-25"
    assert open_row.summary and "positive psychology" in open_row.summary
