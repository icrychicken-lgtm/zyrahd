"""HTTP-Client für die interne Bot-API."""

from __future__ import annotations

from typing import Any, Optional

import requests

import config


class BotAPIError(Exception):
    def __init__(self, message: str, status: int = 500):
        super().__init__(message)
        self.status = status


def _headers() -> dict[str, str]:
    return {
        "X-Internal-Secret": config.INTERNAL_API_SECRET,
        "Content-Type": "application/json",
    }


def _url(path: str) -> str:
    return f"{config.internal_api_base()}{path}"


def request(method: str, path: str, *, json: Optional[dict] = None, params: Optional[dict] = None, timeout: int = 12) -> Any:
    try:
        resp = requests.request(
            method,
            _url(path),
            headers=_headers(),
            json=json,
            params=params,
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise BotAPIError(f"Bot-API nicht erreichbar: {exc}") from exc

    try:
        data = resp.json()
    except ValueError as exc:
        raise BotAPIError(f"Ungültige API-Antwort ({resp.status_code})") from exc

    if not data.get("ok"):
        raise BotAPIError(data.get("error") or "Unbekannter API-Fehler", status=resp.status_code)
    return data.get("data")


def get(path: str, **kwargs) -> Any:
    return request("GET", path, **kwargs)


def post(path: str, json: Optional[dict] = None, **kwargs) -> Any:
    return request("POST", path, json=json or {}, **kwargs)


def bot_status() -> dict:
    try:
        return get("/bot/status") or {}
    except BotAPIError:
        return {"ready": False}


def list_roles(force: bool = False) -> list[dict]:
    return get("/roles", params={"force": "1" if force else "0"}) or []


def list_channels(channel_type: str = "all", force: bool = False) -> list[dict]:
    return get("/channels", params={"type": channel_type, "force": "1" if force else "0"}) or []
