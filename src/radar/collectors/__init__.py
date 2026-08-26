from __future__ import annotations

from typing import Protocol

from radar.http import Fetcher
from radar.models import SourceResult


class Collector(Protocol):
    key: str

    def collect(self, fetcher: Fetcher, source: dict) -> SourceResult: ...
