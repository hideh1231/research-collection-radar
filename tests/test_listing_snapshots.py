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
