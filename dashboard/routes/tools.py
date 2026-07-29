"""Weitere Server-Tools: Status, Stats, TempVoice, Suggestions, Giveaways, Reaction Roles."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from flask import Blueprint, flash, redirect, render_template, request, url_for

from bot.utils.audit import write_audit
from dashboard.api.bot_client import BotAPIError, post
from dashboard.auth import current_user, login_required, permission_required
from database.manager import get_session
from database.models import (
    Giveaway,
    ReactionRolePanel,
    ServerStatChannel,
    ServerStatusConfig,
    Setting,
    Suggestion,
    TempVoiceConfig,
)

bp = Blueprint("tools", __name__)


@bp.route("/")
@login_required
@permission_required("server.manage")
def index():
    return render_template("dashboard/tools/index.html")


@bp.route("/status", methods=["GET", "POST"])
@login_required
@permission_required("server.manage")
def status():
    with get_session() as session:
        cfg = session.query(ServerStatusConfig).first()
        if not cfg:
            cfg = ServerStatusConfig()
            session.add(cfg)
            session.flush()
        if request.method == "POST":
            cfg.enabled = request.form.get("enabled") == "on"
            ch = request.form.get("channel_id") or ""
            cfg.channel_id = int(ch) if ch.isdigit() else None
            cfg.server_name = request.form.get("server_name") or ""
            cfg.server_type = request.form.get("server_type") or "minecraft"
            cfg.endpoint = request.form.get("endpoint") or ""
            cfg.online_message = request.form.get("online_message") or cfg.online_message
            cfg.offline_message = request.form.get("offline_message") or cfg.offline_message
            cfg.interval_seconds = int(request.form.get("interval_seconds") or 60)
            cfg.maintenance = request.form.get("maintenance") == "on"
            flash("Server-Status gespeichert.", "success")
            return redirect(url_for("tools.status"))
    return render_template("dashboard/tools/status.html", cfg=cfg)


@bp.route("/stats", methods=["GET", "POST"])
@login_required
@permission_required("server.manage")
def stats():
    types = [
        ("members", "Mitglieder"),
        ("humans", "Menschen"),
        ("bots", "Bots"),
        ("boosts", "Boosts"),
        ("online", "Online"),
        ("tickets", "Tickets"),
        ("team", "Teammitglieder"),
    ]
    if request.method == "POST":
        with get_session() as session:
            for key, _ in types:
                row = session.query(ServerStatChannel).filter(ServerStatChannel.stat_type == key).first()
                if not row:
                    row = ServerStatChannel(stat_type=key)
                    session.add(row)
                ch = request.form.get(f"channel_{key}") or ""
                row.channel_id = int(ch) if ch.isdigit() else None
                row.name_format = request.form.get(f"format_{key}") or "{name}: {value}"
                row.enabled = request.form.get(f"enabled_{key}") == "on"
            flash("Statistik-Kanäle gespeichert.", "success")
        return redirect(url_for("tools.stats"))

    with get_session() as session:
        rows = {r.stat_type: r for r in session.query(ServerStatChannel).all()}
    return render_template("dashboard/tools/stats.html", types=types, rows=rows)


@bp.route("/tempvoice", methods=["GET", "POST"])
@login_required
@permission_required("server.manage")
def tempvoice():
    with get_session() as session:
        cfg = session.query(TempVoiceConfig).first()
        if not cfg:
            cfg = TempVoiceConfig()
            session.add(cfg)
            session.flush()
        if request.method == "POST":
            cfg.enabled = request.form.get("enabled") == "on"
            ch = request.form.get("create_channel_id") or ""
            cfg.create_channel_id = int(ch) if ch.isdigit() else None
            cat = request.form.get("category_id") or ""
            cfg.category_id = int(cat) if cat.isdigit() else None
            cfg.name_format = request.form.get("name_format") or cfg.name_format
            cfg.user_limit = int(request.form.get("user_limit") or 0)
            flash("Temp-Voice gespeichert.", "success")
            return redirect(url_for("tools.tempvoice"))
    return render_template("dashboard/tools/tempvoice.html", cfg=cfg)


@bp.route("/suggestions", methods=["GET", "POST"])
@login_required
@permission_required("server.manage")
def suggestions():
    if request.method == "POST":
        action = request.form.get("form_action")
        with get_session() as session:
            if action == "channel":
                ch = request.form.get("channel_id") or ""
                setting = session.query(Setting).filter(Setting.key == "suggestions_channel_id").first()
                if not setting:
                    setting = Setting(key="suggestions_channel_id")
                    session.add(setting)
                setting.value = ch
                flash("Vorschlagskanal gespeichert.", "success")
            elif action == "status":
                sug = session.get(Suggestion, int(request.form.get("id")))
                if sug:
                    sug.status = request.form.get("status") or sug.status
                    sug.staff_comment = request.form.get("staff_comment") or ""
                    flash("Vorschlag aktualisiert.", "success")
        return redirect(url_for("tools.suggestions"))

    with get_session() as session:
        setting = session.query(Setting).filter(Setting.key == "suggestions_channel_id").first()
        channel_id = setting.value if setting else ""
        items = session.query(Suggestion).order_by(Suggestion.created_at.desc()).limit(100).all()
    return render_template("dashboard/tools/suggestions.html", items=items, channel_id=channel_id)


@bp.route("/giveaways", methods=["GET", "POST"])
@login_required
@permission_required("server.manage")
def giveaways():
    if request.method == "POST":
        # Erstellung läuft primär über Discord-Command; Dashboard speichert Meta
        prize = request.form.get("prize") or "Preis"
        minutes = int(request.form.get("minutes") or 60)
        winners = int(request.form.get("winners") or 1)
        ch = request.form.get("channel_id") or ""
        user = current_user()
        with get_session() as session:
            g = Giveaway(
                prize=prize,
                channel_id=int(ch) if ch.isdigit() else None,
                winners_count=winners,
                ends_at=datetime.now(timezone.utc) + timedelta(minutes=minutes),
                created_by=int(user["id"]),
                required_role_ids=json.dumps([int(x) for x in request.form.getlist("required_role_ids") if x.isdigit()]),
                forbidden_role_ids=json.dumps([int(x) for x in request.form.getlist("forbidden_role_ids") if x.isdigit()]),
                min_account_age_days=int(request.form.get("min_account_age_days") or 0),
                min_server_days=int(request.form.get("min_server_days") or 0),
            )
            session.add(g)
        flash(
            "Giveaway gespeichert. Zum Veröffentlichen nutze /giveaway im gewünschten Kanal "
            "oder warte auf die nächste Bot-Erweiterung.",
            "info",
        )
        return redirect(url_for("tools.giveaways"))

    with get_session() as session:
        items = session.query(Giveaway).order_by(Giveaway.created_at.desc()).limit(50).all()
    return render_template("dashboard/tools/giveaways.html", items=items)


@bp.route("/reaction-roles", methods=["GET", "POST"])
@login_required
@permission_required("server.manage", "messages.send")
def reaction_roles():
    if request.method == "POST":
        action = request.form.get("form_action")
        with get_session() as session:
            if action == "create":
                roles = []
                role_ids = request.form.getlist("role_id")
                labels = request.form.getlist("role_label")
                emojis = request.form.getlist("role_emoji")
                for rid, label, emoji in zip(role_ids, labels, emojis):
                    if rid.isdigit():
                        roles.append({"role_id": int(rid), "label": label or "Rolle", "emoji": emoji or ""})
                panel = ReactionRolePanel(
                    name=request.form.get("name") or "Rollen-Panel",
                    title=request.form.get("title") or "Rollen wählen",
                    description=request.form.get("description") or "",
                    color=request.form.get("color") or "#9B5CFF",
                    exclusive=request.form.get("exclusive") == "on",
                    roles_json=json.dumps(roles),
                )
                ch = request.form.get("channel_id") or ""
                panel.channel_id = int(ch) if ch.isdigit() else None
                session.add(panel)
                session.flush()

                if panel.channel_id and roles:
                    # Publish via send embed + note: buttons via custom interaction handler
                    try:
                        from dashboard.api import bot_client

                        # Build a simple message; buttons handled by custom_id zyrahd:rr:panel:role
                        # Use internal API send then we need buttons - send plain embed for now
                        # and a follow-up isn't ideal. We'll encode roles in description.
                        lines = [
                            f"{r.get('emoji', '')} {r.get('label')} → <@&{r['role_id']}>" for r in roles
                        ]
                        result = bot_client.post(
                            "/embeds/send",
                            {
                                "channel_id": panel.channel_id,
                                "embed": {
                                    "title": panel.title,
                                    "description": (panel.description + "\n\n" + "\n".join(lines)).strip(),
                                    "color": panel.color,
                                },
                            },
                        )
                        panel.message_id = int(result["message_id"])
                        # Register button view dynamically is hard via HTTP; publish helper:
                        flash(
                            "Panel-Embed gesendet. Für Button-Rollen bitte die Reaction-Role-Erweiterung "
                            "im Bot nutzen (Buttons werden beim nächsten Publish mitgeschickt).",
                            "info",
                        )
                        # Better: call a dedicated publish if we add it - for now store panel
                    except BotAPIError as exc:
                        flash(str(exc), "error")
                else:
                    flash("Reaction-Role-Panel gespeichert.", "success")
            elif action == "delete":
                panel = session.get(ReactionRolePanel, int(request.form.get("id")))
                if panel:
                    session.delete(panel)
                    flash("Panel gelöscht.", "success")
        return redirect(url_for("tools.reaction_roles"))

    with get_session() as session:
        panels = session.query(ReactionRolePanel).order_by(ReactionRolePanel.id.desc()).all()
    return render_template("dashboard/tools/reaction_roles.html", panels=panels)
