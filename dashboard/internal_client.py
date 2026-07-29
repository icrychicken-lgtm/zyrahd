"""Authenticated client for the bot's loopback-only API."""

from __future__ import annotations

from typing import Any

import requests

from config import settings


class BotUnavailable(RuntimeError):
    pass


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
            timeout=15,
        )
    except requests.RequestException as exc:
        raise BotUnavailable(
            "Der Discord-Bot ist momentan nicht erreichbar."
        ) from exc
    try:
        data = response.json()
    except ValueError:
        data = {}
    if not response.ok:
        raise BotUnavailable(data.get("error", "Die Bot-Aktion ist fehlgeschlagen."))
    return data
