"""Ticket-Routen für Dashboard und Kundenbereich."""

from __future__ import annotations

import json

from flask import Blueprint, flash, redirect, render_template, request, url_for
from werkzeug.utils import secure_filename

import config
from bot.utils.audit import write_audit
from dashboard.api.bot_client import BotAPIError, post
from dashboard.auth import current_user, login_required, permission_required, require_perms
from database.manager import get_session
from database.models import Ticket, TicketFormField, TicketMessage, TicketPanel, TicketType

bp = Blueprint("tickets", __name__)


def _user_id() -> int:
    return int(current_user()["id"])


@bp.route("/")
@login_required
@permission_required("tickets.view")
def overview():
    status = request.args.get("status", "")
    type_id = request.args.get("type", "")
    q = request.args.get("q", "").strip()
    with get_session() as session:
        query = session.query(Ticket).order_by(Ticket.created_at.desc())
        if status:
            query = query.filter(Ticket.status == status)
        if type_id.isdigit():
            query = query.filter(Ticket.ticket_type_id == int(type_id))
        if q:
            like = f"%{q}%"
            query = query.filter(
                (Ticket.opener_name.ilike(like))
                | (Ticket.title.ilike(like))
                | (Ticket.reason.ilike(like))
            )
        tickets = query.limit(200).all()
        types = session.query(TicketType).order_by(TicketType.sort_order).all()
        # detach
        for t in tickets:
            _ = t.ticket_type
    return render_template("dashboard/tickets/overview.html", tickets=tickets, types=types)


@bp.route("/mine")
@login_required
@permission_required("dashboard.access")
def mine():
    uid = _user_id()
    with get_session() as session:
        tickets = (
            session.query(Ticket)
            .filter(Ticket.opener_id == uid)
            .order_by(Ticket.created_at.desc())
            .limit(100)
            .all()
        )
        types = session.query(TicketType).filter(TicketType.enabled.is_(True)).order_by(TicketType.sort_order).all()
        for t in tickets:
            _ = t.ticket_type
    return render_template("dashboard/tickets/mine.html", tickets=tickets, types=types)


@bp.route("/create", methods=["GET", "POST"])
@login_required
@permission_required("dashboard.access")
def create():
    with get_session() as session:
        types = (
            session.query(TicketType)
            .filter(TicketType.enabled.is_(True))
            .order_by(TicketType.sort_order)
            .all()
        )
        type_list = [
            {
                "id": t.id,
                "name": t.name,
                "description": t.description,
                "emoji": t.emoji,
                "color": t.color,
                "fields": [
                    {
                        "id": f.id,
                        "label": f.label,
                        "field_type": f.field_type,
                        "placeholder": f.placeholder,
                        "description": f.description,
                        "required": f.required,
                        "min_length": f.min_length,
                        "max_length": f.max_length,
                        "options": f.get_options(),
                    }
                    for f in sorted(t.fields, key=lambda x: x.sort_order)
                ],
            }
            for t in types
        ]

    if request.method == "POST":
        type_id = int(request.form.get("ticket_type_id") or 0)
        form_data = {}
        selected = next((t for t in type_list if t["id"] == type_id), None)
        if not selected:
            flash("Ungültige Ticket-Art.", "error")
            return redirect(url_for("tickets.create"))
        for field in selected["fields"]:
            key = f"field_{field['id']}"
            value = (request.form.get(key) or "").strip()
            if field["required"] and not value:
                flash(f"Feld „{field['label']}“ ist erforderlich.", "error")
                return render_template("dashboard/tickets/create.html", types=type_list, selected_id=type_id)
            if value and field["min_length"] and len(value) < field["min_length"]:
                flash(f"Feld „{field['label']}“ ist zu kurz.", "error")
                return render_template("dashboard/tickets/create.html", types=type_list, selected_id=type_id)
            form_data[field["label"]] = value

        user = current_user()
        try:
            result = post(
                "/tickets/create",
                {
                    "ticket_type_id": type_id,
                    "opener_id": int(user["id"]),
                    "opener_name": user["username"],
                    "form_data": form_data,
                },
            )
            flash(f"Ticket #{result.get('ticket_number')} erstellt!", "success")
            return redirect(url_for("tickets.detail", ticket_id=result["ticket_id"]))
        except BotAPIError as exc:
            flash(str(exc), "error")

    return render_template("dashboard/tickets/create.html", types=type_list, selected_id=None)


@bp.route("/<int:ticket_id>")
@login_required
@permission_required("dashboard.access")
def detail(ticket_id: int):
    uid = _user_id()
    with get_session() as session:
        ticket = session.get(Ticket, ticket_id)
        if not ticket:
            flash("Ticket nicht gefunden.", "error")
            return redirect(url_for("tickets.mine"))
        is_staff = require_perms("tickets.view", "tickets.manage")
        if ticket.opener_id != uid and not is_staff:
            flash("Kein Zugriff auf dieses Ticket.", "error")
            return redirect(url_for("tickets.mine"))
        messages = (
            session.query(TicketMessage)
            .filter(TicketMessage.ticket_id == ticket_id)
            .order_by(TicketMessage.created_at.asc())
            .all()
        )
        types = session.query(TicketType).all()
        _ = ticket.ticket_type
    return render_template(
        "dashboard/tickets/detail.html",
        ticket=ticket,
        messages=messages,
        types=types,
        is_staff=is_staff,
    )


@bp.route("/<int:ticket_id>/message", methods=["POST"])
@login_required
@permission_required("dashboard.access")
def send_message(ticket_id: int):
    uid = _user_id()
    content = (request.form.get("content") or "").strip()
    if not content:
        flash("Nachricht darf nicht leer sein.", "error")
        return redirect(url_for("tickets.detail", ticket_id=ticket_id))

    with get_session() as session:
        ticket = session.get(Ticket, ticket_id)
        if not ticket:
            flash("Ticket nicht gefunden.", "error")
            return redirect(url_for("tickets.mine"))
        is_staff = require_perms("tickets.manage", "tickets.view")
        if ticket.opener_id != uid and not is_staff:
            flash("Keine Berechtigung.", "error")
            return redirect(url_for("tickets.mine"))
        if ticket.status in {"closed", "archived"} and not is_staff:
            flash("Geschlossene Tickets können nicht beschrieben werden.", "error")
            return redirect(url_for("tickets.detail", ticket_id=ticket_id))

    user = current_user()
    try:
        post(
            "/tickets/message",
            {
                "ticket_id": ticket_id,
                "content": content,
                "author_id": uid,
                "author_name": user["username"],
                "author_avatar": user.get("avatar_url") or "",
                "source": "web",
            },
        )
        flash("Nachricht gesendet.", "success")
    except BotAPIError as exc:
        flash(str(exc), "error")
    return redirect(url_for("tickets.detail", ticket_id=ticket_id))


@bp.route("/<int:ticket_id>/action", methods=["POST"])
@login_required
@permission_required("tickets.manage")
def action(ticket_id: int):
    user = current_user()
    action_name = request.form.get("action") or ""
    payload = {
        "ticket_id": ticket_id,
        "action": action_name,
        "actor_id": int(user["id"]),
        "actor_name": user["username"],
        "reason": request.form.get("reason") or "",
        "priority": request.form.get("priority"),
        "ticket_type_id": request.form.get("ticket_type_id"),
        "target_user_id": request.form.get("target_user_id"),
        "note": request.form.get("note") or "",
        "title": request.form.get("title") or "",
        "rating": request.form.get("rating"),
        "rating_comment": request.form.get("rating_comment") or "",
    }
    if action_name == "delete" and not require_perms("tickets.delete"):
        flash("Keine Berechtigung zum Löschen.", "error")
        return redirect(url_for("tickets.detail", ticket_id=ticket_id))
    try:
        result = post("/tickets/action", payload)
        write_audit(
            user_id=int(user["id"]),
            username=user["username"],
            action=f"Ticket-Aktion: {action_name}",
            area="tickets",
            after=payload,
            ip_address=request.remote_addr or "",
        )
        flash(result.get("message") or "Aktion ausgeführt.", "success")
    except BotAPIError as exc:
        flash(str(exc), "error")
    return redirect(url_for("tickets.detail", ticket_id=ticket_id))


@bp.route("/types", methods=["GET", "POST"])
@login_required
@permission_required("tickets.manage", "admin.full")
def types():
    if request.method == "POST":
        action = request.form.get("form_action")
        user = current_user()
        with get_session() as session:
            if action == "create":
                tt = TicketType(
                    name=request.form.get("name") or "Neu",
                    description=request.form.get("description") or "",
                    emoji=request.form.get("emoji") or "🎫",
                    color=request.form.get("color") or "#9B5CFF",
                )
                session.add(tt)
                flash("Ticket-Art erstellt.", "success")
            elif action == "update":
                tt = session.get(TicketType, int(request.form.get("id")))
                if tt:
                    tt.name = request.form.get("name") or tt.name
                    tt.description = request.form.get("description") or ""
                    tt.emoji = request.form.get("emoji") or "🎫"
                    tt.color = request.form.get("color") or "#9B5CFF"
                    cat = request.form.get("category_id") or ""
                    tt.category_id = int(cat) if cat.isdigit() else None
                    roles = request.form.getlist("staff_role_ids")
                    tt.set_staff_roles([int(r) for r in roles if str(r).isdigit()])
                    log_ch = request.form.get("log_channel_id") or ""
                    tt.log_channel_id = int(log_ch) if log_ch.isdigit() else None
                    tr_ch = request.form.get("transcript_channel_id") or ""
                    tt.transcript_channel_id = int(tr_ch) if tr_ch.isdigit() else None
                    tt.max_open_per_user = int(request.form.get("max_open_per_user") or 1)
                    tt.cooldown_seconds = int(request.form.get("cooldown_seconds") or 0)
                    tt.name_format = request.form.get("name_format") or tt.name_format
                    tt.greeting_message = request.form.get("greeting_message") or tt.greeting_message
                    tt.ping_staff = request.form.get("ping_staff") == "on"
                    tt.priority = request.form.get("priority") or "normal"
                    tt.inactivity_close_hours = int(request.form.get("inactivity_close_hours") or 0)
                    tt.enabled = request.form.get("enabled") == "on"
                    hours = {
                        "enabled": request.form.get("hours_enabled") == "on",
                        "start": request.form.get("hours_start") or "09:00",
                        "end": request.form.get("hours_end") or "22:00",
                    }
                    tt.open_hours_json = json.dumps(hours)
                    flash("Ticket-Art gespeichert.", "success")
            elif action == "delete":
                tt = session.get(TicketType, int(request.form.get("id")))
                if tt:
                    session.delete(tt)
                    flash("Ticket-Art gelöscht.", "success")
            elif action == "add_field":
                tt_id = int(request.form.get("ticket_type_id"))
                session.add(
                    TicketFormField(
                        ticket_type_id=tt_id,
                        label=request.form.get("label") or "Feld",
                        field_type=request.form.get("field_type") or "short",
                        placeholder=request.form.get("placeholder") or "",
                        description=request.form.get("description") or "",
                        required=request.form.get("required") == "on",
                        min_length=int(request.form.get("min_length") or 0),
                        max_length=int(request.form.get("max_length") or 1000),
                        options_json=json.dumps(
                            [x.strip() for x in (request.form.get("options") or "").split(",") if x.strip()]
                        ),
                    )
                )
                flash("Feld hinzugefügt.", "success")
            elif action == "delete_field":
                field = session.get(TicketFormField, int(request.form.get("field_id")))
                if field:
                    session.delete(field)
                    flash("Feld gelöscht.", "success")
            write_audit(
                user_id=int(user["id"]),
                username=user["username"],
                action=f"Ticket-Typen: {action}",
                area="tickets",
                ip_address=request.remote_addr or "",
            )
        return redirect(url_for("tickets.types"))

    with get_session() as session:
        types = session.query(TicketType).order_by(TicketType.sort_order, TicketType.id).all()
        for t in types:
            _ = list(t.fields)
    return render_template("dashboard/tickets/types.html", types=types)


@bp.route("/panel", methods=["GET", "POST"])
@login_required
@permission_required("tickets.manage", "messages.send")
def panel():
    with get_session() as session:
        panel = session.query(TicketPanel).first()
        if not panel:
            panel = TicketPanel()
            session.add(panel)
            session.flush()

        if request.method == "POST":
            panel.title = request.form.get("title") or panel.title
            panel.description = request.form.get("description") or panel.description
            panel.color = request.form.get("color") or panel.color
            panel.button_label = request.form.get("button_label") or panel.button_label
            ch = request.form.get("channel_id") or ""
            panel.channel_id = int(ch) if ch.isdigit() else None
            publish = request.form.get("publish") == "1"
            channel_id = panel.channel_id
            message_id = panel.message_id
            payload = {
                "channel_id": channel_id,
                "title": panel.title,
                "description": panel.description,
                "color": panel.color,
                "button_label": panel.button_label,
                "message_id": message_id,
            }
            session.commit()
            if publish and channel_id:
                try:
                    result = post("/panels/ticket", payload)
                    with get_session() as s2:
                        p2 = s2.query(TicketPanel).first()
                        if p2:
                            p2.message_id = int(result["message_id"])
                            p2.channel_id = int(result["channel_id"])
                    flash("Ticket-Panel veröffentlicht.", "success")
                except BotAPIError as exc:
                    flash(str(exc), "error")
            else:
                flash("Panel gespeichert.", "success")
            user = current_user()
            write_audit(
                user_id=int(user["id"]),
                username=user["username"],
                action="Ticket-Panel aktualisiert",
                area="tickets",
                ip_address=request.remote_addr or "",
            )
            return redirect(url_for("tickets.panel"))

        panel_data = panel
    return render_template("dashboard/tickets/panel.html", panel=panel_data)
