"""Central application configuration loaded from the existing .env file."""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
load_dotenv(BASE_DIR / ".env")


def _integer(name: str, default: int = 0) -> int:
    value = os.getenv(name, "").strip()
    if not value:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise RuntimeError(f"{name} muss eine gültige Zahl sein.") from exc


def _ids(name: str) -> frozenset[int]:
    values: set[int] = set()
    for raw in os.getenv(name, "").replace(";", ",").split(","):
        raw = raw.strip()
        if raw:
            try:
                values.add(int(raw))
            except ValueError as exc:
                raise RuntimeError(
                    f"{name} enthält eine ungültige Discord-ID."
                ) from exc
    return frozenset(values)


@dataclass(frozen=True, slots=True)
class Settings:
    discord_bot_token: str = os.getenv("DISCORD_BOT_TOKEN", "")
    guild_id: int = _integer("GUILD_ID")
    initial_admin_ids: frozenset[int] = _ids("INITIAL_ADMIN_DISCORD_IDS")

    discord_client_id: str = os.getenv("DISCORD_CLIENT_ID", "")
    discord_client_secret: str = os.getenv("DISCORD_CLIENT_SECRET", "")
    discord_redirect_uri: str = os.getenv("DISCORD_REDIRECT_URI", "")

    flask_secret_key: str = os.getenv("FLASK_SECRET_KEY", "") or secrets.token_hex(32)
    flask_host: str = os.getenv("FLASK_HOST", "0.0.0.0")
    flask_port: int = _integer("FLASK_PORT", 5042)

    internal_api_host: str = os.getenv("INTERNAL_API_HOST", "127.0.0.1")
    internal_api_port: int = _integer("INTERNAL_API_PORT", 5050)
    internal_api_secret: str = os.getenv("INTERNAL_API_SECRET", "")
    timezone: str = os.getenv("TIMEZONE", "Europe/Berlin")

    database_url: str = os.getenv(
        "DATABASE_URL", f"sqlite:///{(DATA_DIR / 'bot.db').as_posix()}"
    )

    @property
    def oauth_ready(self) -> bool:
        return all(
            (
                self.discord_client_id,
                self.discord_client_secret,
                self.discord_redirect_uri,
            )
        )

    def validate(self) -> list[str]:
        warnings: list[str] = []
        if not self.discord_bot_token:
            warnings.append("DISCORD_BOT_TOKEN fehlt; der Bot wird nicht gestartet.")
        if not self.guild_id:
            warnings.append("GUILD_ID fehlt; Guild-Synchronisierung ist deaktiviert.")
        if not self.oauth_ready:
            warnings.append("Discord OAuth2 ist noch nicht vollständig konfiguriert.")
        if not os.getenv("FLASK_SECRET_KEY"):
            warnings.append("FLASK_SECRET_KEY fehlt; Sessions verfallen beim Neustart.")
        if not self.internal_api_secret:
            warnings.append(
                "INTERNAL_API_SECRET fehlt; interne API-Aktionen sind gesperrt."
            )
        return warnings


settings = Settings()
