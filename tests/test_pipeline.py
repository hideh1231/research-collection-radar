from radar.pipeline import run
from radar.config import repo_root


def test_offline_run() -> None:
    assert run(repo_root(), dry_run=True, offline=True) == 0
