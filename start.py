"""Start Discord bot, internal API and dashboard together."""

from __future__ import annotations

import logging
import sys
import threading
from logging.handlers import RotatingFileHandler

from waitress import serve

from bot import ZyrahdBot
from bot.internal_api import create_internal_app
from config import DATA_DIR, settings
from dashboard import create_dashboard
from database import init_database


def configure_logging() -> None:
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    )
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    file_handler = RotatingFileHandler(
        DATA_DIR / "zyrahd.log",
        maxBytes=2_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    logging.basicConfig(level=logging.INFO, handlers=[console, file_handler])
    logging.getLogger("waitress").setLevel(logging.WARNING)
    logging.getLogger("discord.http").setLevel(logging.WARNING)


def serve_app(app, host: str, port: int, name: str) -> None:
    logging.getLogger("zyrahd.start").info(
        "%s gestartet: http://%s:%s", name, host, port
    )
    serve(app, host=host, port=port, threads=8, channel_timeout=60)


def main() -> None:
    configure_logging()
    log = logging.getLogger("zyrahd.start")
    init_database()
    log.info("Datenbank bereit: %s", settings.database_url)
    for warning in settings.validate():
        log.warning(warning)

    bot = ZyrahdBot()
    dashboard = create_dashboard()
    internal_api = create_internal_app(bot)

    if not settings.discord_bot_token:
        log.warning("Dashboard läuft ohne Discord-Verbindung.")
        serve_app(dashboard, settings.flask_host, settings.flask_port, "Dashboard")
        return

    dashboard_thread = threading.Thread(
        target=serve_app,
        args=(dashboard, settings.flask_host, settings.flask_port, "Dashboard"),
        daemon=True,
        name="dashboard",
    )
    internal_thread = threading.Thread(
        target=serve_app,
        args=(
            internal_api,
            settings.internal_api_host,
            settings.internal_api_port,
            "Interne API",
        ),
        daemon=True,
        name="internal-api",
    )
    dashboard_thread.start()
    internal_thread.start()
    try:
        bot.run(settings.discord_bot_token, log_handler=None)
    except KeyboardInterrupt:
        log.info("Zyrahd wurde beendet.")
    except Exception:
        log.exception("Discord-Bot konnte nicht gestartet werden.")
        raise


if __name__ == "__main__":
    main()
