"""Rendered dashboard pages."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import requests
from flask import Blueprint, abort, redirect, render_template, request, url_for
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from config import settings
from dashboard.decorators import (
    can_access_ticket,
    current_user,
    login_required,
    permission_required,
    permissions_for,
)
from database.manager import session_scope
from database.models import (
    AuditLog,
    DashboardRole,
    ModerationCase,
    TeamAnnouncement,
    Ticket,
    TicketType,
    WordFilter,
)

main = Blueprint("main", __name__)


def _bot_health() -> dict:
    try:
        response = requests.get(
            f"http://{settings.internal_api_host}:{settings.internal_api_port}/health",
            timeout=1.5,
        )
        response.raise_for_status()
        return response.json()
    except requests.RequestException:
        return {"online": False, "guild": None, "latency": None}


@main.get("/")
def index():
    return redirect(
        url_for("main.dashboard") if current_user() else url_for("auth.login")
    )


@main.get("/dashboard")
@permission_required("dashboard.open")
def dashboard():
    guild_id = str(settings.guild_id)
    now = datetime.now(UTC)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    with session_scope() as db:
        open_tickets = (
            db.scalar(
                select(func.count(Ticket.id)).where(
                    Ticket.guild_id == guild_id,
                    Ticket.status.in_(("open", "claimed", "waiting")),
                )
            )
            or 0
        )
        tickets_today = (
            db.scalar(
                select(func.count(Ticket.id)).where(
                    Ticket.guild_id == guild_id, Ticket.created_at >= today
                )
            )
            or 0
        )
        moderation_today = (
            db.scalar(
                select(func.count(ModerationCase.id)).where(
                    ModerationCase.guild_id == guild_id,
                    ModerationCase.created_at >= today,
                )
            )
            or 0
        )
        recent_tickets = list(
            db.scalars(
                select(Ticket)
                .options(selectinload(Ticket.ticket_type))
                .where(Ticket.guild_id == guild_id)
                .order_by(Ticket.created_at.desc())
                .limit(6)
            )
        )
        audit_logs = (
            list(
                db.scalars(
                    select(AuditLog)
                    .where(AuditLog.guild_id == guild_id)
                    .order_by(AuditLog.created_at.desc())
                    .limit(6)
                )
            )
            if "audit.view" in permissions_for()
            else []
        )
        ticket_dates = list(
            db.scalars(
                select(Ticket.created_at).where(
                    Ticket.guild_id == guild_id,
                    Ticket.created_at >= now - timedelta(days=6),
                )
            )
        )
    labels: list[str] = []
    values: list[int] = []
    for days_ago in range(6, -1, -1):
        day = (now - timedelta(days=days_ago)).date()
        labels.append(day.strftime("%d.%m."))
        values.append(sum(1 for created in ticket_dates if created.date() == day))
    return render_template(
        "dashboard.html",
        stats={
            "open_tickets": open_tickets,
            "tickets_today": tickets_today,
            "moderation_today": moderation_today,
        },
        recent_tickets=recent_tickets,
        audit_logs=audit_logs,
        chart_labels=labels,
        chart_values=values,
        bot_health=_bot_health(),
    )


@main.get("/tickets")
@login_required
def tickets():
    user = current_user()
    status = request.args.get("status", "")
    granted = permissions_for(user)
    query = (
        select(Ticket)
        .options(selectinload(Ticket.ticket_type))
        .where(Ticket.guild_id == str(settings.guild_id))
        .order_by(Ticket.updated_at.desc())
    )
    if "tickets.view" not in granted and "tickets.manage" not in granted:
        query = query.where(Ticket.creator_id == str(user["id"]))
    if status in {"open", "claimed", "waiting", "closed", "archived"}:
        query = query.where(Ticket.status == status)
    with session_scope() as db:
        items = list(db.scalars(query.limit(100)))
        ticket_types = list(
            db.scalars(
                select(TicketType)
                .options(selectinload(TicketType.fields))
                .where(
                    TicketType.guild_id == str(settings.guild_id),
                    TicketType.enabled.is_(True),
                )
                .order_by(TicketType.position)
            )
        )
    return render_template(
        "tickets.html",
        tickets=items,
        ticket_types=ticket_types,
        selected_status=status,
    )


@main.get("/tickets/<int:ticket_id>")
@login_required
def ticket_detail(ticket_id: int):
    with session_scope() as db:
        ticket = db.scalar(
            select(Ticket)
            .options(selectinload(Ticket.ticket_type), selectinload(Ticket.messages))
            .where(Ticket.id == ticket_id, Ticket.guild_id == str(settings.guild_id))
        )
    if not ticket:
        abort(404)
    if not can_access_ticket(ticket):
        abort(403)
    try:
        form_data = json.loads(ticket.form_data)
    except json.JSONDecodeError:
        form_data = {}
    return render_template("ticket_detail.html", ticket=ticket, form_data=form_data)


@main.get("/settings")
@permission_required("server.manage")
def settings_page():
    return render_template("settings.html")


@main.get("/ticket-settings")
@permission_required("tickets.manage")
def ticket_settings():
    with session_scope() as db:
        ticket_types = list(
            db.scalars(
                select(TicketType)
                .options(selectinload(TicketType.fields))
                .where(TicketType.guild_id == str(settings.guild_id))
                .order_by(TicketType.position)
            )
        )
    return render_template("ticket_settings.html", ticket_types=ticket_types)


@main.get("/security")
@permission_required("security.manage")
def security():
    with session_scope() as db:
        filters = list(
            db.scalars(
                select(WordFilter)
                .where(WordFilter.guild_id == str(settings.guild_id))
                .order_by(WordFilter.created_at.desc())
            )
        )
    return render_template("security.html", filters=filters)


@main.get("/moderation")
@permission_required("moderation.execute")
def moderation():
    with session_scope() as db:
        cases = list(
            db.scalars(
                select(ModerationCase)
                .where(ModerationCase.guild_id == str(settings.guild_id))
                .order_by(ModerationCase.created_at.desc())
                .limit(100)
            )
        )
    return render_template("moderation.html", cases=cases)


@main.get("/embed-designer")
@permission_required("embeds.send")
def embed_designer():
    return render_template("embed_designer.html")


@main.get("/team")
@permission_required("team.manage")
def team():
    with session_scope() as db:
        announcements = list(
            db.scalars(
                select(TeamAnnouncement)
                .where(TeamAnnouncement.guild_id == str(settings.guild_id))
                .order_by(TeamAnnouncement.created_at.desc())
            )
        )
    return render_template("team.html", announcements=announcements)


@main.get("/dashboard-roles")
@permission_required("roles.manage")
def dashboard_roles():
    with session_scope() as db:
        mappings = list(
            db.scalars(
                select(DashboardRole)
                .where(DashboardRole.guild_id == str(settings.guild_id))
                .order_by(DashboardRole.role_name)
            )
        )
    return render_template("roles.html", mappings=mappings)


@main.get("/audit-log")
@permission_required("audit.view")
def audit_log():
    with session_scope() as db:
        logs = list(
            db.scalars(
                select(AuditLog)
                .where(AuditLog.guild_id == str(settings.guild_id))
                .order_by(AuditLog.created_at.desc())
                .limit(250)
            )
        )
    return render_template("audit.html", logs=logs)
