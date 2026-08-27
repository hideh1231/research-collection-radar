from radar.alerts import deadline_text, digest_text, new_alert_key, new_records


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


def test_digest_distinguishes_deadline_states() -> None:
    rows = [
        {"id": "a", "title": "Listed", "journal": "J", "url": "https://example.org/a", "deadline": "2027-01-01", "domains": []},
        {"id": "b", "title": "Absent", "journal": "J", "url": "https://example.org/b", "deadline": None, "deadline_status": "not_listed", "domains": []},
        {"id": "c", "title": "Unchecked", "journal": "J", "url": "https://example.org/c", "deadline": None, "deadline_status": "not_checked", "domains": []},
    ]
    text = digest_text(rows, limit=3)
    assert deadline_text(rows[0]) == "2027-01-01"
    assert "Listed" in text and "2027-01-01" in text
    assert "Absent" in text and "Deadline not listed" in text
    assert "Unchecked" in text and "Deadline not checked" in text


def test_digest_reports_only_omitted_count() -> None:
    rows = [{"id": str(i), "title": f"T{i}", "journal": "J", "url": f"https://example.org/{i}", "domains": []} for i in range(3)]
    text = digest_text(rows, limit=1)
    assert "… 2 more" in text
    assert "OPEN.md" not in text
