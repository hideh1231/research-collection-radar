from __future__ import annotations

from radar.collectors.apa import ApaCollector, parse_listing as parse_apa
from radar.collectors.frontiers import FrontiersCollector
from radar.collectors.nature import NatureCollector
from radar.collectors.plos import PlosCollector
from radar.collectors.royal_society import RoyalSocietyCollector, parse_listing as parse_royal_society
from radar.collectors.sciencedirect import ScienceDirectCollector, parse_listing as parse_sciencedirect
from radar.collectors.springer import SpringerCollector
from radar.http import Fetcher
from radar.models import SourceResult

REGISTRY = {
    "nature": NatureCollector(),
    "frontiers": FrontiersCollector(),
    "sciencedirect": ScienceDirectCollector(),
    "springer": SpringerCollector(),
    "apa": ApaCollector(),
    "royal_society": RoyalSocietyCollector(),
    "plos": PlosCollector(),
}

LISTING_PARSERS = {
    "apa": parse_apa,
    "sciencedirect": parse_sciencedirect,
    "royal_society": parse_royal_society,
}


def run_source(fetcher: Fetcher, source: dict) -> SourceResult:
    collector = REGISTRY[source["collector"]]
    return collector.collect(fetcher, source)


def parse_listing_html(source: dict, html: str) -> list:
    parser = LISTING_PARSERS[source["collector"]]
    return parser(html, source)
