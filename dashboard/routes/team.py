"""Team-Bereich und Ankündigungen."""

from __future__ import annotations

import json
from datetime import datetime

from flask import Blueprint, flash, redirect, render_template, request, url_for

from bot.utils.audit import write_audit
from dashboard.api.bot_client import BotAPIError, post
from dashboard.auth import current_user, login_required, permission_required
from database.manager import get_session
from database.models import TeamAnnouncement, TeamMember, Ticket, ModCase

bp = Blueprint("team", __name__)


@bp.route("/")
@login_required
@permission_required("team.manage", "tickets.view")
def index():
    with get_session() as session:
        members = session.query(TeamMember).order_by(TeamMember.tickets_handled.desc()).all()
        # Auto-stats from tickets/mod
        top_claimers = (
            session.query(Ticket.claimed_by_name, Ticket.claimed_by)
            .filter(Ticket.claimed_by.isnot(None))
            .all()
        )
        counts: dict[int, dict] = {}
        for name, uid in top_claimers:
            if not uid:
                continue
            counts.setdefault(uid, {"name": name, "tickets": 0})
            counts[uid]["tickets"] += 1
        leaderboard = sorted(counts.values(), key=lambda x: x["tickets"], reverse=True)[:10]
        announcements = (
            session.query(TeamAnnouncement).order_by(TeamAnnouncement.created_at.desc()).limit(10).all()
        )
    return render_template(
        "dashboard/team/index.html",
        members=members,
        leaderboard=leaderboard,
        announcements=announcements,
    )


@bp.route("/announcements", methods=["GET", "POST"])
@login_required
@permission_required("team.manage")
def announcements():
    if request.method == "POST":
        user = current_user()
        title = request.form.get("title") or "Ankündigung"
        message = request.form.get("message") or ""
        priority = request.form.get("priority") or "normal"
        roles = [int(x) for x in request.form.getlist("target_role_ids") if x.isdigit()]
        ch = request.form.get("channel_id") or ""
        channel_id = int(ch) if ch.isdigit() else None
        require_ack = request.form.get("require_ack") == "on"
        publish_now = request.form.get("publish_now") == "on"
        publish_at_raw = request.form.get("publish_at") or ""
        publish_at = None
        if publish_at_raw:
            try:
                publish_at = datetime.fromisoformat(publish_at_raw)
            except ValueError:
                publish_at = None

        with get_session() as session:
            ann = TeamAnnouncement(
                title=title,
                message=message,
                priority=priority,
                target_role_ids=json.dumps(roles),
                channel_id=channel_id,
                require_ack=require_ack,
                created_by=int(user["id"]),
                created_by_name=user["username"],
                publish_at=publish_at,
            )
            session.add(ann)
            session.flush()
            aid = ann.id

        if publish_now and channel_id:
            try:
                result = post(
                    "/announcements/publish",
                    {
                        "channel_id": channel_id,
                        "title": title,
                        "message": message,
                        "priority": priority,
                    },
                )
                with get_session() as session:
                    ann = session.get(TeamAnnouncement, aid)
                    if ann:
                        ann.published = True
                        ann.message_id = int(result["message_id"])
                flash("Ankündigung veröffentlicht.", "success")
            except BotAPIError as exc:
                flash(str(exc), "error")
        else:
            flash("Ankündigung gespeichert.", "success")

        write_audit(
            user_id=int(user["id"]),
            username=user["username"],
            action=f"Team-Ankündigung: {title}",
            area="team",
            ip_address=request.remote_addr or "",
        )
        return redirect(url_for("team.announcements"))

    with get_session() as session:
        items = session.query(TeamAnnouncement).order_by(TeamAnnouncement.created_at.desc()).all()
    return render_template("dashboard/team/announcements.html", items=items)


@bp.route("/member", methods=["POST"])
@login_required
@permission_required("team.manage")
def upsert_member():
    with get_session() as session:
        uid = int(request.form.get("user_id") or 0)
        member = session.query(TeamMember).filter(TeamMember.user_id == uid).first()
        if not member:
            member = TeamMember(user_id=uid)
            session.add(member)
        member.username = request.form.get("username") or member.username
        member.display_name = request.form.get("display_name") or member.display_name
        member.status = request.form.get("status") or "active"
        member.notes = request.form.get("notes") or ""
        member.absence_reason = request.form.get("absence_reason") or ""
        flash("Teammitglied gespeichert.", "success")
    return redirect(url_for("team.index"))
