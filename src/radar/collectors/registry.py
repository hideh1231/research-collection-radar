from __future__ import annotations

from radar.collectors.apa import ApaCollector
from radar.collectors.frontiers import FrontiersCollector
from radar.collectors.nature import NatureCollector
from radar.collectors.plos import PlosCollector
from radar.collectors.royal_society import RoyalSocietyCollector
from radar.collectors.sciencedirect import ScienceDirectCollector
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


def run_source(fetcher: Fetcher, source: dict) -> SourceResult:
    collector = REGISTRY[source["collector"]]
    return collector.collect(fetcher, source)
