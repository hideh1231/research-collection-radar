from radar.ids import allowed_url, canonicalize_url, content_hash, stable_id


def test_strips_tracking_query() -> None:
    url = "https://www.nature.com/collections/abc?utm_source=x&foo=1"
    assert canonicalize_url(url) == "https://nature.com/collections/abc?foo=1"


def test_allowed_hosts() -> None:
    assert allowed_url("https://www.nature.com/collections/abc", ["nature.com"])
    assert not allowed_url("javascript:alert(1)", ["nature.com"])
    assert not allowed_url("https://evil.example/collections/abc", ["nature.com"])


def test_stable_id_is_deterministic() -> None:
    assert stable_id("nature", "https://nature.com/x") == stable_id("nature", "https://nature.com/x")


def test_content_hash_ignores_check_timestamps() -> None:
    row = {
        "title": "A",
        "journal": "J",
        "journals": ["J"],
        "collection_type": "collection",
        "deadline": None,
        "deadline_status": "not_checked",
        "status": "open",
        "summary": None,
        "publisher_keywords": [],
        "topics": [],
        "image_url": None,
        "metadata_checked_at": "2026-08-01T00:00:00Z",
        "deadline_checked_at": "2026-08-01T00:00:00Z",
    }
    later = dict(row, metadata_checked_at="2026-08-27T00:00:00Z", deadline_checked_at="2026-08-27T00:00:00Z")
    changed = dict(row, summary="About the call")
    assert content_hash(row) == content_hash(later)
    assert content_hash(row) != content_hash(changed)
