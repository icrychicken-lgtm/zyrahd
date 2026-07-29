"""Authenticated client for the bot's loopback-only API."""

from __future__ import annotations

from typing import Any

import requests

from config import settings


class BotUnavailable(RuntimeError):
    pass


class BotActionError(ValueError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def bot_request(
    method: str, path: str, payload: dict[str, Any] | None = None
) -> dict[str, Any]:
    if not settings.internal_api_secret:
        raise BotUnavailable("Die interne API ist nicht konfiguriert.")
    url = (
        f"http://{settings.internal_api_host}:{settings.internal_api_port}"
        f"/internal{path}"
    )
    try:
        response = requests.request(
            method,
            url,
            json=payload,
            headers={"X-Internal-Secret": settings.internal_api_secret},
            # Longer than the bridge timeout so the dashboard never reports a
            # failure while the internal API is still waiting on Discord.
            timeout=30,
        )
    except requests.RequestException as exc:
        raise BotUnavailable("Der Discord-Bot ist momentan nicht erreichbar.") from exc
    try:
        data = response.json()
    except ValueError:
        data = {}
    if not response.ok:
        message = data.get("error", "Die Bot-Aktion ist fehlgeschlagen.")
        if 400 <= response.status_code < 500 and response.status_code != 429:
            raise BotActionError(message, response.status_code)
        raise BotUnavailable(message)
    return data
