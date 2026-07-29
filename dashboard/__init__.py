"""Flask application factory for zyrahd.net."""

from __future__ import annotations

import logging
import secrets
from datetime import timedelta

from flask import Flask, jsonify, render_template, request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_session import Session
from flask_wtf.csrf import CSRFError, CSRFProtect
from werkzeug.middleware.proxy_fix import ProxyFix

from config import DATA_DIR, settings
from dashboard.api.routes import bp as api_bp
from dashboard.routes.auth import bp as auth_bp
from dashboard.routes.main import bp as main_bp


log = logging.getLogger("zyrahd.dashboard")
csrf = CSRFProtect()


def create_app(*, testing: bool = False) -> Flask:
    app = Flask(__name__)
    session_dir = DATA_DIR / "sessions"
    session_dir.mkdir(parents=True, exist_ok=True)
    secret = settings.flask_secret_key
    if not secret:
        secret = secrets.token_hex(32)
        if not testing:
            log.warning(
                "FLASK_SECRET_KEY fehlt; Sitzungen gelten nur bis zum nächsten Neustart."
            )
    app.config.update(
        SECRET_KEY=secret,
        TESTING=testing,
        SESSION_TYPE="filesystem",
        SESSION_FILE_DIR=str(session_dir),
        SESSION_PERMANENT=True,
        PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
        SESSION_COOKIE_NAME="zyrahd_session",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SECURE=settings.cookie_secure,
        SESSION_COOKIE_SAMESITE="Lax",
        MAX_CONTENT_LENGTH=8 * 1024 * 1024,
        WTF_CSRF_TIME_LIMIT=timedelta(hours=4),
    )
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    Session(app)
    csrf.init_app(app)
    Limiter(
        key_func=get_remote_address,
        app=app,
        default_limits=["300 per hour", "60 per minute"],
        storage_uri="memory://",
    )
    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(api_bp)

    @app.after_request
    def security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
        )
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' https://cdn.discordapp.com data:; "
            "style-src 'self'; script-src 'self'; connect-src 'self'; "
            "frame-ancestors 'none'; form-action 'self' https://discord.com",
        )
        return response

    @app.errorhandler(CSRFError)
    def csrf_error(error: CSRFError):
        if request.path.startswith("/api/"):
            return jsonify(error="Sicherheits-Token abgelaufen. Lade die Seite neu."), 400
        return render_template(
            "error.html",
            code=400,
            title="Sitzung abgelaufen",
            message="Lade die Seite neu und versuche es noch einmal.",
        ), 400

    @app.errorhandler(400)
    @app.errorhandler(401)
    @app.errorhandler(403)
    @app.errorhandler(404)
    @app.errorhandler(429)
    @app.errorhandler(500)
    def error_page(error):
        code = getattr(error, "code", 500)
        if request.path.startswith("/api/"):
            return jsonify(error=getattr(error, "description", "Interner Fehler")), code
        titles = {
            400: "Ungültige Anfrage",
            401: "Anmeldung erforderlich",
            403: "Zugriff verweigert",
            404: "Seite nicht gefunden",
            429: "Zu viele Anfragen",
            500: "Interner Fehler",
        }
        return render_template(
            "error.html",
            code=code,
            title=titles.get(code, "Fehler"),
            message=getattr(error, "description", "Bitte versuche es später erneut."),
        ), code

    return app
