#!/usr/bin/env python3
"""Startet Discord-Bot und Web-Dashboard gemeinsam."""

from __future__ import annotations

import logging
import signal
import sys
import threading
import time
import traceback

import config
from database.manager import init_db


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def run_dashboard_thread() -> None:
    from dashboard.app import create_app

    app = create_app()
    logging.getLogger("zyrahd").info(
        "Dashboard startet auf http://%s:%s", config.FLASK_HOST, config.FLASK_PORT
    )
    app.run(
        host=config.FLASK_HOST,
        port=config.FLASK_PORT,
        debug=False,
        use_reloader=False,
        threaded=True,
    )


def main() -> int:
    setup_logging()
    log = logging.getLogger("zyrahd")

    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    missing = config.validate_runtime_config(require_bot=True, require_oauth=True)
    if missing:
        log.error("Fehlende .env-Variablen: %s", ", ".join(missing))
        log.error("Kopiere .env.example nach .env und trage deine Werte ein.")
        return 1

    try:
        init_db()
        log.info("Datenbank bereit: %s", config.DATABASE_URL)
    except Exception:
        log.error("Datenbank-Initialisierung fehlgeschlagen:\n%s", traceback.format_exc())
        return 1

    # Dashboard in eigenem Thread
    dash_thread = threading.Thread(target=run_dashboard_thread, name="dashboard", daemon=True)
    dash_thread.start()
    time.sleep(0.5)

    # Bot im Hauptthread (discord.py Event-Loop)
    try:
        from bot.client import run_bot

        log.info("Starte Discord-Bot…")
        run_bot()
    except KeyboardInterrupt:
        log.info("Beende…")
        return 0
    except Exception:
        log.error("Bot-Absturz:\n%s", traceback.format_exc())
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
