from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "config" / "sources.yml").exists():
            return parent
    return Path.cwd()


def load_yaml(path: Path) -> Any:
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_sources(root: Path | None = None) -> dict[str, Any]:
    root = root or repo_root()
    return load_yaml(root / "config" / "sources.yml")


def load_domains(root: Path | None = None) -> dict[str, Any]:
    root = root or repo_root()
    return load_yaml(root / "config" / "domains.yml")


def load_alerts(root: Path | None = None) -> dict[str, Any]:
    root = root or repo_root()
    return load_yaml(root / "config" / "alerts.yml")


def domain_labels(config: dict[str, Any]) -> dict[str, str]:
    return {
        key: str(spec.get("label") or key)
        for key, spec in (config.get("domains") or {}).items()
    }


def collection_type_labels(config: dict[str, Any]) -> dict[str, str]:
    labels = config.get("collection_types") or config.get("type_labels") or {}
    return {str(key): str(value) for key, value in labels.items()}
