"""Verify collection submission metadata against the actual publisher detail page."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
import re
import unicodedata
from urllib.parse import urlsplit, urlunsplit

from bs4 import BeautifulSoup

from radar.ids import content_hash
from radar.normalize import listing_status, parse_date, utc_now

COLLECTION_PATH = re.compile(r"^/collections/([a-z0-9]+)(?:/how-to-submit)?/?$")
HOSTS = {"nature.com", "www.nature.com", "link.springer.com"}
JSKE_PATH = re.compile(r"^/cfp/[a-z0-9-]+/?$")


def _words(text: str) -> set[str]:
    return set(re.findall(r"\w+", unicodedata.normalize("NFKC", text).casefold()))


def detail_url(row: dict) -> str | None:
    parts = urlsplit(row.get("url") or "")
    if (parts.scheme == "https" and parts.hostname in {"jske.org", "www.jske.org"}
            and JSKE_PATH.fullmatch(parts.path)
            and re.search(r"special\s+issue|extended\s+papers?|特集", row.get("title") or "", re.I)):
        return urlunsplit(parts._replace(netloc="www.jske.org"))
    if parts.scheme != "https" or parts.hostname not in HOSTS or not COLLECTION_PATH.fullmatch(parts.path):
        return None
    if parts.hostname == "nature.com":
        parts = parts._replace(netloc="www.nature.com")
    return urlunsplit(parts)


def parse_detail(html: str, row: dict, final_url: str) -> dict:
    """Reject redirects/unrelated pages before accepting dates or their absence."""
    expected = urlsplit(detail_url(row) or "")
    actual = urlsplit(final_url)
    if actual.hostname != expected.hostname or actual.path.rstrip("/") != expected.path.rstrip("/"):
        raise ValueError("detail redirected to another page")
    soup = BeautifulSoup(html, "lxml")
    main = soup.find("main") or soup.select_one("article.article_page") or soup
    heading = main.find("h1") or soup.title
    wanted = _words(row.get("title") or "")
    found = _words(heading.get_text(" ", strip=True) if heading else "")
    title_matches = bool(wanted) and len(wanted & found) / len(wanted) >= 0.8
    if expected.hostname in {"jske.org", "www.jske.org"}:
        if not title_matches:
            raise ValueError("detail title does not match collection")
        text = main.get_text(" ", strip=True)
        # Use the submission label and its optional extension; never the post date.
        date_value = r"[A-Za-z]+\s+\d{1,2}(?:st|nd|rd|th)?\s*,\s*\d{4}"
        match = re.search(r"Deadline (?:for|of) paper submission\s*:\s*(" + date_value +
                          r")(?:\s*[.。]?\s*→\s*(" + date_value + r"))?", text, re.I)
        if not match:
            raise ValueError("manuscript deadline label missing")
        value = match.group(2) or match.group(1)
        value = re.sub(r"(\d)(?:st|nd|rd|th)\b", r"\1", value, flags=re.I)
        deadline = parse_date(value)
        if deadline is None:
            raise ValueError("unrecognized submission deadline")
        status = listing_status(deadline)
    elif expected.hostname == "www.nature.com":
        state = main.select_one('[data-test="status"]')
        state_text = state.get_text(" ", strip=True).casefold() if state else ""
        status = state_text if state_text in {"open", "closed"} else "unknown"
        # Collections can be renamed. An exact collection URL and the publisher's
        # submission panel establish identity even after a complete title change.
        if not title_matches and not (main.find("h1") and status in {"open", "closed"}):
            raise ValueError("detail title does not match collection")
        end = main.select_one('time[data-test="end-date"]')
        deadline = parse_date(end.get("datetime") or end.get_text(" ", strip=True)) if end else None
        if end and deadline is None:
            raise ValueError("unrecognized submission deadline")
    else:
        if not title_matches:
            raise ValueError("detail title does not match collection")
        text = main.get_text(" ", strip=True)
        status = "closed" if "Closed for submissions" in text else "open" if "Open for submissions" in text else "unknown"
        end = main.select_one('[data-test="submission-deadline"]')
        value = end.get_text(" ", strip=True).removeprefix("Submission deadline").strip() if end else ""
        deadline = parse_date(value)
        if value and deadline is None and value.casefold() != "ongoing":
            raise ValueError("unrecognized submission deadline")
    result = {"deadline": deadline.isoformat() if deadline else None,
              "deadline_status": "listed" if deadline else "not_listed", "status": status}
    if not title_matches:
        result["title"] = heading.get_text(" ", strip=True)
    return result


def check_deadlines(rows: list[dict], fetcher, *, limit: int = 100, only: set[str] | None = None,
                    now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    stats = {"checked_at": now.isoformat(), "attempted": 0, "checked": 0, "updated": 0,
             "listed": 0, "not_listed": 0, "closed": 0, "unknown": 0, "errors": {}}
    if only:
        stats["source_keys"] = sorted(only)
    targets = []
    for row in rows:
        if not detail_url(row) or row.get("status") not in {"open", "unknown"}:
            continue
        if only and not (only & set(row.get("source_keys") or [row.get("discovered_via")])):
            continue
        checked = row.get("deadline_checked_at")
        try:
            due = not checked or datetime.fromisoformat(checked.replace("Z", "+00:00")) <= now - timedelta(days=7)
        except (ValueError, TypeError):
            due = True
        if row.get("deadline_status") == "not_checked" or (row.get("deadline_status") == "not_listed" and due):
            targets.append(row)
    targets.sort(key=lambda r: (r.get("deadline_status") != "not_checked", r.get("deadline_checked_at") or "", r["id"]))
    for row in targets[:max(0, limit)]:
        stats["attempted"] += 1
        try:
            response = fetcher.get(detail_url(row))
            if response.status_code != 200:
                raise ValueError(f"http {response.status_code}")
            observation = parse_detail(response.text, row, str(response.url))
        except Exception as exc:
            stats["errors"][row["id"]] = str(exc)
            continue
        checked_at = utc_now()
        # A missing value never deletes a previously confirmed exact deadline.
        if row.get("deadline") and observation["deadline"] is None:
            observation["deadline"] = row["deadline"]
            observation["deadline_status"] = "listed"
        row.update(observation, deadline_checked_at=checked_at)
        new_hash = content_hash(row)
        if new_hash != row.get("content_hash"):
            row.update(content_hash=new_hash, last_changed=checked_at)
            stats["updated"] += 1
        stats["checked"] += 1
        stats[observation["deadline_status"]] += 1
        if observation["status"] in {"closed", "unknown"}:
            stats[observation["status"]] += 1
    stats["remaining"] = len(targets) - stats["checked"]
    return stats
