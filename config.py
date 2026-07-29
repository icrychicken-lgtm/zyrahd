"""Central, environment-only application configuration."""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
load_dotenv(BASE_DIR / ".env")


def _int(name: str, default: int = 0) -> int:
    value = os.getenv(name, str(default)).strip()
    try:
        return int(value)
    except ValueError as exc:
        raise RuntimeError(f"{name} muss eine ganze Zahl sein.") from exc


def _id_set(name: str) -> frozenset[int]:
    result: set[int] = set()
    for value in os.getenv(name, "").replace(";", ",").split(","):
        value = value.strip()
        if not value:
            continue
        try:
            result.add(int(value))
        except ValueError as exc:
            raise RuntimeError(f"{name} enthält eine ungültige Discord-ID.") from exc
    return frozenset(result)


@dataclass(frozen=True, slots=True)
class Settings:
    discord_bot_token: str
    guild_id: int
    initial_admin_ids: frozenset[int]
    discord_client_id: str
    discord_client_secret: str
    discord_redirect_uri: str
    flask_secret_key: str
    flask_host: str
    flask_port: int
    internal_api_host: str
    internal_api_port: int
    internal_api_secret: str
    timezone: str
    database_url: str

    @classmethod
    def from_env(cls) -> "Settings":
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        default_database = f"sqlite:///{(DATA_DIR / 'bot.db').as_posix()}"
        return cls(
            discord_bot_token=os.getenv("DISCORD_BOT_TOKEN", "").strip(),
            guild_id=_int("GUILD_ID"),
            initial_admin_ids=_id_set("INITIAL_ADMIN_DISCORD_IDS"),
            discord_client_id=os.getenv("DISCORD_CLIENT_ID", "").strip(),
            discord_client_secret=os.getenv("DISCORD_CLIENT_SECRET", "").strip(),
            discord_redirect_uri=os.getenv("DISCORD_REDIRECT_URI", "").strip(),
            flask_secret_key=os.getenv("FLASK_SECRET_KEY", "").strip(),
            flask_host=os.getenv("FLASK_HOST", "0.0.0.0").strip(),
            flask_port=_int("FLASK_PORT", 5042),
            internal_api_host=os.getenv("INTERNAL_API_HOST", "127.0.0.1").strip(),
            internal_api_port=_int("INTERNAL_API_PORT", 5050),
            internal_api_secret=os.getenv("INTERNAL_API_SECRET", "").strip(),
            timezone=os.getenv("TIMEZONE", "Europe/Berlin").strip(),
            database_url=os.getenv("DATABASE_URL", default_database).strip(),
        )

    def missing_required(self) -> list[str]:
        values = {
            "DISCORD_BOT_TOKEN": self.discord_bot_token,
            "GUILD_ID": self.guild_id,
            "DISCORD_CLIENT_ID": self.discord_client_id,
            "DISCORD_CLIENT_SECRET": self.discord_client_secret,
            "DISCORD_REDIRECT_URI": self.discord_redirect_uri,
            "FLASK_SECRET_KEY": self.flask_secret_key,
            "INTERNAL_API_SECRET": self.internal_api_secret,
        }
        return [name for name, value in values.items() if not value]

    def flask_config(self) -> dict[str, object]:
        # A random fallback keeps local diagnostics usable, but startup reports
        # the missing persistent key and production operators must configure it.
        secret = self.flask_secret_key or secrets.token_hex(32)
        return {
            "SECRET_KEY": secret,
            "SQLALCHEMY_DATABASE_URI": self.database_url,
            "SQLALCHEMY_TRACK_MODIFICATIONS": False,
            "SESSION_COOKIE_HTTPONLY": True,
            "SESSION_COOKIE_SAMESITE": "Lax",
            "SESSION_COOKIE_SECURE": self.discord_redirect_uri.startswith("https://"),
            "PERMANENT_SESSION_LIFETIME": 60 * 60 * 12,
            "MAX_CONTENT_LENGTH": 8 * 1024 * 1024,
        }


settings = Settings.from_env()
