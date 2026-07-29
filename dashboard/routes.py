"""HTML routes for the public landing page and protected dashboard."""

from __future__ import annotations

from flask import Blueprint, redirect, render_template, url_for

from dashboard.permissions import (
    current_user,
    granted_permissions,
    has_permission,
    require_permission,
)

pages_bp = Blueprint("pages", __name__)

SECTIONS = {
    "overview": ("Übersicht", "dashboard.open"),
    "tickets": ("Tickets", "tickets.view"),
    "welcome": ("Willkommen", "server.manage"),
    "verify": ("Verifizierung", "server.manage"),
    "security": ("Sicherheit", "security.manage"),
    "moderation": ("Moderation", "moderation.execute"),
    "designer": ("Embed Designer", "messages.send"),
    "announcements": ("Team-News", "team.manage"),
    "permissions": ("Berechtigungen", "roles.manage"),
    "audit": ("Audit-Log", "audit.view"),
}


@pages_bp.get("/")
def index():
    if current_user():
        return redirect(url_for("pages.dashboard"))
    return render_template("login.html")


@pages_bp.get("/dashboard")
@require_permission("dashboard.open")
def dashboard():
    return render_dashboard("overview")


@pages_bp.get("/dashboard/<section>")
@require_permission("dashboard.open")
def dashboard_section(section: str):
    if section not in SECTIONS:
        return redirect(url_for("pages.dashboard"))
    required_permission = SECTIONS[section][1]
    if not has_permission(required_permission):
        return render_template("errors/403.html"), 403
    return render_dashboard(section)


def render_dashboard(section: str):
    permissions = granted_permissions()
    visible_sections = {
        slug: label
        for slug, (label, permission) in SECTIONS.items()
        if permission in permissions or "admin.all" in permissions
    }
    return render_template(
        "dashboard.html",
        active_section=section,
        sections=visible_sections,
        permissions=permissions,
        user=current_user(),
    )
