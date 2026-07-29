"""Einstellungen: Welcome, Verify, Permissions, Logs, Team-Rollen."""

from __future__ import annotations

import json

from flask import Blueprint, flash, redirect, render_template, request, url_for

from bot.utils.audit import write_audit
from bot.utils.permissions import ALL_PERMISSIONS
from dashboard.api.bot_client import BotAPIError, post
from dashboard.auth import current_user, login_required, permission_required
from database.manager import get_session
from database.models import (
    DashboardPermission,
    GoodbyeConfig,
    LogConfig,
    TeamConfig,
    VerifyConfig,
    WelcomeConfig,
)

bp = Blueprint("settings", __name__)


@bp.route("/")
@login_required
@permission_required("server.manage", "admin.full")
def index():
    return render_template("dashboard/settings/index.html")


@bp.route("/welcome", methods=["GET", "POST"])
@login_required
@permission_required("server.manage", "admin.full")
def welcome():
    with get_session() as session:
        welcome = session.query(WelcomeConfig).first() or WelcomeConfig()
        goodbye = session.query(GoodbyeConfig).first() or GoodbyeConfig()
        if not welcome.id:
            session.add(welcome)
        if not goodbye.id:
            session.add(goodbye)
        session.flush()

        if request.method == "POST":
            section = request.form.get("section")
            if section == "welcome":
                welcome.enabled = request.form.get("enabled") == "on"
                ch = request.form.get("channel_id") or ""
                welcome.channel_id = int(ch) if ch.isdigit() else None
                welcome.use_embed = request.form.get("use_embed") == "on"
                welcome.title = request.form.get("title") or welcome.title
                welcome.description = request.form.get("description") or welcome.description
                welcome.color = request.form.get("color") or welcome.color
                welcome.thumbnail_url = request.form.get("thumbnail_url") or ""
                welcome.image_url = request.form.get("image_url") or ""
                welcome.footer = request.form.get("footer") or ""
                welcome.plain_message = request.form.get("plain_message") or welcome.plain_message
                welcome.dm_enabled = request.form.get("dm_enabled") == "on"
                welcome.dm_message = request.form.get("dm_message") or ""
                roles = request.form.getlist("role_ids")
                welcome.set_roles([int(r) for r in roles if str(r).isdigit()])
                flash("Willkommen gespeichert.", "success")
            else:
                goodbye.enabled = request.form.get("enabled") == "on"
                ch = request.form.get("channel_id") or ""
                goodbye.channel_id = int(ch) if ch.isdigit() else None
                goodbye.use_embed = request.form.get("use_embed") == "on"
                goodbye.title = request.form.get("title") or goodbye.title
                goodbye.description = request.form.get("description") or goodbye.description
                goodbye.color = request.form.get("color") or goodbye.color
                goodbye.image_url = request.form.get("image_url") or ""
                goodbye.plain_message = request.form.get("plain_message") or goodbye.plain_message
                goodbye.show_kick_ban_reason = request.form.get("show_kick_ban_reason") == "on"
                flash("Abschied gespeichert.", "success")
            user = current_user()
            write_audit(
                user_id=int(user["id"]),
                username=user["username"],
                action=f"{section} Einstellungen geändert",
                area="welcome",
                ip_address=request.remote_addr or "",
            )
            return redirect(url_for("settings.welcome"))

    return render_template("dashboard/settings/welcome.html", welcome=welcome, goodbye=goodbye)


@bp.route("/verify", methods=["GET", "POST"])
@login_required
@permission_required("server.manage", "admin.full")
def verify():
    with get_session() as session:
        cfg = session.query(VerifyConfig).first() or VerifyConfig()
        if not cfg.id:
            session.add(cfg)
            session.flush()

        if request.method == "POST":
            cfg.enabled = request.form.get("enabled") == "on"
            ch = request.form.get("channel_id") or ""
            cfg.channel_id = int(ch) if ch.isdigit() else None
            role = request.form.get("verified_role_id") or ""
            cfg.verified_role_id = int(role) if role.isdigit() else None
            remove = request.form.getlist("remove_role_ids")
            cfg.set_remove_roles([int(r) for r in remove if str(r).isdigit()])
            cfg.title = request.form.get("title") or cfg.title
            cfg.description = request.form.get("description") or cfg.description
            cfg.color = request.form.get("color") or cfg.color
            cfg.button_label = request.form.get("button_label") or cfg.button_label
            cfg.button_emoji = request.form.get("button_emoji") or ""
            cfg.captcha_enabled = request.form.get("captcha_enabled") == "on"
            cfg.min_account_age_days = int(request.form.get("min_account_age_days") or 0)
            log_ch = request.form.get("log_channel_id") or ""
            cfg.log_channel_id = int(log_ch) if log_ch.isdigit() else None
            cfg.dm_enabled = request.form.get("dm_enabled") == "on"
            cfg.dm_message = request.form.get("dm_message") or cfg.dm_message

            if request.form.get("publish") == "1" and cfg.channel_id:
                try:
                    result = post(
                        "/panels/verify",
                        {
                            "channel_id": cfg.channel_id,
                            "title": cfg.title,
                            "description": cfg.description,
                            "color": cfg.color,
                            "button_label": cfg.button_label,
                            "message_id": cfg.message_id,
                        },
                    )
                    cfg.message_id = int(result["message_id"])
                    flash("Verify-Panel veröffentlicht.", "success")
                except BotAPIError as exc:
                    flash(str(exc), "error")
            else:
                flash("Verify gespeichert.", "success")

            user = current_user()
            write_audit(
                user_id=int(user["id"]),
                username=user["username"],
                action="Verify-Einstellungen geändert",
                area="verify",
                ip_address=request.remote_addr or "",
            )
            return redirect(url_for("settings.verify"))

    return render_template("dashboard/settings/verify.html", cfg=cfg)


@bp.route("/permissions", methods=["GET", "POST"])
@login_required
@permission_required("roles.manage", "admin.full")
def permissions():
    if request.method == "POST":
        role_id = request.form.get("role_id") or ""
        role_name = request.form.get("role_name") or ""
        perms = request.form.getlist("permissions")
        action = request.form.get("form_action")
        with get_session() as session:
            if action == "delete":
                row = session.query(DashboardPermission).filter(DashboardPermission.role_id == int(role_id)).first()
                if row:
                    session.delete(row)
                    flash("Rollen-Berechtigung entfernt.", "success")
            elif role_id.isdigit():
                row = session.query(DashboardPermission).filter(DashboardPermission.role_id == int(role_id)).first()
                if not row:
                    row = DashboardPermission(role_id=int(role_id))
                    session.add(row)
                row.role_name = role_name
                row.set_permissions(perms)
                flash("Berechtigungen gespeichert.", "success")
        user = current_user()
        write_audit(
            user_id=int(user["id"]),
            username=user["username"],
            action="Dashboard-Berechtigungen geändert",
            area="permissions",
            after={"role_id": role_id, "permissions": perms},
            ip_address=request.remote_addr or "",
        )
        return redirect(url_for("settings.permissions"))

    with get_session() as session:
        rows = session.query(DashboardPermission).order_by(DashboardPermission.role_name).all()
    return render_template(
        "dashboard/settings/permissions.html",
        rows=rows,
        all_permissions=ALL_PERMISSIONS,
    )


@bp.route("/logs", methods=["GET", "POST"])
@login_required
@permission_required("server.manage", "admin.full")
def logs():
    fields = [
        ("message_delete", "Nachrichten gelöscht"),
        ("message_edit", "Nachrichten bearbeitet"),
        ("member_join", "Mitglieder beigetreten"),
        ("member_leave", "Mitglieder verlassen"),
        ("role_update", "Rollen geändert"),
        ("nickname", "Nicknames geändert"),
        ("voice", "Sprachkanal-Aktivität"),
        ("channel", "Kanäle erstellt/gelöscht"),
        ("role_create", "Rollen erstellt/gelöscht"),
        ("bans", "Bans"),
        ("kicks", "Kicks"),
        ("timeouts", "Timeouts"),
        ("automod", "Automod"),
        ("tickets", "Tickets"),
        ("applications", "Bewerbungen"),
        ("dashboard", "Dashboard-Änderungen"),
    ]
    with get_session() as session:
        cfg = session.query(LogConfig).first() or LogConfig()
        if not cfg.id:
            session.add(cfg)
            session.flush()
        if request.method == "POST":
            for key, _ in fields:
                val = request.form.get(key) or ""
                setattr(cfg, key, int(val) if val.isdigit() else None)
            flash("Log-Kanäle gespeichert.", "success")
            user = current_user()
            write_audit(
                user_id=int(user["id"]),
                username=user["username"],
                action="Log-Kanäle geändert",
                area="logs",
                ip_address=request.remote_addr or "",
            )
            return redirect(url_for("settings.logs"))
    return render_template("dashboard/settings/logs.html", cfg=cfg, fields=fields)


@bp.route("/team-roles", methods=["GET", "POST"])
@login_required
@permission_required("team.manage", "admin.full")
def team_roles():
    with get_session() as session:
        cfg = session.query(TeamConfig).first() or TeamConfig()
        if not cfg.id:
            session.add(cfg)
            session.flush()
        if request.method == "POST":
            for field in ("support_role_ids", "mod_role_ids", "lead_role_ids", "admin_role_ids"):
                values = request.form.getlist(field)
                cfg.set_roles(field, [int(v) for v in values if str(v).isdigit()])
            flash("Team-Rollen gespeichert.", "success")
            return redirect(url_for("settings.team_roles"))
    return render_template("dashboard/settings/team_roles.html", cfg=cfg)
