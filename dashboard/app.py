"""Flask application factory."""

from __future__ import annotations

import logging

from flask import Flask, flash, jsonify, redirect, render_template, request, url_for
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_wtf.csrf import CSRFError, CSRFProtect

from config import Settings, settings
from dashboard.api import api_bp
from dashboard.auth import auth_bp, refresh_member_session
from dashboard.routes import pages_bp
from database.manager import init_database

csrf = CSRFProtect()
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200 per day", "60 per minute"],
    storage_uri="memory://",
)


def create_app(app_settings: Settings = settings) -> Flask:
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config.update(app_settings.flask_config())
    csrf.init_app(app)
    limiter.init_app(app)
    init_database(app, app_settings.guild_id)

    app.register_blueprint(auth_bp)
    app.register_blueprint(pages_bp)
    app.register_blueprint(api_bp)

    @app.before_request
    def refresh_discord_roles():
        if not (
            request.path.startswith("/dashboard") or request.path.startswith("/api/")
        ):
            return None
        if refresh_member_session():
            return None
        if request.path.startswith("/api/"):
            return jsonify(error="Du bist nicht mehr Mitglied des Servers."), 401
        flash("Deine Servermitgliedschaft konnte nicht mehr bestätigt werden.", "error")
        return redirect(url_for("pages.index"))

    @app.get("/health")
    @limiter.exempt
    def health():
        return jsonify(status="ok", service="zyrahd.net")

    @app.after_request
    def security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=()"
        )
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' https: data:; "
            "style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; "
            "frame-ancestors 'none'; base-uri 'self'; form-action 'self' "
            "https://discord.com"
        )
        return response

    @app.errorhandler(CSRFError)
    def csrf_error(error: CSRFError):
        if request.path.startswith("/api/"):
            return jsonify(
                error="Sicherheitsprüfung fehlgeschlagen. Bitte neu laden."
            ), 400
        return render_template("errors/400.html"), 400

    @app.errorhandler(403)
    def forbidden(_error):
        if request.path.startswith("/api/"):
            return jsonify(error="Dafür fehlt dir die Berechtigung."), 403
        return render_template("errors/403.html"), 403

    @app.errorhandler(404)
    def not_found(_error):
        if request.path.startswith("/api/"):
            return jsonify(error="Nicht gefunden."), 404
        return render_template("errors/404.html"), 404

    @app.errorhandler(429)
    def rate_limited(_error):
        return jsonify(error="Zu viele Anfragen. Bitte kurz warten."), 429

    @app.errorhandler(500)
    def server_error(error):
        logging.getLogger(__name__).exception("Dashboard-Fehler", exc_info=error)
        if request.path.startswith("/api/"):
            return jsonify(error="Ein interner Fehler ist aufgetreten."), 500
        return render_template("errors/500.html"), 500

    return app
