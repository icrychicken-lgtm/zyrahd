"""Authentication context and server-side dashboard authorization."""

from __future__ import annotations

from functools import wraps
from typing import Any, Callable, TypeVar

from flask import abort, jsonify, request, session
from sqlalchemy import select

from bot import runtime
from config import settings
from database.manager import session_scope
from database.models import DashboardRolePermission


ALL_PERMISSIONS = {
    "dashboard.open",
    "tickets.view",
    "tickets.edit",
    "tickets.delete",
    "applications.edit",
    "moderation.execute",
    "security.edit",
    "messages.send",
    "server.edit",
    "team.manage",
    "roles.manage",
    "audit.view",
    "admin",
}
F = TypeVar("F", bound=Callable[..., Any])


def current_user() -> dict[str, Any] | None:
    value = session.get("user")
    return value if isinstance(value, dict) else None


def discord_context() -> dict[str, Any] | None:
    user = current_user()
    if not user:
        return None
    try:
        return runtime.call("dashboard_snapshot", int(user["id"]), timeout=8)
    except (runtime.BotUnavailable, TimeoutError, ValueError):
        return None


def permission_set() -> set[str]:
    user = current_user()
    if not user:
        return set()
    user_id = int(user["id"])
    if user_id in settings.initial_admin_discord_ids:
        return set(ALL_PERMISSIONS)
    context = discord_context()
    if not context or not context.get("member"):
        return set()
    member = context["member"]
    if (
        member.get("administrator")
        or str(user_id) == str(context.get("guild", {}).get("owner_id"))
    ):
        return set(ALL_PERMISSIONS)
    role_ids = {str(role_id) for role_id in member.get("role_ids", [])}
    with session_scope() as db:
        rows = list(
            db.scalars(
                select(DashboardRolePermission).where(
                    DashboardRolePermission.guild_id == str(settings.guild_id),
                    DashboardRolePermission.role_id.in_(role_ids),
                )
            )
        )
        permissions = {
            permission for row in rows for permission in row.permissions
        }
    if "admin" in permissions:
        return set(ALL_PERMISSIONS)
    return permissions


def has_permission(permission: str) -> bool:
    return permission in permission_set()


def require_login(view: F) -> F:
    @wraps(view)
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        if not current_user():
            if request.path.startswith("/api/"):
                return jsonify(error="Bitte melde dich mit Discord an."), 401
            abort(401)
        return view(*args, **kwargs)

    return wrapped  # type: ignore[return-value]


def require_permission(permission: str) -> Callable[[F], F]:
    def decorator(view: F) -> F:
        @wraps(view)
        @require_login
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            if not has_permission(permission):
                if request.path.startswith("/api/"):
                    return jsonify(error="Dafür fehlt dir die Dashboard-Berechtigung."), 403
                abort(403)
            return view(*args, **kwargs)

        return wrapped  # type: ignore[return-value]

    return decorator
