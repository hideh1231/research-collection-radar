from datetime import date
import json

from radar.collectors.apa import parse_listing as parse_apa
from radar.collectors.royal_society import parse_listing as parse_royal_society
from radar.collectors.sciencedirect import parse_listing as parse_sciencedirect
from radar.config import repo_root
from radar.normalize import publisher_id_from_url
from radar.pipeline import run
from support import workspace_tempdir


def _apa_source() -> dict:
    return {
        "key": "apa-cfp",
        "publisher": "APA",
        "journal": "APA Journals",
        "url": "https://www.apa.org/pubs/journals/resources/calls-for-papers",
        "allowed_hosts": ["www.apa.org", "apa.org"],
    }


def _sd_source(**extra) -> dict:
    source = {
        "key": "sciencedirect-cfp",
        "publisher": "Elsevier",
        "journal": "ScienceDirect",
        "url": "https://www.sciencedirect.com/browse/calls-for-papers",
        "allowed_hosts": ["www.sciencedirect.com", "sciencedirect.com"],
    }
    source.update(extra)
    return source


def _rs_source(url: str) -> dict:
    return {
        "key": "royal-society-themes",
        "publisher": "The Royal Society",
        "journal": "Royal Society",
        "url": url,
        "allowed_hosts": ["royalsociety.org", "royalsocietypublishing.org"],
    }


def test_apa_listing_uses_journal_modules_and_manuscript_deadline() -> None:
    html = (repo_root() / "tests/fixtures/apa_calls.html").read_text(encoding="utf-8")
    records = parse_apa(html, _apa_source())
    by_title = {row.title: row for row in records}
    assert "General call for papers" not in by_title
    trauma = by_title["Intergenerational trauma and community strengths: Theory, research, practice, and policy"]
    assert trauma.journal.startswith("American Psychologist")
    assert trauma.deadline == date(2025, 12, 1)
    assert trauma.url.endswith("/amp/intergenerational-trauma-community-strengths")
    novel = next(row for row in records if row.title.startswith("Call for papers: Novel technologies"))
    assert novel.deadline == date(2025, 8, 15)
    assert novel.status == "closed"
    assert trauma.status == "closed"
    assert novel.journal.startswith("Experimental and Clinical Psychopharmacology")
    avian = by_title["Special issue on avian cognition"]
    assert avian.journal.startswith("Journal of Experimental Psychology: Animal")
    assert avian.deadline == date(2026, 10, 15)
    assert avian.status == "open"
    assert avian.url.endswith("/pubs/journals/resources/calls-for-papers")
    assert avian.publisher_id == "special-issue-on-avian-cognition"
    assert len(records) == 7


def test_sciencedirect_listing_uses_publication_cards() -> None:
    html = (repo_root() / "tests/fixtures/sciencedirect_cfp.html").read_text(encoding="utf-8")
    records = parse_sciencedirect(html, _sd_source())
    assert {row.title for row in records} == {
        "Atmospheric Chemistry in China",
        "Learning-Based Control for Soft Robotics: Theory, Algorithms, and Applications",
        "Spotlight on scientific advances by early-career neuroscientists",
    }
    robots = next(row for row in records if "Soft Robotics" in row.title)
    assert robots.journal == "Biomimetic Intelligence and Robotics"
    assert robots.deadline == date(2026, 12, 31)
    assert robots.status == "open"
    chemistry = next(row for row in records if row.title == "Atmospheric Chemistry in China")
    assert chemistry.status == "closed"
    assert robots.publisher_id == "325000"
    assert robots.url.endswith("/special-issue/325000/learning-based-control-for-soft-robotics")
    assert all("My account" not in row.title for row in records)
    assert publisher_id_from_url(robots.url) == "325000"


def test_royal_society_theme_page_splits_cfp_heading_block() -> None:
    html = (repo_root() / "tests/fixtures/royal_society_ai.html").read_text(encoding="utf-8")
    records = parse_royal_society(
        html,
        _rs_source("https://royalsociety.org/journals/publishing-activities/journal-article-collections/ai/"),
    )
    titles = {row.title for row in records}
    assert "The quest for integrated information" in titles
    assert "AI and its relationship to public policy" in titles
    assert all(row.journal == "Royal Society Open Science" for row in records)
    assert all(row.deadline is None for row in records)
    urls = {row.url for row in records}
    assert urls == {"https://royalsocietypublishing.org/rsos/pages/special-collections"}
    assert len({row.publisher_id for row in records}) == 2


def test_royal_society_proposal_call_uses_heading_title() -> None:
    html = (repo_root() / "tests/fixtures/royal_society_cell.html").read_text(encoding="utf-8")
    records = parse_royal_society(
        html,
        _rs_source("https://royalsociety.org/journals/publishing-activities/journal-article-collections/cell-mol-bio/"),
    )
    assert len(records) == 1
    row = records[0]
    assert "Beyond boundaries" in row.title
    assert row.journal == "Open Biology"
    assert row.submission_mode == "invited_or_proposal"
    assert "special-features" in row.url


def test_ingest_html_merges_listing_without_fetch() -> None:
    source_root = repo_root()
    with workspace_tempdir("ingest-html") as root:
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
        assert (
            run(
                root,
                dry_run=True,
                ingest_html={
                    "apa-cfp": source_root / "tests/fixtures/apa_calls.html",
                    "sciencedirect-cfp": source_root / "tests/fixtures/sciencedirect_cfp.html",
                    "royal-society-themes": source_root / "tests/fixtures/royal_society_ai.html",
                },
            )
            == 0
        )
        rows = [
            json.loads(line)
            for line in (root / "data/collections.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        titles = {row["title"] for row in rows}
        assert any("Intergenerational trauma" in title for title in titles)
        assert any("Soft Robotics" in title for title in titles)
        assert "Atmospheric Chemistry in China" not in titles
        assert any(title == "The quest for integrated information" for title in titles)
        status = json.loads((root / "data/source_status.json").read_text(encoding="utf-8"))
        assert status["sources"]["apa-cfp"]["ok"] is True
        assert status["sources"]["sciencedirect-cfp"]["dropped_unclassified"] == 1
        assert status["sources"]["royal-society-themes"]["parsed"] == 2


def test_ingest_html_open_only_skips_closed_and_keeps_other_source_status() -> None:
    source_root = repo_root()
    with workspace_tempdir("ingest-html-open-only") as root:
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
        prior_status = {
            "checked_at": "2026-08-01T00:00:00Z",
            "frontiers_detail": {"publisher": "Frontiers", "deadline_enrichment": {"checked": 7}},
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
        (root / "data/source_status.json").write_text(json.dumps(prior_status), encoding="utf-8")
        assert (
            run(
                root,
                dry_run=True,
                open_only=True,
                ingest_html={
                    "sciencedirect-cfp": source_root / "tests/fixtures/sciencedirect_cfp.html",
                },
            )
            == 0
        )
        rows = [
            json.loads(line)
            for line in (root / "data/collections.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        titles = {row["title"] for row in rows}
        assert any("Soft Robotics" in title for title in titles)
        assert not any("neuroscientists" in title for title in titles)
        assert "Atmospheric Chemistry in China" not in titles
        assert all(row["status"] == "open" for row in rows)
        status = json.loads((root / "data/source_status.json").read_text(encoding="utf-8"))
        assert status["sources"]["nature-psychology"]["parsed"] == 55
        assert status["frontiers_detail"]["deadline_enrichment"]["checked"] == 7
        assert status["sources"]["sciencedirect-cfp"]["ok"] is True
        assert status["sources"]["sciencedirect-cfp"]["enabled"] is False
        assert status["sources"]["sciencedirect-cfp"]["dropped_unclassified"] == 1
        assert status["sources"]["sciencedirect-cfp"]["skipped_closed"] == 1


def test_elsevier_scope_pattern_requires_cognition_as_a_word() -> None:
    import re

    from radar.config import load_sources

    pattern = next(
        source["scope_pattern"]
        for source in load_sources(repo_root())["sources"]
        if source["key"] == "sciencedirect-cfp"
    )
    assert re.search(pattern, "Cognition, Learning, and Agency BioSystems", re.I)
    assert re.search(pattern, "Brain and Cognition Neurocognitive Adaptations", re.I)
    assert not re.search(pattern, "Pattern Recognition Letters Generative Models", re.I)
    assert not re.search(pattern, "Journal of Business Venturing Recognition of Hidden Potential", re.I)
