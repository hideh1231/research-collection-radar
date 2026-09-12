from copy import deepcopy
from datetime import UTC, date, datetime
from io import BytesIO
from types import SimpleNamespace
from zipfile import ZipFile

import pytest

from radar.collectors.apa import parse_listing
from radar.collectors.call_document import parse_document
from radar.collectors.html_listing import parse_vrsj
from radar.deadline_checks import check_deadlines, parse_detail


def row(**extra):
    return dict(id="test", title="Cognitive biases", url="https://nature.com/collections/abcdefghij/how-to-submit",
                status="open", deadline=None, deadline_status="not_checked", **extra)


def page(state="Open", end=""):
    return f'<main><h1>Cognitive biases</h1><dd data-test="status">{state}</dd>{end}</main>'


def test_closed_detail_uses_submission_date_not_publication_date():
    result = parse_detail(page("Closed", '<time data-test="end-date" datetime="2024-10-28"></time>'
                               '<time datetime="2027-03-01">Publication</time>'), row(),
                          "https://www.nature.com/collections/abcdefghij/how-to-submit")
    assert result == {"deadline": "2024-10-28", "deadline_status": "listed", "status": "closed"}


@pytest.mark.parametrize("state, expected", [("Open", "open"), ("", "unknown")])
def test_checked_page_without_date_does_not_invent_a_deadline_or_open_status(state, expected):
    result = parse_detail(page(state), row(), "https://www.nature.com/collections/abcdefghij/how-to-submit")
    assert result == {"deadline": None, "deadline_status": "not_listed", "status": expected}


def test_springer_ongoing_is_explicitly_without_date():
    item = row()
    item["url"] = "https://link.springer.com/collections/abcdefghij"
    html = '<title>Cognitive biases | Springer Nature Link</title><main>Open for submissions' \
           '<div data-test="submission-deadline">Submission deadlineOngoing</div></main>'
    assert parse_detail(html, item, item["url"])["deadline_status"] == "not_listed"


@pytest.mark.parametrize("html, url, code", [
    (page(), "https://www.nature.com/", 200),
    ("<main><h1>Access denied</h1></main>", "https://www.nature.com/collections/abcdefghij/how-to-submit", 200),
    (page("Open", '<time data-test="end-date">Later</time>'), "https://www.nature.com/collections/abcdefghij/how-to-submit", 200),
    (page(), "https://www.nature.com/collections/abcdefghij/how-to-submit", 403),
])
def test_failed_check_preserves_entire_record(html, url, code):
    item = row(first_seen="2020-01-01", last_seen="2026-09-12")
    before = deepcopy(item)
    fetcher = SimpleNamespace(get=lambda _: SimpleNamespace(text=html, url=url, status_code=code))
    stats = check_deadlines([item], fetcher)
    assert item == before
    assert stats["checked"] == 0 and stats["remaining"] == 1
    assert stats["errors"][item["id"]]


def test_success_preserves_identity_history_and_obeys_recheck_interval():
    item = row(first_seen="2020-01-01", last_seen="2026-09-12", source_keys=["target"])
    calls = []
    def get(url):
        calls.append(url)
        return SimpleNamespace(text=page(), url=url, status_code=200)
    fetcher = SimpleNamespace(get=get)
    now = datetime.now(UTC)
    assert check_deadlines([item], fetcher, limit=0)["attempted"] == 0
    assert check_deadlines([item], fetcher, only={"another"})["attempted"] == 0
    assert check_deadlines([item], fetcher, now=now)["checked"] == 1
    assert check_deadlines([item], fetcher, now=now)["attempted"] == 0
    assert len(calls) == 1
    assert item["id"] == "test" and item["first_seen"] == "2020-01-01" and item["last_seen"] == "2026-09-12"


def test_explicit_apa_no_deadline_differs_from_unchecked():
    source = dict(key="apa-cfp", publisher="APA", journal="APA Journals", url="https://www.apa.org/calls")
    html = '<div class="bodyleft"><p class="title">Test Journal</p><ul>' \
           '<li><a href="/pubs/journals/test/rolling">A rolling research section</a> (no submission deadline)</li>' \
           '<li><a href="/pubs/journals/test/unknown">Another research section</a></li></ul></div>'
    records = parse_listing(html, source)
    assert records[0].extra["deadline_status"] == "not_listed"
    assert records[0].extra["deadline_checked_at"]
    assert records[1].extra == {}


def docx(text):
    out = BytesIO()
    with ZipFile(out, "w") as z:
        z.writestr("word/document.xml", '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                   f'<w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>')
    return out.getvalue()


def document_source():
    return dict(key="sage-test", title="Test collection", publisher="SAGE", journal="Test Journal",
                url="https://journals.sagepub.com/call.docx", allowed_hosts=["journals.sagepub.com"],
                document_format="docx", deadline_pattern=r"Submission deadline (?P<date>\d+ [A-Za-z]+ \d{4})")


def test_document_chooses_manuscript_deadline_and_fails_on_missing_label():
    source = document_source()
    item = parse_document(docx("Test collection. Abstract 1 January 2026. Submission deadline 1 November 2026. Publication 1 May 2027."), source, source["url"])
    assert item.deadline == date(2026, 11, 1)
    assert item.extra["deadline_status"] == "listed"
    with pytest.raises(ValueError, match="label missing"):
        parse_document(docx("Test collection. Abstract 1 January 2026."), source, source["url"])
    with pytest.raises(ValueError, match="redirected"):
        parse_document(docx("Test collection. Submission deadline 1 November 2026."), source, "https://journals.sagepub.com/")


def test_vrsj_uses_paper_deadline_and_does_not_invent_a_day_for_mid_month():
    source = dict(key="vrsj", publisher="VRSJ", journal="VRSJ", url="https://vrsj.org/calls")
    html = '<div><strong>【VR心理学10】</strong>申込締切 2026年8月28日 論文締切 2026年9月14日</div>' \
           '<div><strong>【クロスモーダル４】</strong>申込締切 2027年5月上旬 論文締切 2027年5月中旬</div>'
    records = parse_vrsj(html, source)
    assert records[0].deadline == date(2026, 9, 14)
    assert records[1].title == "クロスモーダル4"
    assert records[1].deadline is None and records[1].extra["deadline_status"] == "not_listed"


def test_renamed_nature_collection_requires_exact_url_and_submission_panel():
    html = '<main><h1>Interdisciplinarity in theory and practice</h1>' \
           '<dd data-test="status">Open</dd><time data-test="end-date" datetime="2026-12-31"></time></main>'
    result = parse_detail(html, row(), "https://www.nature.com/collections/abcdefghij/how-to-submit")
    assert result["deadline"] == "2026-12-31" and result["title"] == "Interdisciplinarity in theory and practice"


def test_jske_uses_extended_deadline_not_announcement_or_original_deadline():
    item = row()
    item["url"] = "https://jske.org/cfp/test-call"
    item["title"] = "Cognitive biases special issue"
    html = '<article class="article_page"><h1>Cognitive biases special issue</h1>2025/04/04 '
    html += 'Deadline for paper submission: June 30th, 2025 . → July 31, 2025 </article>'
    result = parse_detail(html, item, "https://www.jske.org/cfp/test-call")
    assert result["deadline"] == "2025-07-31" and result["status"] == "closed"


def test_deadline_cli_writes_valid_artifacts_and_never_notifies(tmp_path, monkeypatch):
    import json
    from radar.config import repo_root
    from radar.models import RawRecord
    from radar.normalize import to_record
    from radar.pipeline import main
    from radar.store import load_jsonl, write_jsonl
    from support import copy_radar_config

    copy_radar_config(repo_root(), tmp_path)
    raw = RawRecord(title="Cognitive biases", url=row()["url"], source_url="https://www.nature.com/calls",
                    publisher="Nature Portfolio", journal="Nature", collection_type="collection",
                    discovered_via="nature-humanities-social-sciences-communications")
    original = to_record(raw, today=date(2026, 1, 1), domains=[], domain_scores={}, topics=[], classification_method="keyword")
    write_jsonl(tmp_path / "data/collections.jsonl", [original])
    class Fetcher:
        def __init__(self, *args, **kwargs): pass
        def get(self, url): return SimpleNamespace(text=page("Closed"), url=url, status_code=200)
        def close(self): pass
    def forbidden(*args, **kwargs): raise AssertionError("dry deadline checks must not notify or commit")
    monkeypatch.setattr("radar.pipeline.Fetcher", Fetcher)
    monkeypatch.setattr("radar.pipeline.post_message", forbidden)
    monkeypatch.setattr("radar.pipeline.commit_if_actions", forbidden)
    assert main(["--root", str(tmp_path), "--check-deadlines", "--dry-run"]) == 0
    result = load_jsonl(tmp_path / "data/collections.jsonl")[0]
    assert result["id"] == original["id"] and result["first_seen"] == original["first_seen"]
    assert result["status"] == "closed"
    assert json.loads((tmp_path / "site/data/collections.json").read_text()) == []
    before = (tmp_path / "data/collections.jsonl").read_bytes()
    assert main(["--root", str(tmp_path), "--check-deadlines", "--limit", "-1"]) == 1
    assert (tmp_path / "data/collections.jsonl").read_bytes() == before
