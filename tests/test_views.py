from datetime import date

from radar.views import render_open_md


def _row(title: str, **updates) -> dict:
    row = {
        "title": title,
        "journal": "Journal",
        "url": "https://example.org/call",
        "status": "open",
        "deadline": "2027-01-02",
        "domains": ["psychology"],
        "collection_type": "collection",
    }
    row.update(updates)
    return row


def test_open_view_filters_and_uses_configured_labels() -> None:
    text = render_open_md(
        [
            _row("Included"),
            _row("No deadline", deadline=None, deadline_status="not_checked"),
            _row("Closed", status="closed"),
            _row("Unknown", status="unknown"),
        ],
        date(2026, 8, 26),
        domain_labels={"psychology": "Psychology (configured)"},
        type_labels={"collection": "Collection (configured)"},
    )
    assert "Included" in text
    assert "Psychology (configured)" in text
    assert "Collection (configured)" in text
    assert "No deadline" not in text
    assert "Closed" not in text
    assert "Unknown" not in text


def test_open_view_has_all_public_columns() -> None:
    text = render_open_md([_row("A")], date(2026, 8, 26))
    assert "| Deadline | Title | Journal | Fields | Type | URL |" in text
    assert "| 2027-01-02 | A | Journal | Psychology | Collection | https://example.org/call |" in text
