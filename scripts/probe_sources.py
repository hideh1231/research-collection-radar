"""Check configured collectors without changing the index or sending notifications."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import UTC, datetime
import json
from pathlib import Path
from time import monotonic

from radar.collectors.registry import run_source
from radar.config import load_sources, repo_root
from radar.http import Fetcher


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=repo_root())
    parser.add_argument("--only", action="append", default=[], metavar="SOURCE_KEY")
    parser.add_argument("--include-disabled", action="store_true")
    parser.add_argument("--timeout", type=float)
    parser.add_argument("--retries", type=int, default=1)
    parser.add_argument("--max-pages", type=int, help="Override pagination budget (truncation remains a failure).")
    parser.add_argument("--output", type=Path, help="Write diagnostic JSON; never updates collection data.")
    args = parser.parse_args(argv)
    cfg = load_sources(args.root)
    configured = {source["key"]: source for source in cfg["sources"]}
    unknown = set(args.only) - configured.keys()
    if unknown:
        parser.error(f"unknown source keys: {', '.join(sorted(unknown))}")
    if args.retries < 1 or (args.timeout is not None and args.timeout <= 0):
        parser.error("retries and timeout must be positive")
    if args.max_pages is not None and args.max_pages < 1:
        parser.error("max-pages must be positive")
    sources = [source for source in configured.values()
               if (source["key"] in args.only if args.only else
                   source.get("enabled") or args.include_disabled)]
    report = {"checked_at": datetime.now(UTC).isoformat(), "sources": {}}
    fetcher = Fetcher(cfg["user_agent"], args.timeout or cfg.get("timeout_seconds", 40),
                      retries=args.retries, min_interval_seconds=0.2)
    try:
        for source in sources:
            source = {"max_pages": cfg.get("max_pages", 40), **source}
            if args.max_pages is not None:
                source["max_pages"] = args.max_pages
            started = monotonic()
            try:
                result = run_source(fetcher, source)
                entry = {
                    "ok": result.ok, "http_status": result.http_status, "error": result.error,
                    "pages": result.page_count, "parsed": result.parsed_count,
                    "statuses": dict(Counter(record.status for record in result.records)),
                    "with_deadline": sum(record.deadline is not None for record in result.records),
                    "samples": [{"title": row.title, "journal": row.journal, "url": row.url,
                                 "status": row.status,
                                 "deadline": row.deadline.isoformat() if row.deadline else None}
                                for row in result.records[:3]],
                }
            except Exception as exc:
                entry = {"ok": False, "error": f"{type(exc).__name__}: {exc}", "parsed": 0}
            entry["seconds"] = round(monotonic() - started, 2)
            entry["url"] = source["url"]
            entry["enabled"] = bool(source.get("enabled"))
            report["sources"][source["key"]] = entry
            print(f"{source['key']}: ok={entry['ok']} parsed={entry['parsed']} "
                  f"error={entry.get('error')} seconds={entry['seconds']}", flush=True)
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    finally:
        fetcher.close()
    return int(any(not result["ok"] for result in report["sources"].values()))


if __name__ == "__main__":
    raise SystemExit(main())
