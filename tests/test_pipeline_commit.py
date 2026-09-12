import subprocess

import pytest

from radar.pipeline import commit_if_actions
from support import workspace_tempdir


@pytest.mark.parametrize("failed_command", ["add", "push", None])
def test_actions_commit_is_scoped_and_reports_persistence_failure(monkeypatch, failed_command):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    calls = []

    def execute(args, **kwargs):
        calls.append(args)
        if args[1] == failed_command:
            assert kwargs["check"] is True
            raise subprocess.CalledProcessError(1, args)
        return subprocess.CompletedProcess(args, 1 if args[1] == "diff" else 0)

    monkeypatch.setattr("radar.pipeline.subprocess.run", execute)
    with workspace_tempdir("pipeline-commit-scope") as root:
        (root / "OPEN.md").write_text("generated", encoding="utf-8")
        (root / "unrelated.txt").write_text("user changes", encoding="utf-8")
        if failed_command:
            with pytest.raises(subprocess.CalledProcessError):
                commit_if_actions(root, "data: update")
        else:
            commit_if_actions(root, "data: update")
        assert calls[0] == ["git", "add", "--", "OPEN.md"]
        if failed_command != "add":
            commit = next(args for args in calls if args[1] == "commit")
            assert commit == ["git", "commit", "--only", "-m", "data: update", "--", "OPEN.md"]
        assert (root / "unrelated.txt").read_text(encoding="utf-8") == "user changes"


def test_actions_skips_commit_when_generated_artifacts_are_unchanged(monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    calls = []
    monkeypatch.setattr("radar.pipeline.subprocess.run", lambda args, **_kwargs: (
        calls.append(args) or subprocess.CompletedProcess(args, 0)
    ))
    with workspace_tempdir("pipeline-commit-unchanged") as root:
        (root / "OPEN.md").write_text("unchanged", encoding="utf-8")
        commit_if_actions(root, "data: update")
    assert [args[1] for args in calls] == ["add", "diff"]
