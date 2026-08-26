from __future__ import annotations

import re
from typing import Any

from radar.models import RawRecord


def _tokens(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower())


def classify(raw: RawRecord, domains_cfg: dict[str, Any], source_key: str) -> tuple[list[str], dict[str, float], list[str], str]:
    scores: dict[str, float] = {key: 0.0 for key in domains_cfg.get("domains", {})}
    methods = ["keyword"]
    haystack = _tokens(" ".join(filter(None, [raw.title, raw.summary or "", raw.journal, raw.source_section or ""])))

    for rule in domains_cfg.get("journal_rules", []):
        match = str(rule.get("match", "")).lower()
        when = rule.get("when_source")
        if match and match in raw.journal.lower():
            if when and when != source_key:
                continue
            for domain in rule.get("domains", []):
                scores[domain] = max(scores.get(domain, 0.0), 0.95)
            methods = ["source_rule", "keyword"]

    for domain, spec in domains_cfg.get("domains", {}).items():
        for keyword in spec.get("keywords", []):
            if _tokens(keyword) in haystack:
                scores[domain] = min(1.0, max(scores.get(domain, 0.0), 0.7) + 0.08)

    include = float(domains_cfg.get("threshold", {}).get("include", 0.65))
    selected = sorted(name for name, score in scores.items() if score >= include)
    topics: list[str] = []
    return selected, scores, topics, "+".join(methods)
