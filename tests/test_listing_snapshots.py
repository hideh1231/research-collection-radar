import httpx
import pytest

from radar.listing_snapshots import SnapshotError, download_snapshot, snapshot_url_allowed


def test_snapshot_url_allows_github_raw_and_gists() -> None:
    assert snapshot_url_allowed("https://raw.githubusercontent.com/org/repo/main/apa.html")
    assert snapshot_url_allowed("https://gist.githubusercontent.com/user/id/raw/apa.html")
    assert snapshot_url_allowed("https://objects.githubusercontent.com/release-asset")


def test_snapshot_url_rejects_arbitrary_hosts() -> None:
    assert not snapshot_url_allowed("https://www.apa.org/pubs/journals/resources/calls-for-papers")
    assert not snapshot_url_allowed("https://www.sciencedirect.com/browse/calls-for-papers")
    assert not snapshot_url_allowed("http://raw.githubusercontent.com/org/repo/main/apa.html")
    assert not snapshot_url_allowed("https://example.com/apa.html")


def test_download_snapshot_refuses_disallowed_host(tmp_path) -> None:
    with pytest.raises(SnapshotError, match="not allowed"):
        download_snapshot("https://127.0.0.1/secret", tmp_path / "x.html")


@pytest.mark.parametrize("url", [
    "https://raw.githubusercontent.com:8080/org/repo/main/apa.html",
    "https://user:password@raw.githubusercontent.com/org/repo/main/apa.html",
    "https://raw.githubusercontent.com:invalid/org/repo/main/apa.html",
    "https://[invalid/apa.html",
])
def test_snapshot_url_rejects_credentials_and_invalid_authorities(url) -> None:
    assert not snapshot_url_allowed(url)


def _mock_client(monkeypatch, handler) -> None:
    client = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: client(transport=httpx.MockTransport(handler), **kwargs))


def test_snapshot_rejects_redirect_before_contacting_unapproved_host(monkeypatch, tmp_path) -> None:
    requests = []

    def handler(request):
        requests.append(str(request.url))
        return httpx.Response(302, headers={"Location": "https://127.0.0.1/private"})

    _mock_client(monkeypatch, handler)
    dest = tmp_path / "snapshot.html"
    with pytest.raises(SnapshotError, match="not allowed"):
        download_snapshot("https://raw.githubusercontent.com/org/repo/main/apa.html", dest)
    assert len(requests) == 1
    assert not dest.exists()


def test_snapshot_follows_allowed_redirect(monkeypatch, tmp_path) -> None:
    def handler(request):
        if request.url.path == "/start":
            return httpx.Response(302, headers={"Location": "https://gist.githubusercontent.com/user/id/raw/apa.html"})
        return httpx.Response(200, text="<html>APA listing</html>")

    _mock_client(monkeypatch, handler)
    dest = download_snapshot("https://raw.githubusercontent.com/start", tmp_path / "snapshot.html")
    assert dest.read_text(encoding="utf-8") == "<html>APA listing</html>"


def test_snapshot_stops_oversized_stream_without_replacing_existing_file(monkeypatch, tmp_path) -> None:
    read_chunks = []

    class Stream(httpx.SyncByteStream):
        def __iter__(self):
            for chunk in (b"1234", b"5678", b"unneeded"):
                read_chunks.append(chunk)
                yield chunk

    _mock_client(monkeypatch, lambda _request: httpx.Response(200, stream=Stream()))
    monkeypatch.setattr("radar.listing_snapshots.SNAPSHOT_MAX_BYTES", 5)
    dest = tmp_path / "snapshot.html"
    dest.write_text("original", encoding="utf-8")
    with pytest.raises(SnapshotError, match="exceeds"):
        download_snapshot("https://raw.githubusercontent.com/start", dest)
    assert read_chunks == [b"1234", b"5678"]
    assert dest.read_text(encoding="utf-8") == "original"


def test_snapshot_transport_failure_uses_cli_error_type(monkeypatch, tmp_path) -> None:
    def handler(request):
        raise httpx.ReadTimeout("timed out", request=request)

    _mock_client(monkeypatch, handler)
    with pytest.raises(SnapshotError, match="download failed"):
        download_snapshot("https://raw.githubusercontent.com/start", tmp_path / "snapshot.html")
