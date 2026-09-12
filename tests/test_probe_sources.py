import importlib.util
import json
from pathlib import Path

import pytest

from radar.models import SourceResult


@pytest.fixture
def probe():
    script = Path(__file__).resolve().parents[1] / "scripts/probe_sources.py"
    spec = importlib.util.spec_from_file_location("probe_sources", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_probe_continues_after_error_and_reports_disabled_selected_source(probe, monkeypatch, tmp_path):
    sources = [dict(key=key, collector="jmir", url=f"https://example.org/{key}", enabled=enabled)
               for key, enabled in [("broken", True), ("healthy", True), ("disabled", False)]]
    monkeypatch.setattr(probe, "load_sources", lambda _: {"user_agent": "test", "sources": sources})
    closed = []

    class Fetcher:
        def __init__(self, *args, **kwargs):
            pass

        def close(self):
            closed.append(True)

    monkeypatch.setattr(probe, "Fetcher", Fetcher)
    calls = []

    def run_source(fetcher, source):
        calls.append(source["key"])
        if source["key"] == "broken":
            raise TimeoutError("publisher timed out")
        return SourceResult(source["key"], True, [], parsed_count=2)

    monkeypatch.setattr(probe, "run_source", run_source)
    output = tmp_path / "report.json"
    assert probe.main(["--output", str(output)]) == 1
    assert calls == ["broken", "healthy"]
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["sources"]["healthy"]["ok"] is True
    assert "TimeoutError" in report["sources"]["broken"]["error"]
    assert closed == [True]
    assert probe.main(["--only", "disabled"]) == 0
    assert calls[-1] == "disabled"


def test_unknown_probe_source_fails_before_requests(probe, monkeypatch):
    monkeypatch.setattr(probe, "load_sources", lambda _: {"user_agent": "test", "sources": []})
    monkeypatch.setattr(probe, "Fetcher", lambda *args, **kwargs: pytest.fail("unexpected request"))
    with pytest.raises(SystemExit) as exc:
        probe.main(["--only", "typo"])
    assert exc.value.code == 2
