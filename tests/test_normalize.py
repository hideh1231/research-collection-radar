from datetime import date

import pytest

from radar.normalize import normalize_status, parse_date


def test_parse_deadline() -> None:
    assert parse_date("21 April 2027") == date(2027, 4, 21)
    assert parse_date("Deadline: 26 May 2027") == date(2027, 5, 26)
    assert parse_date("Manuscript Extension Submission Deadline 7 September 2026") == date(2026, 9, 7)


def test_normalize_status() -> None:
    assert normalize_status("Open") == "open"
    assert normalize_status("Submission closed") == "closed"
    assert normalize_status("") == "unknown"


@pytest.mark.parametrize("value", ["April 21", "2027", "April 2027", "Deadline: 30", "TBA"])
def test_parse_date_requires_year_month_and_day(value) -> None:
    assert parse_date(value) is None


@pytest.mark.parametrize("value", ["2028-02-29", "29 February 2028", "February 29th, 2028"])
def test_parse_date_accepts_complete_leap_day(value) -> None:
    assert parse_date(value) == date(2028, 2, 29)


@pytest.mark.parametrize("value", [
    "Not accepting submissions",
    "We are not currently accepting submissions",
    "Submissions are no longer open",
    "Submission closed for this open access collection",
])
def test_normalize_status_closed_takes_precedence(value) -> None:
    assert normalize_status(value) == "closed"


def test_open_access_is_not_a_submission_status() -> None:
    assert normalize_status("Open access collection") == "unknown"
    assert normalize_status("Open for submissions") == "open"
    assert normalize_status("Currently open") == "open"
    assert normalize_status("An open-access collection") == "unknown"


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


def test_migration_preserves_catalog_overlay_without_timestamp_churn() -> None:
    from radar.normalize import migrate_record
    from radar.topics import apply_catalog_topics

    aliases = {"artificial intelligence": "AI", "human-robot interaction": "HRI"}
    row = migrate_record({
        "id": "frontiers-overlay", "publisher": "Frontiers",
        "journal": "Frontiers in Robotics and AI", "discovered_via": "frontiers-robotics",
        "url": "https://frontiersin.org/research-topics/1/robots",
        "title": "Robots and artificial intelligence", "summary": "Human-robot interaction",
        "status": "open", "deadline": None, "publisher_keywords": ["navigation"],
        "topics": ["navigation"], "topics_method": "publisher",
    })
    assert apply_catalog_topics([row], aliases=aliases, checked_at="2026-09-01T00:00:00Z") == 1
    restored = migrate_record(row)
    assert restored == row
    assert apply_catalog_topics([restored], aliases=aliases, checked_at="2026-09-02T00:00:00Z") == 0
    assert restored["topics"] == ["navigation", "AI", "HRI"]
    assert restored["topics_updated_at"] == "2026-09-01T00:00:00Z"


def test_migration_prioritizes_publisher_topics_and_retains_limit() -> None:
    from radar.normalize import migrate_record

    row = migrate_record({
        "publisher_keywords": ["navigation", "navigation"],
        "topics": ["navigation", *[f"topic {i}" for i in range(10)]],
    })
    assert len(row["topics"]) == 8
    assert row["topics"][0] == "navigation"
    assert row["topics"].count("navigation") == 1


def test_catalog_overlay_does_not_readd_differently_cased_publisher_topics() -> None:
    from radar.normalize import migrate_record
    from radar.topics import apply_catalog_topics

    rows = [migrate_record({
        "id": f"case-{i}", "status": "open", "title": "Mental health",
        "publisher_keywords": [label], "topics": [label],
        "topics_updated_at": "2026-09-01T00:00:00Z",
    }) for i, label in enumerate(["Mental Health", "mental health"])]
    assert apply_catalog_topics(rows, aliases={}, checked_at="2026-09-02T00:00:00Z") == 0
    assert [migrate_record(row) for row in rows] == rows
    assert all(row["topics_updated_at"] == "2026-09-01T00:00:00Z" for row in rows)


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


@pytest.mark.parametrize("status", ["open", "closed"])
def test_unknown_listing_preserves_verified_status_and_deadline_state(status) -> None:
    from radar.normalize import merge_collection_rows, to_record
    from radar.models import RawRecord

    raw = RawRecord(
        title="Psychology collection", url="https://example.org/collection", source_url="https://example.org/calls",
        publisher="Example", journal="Journal", collection_type="collection", discovered_via="first-source",
        status=status, extra={"id": "collection-example"},
    )
    kwargs = dict(
        today=date(2026, 9, 12), domains=[], domain_scores={}, topics=[], classification_method="keyword",
    )
    previous = to_record(raw, **kwargs)
    previous.update(deadline_status="not_listed", deadline_checked_at="2026-09-12T01:00:00Z")
    raw.status = "unknown"
    current = to_record(raw, prior={previous["id"]: previous}, **kwargs)
    assert current["status"] == status
    assert current["deadline_status"] == "not_listed"

    # Cross-listed observations may be normalized before either becomes prior data.
    unknown = to_record(raw, **kwargs)
    merged = merge_collection_rows(previous, unknown)
    assert merged["status"] == status
    assert merged["deadline_status"] == "not_listed"
    assert merged["deadline_checked_at"] == "2026-09-12T01:00:00Z"

    raw.status = "closed" if status == "open" else "open"
    updated = to_record(raw, prior={previous["id"]: previous}, **kwargs)
    assert merge_collection_rows(previous, updated)["status"] == raw.status
