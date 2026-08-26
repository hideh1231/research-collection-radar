from __future__ import annotations

import os

import httpx


def credentials() -> tuple[str | None, str | None]:
    token = os.environ.get("SLACK_BOT_TOKEN")
    channel = os.environ.get("SLACK_CHANNEL_ID")
    if token and channel:
        return token, channel
    return None, None


def post_message(text: str, token: str, channel: str) -> bool:
    response = httpx.post(
        "https://slack.com/api/chat.postMessage",
        headers={"Authorization": f"Bearer {token}"},
        json={"channel": channel, "text": text},
        timeout=20,
    )
    if response.status_code >= 400:
        return False
    payload = response.json()
    return bool(payload.get("ok"))
