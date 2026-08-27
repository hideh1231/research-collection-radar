from datetime import date

from radar.normalize import normalize_status, parse_date


def test_parse_deadline() -> None:
    assert parse_date("21 April 2027") == date(2027, 4, 21)
    assert parse_date("Deadline: 26 May 2027") == date(2027, 5, 26)


def test_normalize_status() -> None:
    assert normalize_status("Open") == "open"
    assert normalize_status("Submission closed") == "closed"
    assert normalize_status("") == "unknown"


def test_migrate_record_canonicalizes_plos_journal_names() -> None:
    from radar.normalize import migrate_record

    row = migrate_record(
        {
            "id": "plos-1",
            "publisher": "PLOS",
            "discovered_via": "plos-collections",
            "journal": "PLOS Medicine Is Calling Submissions Of",
            "journals": ["PLOS Medicine Is Calling Submissions Of", "PLOS One Submit To PLOS One"],
            "title": "A call",
            "url": "https://collections.plos.org/call-for-papers/a-call",
            "status": "open",
            "deadline": None,
            "content_hash": "old",
        }
    )
    assert row["journal"] == "PLOS Medicine"
    assert row["journals"] == ["PLOS Medicine", "PLOS ONE"]
