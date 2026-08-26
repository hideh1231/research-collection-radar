from datetime import date

from radar.normalize import normalize_status, parse_date


def test_parse_deadline() -> None:
    assert parse_date("21 April 2027") == date(2027, 4, 21)
    assert parse_date("Deadline: 26 May 2027") == date(2027, 5, 26)


def test_normalize_status() -> None:
    assert normalize_status("Open") == "open"
    assert normalize_status("Submission closed") == "closed"
    assert normalize_status("") == "unknown"
