import httpx
import pytest

from radar.slack import post_message


@pytest.mark.parametrize("outcome", [
    httpx.ConnectTimeout("timed out"),
    httpx.Response(429),
    httpx.Response(200, text="not JSON"),
    httpx.Response(200, json=[]),
    httpx.Response(200, json={"ok": False}),
])
def test_failed_slack_delivery_returns_false(monkeypatch, outcome):
    def post(*_args, **_kwargs):
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr("radar.slack.httpx.post", post)
    assert post_message("test", "fake-token", "fake-channel") is False


def test_successful_slack_delivery(monkeypatch):
    monkeypatch.setattr("radar.slack.httpx.post", lambda *_args, **_kwargs: httpx.Response(200, json={"ok": True}))
    assert post_message("test", "fake-token", "fake-channel") is True
