"""Central configuration loaded from the documented environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
load_dotenv(BASE_DIR / ".env")


def _integer(name: str, default: int = 0) -> int:
    value = os.getenv(name, str(default)).strip()
    try:
        return int(value)
    except ValueError as exc:
        raise RuntimeError(f"{name} muss eine ganze Zahl sein.") from exc


def _ids(name: str) -> frozenset[int]:
    result: set[int] = set()
    for raw in os.getenv(name, "").replace(";", ",").split(","):
        raw = raw.strip()
        if not raw:
            continue
        try:
            result.add(int(raw))
        except ValueError as exc:
            raise RuntimeError(f"{name} enthält eine ungültige Discord-ID.") from exc
    return frozenset(result)


@dataclass(frozen=True, slots=True)
class Settings:
    discord_bot_token: str
    guild_id: int
    initial_admin_discord_ids: frozenset[int]
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

    @property
    def oauth_ready(self) -> bool:
        return bool(
            self.discord_client_id
            and self.discord_client_secret
            and self.discord_redirect_uri
        )

    @property
    def bot_ready(self) -> bool:
        return bool(self.discord_bot_token and self.guild_id)

    @property
    def cookie_secure(self) -> bool:
        return self.discord_redirect_uri.lower().startswith("https://")


def load_settings() -> Settings:
    default_database = f"sqlite:///{(DATA_DIR / 'bot.db').as_posix()}"
    return Settings(
        discord_bot_token=os.getenv("DISCORD_BOT_TOKEN", "").strip(),
        guild_id=_integer("GUILD_ID"),
        initial_admin_discord_ids=_ids("INITIAL_ADMIN_DISCORD_IDS"),
        discord_client_id=os.getenv("DISCORD_CLIENT_ID", "").strip(),
        discord_client_secret=os.getenv("DISCORD_CLIENT_SECRET", "").strip(),
        discord_redirect_uri=os.getenv("DISCORD_REDIRECT_URI", "").strip(),
        flask_secret_key=os.getenv("FLASK_SECRET_KEY", "").strip(),
        flask_host=os.getenv("FLASK_HOST", "0.0.0.0").strip(),
        flask_port=_integer("FLASK_PORT", 5042),
        internal_api_host=os.getenv("INTERNAL_API_HOST", "127.0.0.1").strip(),
        internal_api_port=_integer("INTERNAL_API_PORT", 5050),
        internal_api_secret=os.getenv("INTERNAL_API_SECRET", "").strip(),
        timezone=os.getenv("TIMEZONE", "Europe/Berlin").strip(),
        database_url=os.getenv("DATABASE_URL", default_database).strip(),
    )


settings = load_settings()
