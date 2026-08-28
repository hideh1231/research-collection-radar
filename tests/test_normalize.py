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


def test_merge_keeps_existing_journal_and_deadline() -> None:
    from radar.normalize import merge_collection_rows

    current = {
        "id": "nature-commsbio-abc",
        "journal": "Communications Biology",
        "journals": ["Communications Biology"],
        "source_keys": ["nature-commsbio"],
        "url": "https://nature.com/collections/abc",
        "source_url": "https://nature.com/commsbio/calls-for-papers",
        "deadline": "2027-02-14",
        "deadline_status": "listed",
        "deadline_checked_at": "2026-08-27T00:00:00Z",
        "topics": ["parenting"],
        "first_seen": "2026-08-01",
        "content_hash": "old",
        "discovered_via": "nature-commsbio",
        "domains": [],
    }
    incoming = {
        "id": "nature-neuro-abc",
        "journal": "Nature Neuroscience",
        "journals": ["Nature Neuroscience"],
        "source_keys": ["nature-neuro"],
        "url": "https://nature.com/collections/abc",
        "source_url": "https://nature.com/neuro/collections",
        "deadline": None,
        "deadline_status": "not_checked",
        "topics": [],
        "first_seen": "2026-08-28",
        "content_hash": "new",
        "discovered_via": "nature-neuro",
        "domains": ["neuroscience"],
        "title": "Parenting circuits",
        "status": "open",
    }
    merged = merge_collection_rows(current, incoming)
    assert merged["id"] == "nature-commsbio-abc"
    assert merged["journal"] == "Communications Biology"
    assert merged["journals"] == ["Communications Biology", "Nature Neuroscience"]
    assert merged["deadline"] == "2027-02-14"
    assert merged["deadline_status"] == "listed"
    assert "nature-commsbio" in merged["source_keys"]
    assert "nature-neuro" in merged["source_keys"]
    assert "neuroscience" in merged["domains"]
    assert "parenting" in merged["topics"]


def test_collapse_duplicate_nature_collection_ids() -> None:
    from radar.normalize import collapse_duplicate_publisher_ids

    rows = [
        {
            "id": "nature-ncomms-xyz",
            "publisher": "Nature Portfolio",
            "publisher_id": "abc123",
            "journal": "Nature Communications",
            "journals": ["Nature Communications"],
            "source_keys": ["nature-ncomms"],
            "discovered_via": "nature-ncomms",
            "deadline": "2027-01-01",
            "deadline_status": "listed",
            "topics": ["circuits"],
            "first_seen": "2026-08-02",
            "content_hash": "b",
            "domains": [],
        },
        {
            "id": "nature-commsbio-xyz",
            "publisher": "Nature Portfolio",
            "publisher_id": "abc123",
            "journal": "Communications Biology",
            "journals": ["Communications Biology"],
            "source_keys": ["nature-commsbio"],
            "discovered_via": "nature-commsbio",
            "deadline": "2027-01-01",
            "deadline_status": "listed",
            "topics": [],
            "first_seen": "2026-08-01",
            "content_hash": "a",
            "domains": [],
        },
        {
            "id": "frontiers-1",
            "publisher": "Frontiers",
            "publisher_id": "99",
            "journal": "Frontiers in Psychology",
            "journals": ["Frontiers in Psychology"],
            "source_keys": ["frontiers-psychology"],
            "discovered_via": "frontiers-psychology",
            "first_seen": "2026-08-01",
            "content_hash": "c",
            "domains": ["psychology"],
        },
    ]
    collapsed = collapse_duplicate_publisher_ids(rows)
    nature = [row for row in collapsed if row["publisher"] == "Nature Portfolio"]
    assert len(collapsed) == 2
    assert len(nature) == 1
    assert nature[0]["id"] == "nature-commsbio-xyz"
    assert nature[0]["journal"] == "Communications Biology"
    assert nature[0]["journals"] == ["Communications Biology", "Nature Communications"]
    assert nature[0]["deadline"] == "2027-01-01"
    assert "circuits" in nature[0]["topics"]
