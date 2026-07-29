"""Loopback-oriented API used for explicit bot/dashboard integrations."""

from __future__ import annotations

import secrets
from typing import Any

from flask import Flask, jsonify, request

from bot import runtime
from config import settings


def create_internal_api() -> Flask:
    app = Flask("zyrahd-internal-api")

    @app.before_request
    def protect() -> Any:
        expected = settings.internal_api_secret
        provided = request.headers.get("X-Internal-Secret", "")
        if not expected:
            return jsonify(error="INTERNAL_API_SECRET ist nicht konfiguriert."), 503
        if not secrets.compare_digest(expected, provided):
            return jsonify(error="Nicht autorisiert."), 401
        return None

    @app.errorhandler(runtime.BotUnavailable)
    def unavailable(error: runtime.BotUnavailable):
        return jsonify(error=str(error)), 503

    @app.get("/status")
    def status():
        return {
            "bot_ready": runtime.is_ready(),
            "guild_id": str(settings.guild_id),
        }

    @app.get("/resources")
    def resources():
        return runtime.call("dashboard_snapshot", timeout=10)

    @app.post("/panels/<panel>")
    def panels(panel: str):
        data = request.get_json(silent=True) or {}
        return runtime.call(
            "publish_panel", panel, int(data.get("channel_id", 0)), timeout=15
        )

    @app.post("/embeds")
    def embeds():
        return runtime.call(
            "send_designed_embed", request.get_json(silent=True) or {}, timeout=15
        )

    @app.post("/moderation")
    def moderation():
        data = request.get_json(silent=True) or {}
        return runtime.call("execute_moderation", timeout=15, **data)

    return app
