"""Start the Discord bot, dashboard and protected internal API together."""

from __future__ import annotations

import logging
import threading

from werkzeug.serving import make_server

from bot import ZyrahdBot
from config import settings
from dashboard import create_app
from internal_api import create_internal_app


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    )
    logging.getLogger("discord.http").setLevel(logging.WARNING)
    logging.getLogger("werkzeug").setLevel(logging.WARNING)


def serve(app, host: str, port: int, name: str) -> None:
    server = make_server(host, port, app, threaded=True)
    logging.getLogger(__name__).info("%s läuft auf %s:%d.", name, host, port)
    server.serve_forever()


def main() -> None:
    configure_logging()
    logger = logging.getLogger(__name__)
    missing = settings.missing_required()
    if missing:
        logger.error(
            "Start abgebrochen. Folgende .env-Werte fehlen: %s",
            ", ".join(missing),
        )
        raise SystemExit(2)
    if settings.internal_api_host not in {"127.0.0.1", "::1", "localhost"}:
        logger.warning(
            "INTERNAL_API_HOST ist nicht auf Loopback gesetzt. "
            "Eine Firewall muss den Port vor externem Zugriff schützen."
        )

    dashboard_app = create_app(settings)
    bot = ZyrahdBot(dashboard_app)
    internal_app = create_internal_app(bot)

    threads = (
        threading.Thread(
            target=serve,
            args=(
                dashboard_app,
                settings.flask_host,
                settings.flask_port,
                "Dashboard",
            ),
            name="dashboard",
            daemon=True,
        ),
        threading.Thread(
            target=serve,
            args=(
                internal_app,
                settings.internal_api_host,
                settings.internal_api_port,
                "Interne API",
            ),
            name="internal-api",
            daemon=True,
        ),
    )
    for thread in threads:
        thread.start()

    logger.info("Discord-Bot wird gestartet …")
    bot.run(settings.discord_bot_token, log_handler=None)


if __name__ == "__main__":
    main()
