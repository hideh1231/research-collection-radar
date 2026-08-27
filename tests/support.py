from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from uuid import uuid4

CONFIG_FILES = (
    "config/sources.yml",
    "config/domains.yml",
    "config/alerts.yml",
    "config/journals.yml",
    "schema/collection.schema.json",
)


def copy_radar_config(source_root: Path, dest_root: Path) -> None:
    for relative in CONFIG_FILES:
        target = dest_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((source_root / relative).read_bytes())


@contextmanager
def workspace_tempdir(prefix: str) -> Iterator[Path]:
    """Create a writable test directory on the workspace volume on Windows."""
    root = Path.cwd() / f".{prefix}-{uuid4().hex}"
    root.mkdir()
    try:
        yield root
    finally:
        for path in sorted(root.rglob("*"), reverse=True):
            if path.is_file():
                path.unlink()
            else:
                path.rmdir()
        root.rmdir()
