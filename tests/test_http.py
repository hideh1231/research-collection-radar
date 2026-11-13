import httpx

from radar import http as radar_http


class _Client:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def get(self, url, headers=None):
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


def test_fetcher_does_not_retry_forbidden_by_default(monkeypatch) -> None:
    client = _Client([httpx.Response(403)])
    sleeps: list[float] = []
    monkeypatch.setattr(radar_http.time, "sleep", sleeps.append)
    fetcher = radar_http.Fetcher("test", 1, min_interval_seconds=0)
    fetcher._client = client

    response = fetcher.get("https://example.org")

    assert response.status_code == 403
    assert len(client.calls) == 1
    assert sleeps == []


def test_fetcher_retries_forbidden_for_json_requests(monkeypatch) -> None:
    responses = [
        httpx.Response(403, headers={"Retry-After": "5"}),
        httpx.Response(403),
        httpx.Response(200, json=[{"id": 1}]),
    ]
    client = _Client(responses)
    sleeps: list[float] = []
    monkeypatch.setattr(radar_http.time, "sleep", sleeps.append)
    fetcher = radar_http.Fetcher("test", 1, min_interval_seconds=0)
    fetcher._client = client

    status, payload, _headers = fetcher.get_json("https://example.org/api")

    assert status == 200
    assert payload == [{"id": 1}]
    assert len(client.calls) == 3
    assert sleeps == [5.0, 15.0]


def test_fetcher_gives_up_on_forbidden_after_the_retry_budget(monkeypatch) -> None:
    client = _Client([httpx.Response(403), httpx.Response(403), httpx.Response(403)])
    monkeypatch.setattr(radar_http.time, "sleep", lambda _seconds: None)
    fetcher = radar_http.Fetcher("test", 1, min_interval_seconds=0)
    fetcher._client = client

    status, payload, _headers = fetcher.get_json("https://example.org/api")

    assert status == 403
    assert payload is None
    assert len(client.calls) == 3


def test_retry_delay_is_exponential() -> None:
    assert [radar_http.Fetcher.retry_delay(attempt) for attempt in range(4)] == [1.5, 3.0, 6.0, 12.0]
