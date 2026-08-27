import httpx

from radar import http as radar_http


class _Client:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def get(self, url):
        self.calls.append(url)
        return next(self.responses)


def test_fetcher_retries_rate_limits_and_honors_retry_after(monkeypatch) -> None:
    responses = [
        httpx.Response(429, headers={"Retry-After": "5"}),
        httpx.Response(429),
        httpx.Response(200, text="ok"),
    ]
    client = _Client(responses)
    sleeps: list[float] = []
    monkeypatch.setattr(radar_http.time, "sleep", sleeps.append)
    fetcher = radar_http.Fetcher("test", 1, min_interval_seconds=0)
    fetcher._client = client

    response = fetcher.get("https://example.org")

    assert response.status_code == 200
    assert len(client.calls) == 3
    assert sleeps == [5.0, 15.0]
