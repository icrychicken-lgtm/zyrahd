"""Authentication and server-side dashboard authorization."""

from __future__ import annotations

import json
from functools import wraps
from typing import Any, Callable, ParamSpec, TypeVar

from flask import abort, redirect, request, session, url_for
from sqlalchemy import select

from config import settings
from database.manager import session_scope
from database.models import DashboardRole

P = ParamSpec("P")
R = TypeVar("R")

ALL_PERMISSIONS = frozenset(
    {
        "dashboard.open",
        "tickets.view",
        "tickets.manage",
        "tickets.delete",
        "applications.manage",
        "moderation.execute",
        "security.manage",
        "embeds.send",
        "server.manage",
        "team.manage",
        "roles.manage",
        "audit.view",
        "admin",
    }
)


def current_user() -> dict[str, Any] | None:
    return session.get("user")


def permissions_for(user: dict[str, Any] | None = None) -> set[str]:
    user = user or current_user()
    if not user:
        return set()
    try:
        user_id = int(user["id"])
    except (KeyError, TypeError, ValueError):
        return set()
    if user_id in settings.initial_admin_ids:
        return set(ALL_PERMISSIONS)
    discord_permissions = int(user.get("guild_permissions", 0))
    if discord_permissions & 0x8:
        return set(ALL_PERMISSIONS)
    role_ids = {str(item) for item in user.get("roles", [])}
    if not role_ids:
        return set()
    with session_scope() as db:
        mappings = list(
            db.scalars(
                select(DashboardRole).where(
                    DashboardRole.guild_id == str(settings.guild_id),
                    DashboardRole.role_id.in_(role_ids),
                )
            )
        )
    granted: set[str] = set()
    for mapping in mappings:
        try:
            granted.update(json.loads(mapping.permissions))
        except json.JSONDecodeError:
            continue
    if "admin" in granted:
        return set(ALL_PERMISSIONS)
    return granted & ALL_PERMISSIONS


def login_required(view: Callable[P, R]) -> Callable[P, R]:
    @wraps(view)
    def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
        if not current_user():
            return redirect(url_for("auth.login", next=request.full_path))
        return view(*args, **kwargs)

    return wrapped


def permission_required(permission: str) -> Callable[[Callable[P, R]], Callable[P, R]]:
    def decorator(view: Callable[P, R]) -> Callable[P, R]:
        @wraps(view)
        @login_required
        def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
            granted = permissions_for()
            if permission not in granted and "admin" not in granted:
                abort(403)
            return view(*args, **kwargs)

        return wrapped

    return decorator


def can_access_ticket(ticket: Any, *, manage: bool = False) -> bool:
    user = current_user()
    if not user:
        return False
    granted = permissions_for(user)
    if manage:
        return "tickets.manage" in granted or "admin" in granted
    return (
        str(ticket.creator_id) == str(user["id"])
        or "tickets.view" in granted
        or "tickets.manage" in granted
        or "admin" in granted
    )
