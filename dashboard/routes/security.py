"""Sicherheits- und Automod-Einstellungen."""

from __future__ import annotations

import json

from flask import Blueprint, flash, redirect, render_template, request, url_for

from bot.utils.audit import write_audit
from dashboard.auth import current_user, login_required, permission_required
from database.manager import get_session
from database.models import SecurityConfig, SecurityEvent, WordFilter

bp = Blueprint("security", __name__)


@bp.route("/", methods=["GET", "POST"])
@login_required
@permission_required("security.manage")
def index():
    with get_session() as session:
        cfg = session.query(SecurityConfig).first() or SecurityConfig()
        if not cfg.id:
            session.add(cfg)
            session.flush()

        if request.method == "POST":
            bool_fields = [
                "anti_spam", "anti_link", "anti_invite", "anti_mention_spam", "anti_caps",
                "anti_zalgo", "anti_duplicate", "anti_mass_emoji", "anti_raid", "anti_bot_join",
                "raid_lock_channels", "emergency_mode",
            ]
            for f in bool_fields:
                setattr(cfg, f, request.form.get(f) == "on")
            cfg.min_account_age_days = int(request.form.get("min_account_age_days") or 0)
            cfg.join_cooldown_seconds = int(request.form.get("join_cooldown_seconds") or 0)
            cfg.raid_join_threshold = int(request.form.get("raid_join_threshold") or 8)
            cfg.raid_join_window_seconds = int(request.form.get("raid_join_window_seconds") or 10)
            cfg.raid_timeout_seconds = int(request.form.get("raid_timeout_seconds") or 600)
            cfg.spam_messages = int(request.form.get("spam_messages") or 5)
            cfg.spam_seconds = int(request.form.get("spam_seconds") or 5)
            cfg.mention_limit = int(request.form.get("mention_limit") or 5)
            cfg.caps_percent = int(request.form.get("caps_percent") or 70)
            cfg.emoji_limit = int(request.form.get("emoji_limit") or 10)
            log_ch = request.form.get("log_channel_id") or ""
            cfg.log_channel_id = int(log_ch) if log_ch.isdigit() else None
            cfg.exempt_role_ids = json.dumps([int(x) for x in request.form.getlist("exempt_role_ids") if x.isdigit()])
            cfg.exempt_channel_ids = json.dumps([int(x) for x in request.form.getlist("exempt_channel_ids") if x.isdigit()])
            cfg.whitelist_user_ids = json.dumps(
                [int(x.strip()) for x in (request.form.get("whitelist_user_ids") or "").split(",") if x.strip().isdigit()]
            )
            cfg.link_whitelist = json.dumps(
                [x.strip() for x in (request.form.get("link_whitelist") or "").split(",") if x.strip()]
            )
            flash("Sicherheitseinstellungen gespeichert.", "success")
            user = current_user()
            write_audit(
                user_id=int(user["id"]),
                username=user["username"],
                action="Sicherheitseinstellungen geändert",
                area="security",
                ip_address=request.remote_addr or "",
            )
            return redirect(url_for("security.index"))

        events = session.query(SecurityEvent).order_by(SecurityEvent.created_at.desc()).limit(50).all()
    return render_template("dashboard/security/index.html", cfg=cfg, events=events)


@bp.route("/words", methods=["GET", "POST"])
@login_required
@permission_required("security.manage")
def words():
    if request.method == "POST":
        action = request.form.get("form_action")
        with get_session() as session:
            if action == "create":
                wf = WordFilter(
                    pattern=request.form.get("pattern") or "",
                    match_type=request.form.get("match_type") or "contains",
                    case_sensitive=request.form.get("case_sensitive") == "on",
                    delete_message=request.form.get("delete_message") == "on",
                    warn_user=request.form.get("warn_user") == "on",
                    timeout_seconds=int(request.form.get("timeout_seconds") or 0),
                    kick=request.form.get("kick") == "on",
                    ban=request.form.get("ban") == "on",
                    strikes_needed=int(request.form.get("strikes_needed") or 1),
                    response_message=request.form.get("response_message") or "",
                )
                log_ch = request.form.get("log_channel_id") or ""
                wf.log_channel_id = int(log_ch) if log_ch.isdigit() else None
                wf.allowed_channel_ids = json.dumps(
                    [int(x) for x in request.form.getlist("allowed_channel_ids") if x.isdigit()]
                )
                wf.exempt_role_ids = json.dumps(
                    [int(x) for x in request.form.getlist("exempt_role_ids") if x.isdigit()]
                )
                session.add(wf)
                flash("Wortfilter hinzugefügt.", "success")
            elif action == "delete":
                wf = session.get(WordFilter, int(request.form.get("id")))
                if wf:
                    session.delete(wf)
                    flash("Eintrag gelöscht.", "success")
            elif action == "toggle":
                wf = session.get(WordFilter, int(request.form.get("id")))
                if wf:
                    wf.enabled = not wf.enabled
                    flash("Status geändert.", "success")
        user = current_user()
        write_audit(
            user_id=int(user["id"]),
            username=user["username"],
            action=f"Wortfilter: {action}",
            area="security",
            ip_address=request.remote_addr or "",
        )
        return redirect(url_for("security.words"))

    with get_session() as session:
        words = session.query(WordFilter).order_by(WordFilter.id.desc()).all()
    return render_template("dashboard/security/words.html", words=words)


@bp.route("/emergency", methods=["POST"])
@login_required
@permission_required("security.manage", "admin.full")
def emergency():
    enable = request.form.get("enable") == "1"
    with get_session() as session:
        cfg = session.query(SecurityConfig).first()
        if cfg:
            cfg.emergency_mode = enable
    flash("Notfallmodus " + ("aktiviert" if enable else "deaktiviert") + ".", "success" if not enable else "error")
    user = current_user()
    write_audit(
        user_id=int(user["id"]),
        username=user["username"],
        action=f"Notfallmodus {'an' if enable else 'aus'}",
        area="security",
        ip_address=request.remote_addr or "",
    )
    return redirect(url_for("security.index"))
