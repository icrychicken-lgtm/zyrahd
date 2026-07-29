"""Dashboard- und Bot-Berechtigungen."""

from __future__ import annotations

from typing import Iterable

import config
from database.manager import get_session
from database.models import DashboardPermission

ALL_PERMISSIONS: list[tuple[str, str]] = [
    ("dashboard.access", "Dashboard öffnen"),
    ("tickets.view", "Tickets ansehen"),
    ("tickets.manage", "Tickets bearbeiten"),
    ("tickets.delete", "Tickets löschen"),
    ("applications.manage", "Bewerbungen bearbeiten"),
    ("moderation.use", "Moderationen ausführen"),
    ("security.manage", "Sicherheitsregeln bearbeiten"),
    ("messages.send", "Nachrichten und Embeds senden"),
    ("server.manage", "Server-Tools bearbeiten"),
    ("team.manage", "Teammitglieder verwalten"),
    ("roles.manage", "Dashboard-Rollen verwalten"),
    ("audit.view", "Audit-Logs ansehen"),
    ("admin.full", "vollständige Administration"),
]

PERMISSION_KEYS = [p[0] for p in ALL_PERMISSIONS]


def is_initial_admin(user_id: int) -> bool:
    return int(user_id) in set(config.INITIAL_ADMIN_DISCORD_IDS)


def permissions_for_roles(role_ids: Iterable[int]) -> set[str]:
    role_ids = [int(r) for r in role_ids]
    perms: set[str] = set()
    with get_session() as session:
        rows = (
            session.query(DashboardPermission)
            .filter(DashboardPermission.role_id.in_(role_ids))
            .all()
            if role_ids
            else []
        )
        for row in rows:
            perms.update(row.get_permissions())
    return perms


def user_permissions(user_id: int, role_ids: Iterable[int]) -> set[str]:
    if is_initial_admin(user_id):
        return set(PERMISSION_KEYS)
    perms = permissions_for_roles(role_ids)
    if "admin.full" in perms:
        return set(PERMISSION_KEYS)
    return perms


def has_permission(user_id: int, role_ids: Iterable[int], permission: str) -> bool:
    perms = user_permissions(user_id, role_ids)
    if "admin.full" in perms:
        return True
    return permission in perms


def has_any(user_id: int, role_ids: Iterable[int], *permissions: str) -> bool:
    perms = user_permissions(user_id, role_ids)
    if "admin.full" in perms:
        return True
    return any(p in perms for p in permissions)
