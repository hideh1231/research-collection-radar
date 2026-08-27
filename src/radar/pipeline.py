from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import UTC, date, datetime
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
from threading import Event
from typing import Any, Iterator

from radar.alerts import digest_text, ledger_entries, ledger_keys, new_alert_key, new_records
from radar.classify import classify
from radar.collectors.frontiers import enrich_deadlines
from radar.collectors.registry import run_source
from radar.config import (
    collection_type_labels,
    domain_labels,
    load_alerts,
    load_domains,
    load_sources,
    repo_root,
)
from radar.http import Fetcher
from radar.normalize import to_record
from radar.slack import credentials, post_message
from radar.store import (
    index_by_id,
    load_jsonl,
    load_schema,
    migrate_rows,
    replace_staged,
    stage_jsonl,
    validate_record,
)
from radar.views import render_open_md


def log(message: str) -> None:
    print(message, file=sys.stderr)


def commit_if_actions(root: Path, summary: str) -> None:
    if os.environ.get("GITHUB_ACTIONS") != "true":
        return
    subprocess.run(["git", "add", "data", "state", "OPEN.md"], cwd=root, check=False)
    status = subprocess.run(["git", "status", "--porcelain"], cwd=root, check=True, capture_output=True, text=True)
    if not status.stdout.strip():
        return
    subprocess.run(["git", "config", "user.name", "github-actions[bot]"], cwd=root, check=True)
    subprocess.run(
        ["git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com"],
        cwd=root,
        check=True,
    )
    subprocess.run(["git", "commit", "-m", summary], cwd=root, check=True)
    subprocess.run(["git", "push"], cwd=root, check=False)


def _stage_text(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return temporary


def _write_artifacts_atomic(
    root: Path,
    rows: list[dict[str, Any]],
    today: date,
    source_status: dict[str, Any],
    schema: Any,
    domain_display_labels: dict[str, str] | None = None,
    type_display_labels: dict[str, str] | None = None,
) -> None:
    errors: list[str] = []
    for row in rows:
        errors.extend(validate_record(row, schema))
    if errors:
        raise ValueError(f"invalid final collection row: {errors[0]}")

    data_path = root / "data" / "collections.jsonl"
    open_path = root / "OPEN.md"
    status_path = root / "data" / "source_status.json"
    staged: list[Path] = []
    try:
        staged.append(stage_jsonl(data_path, rows))
        staged.append(
            _stage_text(
                open_path,
                render_open_md(
                    rows,
                    today,
                    domain_labels=domain_display_labels,
                    type_labels=type_display_labels,
                ),
            )
        )
        staged.append(_stage_text(status_path, json.dumps(source_status, ensure_ascii=False, indent=2) + "\n"))
        # Replace the source of truth first, then its two derived artifacts.
        replace_staged(staged[0], data_path)
        replace_staged(staged[1], open_path)
        replace_staged(staged[2], status_path)
        staged.clear()
    finally:
        for path in staged:
            path.unlink(missing_ok=True)


@contextmanager
def _stop_events(event: Event) -> Iterator[None]:
    previous: dict[int, Any] = {}
    try:
        for signum in (signal.SIGINT, signal.SIGTERM):
            try:
                previous[signum] = signal.getsignal(signum)
                signal.signal(signum, lambda _signum, _frame: event.set())
            except (ValueError, OSError):
                # Signal registration is unavailable outside the main thread.
                continue
        yield
    finally:
        for signum, handler in previous.items():
            try:
                signal.signal(signum, handler)
            except (ValueError, OSError):
                pass


def _frontiers_source(sources_cfg: dict[str, Any]) -> dict[str, Any] | None:
    for source in sources_cfg.get("sources", []):
        if source.get("collector") == "frontiers":
            return source
    return None


def _source_status_entry(result: Any) -> dict[str, Any]:
    return {
        "enabled": True,
        "ok": result.ok,
        "http_status": result.http_status,
        "parsed": result.parsed_count,
        "pages": result.page_count,
        "error": result.error,
    }


def run(
    root: Path,
    *,
    dry_run: bool = False,
    offline: bool = False,
    backfill_deadlines: bool = False,
) -> int:
    today = date.today()
    sources_cfg = load_sources(root)
    domains_cfg = load_domains(root)
    domain_display_labels = domain_labels(domains_cfg)
    type_display_labels = collection_type_labels(domains_cfg)
    alerts_cfg = load_alerts(root)
    schema = load_schema(root / "schema" / "collection.schema.json")
    loaded_rows = load_jsonl(root / "data" / "collections.jsonl")
    prior_rows, migrated = migrate_rows(loaded_rows)
    prior = index_by_id(prior_rows)
    prior_ids = set(prior)
    ledger_path = root / "state" / "notification_ledger.jsonl"
    ledger = load_jsonl(ledger_path)
    known_keys = ledger_keys(ledger)

    source_status: dict[str, Any] = {
        "checked_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sources": {},
    }
    incoming: list[dict[str, Any]] = []
    incoming_frontiers_ids: set[str] = set()
    failures = 0
    stop_event = Event()
    frontiers = _frontiers_source(sources_cfg)

    # The regular run discovers list pages. Backfill only visits detail pages.
    fetcher = Fetcher(
        sources_cfg.get("user_agent", "research-collection-radar/0.1"),
        sources_cfg.get("timeout_seconds", 40),
    )
    try:
        if backfill_deadlines:
            for source in sources_cfg.get("sources", []):
                source_status["sources"][source["key"]] = {
                    "enabled": bool(source.get("enabled")),
                    "skipped": "backfill-deadlines",
                }
        elif offline:
            log("offline: skip network collectors")
            for source in sources_cfg.get("sources", []):
                source_status["sources"][source["key"]] = {"enabled": bool(source.get("enabled")), "skipped": "offline"}
        else:
            for source in sources_cfg.get("sources", []):
                if not source.get("enabled"):
                    source_status["sources"][source["key"]] = {"enabled": False}
                    continue
                result = run_source(fetcher, source)
                entry = _source_status_entry(result)
                source_status["sources"][source["key"]] = entry
                log(
                    f"{source['key']}: ok={result.ok} status={result.http_status} "
                    f"parsed={result.parsed_count} pages={result.page_count}"
                )
                if not result.ok:
                    failures += 1
                    continue
                for raw in result.records:
                    domains, scores, topics, method = classify(raw, domains_cfg, source["key"])
                    row = to_record(
                        raw,
                        today=today,
                        domains=domains,
                        domain_scores=scores,
                        topics=topics,
                        classification_method=method,
                        prior=prior,
                    )
                    errors = validate_record(row, schema)
                    if errors:
                        entry.setdefault("invalid_records", []).append({"id": row.get("id"), "error": errors[0]})
                        log(f"skip invalid {row.get('id')}: {errors[0]}")
                        continue
                    incoming.append(row)
                    if source.get("collector") == "frontiers" and row["id"] not in prior_ids:
                        incoming_frontiers_ids.add(row["id"])
    finally:
        fetcher.close()

    merged = {row["id"]: dict(row) for row in prior_rows}
    for row in incoming:
        # to_record already applies this policy. Keep the merge guard here so
        # callers constructing incoming rows cannot erase a confirmed deadline.
        previous = merged.get(row["id"])
        if previous and previous.get("deadline") and not row.get("deadline"):
            row["deadline"] = previous["deadline"]
            row["deadline_status"] = previous.get("deadline_status", "listed")
            row["deadline_checked_at"] = previous.get("deadline_checked_at")
        merged[row["id"]] = row
    current_rows = list(merged.values())

    if backfill_deadlines:
        # Persist the migrated canonical dataset before requesting any detail page.
        # This makes an interrupted first backfill resumable from valid artifacts.
        try:
            _write_artifacts_atomic(
                root,
                current_rows,
                today,
                source_status,
                schema,
                domain_display_labels,
                type_display_labels,
            )
        except ValueError as exc:
            log(str(exc))
            return 1

    enrichment: dict[str, Any] | None = None
    if frontiers and not offline and (backfill_deadlines or source_status["sources"].get(frontiers["key"], {}).get("ok")):
        source_entry = source_status["sources"].setdefault(frontiers["key"], {"enabled": bool(frontiers.get("enabled"))})
        enrichment_cfg = frontiers.get("deadline_enrichment") or {}
        detail_fetcher = Fetcher(
            sources_cfg.get("user_agent", "research-collection-radar/0.1"),
            sources_cfg.get("timeout_seconds", 40),
            min_interval_seconds=float(enrichment_cfg.get("min_interval_seconds", 1)),
        )

        def checkpoint(stats: dict[str, Any]) -> None:
            source_entry["deadline_enrichment"] = stats
            _write_artifacts_atomic(
                root,
                current_rows,
                today,
                source_status,
                schema,
                domain_display_labels,
                type_display_labels,
            )

        try:
            with _stop_events(stop_event):
                enrichment = enrich_deadlines(
                    detail_fetcher,
                    current_rows,
                    frontiers,
                    incoming_ids=incoming_frontiers_ids,
                    backfill=backfill_deadlines,
                    checkpoint=checkpoint,
                    stop_event=stop_event,
                )
        finally:
            detail_fetcher.close()
        source_entry["deadline_enrichment"] = enrichment
    elif frontiers:
        source_status["sources"].setdefault(frontiers["key"], {})["deadline_enrichment"] = {
            "target_count": 0,
            "checked": 0,
            "listed": 0,
            "with_deadline": 0,
            "not_listed": 0,
            "failed": 0,
            "rate_limited": 0,
            "parse_errors": 0,
            "forbidden": 0,
            "remaining": 0,
        }

    try:
        _write_artifacts_atomic(
            root,
            current_rows,
            today,
            source_status,
            schema,
            domain_display_labels,
            type_display_labels,
        )
    except ValueError as exc:
        log(str(exc))
        return 1

    # Backfill never explores, sends Slack, or mutates the notification ledger.
    if backfill_deadlines:
        if enrichment is None:
            return 1
        if enrichment.get("stop_reason") or enrichment.get("remaining", 0):
            return 1
        return 0

    fresh = new_records(incoming, prior_ids)
    open_new = [row for row in fresh if row.get("status") == "open"]
    unsent = [row for row in open_new if new_alert_key(row["id"]) not in known_keys]
    first_run = len(ledger) == 0
    token, channel = credentials()
    if dry_run:
        log(f"dry-run: {len(unsent)} new open records")
    elif first_run and alerts_cfg.get("skip_slack_when_ledger_empty", True):
        log("first run: write ledger, skip Slack")
        ledger.extend(ledger_entries(unsent))
        from radar.store import write_jsonl

        write_jsonl(ledger_path, ledger, key="alert_key")
    elif unsent and token and channel:
        text = digest_text(unsent, int(alerts_cfg.get("max_items_in_digest", 30)))
        slack_ok = post_message(text, token, channel)
        log(f"slack send success={slack_ok}")
        if slack_ok:
            ledger.extend(ledger_entries(unsent))
            from radar.store import write_jsonl

            write_jsonl(ledger_path, ledger, key="alert_key")
    elif unsent and not (token and channel):
        log("slack skipped: credentials missing")
    else:
        log("no new slack alerts")

    summary = f"data: update {len(incoming)} records ({len(open_new)} new open)"
    if not dry_run:
        commit_if_actions(root, summary)
    nature = source_status["sources"].get("nature-psychology", {})
    if nature.get("enabled") and not nature.get("ok", True) and not offline:
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="radar")
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--backfill-deadlines", action="store_true")
    args = parser.parse_args(argv)
    root = args.root or repo_root()
    return run(
        root,
        dry_run=args.dry_run,
        offline=args.offline,
        backfill_deadlines=args.backfill_deadlines,
    )


if __name__ == "__main__":
    raise SystemExit(main())
