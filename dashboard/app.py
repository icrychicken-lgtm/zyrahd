"""Flask-App Factory für zyrahd.net Dashboard."""

from __future__ import annotations

import logging
from datetime import timedelta

from flask import Flask, render_template
from flask_wtf.csrf import CSRFProtect

import config
from database.manager import init_db

csrf = CSRFProtect()
logger = logging.getLogger("zyrahd.dashboard")


def create_app() -> Flask:
    init_db()
    base = config.BASE_DIR / "dashboard"
    app = Flask(
        __name__,
        template_folder=str(base / "templates"),
        static_folder=str(base / "static"),
    )
    app.config.update(
        SECRET_KEY=config.FLASK_SECRET_KEY,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        PERMANENT_SESSION_LIFETIME=timedelta(days=7),
        WTF_CSRF_TIME_LIMIT=None,
        MAX_CONTENT_LENGTH=16 * 1024 * 1024,
    )
    csrf.init_app(app)

    from dashboard.routes.auth import bp as auth_bp
    from dashboard.routes.main import bp as main_bp
    from dashboard.routes.tickets import bp as tickets_bp
    from dashboard.routes.settings import bp as settings_bp
    from dashboard.routes.moderation import bp as moderation_bp
    from dashboard.routes.security import bp as security_bp
    from dashboard.routes.embeds import bp as embeds_bp
    from dashboard.routes.team import bp as team_bp
    from dashboard.routes.tools import bp as tools_bp
    from dashboard.routes.api_routes import bp as api_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(tickets_bp, url_prefix="/tickets")
    app.register_blueprint(settings_bp, url_prefix="/settings")
    app.register_blueprint(moderation_bp, url_prefix="/moderation")
    app.register_blueprint(security_bp, url_prefix="/security")
    app.register_blueprint(embeds_bp, url_prefix="/embeds")
    app.register_blueprint(team_bp, url_prefix="/team")
    app.register_blueprint(tools_bp, url_prefix="/tools")
    app.register_blueprint(api_bp, url_prefix="/api")

    @app.context_processor
    def inject_globals():
        from dashboard.auth import current_user, current_perms, require_perms
        from dashboard.api.bot_client import bot_status

        user = current_user()
        status = bot_status() if user else {}
        return {
            "current_user": user,
            "user_perms": current_perms() if user else set(),
            "can": require_perms,
            "bot_status": status,
            "brand": "zyrahd.net",
        }

    @app.errorhandler(403)
    def forbidden(e):
        return render_template("errors/403.html"), 403

    @app.errorhandler(404)
    def not_found(e):
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def server_error(e):
        logger.exception("Serverfehler")
        return render_template("errors/500.html"), 500

    return app


def run_dashboard() -> None:
    app = create_app()
    app.run(host=config.FLASK_HOST, port=config.FLASK_PORT, debug=False, use_reloader=False)
