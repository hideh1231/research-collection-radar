from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from uuid import uuid4


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
