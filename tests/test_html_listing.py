from datetime import date

from radar.collectors.html_listing import parse_listing
from radar.config import repo_root
from radar.journals import journal_is_watched, match_watched_journal, normalize_journal_name
from radar.listing_html import inspect_listing_html


def _source(key: str, kind: str, **extra) -> dict:
    base = {
        "key": key,
        "listing_kind": kind,
        "url": "https://example.org/list",
        "publisher": extra.pop("publisher", "Test"),
        "journal": extra.pop("journal", "Test Journal"),
        "allowed_hosts": extra.pop(
            "allowed_hosts",
            [
                "example.org",
                "journals.physiology.org",
                "science.org",
                "think.taylorandfrancis.com",
                "journals.sagepub.com",
                "www.pnas.org",
                "academic.oup.com",
                "bpspsychub.onlinelibrary.wiley.com",
                "opg.optica.org",
                "www.fujipress.jp",
                "vrsj.org",
                "www.ipsj.or.jp",
            ],
        ),
        "collection_type": "special_issue",
    }
    base.update(extra)
    return base


def test_journal_allowlist_matches_aliases_and_prefixes() -> None:
    assert normalize_journal_name("The Vision Research") == "vision research"
    assert match_watched_journal("Vision Research: An International Journal") == "Vision Research"
    assert journal_is_watched("Cognition")
    assert not journal_is_watched("Atmospheric Environment")
    assert journal_is_watched("Aging, Neuropsychology, and Cognition", publisher="Taylor & Francis")
    assert journal_is_watched("Journal of Neurophysiology")
    assert journal_is_watched("PNAS Nexus")
    assert journal_is_watched("J Neurosci")
    assert not journal_is_watched("Pattern Recognition Letters")


def test_aps_parser_reads_journal_sections() -> None:
    html = (repo_root() / "tests/fixtures/aps_calls.html").read_text(encoding="utf-8")
    records = parse_listing(html, _source("aps-cfp", "aps", publisher="American Physiological Society"))
    by_title = {row.title: row for row in records}
    assert "Now and Then" in by_title
    assert by_title["Now and Then"].journal == "Journal of Neurophysiology"
    assert by_title["Now and Then"].deadline == date(2026, 9, 15)
    assert "Cardiac Fibrosis" in by_title
    assert by_title["Cardiac Fibrosis"].journal.startswith("American Journal of Physiology")


def test_science_robotics_and_hub_parsers() -> None:
    html = (repo_root() / "tests/fixtures/science_robotics_cfp.html").read_text(encoding="utf-8")
    records = parse_listing(html, _source("science-robotics-cfp", "science_robotics", publisher="AAAS", journal="Science Robotics"))
    titles = {row.title for row in records}
    assert any("Haptics" in title for title in titles)
    assert any(row.deadline == date(2026, 6, 30) for row in records)

    tandf = parse_listing(
        (repo_root() / "tests/fixtures/tandf_cfp.html").read_text(encoding="utf-8"),
        _source("tandf-cfp", "tandf", publisher="Taylor & Francis", journal="Taylor & Francis"),
    )
    assert {row.journal for row in tandf} == {"Aging, Neuropsychology, and Cognition", "Critical Reviews in Analytical Chemistry"}

    sage = parse_listing(
        (repo_root() / "tests/fixtures/sage_cfp.html").read_text(encoding="utf-8"),
        _source("sage-cfp", "sage", publisher="SAGE"),
    )
    assert any("Timing" in row.title for row in sage)
    assert any(row.journal.startswith("Quarterly Journal") for row in sage)

    wiley = parse_listing(
        (repo_root() / "tests/fixtures/wiley_bjp.html").read_text(encoding="utf-8"),
        _source("wiley-bjp", "wiley", publisher="Wiley", journal="British Journal of Psychology"),
    )
    assert any("Climate" in row.title for row in wiley)
    assert wiley[0].deadline == date(2026, 10, 1)


def test_domestic_and_society_parsers() -> None:
    jrm = parse_listing(
        (repo_root() / "tests/fixtures/fujipress_jrm.html").read_text(encoding="utf-8"),
        _source("fujipress-jrm", "fujipress", publisher="Fuji Technology Press", journal="Journal of Robotics and Mechatronics"),
    )
    titles = {row.title: row for row in jrm}
    assert any("STEM" in title for title in titles)
    assert any(row.status == "closed" for row in jrm)
    assert not any("Regular Papers" in title for title in titles)

    vrsj = parse_listing(
        (repo_root() / "tests/fixtures/vrsj_special.html").read_text(encoding="utf-8"),
        _source("vrsj-special", "vrsj", publisher="VRSJ", journal="日本バーチャルリアリティ学会論文誌"),
    )
    assert any("VR心理学" in row.title for row in vrsj)
    assert any(row.deadline == date(2026, 9, 14) for row in vrsj)
    assert len({row.publisher_id for row in vrsj}) == len(vrsj) >= 2

    ipsj = parse_listing(
        (repo_root() / "tests/fixtures/ipsj_cfp.html").read_text(encoding="utf-8"),
        _source("ipsj-cfp", "ipsj", publisher="IPSJ", journal="情報処理学会論文誌"),
    )
    assert any("インタラクション" in row.title for row in ipsj)
    assert any(row.status == "closed" for row in ipsj)

    pnas = parse_listing(
        (repo_root() / "tests/fixtures/pnas_cfp.html").read_text(encoding="utf-8"),
        _source("pnas-cfp", "pnas", publisher="NAS", journal="PNAS"),
    )
    assert any("Animal Communication" in row.title for row in pnas)

    nexus = parse_listing(
        (repo_root() / "tests/fixtures/pnas_nexus_cfp.html").read_text(encoding="utf-8"),
        _source("pnas-nexus-cfp", "pnas_nexus", publisher="OUP", journal="PNAS Nexus"),
    )
    assert any("Geosciences" in row.title for row in nexus)

    josa = parse_listing(
        (repo_root() / "tests/fixtures/josa_a.html").read_text(encoding="utf-8"),
        _source("josa-a-features", "josa", publisher="Optica", journal="Journal of the Optical Society of America A"),
    )
    assert any("Color Vision" in row.title for row in josa)
    assert any(row.deadline == date(2026, 10, 15) for row in josa)


def test_listing_probes_accept_new_fixtures() -> None:
    root = repo_root()
    assert inspect_listing_html("aps-cfp", (root / "tests/fixtures/aps_calls.html").read_text(encoding="utf-8")).ok
    assert inspect_listing_html("science-robotics-cfp", (root / "tests/fixtures/science_robotics_cfp.html").read_text(encoding="utf-8")).ok
    assert inspect_listing_html("tandf-cfp", (root / "tests/fixtures/tandf_cfp.html").read_text(encoding="utf-8")).ok
    assert inspect_listing_html("sage-cfp", (root / "tests/fixtures/sage_cfp.html").read_text(encoding="utf-8")).ok
    assert inspect_listing_html("wiley-bjp", (root / "tests/fixtures/wiley_bjp.html").read_text(encoding="utf-8")).ok
    wall = inspect_listing_html("aps-cfp", "<html>Performing security verification</html>")
    assert wall.ok is False
