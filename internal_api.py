"""Loopback API that safely bridges Flask request threads into Discord's loop."""

from __future__ import annotations

import asyncio
import hmac
from concurrent.futures import TimeoutError as FutureTimeout
from typing import Any, Awaitable

from flask import Flask, jsonify, request

from config import settings


def create_internal_app(bot) -> Flask:
    app = Flask("zyrahd-internal")

    @app.before_request
    def authenticate():
        supplied = request.headers.get("X-Internal-Secret", "")
        if not settings.internal_api_secret or not hmac.compare_digest(
            supplied, settings.internal_api_secret
        ):
            return jsonify(error="Nicht autorisiert."), 401
        return None

    def payload() -> dict[str, Any]:
        value = request.get_json(silent=True)
        if not isinstance(value, dict):
            raise ValueError("Ungültige Anfrage.")
        return value

    def schedule(awaitable: Awaitable[Any]) -> Any:
        if bot.event_loop is None or not bot.event_loop.is_running():
            if asyncio.iscoroutine(awaitable):
                awaitable.close()
            raise RuntimeError("Der Discord-Bot startet noch.")
        future = asyncio.run_coroutine_threadsafe(awaitable, bot.event_loop)
        try:
            return future.result(timeout=25)
        except FutureTimeout as exc:
            future.cancel()
            raise RuntimeError("Discord hat nicht rechtzeitig geantwortet.") from exc

    async def call(function, *args, **kwargs):
        return function(*args, **kwargs)

    @app.get("/internal/status")
    def status():
        return jsonify(schedule(call(bot.service.status)))

    @app.get("/internal/resources")
    def resources():
        return jsonify(schedule(call(bot.service.resources)))

    @app.post("/internal/reload")
    def reload_settings():
        # Services read current settings from the database for every relevant
        # event. This endpoint is retained as an explicit cache invalidation hook.
        return jsonify(reloaded=payload().get("area", "all"))

    @app.post("/internal/tickets")
    def create_ticket():
        data = payload()
        ticket = schedule(
            bot.service.create_ticket(
                int(data["ticket_type_id"]),
                int(data["creator_id"]),
                str(data["creator_name"]),
                data.get("answers", {}),
            )
        )
        return jsonify(ticket=ticket.to_dict(), channel_id=ticket.channel_id), 201

    @app.post("/internal/tickets/<int:ticket_id>/messages")
    def ticket_message(ticket_id: int):
        data = payload()
        result = schedule(
            bot.service.post_web_message(
                ticket_id,
                str(data["author_id"]),
                str(data["author_name"]),
                data.get("author_avatar"),
                str(data["content"]),
            )
        )
        return jsonify(result)

    @app.post("/internal/tickets/<int:ticket_id>/close")
    def close_ticket(ticket_id: int):
        data = payload()
        schedule(
            bot.service.close_ticket(
                ticket_id, int(data["actor_id"]), str(data["reason"])
            )
        )
        return jsonify(closed=True)

    @app.post("/internal/moderation")
    def moderation():
        return jsonify(schedule(bot.service.moderate(payload())))

    @app.post("/internal/embeds")
    def embeds():
        return jsonify(schedule(bot.service.send_embed(payload())))

    @app.post("/internal/ticket-panel/publish")
    def ticket_panel():
        data = payload()
        return jsonify(
            schedule(bot.service.publish_ticket_panel(int(data["channel_id"])))
        )

    @app.post("/internal/verify/publish")
    def verify_panel():
        return jsonify(schedule(bot.service.publish_verify()))

    @app.post("/internal/announcements")
    def announcements():
        return jsonify(schedule(bot.service.publish_announcement(payload())))

    @app.errorhandler(ValueError)
    def bad_request(error: ValueError):
        return jsonify(error=str(error)), 400

    @app.errorhandler(KeyError)
    @app.errorhandler(TypeError)
    def malformed(_error):
        return jsonify(error="Erforderliche Daten fehlen."), 400

    @app.errorhandler(RuntimeError)
    def unavailable(error: RuntimeError):
        return jsonify(error=str(error)), 503

    return app
