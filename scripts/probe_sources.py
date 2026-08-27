from __future__ import annotations

from radar.collectors.apa import ApaCollector
from radar.collectors.frontiers import parse_listing as parse_frontiers
from radar.collectors.plos import PlosCollector
from radar.collectors.royal_society import RoyalSocietyCollector
from radar.collectors.sciencedirect import ScienceDirectCollector
from radar.collectors.springer import SpringerCollector
from radar.config import load_sources, repo_root
from radar.http import Fetcher


def main() -> None:
    cfg = load_sources(repo_root())
    fetcher = Fetcher(cfg["user_agent"], 40)
    try:
        for source in cfg["sources"]:
            if source["key"] == "nature-psychology":
                continue
            try:
                status, html = fetcher.get_html(source["url"])
            except Exception as exc:
                print(f"{source['key']}: FETCH_ERROR {exc}")
                continue
            lowered = html.lower()
            wall = ""
            if "incapsula" in lowered or "just a moment" in lowered or "cf-browser-verification" in lowered:
                wall = " bot-wall"
            count = 0
            if source["collector"] == "frontiers":
                parsed = parse_frontiers(html, source)
                count = len(parsed.records)
            else:
                collector = {
                    "sciencedirect": ScienceDirectCollector(),
                    "springer": SpringerCollector(),
                    "apa": ApaCollector(),
                    "royal_society": RoyalSocietyCollector(),
                    "plos": PlosCollector(),
                }[source["collector"]]
                result = collector.collect(fetcher, source)
                print(
                    f"{source['key']}: http={status} bytes={len(html)} ok={result.ok} "
                    f"parsed={result.parsed_count} error={result.error}{wall}"
                )
                continue
            print(f"{source['key']}: http={status} bytes={len(html)} parsed={count}{wall}")
    finally:
        fetcher.close()


if __name__ == "__main__":
    main()
