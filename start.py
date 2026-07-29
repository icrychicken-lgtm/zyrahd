"""Start the dashboard, protected internal API, and Discord bot together."""

from __future__ import annotations

import logging
import signal
import sys
import threading

from waitress import serve

from bot import create_bot
from config import settings
from dashboard import create_app
from dashboard.internal_api import create_internal_api
from database.manager import init_database
from database.migrations import run_migrations


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logging.getLogger("waitress.queue").setLevel(logging.WARNING)


def serve_dashboard() -> None:
    app = create_app()
    logging.getLogger("zyrahd.start").info(
        "Dashboard bereit auf http://%s:%d", settings.flask_host, settings.flask_port
    )
    serve(
        app,
        host=settings.flask_host,
        port=settings.flask_port,
        threads=8,
        channel_timeout=60,
    )


def serve_internal_api() -> None:
    app = create_internal_api()
    logging.getLogger("zyrahd.start").info(
        "Interne API bereit auf http://%s:%d",
        settings.internal_api_host,
        settings.internal_api_port,
    )
    serve(
        app,
        host=settings.internal_api_host,
        port=settings.internal_api_port,
        threads=4,
        channel_timeout=30,
    )


def main() -> int:
    configure_logging()
    log = logging.getLogger("zyrahd.start")
    run_migrations()
    init_database(settings.guild_id or None)

    dashboard_thread = threading.Thread(
        target=serve_dashboard, name="zyrahd-dashboard", daemon=True
    )
    dashboard_thread.start()

    if settings.internal_api_secret:
        internal_thread = threading.Thread(
            target=serve_internal_api, name="zyrahd-internal-api", daemon=True
        )
        internal_thread.start()
    else:
        log.warning(
            "INTERNAL_API_SECRET fehlt; die interne API wurde nicht gestartet."
        )

    if not settings.bot_ready:
        log.warning(
            "DISCORD_BOT_TOKEN oder GUILD_ID fehlt. Das Dashboard läuft ohne Bot weiter."
        )
        signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
        dashboard_thread.join()
        return 0

    bot = create_bot()
    try:
        bot.run(settings.discord_bot_token, log_handler=None)
    except KeyboardInterrupt:
        log.info("zyrahd.net wird beendet.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
