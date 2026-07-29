"""HTML routes for the landing page and authenticated dashboard shell."""

from __future__ import annotations

from flask import Blueprint, render_template

from bot import runtime
from config import settings
from dashboard.security import current_user, permission_set, require_login


bp = Blueprint("main", __name__)


@bp.get("/")
def index():
    return render_template(
        "index.html",
        user=current_user(),
        oauth_ready=settings.oauth_ready,
    )


@bp.get("/dashboard")
@require_login
def dashboard():
    user = current_user()
    try:
        snapshot = runtime.call("dashboard_snapshot", int(user["id"]), timeout=8)
    except (runtime.BotUnavailable, TimeoutError, ValueError):
        snapshot = {
            "ready": False,
            "guild": {"name": "Discord-Server", "icon": None},
            "member": None,
        }
    return render_template(
        "dashboard.html",
        user=user,
        snapshot=snapshot,
        permissions=sorted(permission_set()),
    )


@bp.get("/health")
def health():
    return {
        "service": "zyrahd.net",
        "dashboard": "online",
        "bot": "online" if runtime.is_ready() else "offline",
    }
