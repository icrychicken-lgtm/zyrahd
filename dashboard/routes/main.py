"""Startseite und Dashboard-Home."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from flask import Blueprint, render_template
from sqlalchemy import func

from dashboard.auth import login_required, permission_required
from dashboard.api.bot_client import bot_status
from database.manager import get_session
from database.models import (
    ActivityLog,
    AuditLog,
    ModCase,
    SecurityEvent,
    Ticket,
    ServerStatusConfig,
)

bp = Blueprint("main", __name__)


@bp.route("/")
def landing():
    return render_template("auth/landing.html")


@bp.route("/dashboard")
@login_required
@permission_required("dashboard.access")
def dashboard():
    status = bot_status()
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    with get_session() as session:
        open_tickets = session.query(Ticket).filter(Ticket.status.in_(["open", "claimed", "waiting"])).count()
        tickets_today = session.query(Ticket).filter(Ticket.created_at >= today_start).count()
        mods_today = session.query(ModCase).filter(ModCase.created_at >= today_start).count()
        security_today = session.query(SecurityEvent).filter(SecurityEvent.created_at >= today_start).count()
        activities = (
            session.query(ActivityLog).order_by(ActivityLog.created_at.desc()).limit(12).all()
        )
        audits = session.query(AuditLog).order_by(AuditLog.created_at.desc()).limit(8).all()
        server_status = session.query(ServerStatusConfig).first()

        # Chart data last 7 days
        chart_labels = []
        chart_tickets = []
        chart_joins = []
        for i in range(6, -1, -1):
            day = (today_start - timedelta(days=i)).date()
            label = day.strftime("%d.%m")
            chart_labels.append(label)
            day_start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
            day_end = day_start + timedelta(days=1)
            chart_tickets.append(
                session.query(Ticket)
                .filter(Ticket.created_at >= day_start, Ticket.created_at < day_end)
                .count()
            )
            chart_joins.append(
                session.query(ActivityLog)
                .filter(
                    ActivityLog.kind == "member",
                    ActivityLog.message.contains("beigetreten"),
                    ActivityLog.created_at >= day_start,
                    ActivityLog.created_at < day_end,
                )
                .count()
            )

        # Avg response: rough estimate from claimed tickets
        claimed = (
            session.query(Ticket)
            .filter(Ticket.claimed_by.isnot(None), Ticket.created_at.isnot(None))
            .order_by(Ticket.id.desc())
            .limit(50)
            .all()
        )
        avg_response = "—"
        if claimed:
            total = 0
            n = 0
            for t in claimed:
                if t.updated_at and t.created_at:
                    total += max(0, (t.updated_at - t.created_at).total_seconds())
                    n += 1
            if n:
                mins = int((total / n) / 60)
                avg_response = f"{mins} Min"

    stats = {
        "members": status.get("member_count") or 0,
        "online": status.get("online_count") or 0,
        "open_tickets": open_tickets,
        "tickets_today": tickets_today,
        "avg_response": avg_response,
        "mods_today": mods_today,
        "security_today": security_today,
        "guild_name": status.get("guild_name") or "Server",
        "guild_icon": status.get("icon_url"),
        "bot_ready": status.get("ready", False),
        "latency": status.get("latency_ms") or 0,
    }

    return render_template(
        "dashboard/home.html",
        stats=stats,
        activities=activities,
        audits=audits,
        server_status=server_status,
        chart_labels=chart_labels,
        chart_tickets=chart_tickets,
        chart_joins=chart_joins,
    )


@bp.route("/audit")
@login_required
@permission_required("audit.view")
def audit():
    with get_session() as session:
        logs = session.query(AuditLog).order_by(AuditLog.created_at.desc()).limit(200).all()
    return render_template("dashboard/audit.html", logs=logs)
