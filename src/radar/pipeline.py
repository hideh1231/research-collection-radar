from __future__ import annotations

import argparse
from datetime import UTC, date, datetime
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

from radar.alerts import digest_text, ledger_entries, ledger_keys, new_alert_key, new_records
from radar.classify import classify
from radar.collectors.frontiers import FrontiersCollector
from radar.collectors.registry import run_source
from radar.config import load_alerts, load_domains, load_sources, repo_root
from radar.http import Fetcher
from radar.normalize import to_record
from radar.slack import credentials, post_message
from radar.store import index_by_id, load_jsonl, load_schema, validate_record, write_jsonl
from radar.views import write_open_md


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


def run(root: Path, *, dry_run: bool = False, offline: bool = False) -> int:
    today = date.today()
    sources_cfg = load_sources(root)
    domains_cfg = load_domains(root)
    alerts_cfg = load_alerts(root)
    schema = load_schema(root / "schema" / "collection.schema.json")
    prior_rows = load_jsonl(root / "data" / "collections.jsonl")
    prior = index_by_id(prior_rows)
    ledger_path = root / "state" / "notification_ledger.jsonl"
    ledger = load_jsonl(ledger_path)
    known_keys = ledger_keys(ledger)

    fetcher = Fetcher(sources_cfg.get("user_agent", "research-collection-radar/0.1"), sources_cfg.get("timeout_seconds", 40))
    source_status: dict[str, Any] = {
        "checked_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sources": {},
    }
    incoming: list[dict[str, Any]] = []
    failures = 0
    try:
        if offline:
            log("offline: skip network collectors")
        else:
            for source in sources_cfg.get("sources", []):
                if not source.get("enabled"):
                    source_status["sources"][source["key"]] = {"enabled": False}
                    continue
                result = run_source(fetcher, source)
                source_status["sources"][source["key"]] = {
                    "enabled": True,
                    "ok": result.ok,
                    "http_status": result.http_status,
                    "parsed": result.parsed_count,
                    "pages": result.page_count,
                    "error": result.error,
                }
                log(
                    f"{source['key']}: ok={result.ok} status={result.http_status} "
                    f"parsed={result.parsed_count} pages={result.page_count}"
                )
                if not result.ok:
                    failures += 1
                    continue
                records = result.records
                if source["collector"] == "frontiers":
                    existing_ids = set(prior)
                    FrontiersCollector().fill_deadlines(fetcher, records, existing_ids, source)
                for raw in records:
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
                        log(f"skip invalid {row.get('id')}: {errors[0]}")
                        continue
                    incoming.append(row)
    finally:
        fetcher.close()

    merged = {row["id"]: row for row in prior_rows}
    for row in incoming:
        merged[row["id"]] = row
    current_rows = list(merged.values())
    write_jsonl(root / "data" / "collections.jsonl", current_rows)
    write_open_md(root / "OPEN.md", current_rows, today)
    (root / "data").mkdir(parents=True, exist_ok=True)
    (root / "data" / "source_status.json").write_text(
        json.dumps(source_status, indent=2) + "\n",
        encoding="utf-8",
    )

    fresh = new_records(incoming, set(prior))
    open_new = [row for row in fresh if row.get("status") == "open"]
    unsent = [row for row in open_new if new_alert_key(row["id"]) not in known_keys]
    first_run = len(ledger) == 0
    slack_ok = None
    token, channel = credentials()
    if dry_run:
        log(f"dry-run: {len(unsent)} new open records")
    elif first_run and alerts_cfg.get("skip_slack_when_ledger_empty", True):
        log("first run: write ledger, skip Slack")
        ledger.extend(ledger_entries(unsent))
        write_jsonl(ledger_path, ledger, key="alert_key")
    elif unsent and token and channel:
        text = digest_text(unsent, int(alerts_cfg.get("max_items_in_digest", 30)))
        slack_ok = post_message(text, token, channel)
        log(f"slack send success={slack_ok}")
        if slack_ok:
            ledger.extend(ledger_entries(unsent))
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
    args = parser.parse_args(argv)
    root = args.root or repo_root()
    return run(root, dry_run=args.dry_run, offline=args.offline)


if __name__ == "__main__":
    raise SystemExit(main())
