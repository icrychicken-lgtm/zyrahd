"""Flask application factory for zyrahd.net."""

from __future__ import annotations

import logging

from flask import Flask, jsonify, render_template, request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_wtf.csrf import CSRFError, CSRFProtect, generate_csrf
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix

from config import settings
from dashboard.decorators import current_user, permissions_for
from database.manager import db_session

csrf = CSRFProtect()
limiter = Limiter(key_func=get_remote_address, default_limits=["300 per hour"])


def create_dashboard() -> Flask:
    app = Flask(
        "zyrahd-dashboard",
        template_folder="templates",
        static_folder="static",
    )
    app.config.update(
        SECRET_KEY=settings.flask_secret_key,
        MAX_CONTENT_LENGTH=8 * 1024 * 1024,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=settings.discord_redirect_uri.startswith("https://"),
        PERMANENT_SESSION_LIFETIME=60 * 60 * 12,
        WTF_CSRF_TIME_LIMIT=60 * 60 * 12,
    )
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    csrf.init_app(app)
    limiter.init_app(app)

    from dashboard.routes.api import api
    from dashboard.routes.auth import auth
    from dashboard.routes.main import main

    app.register_blueprint(auth)
    app.register_blueprint(main)
    app.register_blueprint(api, url_prefix="/api")

    @app.context_processor
    def inject_globals() -> dict[str, object]:
        return {
            "current_user": current_user(),
            "current_permissions": permissions_for(),
            "csrf_token": generate_csrf,
        }

    @app.teardown_appcontext
    def remove_session(_exception: BaseException | None = None) -> None:
        db_session.remove()

    @app.after_request
    def secure_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: https://cdn.discordapp.com https://images-ext-1.discordapp.net; "
            "connect-src 'self'; font-src 'self'; frame-ancestors 'none'"
        )
        if request.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.errorhandler(CSRFError)
    def csrf_error(error: CSRFError):
        if request.path.startswith("/api/"):
            return jsonify(error="Sicherheits-Token abgelaufen. Lade die Seite neu."), 400
        return render_template("errors/error.html", code=400, message=error.description), 400

    @app.errorhandler(403)
    def forbidden(_error):
        if request.path.startswith("/api/"):
            return jsonify(error="Dafür fehlt dir die Berechtigung."), 403
        return (
            render_template(
                "errors/error.html",
                code=403,
                message="Du hast keinen Zugriff auf diesen Bereich.",
            ),
            403,
        )

    @app.errorhandler(404)
    def not_found(_error):
        if request.path.startswith("/api/"):
            return jsonify(error="Nicht gefunden."), 404
        return (
            render_template(
                "errors/error.html",
                code=404,
                message="Diese Seite existiert nicht.",
            ),
            404,
        )

    @app.errorhandler(HTTPException)
    def http_error(error: HTTPException):
        if request.path.startswith("/api/"):
            return jsonify(error=error.description), error.code
        return (
            render_template(
                "errors/error.html",
                code=error.code,
                message=error.description,
            ),
            error.code,
        )

    @app.errorhandler(500)
    def server_error(error):
        logging.getLogger("zyrahd.dashboard").exception("Dashboard-Fehler", exc_info=error)
        if request.path.startswith("/api/"):
            return jsonify(error="Unerwarteter Serverfehler."), 500
        return (
            render_template(
                "errors/error.html",
                code=500,
                message="Ein unerwarteter Fehler ist aufgetreten.",
            ),
            500,
        )

    return app
