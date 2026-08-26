from radar.ids import allowed_url, canonicalize_url, stable_id


def test_strips_tracking_query() -> None:
    url = "https://www.nature.com/collections/abc?utm_source=x&foo=1"
    assert canonicalize_url(url) == "https://nature.com/collections/abc?foo=1"


def test_allowed_hosts() -> None:
    assert allowed_url("https://www.nature.com/collections/abc", ["nature.com"])
    assert not allowed_url("javascript:alert(1)", ["nature.com"])
    assert not allowed_url("https://evil.example/collections/abc", ["nature.com"])


def test_stable_id_is_deterministic() -> None:
    assert stable_id("nature", "https://nature.com/x") == stable_id("nature", "https://nature.com/x")
