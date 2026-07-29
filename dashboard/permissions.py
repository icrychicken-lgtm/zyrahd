"""Server-side dashboard authorization."""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import ParamSpec, TypeVar

from flask import abort, jsonify, redirect, request, session, url_for

from config import settings
from database.models import DashboardRole, db

P = ParamSpec("P")
R = TypeVar("R")

PERMISSIONS = {
    "dashboard.open": "Dashboard öffnen",
    "tickets.view": "Tickets ansehen",
    "tickets.manage": "Tickets bearbeiten",
    "tickets.delete": "Tickets löschen",
    "applications.manage": "Bewerbungen bearbeiten",
    "moderation.execute": "Moderationen ausführen",
    "security.manage": "Sicherheitsregeln bearbeiten",
    "messages.send": "Nachrichten und Embeds senden",
    "server.manage": "Server-Tools bearbeiten",
    "team.manage": "Teammitglieder verwalten",
    "roles.manage": "Dashboard-Rollen verwalten",
    "audit.view": "Audit-Logs ansehen",
    "admin.all": "Vollständige Administration",
}


def current_user() -> dict | None:
    return session.get("discord_user")


def granted_permissions() -> set[str]:
    user = current_user()
    if not user:
        return set()
    try:
        user_id = int(user["id"])
    except (KeyError, TypeError, ValueError):
        return set()
    if user_id in settings.initial_admin_ids:
        return set(PERMISSIONS)

    role_ids = [str(role) for role in session.get("discord_roles", [])]
    if not role_ids:
        return set()
    grants = db.session.scalars(
        db.select(DashboardRole).where(
            DashboardRole.guild_id == str(settings.guild_id),
            DashboardRole.role_id.in_(role_ids),
        )
    )
    result: set[str] = set()
    for grant in grants:
        result.update(grant.permissions or [])
    if "admin.all" in result:
        result.update(PERMISSIONS)
    return result


def has_permission(permission: str) -> bool:
    permissions = granted_permissions()
    return permission in permissions or "admin.all" in permissions


def require_permission(
    permission: str,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        @wraps(func)
        def wrapped(*args: P.args, **kwargs: P.kwargs):
            if not current_user():
                if request.path.startswith("/api/"):
                    return jsonify(error="Bitte zuerst mit Discord anmelden."), 401
                return redirect(url_for("auth.login"))
            if not has_permission(permission):
                if request.path.startswith("/api/"):
                    return jsonify(error="Dafür fehlt dir die Berechtigung."), 403
                abort(403)
            return func(*args, **kwargs)

        return wrapped

    return decorator
