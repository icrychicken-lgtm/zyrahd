"""Zentrale Konfiguration aus der .env-Datei."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
UPLOAD_DIR = BASE_DIR / "uploads"
TICKET_UPLOAD_DIR = UPLOAD_DIR / "tickets"

load_dotenv(BASE_DIR / ".env")


def _require(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(
            f"Umgebungsvariable '{name}' fehlt. Bitte .env prüfen "
            f"(Vorlage: .env.example)."
        )
    return value


def _optional(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip() or default


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    return int(str(raw).strip())


# Verzeichnisse sicherstellen
DATA_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
TICKET_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# Discord Bot
DISCORD_BOT_TOKEN = _optional("DISCORD_BOT_TOKEN")
GUILD_ID = _int("GUILD_ID", 0)
INITIAL_ADMIN_DISCORD_IDS = [
    int(x.strip())
    for x in _optional("INITIAL_ADMIN_DISCORD_IDS").split(",")
    if x.strip().isdigit()
]

# Discord OAuth2
DISCORD_CLIENT_ID = _optional("DISCORD_CLIENT_ID")
DISCORD_CLIENT_SECRET = _optional("DISCORD_CLIENT_SECRET")
DISCORD_REDIRECT_URI = _optional(
    "DISCORD_REDIRECT_URI", "http://localhost:5042/auth/callback"
)

# Flask
FLASK_SECRET_KEY = _optional("FLASK_SECRET_KEY", "change-me-in-production")
FLASK_HOST = _optional("FLASK_HOST", "0.0.0.0")
FLASK_PORT = _int("FLASK_PORT", 5042)

# Interne API
INTERNAL_API_HOST = _optional("INTERNAL_API_HOST", "127.0.0.1")
INTERNAL_API_PORT = _int("INTERNAL_API_PORT", 5050)
INTERNAL_API_SECRET = _optional("INTERNAL_API_SECRET", "change-me-internal")

# Sonstiges
TIMEZONE = _optional("TIMEZONE", "Europe/Berlin")
DATABASE_URL = _optional(
    "DATABASE_URL",
    f"sqlite:///{(DATA_DIR / 'bot.db').as_posix()}",
)

# Discord API
DISCORD_API_BASE = "https://discord.com/api/v10"
DISCORD_OAUTH_AUTHORIZE = "https://discord.com/api/oauth2/authorize"
DISCORD_OAUTH_TOKEN = "https://discord.com/api/oauth2/token"
OAUTH_SCOPES = "identify guilds guilds.members.read"


def validate_runtime_config(*, require_bot: bool = True, require_oauth: bool = True) -> list[str]:
    """Prüft kritische Variablen und gibt fehlende Namen zurück."""
    missing: list[str] = []
    if require_bot and not DISCORD_BOT_TOKEN:
        missing.append("DISCORD_BOT_TOKEN")
    if require_bot and not GUILD_ID:
        missing.append("GUILD_ID")
    if require_oauth and not DISCORD_CLIENT_ID:
        missing.append("DISCORD_CLIENT_ID")
    if require_oauth and not DISCORD_CLIENT_SECRET:
        missing.append("DISCORD_CLIENT_SECRET")
    if not INTERNAL_API_SECRET or INTERNAL_API_SECRET == "change-me-internal":
        # Warnung, aber kein Hard-Fail beim ersten Setup
        pass
    return missing


def internal_api_base() -> str:
    return f"http://{INTERNAL_API_HOST}:{INTERNAL_API_PORT}"
