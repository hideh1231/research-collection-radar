from radar.alerts import digest_text, new_alert_key, new_records


def test_alert_key() -> None:
    assert new_alert_key("abc") == "abc:new"


def test_new_records() -> None:
    current = [{"id": "a", "status": "open"}, {"id": "b", "status": "open"}]
    assert [row["id"] for row in new_records(current, {"a"})] == ["b"]


def test_digest_mentions_count() -> None:
    text = digest_text(
        [{"id": "a", "title": "Hello", "journal": "J", "deadline": "2027-01-01", "url": "https://example.org", "domains": ["hri"]}],
        limit=10,
    )
    assert "1 new" in text
    assert "Hello" in text
