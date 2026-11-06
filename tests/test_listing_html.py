import json
from unittest.mock import Mock

import httpx
import pytest

from radar.config import repo_root
from radar.listing_html import PublisherPageFetcher, inspect_listing_html, ingest_args_from_status
from radar.pipeline import main


def test_apa_fixture_looks_like_a_real_listing() -> None:
    html = (repo_root() / "tests/fixtures/apa_calls.html").read_text(encoding="utf-8")
    probe = inspect_listing_html("apa-cfp", html)
    assert probe.ok is True


def test_incapsula_stub_is_a_wall() -> None:
    html = (
        "<html><head><META NAME=\"robots\" CONTENT=\"noindex,nofollow\">"
        "<script src=\"/_Incapsula_Resource?SWJIYLWA=1\"></script></head><body></body></html>"
    )
    probe = inspect_listing_html("apa-cfp", html)
    assert probe.ok is False
    assert "incapsula" in probe.reason


def test_sciencedirect_fixture_looks_like_a_real_listing() -> None:
    html = (repo_root() / "tests/fixtures/sciencedirect_cfp.html").read_text(encoding="utf-8")
    probe = inspect_listing_html("sciencedirect-cfp", html)
    assert probe.ok is True


def test_sciencedirect_block_page_is_a_wall() -> None:
    html = "<html><body>There was a problem providing the content you requested</body></html>"
    probe = inspect_listing_html("sciencedirect-cfp", html)
    assert probe.ok is False


def test_tandf_loading_shell_is_not_a_listing() -> None:
    html = (
        '<h2>Search for current calls for papers</h2>'
        '<label>Manuscript deadline (expiring soon)</label>'
        '<div class="jtf__cfptool_filters--buttons-results"><strong>0</strong> result(s)</div>'
        '<div class="jtf__cfptool_posts" aria-busy="true"></div>'
    )
    assert inspect_listing_html("tandf-cfp", html).ok is False


def test_tandf_readiness_requires_parseable_cards() -> None:
    html = (repo_root() / "tests/fixtures/tandf_cfp.html").read_text(encoding="utf-8")
    assert inspect_listing_html("tandf-cfp", html).ok is True
    assert inspect_listing_html("tandf-cfp", "<p>3 results: call for papers deadline</p>").ok is False


def test_ingest_args_skip_failed_pages() -> None:
    args = ingest_args_from_status(
        {
            "pages": {
                "apa-cfp": {"ok": True, "path": "/tmp/apa.html"},
                "sciencedirect-cfp": {"ok": False, "path": "/tmp/sd.html"},
            }
        }
    )
    assert args == ["--ingest-html", "apa-cfp=/tmp/apa.html"]


def test_cli_ingest_rendered_passes_ok_files(monkeypatch, tmp_path) -> None:
    html = tmp_path / "apa-cfp.html"
    html.write_text("<div class='bodyleft'></div>", encoding="utf-8")
    (tmp_path / "status.json").write_text(
        json.dumps({"pages": {"apa-cfp": {"ok": True, "path": str(html)}}}),
        encoding="utf-8",
    )
    captured: dict = {}
    monkeypatch.setattr("radar.pipeline.run", lambda _root, **kwargs: captured.update(kwargs) or 0)
    assert main(["--open-only", "--ingest-rendered", str(tmp_path)]) == 0
    assert captured["open_only"] is True
    assert captured["ingest_html"]["apa-cfp"] == html


@pytest.mark.parametrize(("url", "body", "uses_chrome"), [
    ("https://www.nature.com/collections/abc", "<title>Client Challenge</title>", True),
    ("https://link.springer.com/journal/40359/collections", "<title>Client Challenge</title>", True),
    ("https://www.nature.com/collections/abc", "<title>A collection</title>", False),
    ("https://www.jske.org/cfp/example", "<title>Client Challenge</title>", False),
])
def test_publisher_chrome_runs_only_for_a_challenge_on_the_expected_hosts(monkeypatch, url, body, uses_chrome):
    response = httpx.Response(200, text=body, request=httpx.Request("GET", url))
    rendered = httpx.Response(200, text="<article>Collection</article>",
                              request=httpx.Request("GET", "https://www.nature.com/collections/abc"))
    fetcher = PublisherPageFetcher(Mock(get=Mock(return_value=response)))
    browser_get = Mock(return_value=rendered)
    monkeypatch.setattr(fetcher, "_browser_get", browser_get)

    assert fetcher.get(url) is (rendered if uses_chrome else response)
    if uses_chrome:
        browser_get.assert_called_once_with(url)
    else:
        browser_get.assert_not_called()
