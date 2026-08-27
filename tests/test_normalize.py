from datetime import date

from radar.normalize import normalize_status, parse_date


def test_parse_deadline() -> None:
    assert parse_date("21 April 2027") == date(2027, 4, 21)
    assert parse_date("Deadline: 26 May 2027") == date(2027, 5, 26)
    assert parse_date("Manuscript Extension Submission Deadline 7 September 2026") == date(2026, 9, 7)


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


def test_migrate_record_splits_publisher_keyword_blobs() -> None:
    from radar.normalize import migrate_record

    row = migrate_record(
        {
            "id": "frontiers-1",
            "publisher": "Frontiers",
            "journal": "Frontiers in Robotics and AI",
            "url": "https://frontiersin.org/research-topics/1/robots",
            "status": "open",
            "deadline": None,
            "publisher_keywords": [
                "untethered soft robots; soft actuators; soft sensors; embedded intelligence"
            ],
            "topics": ["untethered soft robots; soft actuators; soft sensors; embedded intelligence"],
            "content_hash": "old",
        }
    )
    assert "untethered soft robots" in row["publisher_keywords"]
    assert "soft actuators" in row["topics"]
    assert all(";" not in topic for topic in row["topics"])
    assert all(len(topic) <= 40 for topic in row["topics"])
    assert row["topics_method"] == "publisher"
