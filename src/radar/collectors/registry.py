from __future__ import annotations

from radar.collectors.apa import ApaCollector, parse_listing as parse_apa
from radar.collectors.frontiers import FrontiersCollector
from radar.collectors.cambridge import CambridgeCollector, parse_listing as parse_cambridge
from radar.collectors.ieee_ras import IeeeRasCollector, parse_listing as parse_ieee_ras
from radar.collectors.jmir import JmirCollector, parse_listing as parse_jmir
from radar.collectors.nature_humanities import NatureHumanitiesCollector, parse_listing as parse_nature_humanities
from radar.collectors.taylor_francis import TaylorFrancisCollector
from radar.collectors.html_listing import HtmlListingCollector, parse_listing as parse_html_listing
from radar.collectors.nature import NatureCollector
from radar.collectors.plos import PlosCollector
from radar.collectors.royal_society import RoyalSocietyCollector, parse_listing as parse_royal_society
from radar.collectors.sciencedirect import ScienceDirectCollector, parse_listing as parse_sciencedirect
from radar.collectors.springer import SpringerCollector
from radar.http import Fetcher
from radar.models import SourceResult

REGISTRY = {
    "nature": NatureCollector(),
    "nature_humanities": NatureHumanitiesCollector(),
    "cambridge": CambridgeCollector(),
    "ieee_ras": IeeeRasCollector(),
    "jmir": JmirCollector(),
    "taylor_francis": TaylorFrancisCollector(),
    "frontiers": FrontiersCollector(),
    "sciencedirect": ScienceDirectCollector(),
    "springer": SpringerCollector(),
    "apa": ApaCollector(),
    "royal_society": RoyalSocietyCollector(),
    "plos": PlosCollector(),
    "html_listing": HtmlListingCollector(),
}

LISTING_PARSERS = {
    "cambridge": parse_cambridge,
    "ieee_ras": parse_ieee_ras,
    "jmir": parse_jmir,
    "nature_humanities": parse_nature_humanities,
    "apa": parse_apa,
    "sciencedirect": parse_sciencedirect,
    "royal_society": parse_royal_society,
    "html_listing": parse_html_listing,
}


def run_source(fetcher: Fetcher, source: dict) -> SourceResult:
    collector = REGISTRY[source["collector"]]
    return collector.collect(fetcher, source)


def parse_listing_html(source: dict, html: str) -> list:
    parser = LISTING_PARSERS[source["collector"]]
    return parser(html, source)
