"""JSON API for every functional dashboard area."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from flask import Blueprint, jsonify, request
from sqlalchemy import func, select

from bot import runtime
from config import settings
from dashboard.security import (
    ALL_PERMISSIONS,
    current_user,
    has_permission,
    require_login,
    require_permission,
)
from database.manager import get_setting, session_scope, set_setting, write_audit
from database.models import (
    AuditLog,
    DashboardRolePermission,
    JsonMixin,
    ModerationCase,
    TeamAnnouncement,
    Ticket,
    TicketMessage,
    TicketType,
    WordFilter,
)


bp = Blueprint("api", __name__, url_prefix="/api")
EDITABLE_MODULES = {
    "welcome": "server.edit",
    "farewell": "server.edit",
    "verify": "server.edit",
    "security": "security.edit",
    "ticket_panel": "tickets.edit",
}


def _user() -> dict[str, Any]:
    return current_user() or {}


def _body() -> dict[str, Any]:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValueError("Es wurde kein gültiges JSON-Objekt gesendet.")
    return data


def _int(value: Any, label: str, minimum: int = 0, maximum: int = 2**31) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} ist ungültig.") from exc
    if not minimum <= result <= maximum:
        raise ValueError(f"{label} liegt außerhalb des erlaubten Bereichs.")
    return result


def _snapshot() -> dict[str, Any]:
    return runtime.call("dashboard_snapshot", int(_user()["id"]), timeout=10)


def _resource_maps() -> tuple[dict[str, Any], dict[str, Any]]:
    snapshot = _snapshot()
    return (
        {item["id"]: item for item in snapshot["roles"]},
        {item["id"]: item for item in snapshot["channels"]},
    )


def _valid_role(role_id: Any, roles: dict[str, Any]) -> str:
    value = str(role_id or "")
    role = roles.get(value)
    if not role or not role.get("usable"):
        raise ValueError("Eine ausgewählte Rolle ist nicht mehr verwendbar.")
    return value


def _valid_channel(
    channel_id: Any, channels: dict[str, Any], types: set[str]
) -> str:
    value = str(channel_id or "")
    channel = channels.get(value)
    if not channel or channel.get("type") not in types:
        raise ValueError("Ein ausgewählter Kanal hat nicht den benötigten Typ.")
    return value


def _audit(
    action: str,
    area: str,
    *,
    target: str | None = None,
    before: Any = None,
    after: Any = None,
) -> None:
    user = _user()
    write_audit(
        str(settings.guild_id),
        str(user["id"]),
        str(user["username"]),
        action,
        area,
        target=target,
        before=before,
        after=after,
        ip_address=request.headers.get("X-Forwarded-For", request.remote_addr or "")
        .split(",")[0]
        .strip(),
    )


def _ticket_dict(item: Ticket, include_form: bool = False) -> dict[str, Any]:
    result = {
        "id": item.id,
        "type_id": item.ticket_type_id,
        "type": item.ticket_type.name if item.ticket_type else "Ticket",
        "creator_id": item.creator_id,
        "creator_name": item.creator_name,
        "channel_id": item.discord_channel_id,
        "status": item.status,
        "priority": item.priority,
        "assigned_to_id": item.assigned_to_id,
        "assigned_to_name": item.assigned_to_name,
        "subject": item.subject,
        "rating": item.rating,
        "created_at": item.created_at.isoformat(),
        "updated_at": item.updated_at.isoformat(),
    }
    if include_form:
        result["form_data"] = item.form_data
        result["closed_reason"] = item.closed_reason
    return result


@bp.errorhandler(ValueError)
def handle_value_error(error: ValueError):
    return jsonify(error=str(error)), 400


@bp.errorhandler(runtime.BotUnavailable)
def handle_bot_unavailable(error: runtime.BotUnavailable):
    return jsonify(error=str(error)), 503


@bp.get("/me")
@require_login
def me():
    try:
        snapshot = _snapshot()
    except (runtime.BotUnavailable, TimeoutError, ValueError):
        snapshot = None
    return {"user": _user(), "server": snapshot}


@bp.get("/overview")
@require_login
def overview():
    guild_id = str(settings.guild_id)
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    is_team = has_permission("tickets.view")
    with session_scope() as db:
        ticket_filter = [Ticket.guild_id == guild_id]
        if not is_team:
            ticket_filter.append(Ticket.creator_id == str(_user()["id"]))
        open_tickets = db.scalar(
            select(func.count(Ticket.id)).where(
                *ticket_filter, Ticket.status.in_(("open", "claimed", "waiting"))
            )
        )
        today_tickets = db.scalar(
            select(func.count(Ticket.id)).where(
                *ticket_filter, Ticket.created_at >= today
            )
        )
        sanctions = (
            db.scalar(
                select(func.count(ModerationCase.id)).where(
                    ModerationCase.guild_id == guild_id,
                    ModerationCase.created_at >= today,
                )
            )
            if is_team
            else 0
        )
        recent = list(
            db.scalars(
                select(AuditLog)
                .where(AuditLog.guild_id == guild_id)
                .order_by(AuditLog.created_at.desc())
                .limit(8)
            )
        )
        chart = []
        for offset in range(6, -1, -1):
            start = today - timedelta(days=offset)
            end = start + timedelta(days=1)
            count = db.scalar(
                select(func.count(Ticket.id)).where(
                    *ticket_filter,
                    Ticket.created_at >= start,
                    Ticket.created_at < end,
                )
            )
            chart.append({"date": start.strftime("%d.%m."), "tickets": int(count or 0)})
    try:
        snapshot = _snapshot()
    except (runtime.BotUnavailable, TimeoutError, ValueError):
        snapshot = {"ready": False, "guild": {}}
    return {
        "stats": {
            "members": snapshot.get("guild", {}).get("member_count", 0),
            "online": snapshot.get("guild", {}).get("online_count", 0),
            "open_tickets": int(open_tickets or 0),
            "today_tickets": int(today_tickets or 0),
            "sanctions_today": int(sanctions or 0),
            "bot_latency": snapshot.get("latency_ms"),
        },
        "chart": chart,
        "activity": [
            {
                "id": row.id,
                "user": row.user_name,
                "action": row.action,
                "area": row.area,
                "created_at": row.created_at.isoformat(),
            }
            for row in recent
        ],
        "bot_ready": snapshot.get("ready", False),
    }


@bp.get("/discord/resources")
@require_permission("dashboard.open")
def discord_resources():
    snapshot = _snapshot()
    return {
        "guild": snapshot["guild"],
        "roles": snapshot["roles"],
        "channels": snapshot["channels"],
    }


@bp.route("/settings/<module>", methods=["GET", "PUT"])
@require_login
def module_settings(module: str):
    permission = EDITABLE_MODULES.get(module)
    if not permission:
        return jsonify(error="Unbekannter Einstellungsbereich."), 404
    if not has_permission(permission):
        return jsonify(error="Dafür fehlt dir die Dashboard-Berechtigung."), 403
    guild_id = str(settings.guild_id)
    if request.method == "GET":
        return {"module": module, "settings": get_setting(guild_id, module, {})}
    data = _body()
    roles, channels = _resource_maps()
    if module in {"welcome", "farewell"} and data.get("channel_id"):
        data["channel_id"] = _valid_channel(
            data["channel_id"], channels, {"text", "announcement"}
        )
    if module == "welcome":
        data["role_ids"] = [
            _valid_role(item, roles) for item in data.get("role_ids", [])
        ][:20]
    if module == "verify":
        if data.get("role_id"):
            data["role_id"] = _valid_role(data["role_id"], roles)
        data["remove_role_ids"] = [
            _valid_role(item, roles) for item in data.get("remove_role_ids", [])
        ][:20]
    if module == "security":
        data["ignored_channels"] = [
            _valid_channel(
                item,
                channels,
                {"text", "announcement", "forum", "voice", "category"},
            )
            for item in data.get("ignored_channels", [])
        ][:50]
        data["ignored_roles"] = [
            _valid_role(item, roles) for item in data.get("ignored_roles", [])
        ][:50]
        data["spam_message_limit"] = _int(
            data.get("spam_message_limit", 6), "Nachrichtenlimit", 3, 20
        )
        data["spam_window_seconds"] = _int(
            data.get("spam_window_seconds", 6), "Zeitfenster", 2, 60
        )
        data["spam_timeout_minutes"] = _int(
            data.get("spam_timeout_minutes", 5), "Timeout", 1, 40320
        )
    before = get_setting(guild_id, module, {})
    set_setting(guild_id, module, data, str(_user()["id"]))
    _audit("Einstellungen geändert", module, before=before, after=data)
    return {"ok": True, "settings": data}


@bp.get("/ticket-types")
@require_login
def ticket_types():
    with session_scope() as db:
        rows = list(
            db.scalars(
                select(TicketType)
                .where(TicketType.guild_id == str(settings.guild_id))
                .order_by(TicketType.id)
            )
        )
        return {
            "items": [
                {
                    "id": row.id,
                    "name": row.name,
                    "description": row.description,
                    "emoji": row.emoji,
                    "color": row.color,
                    "enabled": row.enabled,
                    "category_id": row.category_id,
                    "support_role_ids": row.support_role_ids,
                    "log_channel_id": row.log_channel_id,
                    "transcript_channel_id": row.transcript_channel_id,
                    "max_open": row.max_open,
                    "cooldown_minutes": row.cooldown_minutes,
                    "channel_format": row.channel_format,
                    "welcome_message": row.welcome_message,
                    "ping_roles": row.ping_roles,
                    "priority": row.priority,
                    "auto_close_hours": row.auto_close_hours,
                    "form_fields": row.form_fields,
                }
                for row in rows
                if row.enabled or has_permission("tickets.edit")
            ]
        }


def _apply_ticket_type(row: TicketType, data: dict[str, Any]) -> None:
    roles, channels = _resource_maps()
    name = str(data.get("name", "")).strip()
    if not 2 <= len(name) <= 80:
        raise ValueError("Der Name muss zwischen 2 und 80 Zeichen lang sein.")
    color = str(data.get("color", "#7c5cff"))
    if len(color) != 7 or not color.startswith("#"):
        raise ValueError("Die Embed-Farbe ist ungültig.")
    try:
        int(color[1:], 16)
    except ValueError as exc:
        raise ValueError("Die Embed-Farbe ist ungültig.") from exc
    row.name = name
    row.description = str(data.get("description", "")).strip()[:300]
    row.emoji = str(data.get("emoji", "🎫")).strip()[:40] or "🎫"
    row.color = color
    row.enabled = bool(data.get("enabled", True))
    row.category_id = (
        _valid_channel(data["category_id"], channels, {"category"})
        if data.get("category_id")
        else None
    )
    row.support_role_ids = [
        _valid_role(item, roles) for item in data.get("support_role_ids", [])
    ][:20]
    row.log_channel_id = (
        _valid_channel(data["log_channel_id"], channels, {"text", "announcement"})
        if data.get("log_channel_id")
        else None
    )
    row.transcript_channel_id = (
        _valid_channel(
            data["transcript_channel_id"], channels, {"text", "announcement"}
        )
        if data.get("transcript_channel_id")
        else None
    )
    row.max_open = _int(data.get("max_open", 1), "Maximale Tickets", 1, 20)
    row.cooldown_minutes = _int(
        data.get("cooldown_minutes", 5), "Cooldown", 0, 10080
    )
    row.channel_format = str(
        data.get("channel_format", "ticket-{number}-{user}")
    )[:80]
    row.welcome_message = str(data.get("welcome_message", ""))[:2000]
    row.ping_roles = bool(data.get("ping_roles", True))
    priority = str(data.get("priority", "normal"))
    row.priority = priority if priority in {"low", "normal", "high", "urgent"} else "normal"
    row.auto_close_hours = _int(
        data.get("auto_close_hours", 72), "Schließzeit", 0, 8760
    )
    fields = data.get("form_fields", [])
    if not isinstance(fields, list) or len(fields) > 20:
        raise ValueError("Ein Formular darf höchstens 20 Felder enthalten.")
    clean_fields = []
    seen: set[str] = set()
    for index, field in enumerate(fields):
        if not isinstance(field, dict):
            raise ValueError("Ein Formularfeld ist ungültig.")
        field_id = str(field.get("id", f"field_{index}")).strip()[:40]
        label = str(field.get("label", "")).strip()[:80]
        if not field_id or field_id in seen or not label:
            raise ValueError("Formularfelder brauchen eindeutige IDs und Bezeichnungen.")
        seen.add(field_id)
        clean_fields.append(
            {
                "id": field_id,
                "label": label,
                "type": "long" if field.get("type") == "long" else "short",
                "required": bool(field.get("required")),
                "placeholder": str(field.get("placeholder", ""))[:100],
                "min_length": _int(
                    field.get("min_length", 0), "Mindestlänge", 0, 4000
                ),
                "max_length": _int(
                    field.get("max_length", 1000), "Maximallänge", 1, 4000
                ),
            }
        )
    row.form_fields = clean_fields


@bp.post("/ticket-types")
@require_permission("tickets.edit")
def create_ticket_type():
    data = _body()
    row = TicketType(guild_id=str(settings.guild_id))
    _apply_ticket_type(row, data)
    with session_scope() as db:
        db.add(row)
        db.flush()
        row_id = row.id
    _audit("Ticket-Art erstellt", "tickets", target=row.name, after=data)
    return {"ok": True, "id": row_id}, 201


@bp.put("/ticket-types/<int:type_id>")
@require_permission("tickets.edit")
def update_ticket_type(type_id: int):
    data = _body()
    with session_scope() as db:
        row = db.get(TicketType, type_id)
        if not row or row.guild_id != str(settings.guild_id):
            return jsonify(error="Ticket-Art nicht gefunden."), 404
        before = {
            "name": row.name,
            "enabled": row.enabled,
            "support_role_ids": row.support_role_ids,
        }
        _apply_ticket_type(row, data)
        name = row.name
    _audit("Ticket-Art geändert", "tickets", target=name, before=before, after=data)
    return {"ok": True}


@bp.delete("/ticket-types/<int:type_id>")
@require_permission("tickets.delete")
def delete_ticket_type(type_id: int):
    with session_scope() as db:
        row = db.get(TicketType, type_id)
        if not row or row.guild_id != str(settings.guild_id):
            return jsonify(error="Ticket-Art nicht gefunden."), 404
        in_use = db.scalar(select(func.count(Ticket.id)).where(Ticket.ticket_type_id == type_id))
        name = row.name
        if in_use:
            row.enabled = False
            result = "deaktiviert"
        else:
            db.delete(row)
            result = "gelöscht"
    _audit(f"Ticket-Art {result}", "tickets", target=name)
    return {"ok": True, "result": result}


@bp.get("/tickets")
@require_login
def tickets():
    conditions = [Ticket.guild_id == str(settings.guild_id)]
    if not has_permission("tickets.view"):
        conditions.append(Ticket.creator_id == str(_user()["id"]))
    status = request.args.get("status")
    if status:
        conditions.append(Ticket.status == status)
    with session_scope() as db:
        rows = list(
            db.scalars(
                select(Ticket)
                .where(*conditions)
                .order_by(Ticket.updated_at.desc())
                .limit(250)
            )
        )
        return {"items": [_ticket_dict(row) for row in rows]}


@bp.post("/tickets")
@require_login
def create_web_ticket():
    data = _body()
    result = runtime.call(
        "create_dashboard_ticket",
        ticket_type_id=_int(data.get("ticket_type_id"), "Ticket-Art", 1),
        creator_id=int(_user()["id"]),
        creator_name=str(_user()["username"]),
        answers=data.get("answers", {}),
        timeout=20,
    )
    _audit("Ticket erstellt", "tickets", target=f"#{result['id']}", after=data)
    return {"ok": True, "ticket": result}, 201


def _accessible_ticket(ticket_id: int) -> Ticket | None:
    with session_scope() as db:
        row = db.get(Ticket, ticket_id)
        if not row or row.guild_id != str(settings.guild_id):
            return None
        if row.creator_id != str(_user()["id"]) and not has_permission("tickets.view"):
            return None
        db.expunge(row)
        return row


@bp.get("/tickets/<int:ticket_id>")
@require_login
def ticket_detail(ticket_id: int):
    ticket = _accessible_ticket(ticket_id)
    if not ticket:
        return jsonify(error="Ticket nicht gefunden oder nicht freigegeben."), 404
    with session_scope() as db:
        current = db.get(Ticket, ticket_id)
        messages = list(
            db.scalars(
                select(TicketMessage)
                .where(TicketMessage.ticket_id == ticket_id)
                .order_by(TicketMessage.created_at)
            )
        )
        return {
            "ticket": _ticket_dict(current, include_form=True),
            "messages": [
                {
                    "id": row.id,
                    "author_id": row.author_id,
                    "author_name": row.author_name,
                    "author_avatar": row.author_avatar,
                    "content": row.content,
                    "source": row.source,
                    "attachments": row.attachments,
                    "created_at": row.created_at.isoformat(),
                }
                for row in messages
            ],
        }


@bp.post("/tickets/<int:ticket_id>/messages")
@require_login
def post_ticket_message(ticket_id: int):
    ticket = _accessible_ticket(ticket_id)
    if not ticket:
        return jsonify(error="Ticket nicht gefunden oder nicht freigegeben."), 404
    if ticket.status in {"closed", "archived"}:
        return jsonify(error="In geschlossenen Tickets kann nicht geantwortet werden."), 409
    data = _body()
    result = runtime.call(
        "send_dashboard_ticket_message",
        ticket_id,
        int(_user()["id"]),
        str(_user()["username"]),
        str(data.get("content", "")),
        timeout=15,
    )
    return {"ok": True, "message": result}, 201


@bp.post("/tickets/<int:ticket_id>/status")
@require_login
def change_ticket_status(ticket_id: int):
    ticket = _accessible_ticket(ticket_id)
    if not ticket:
        return jsonify(error="Ticket nicht gefunden oder nicht freigegeben."), 404
    data = _body()
    status = str(data.get("status", ""))
    is_team = has_permission("tickets.edit")
    if not is_team and (status != "closed" or ticket.creator_id != str(_user()["id"])):
        return jsonify(error="Du darfst nur dein eigenes Ticket schließen."), 403
    result = runtime.call(
        "change_ticket_status",
        ticket_id,
        status,
        int(_user()["id"]),
        str(_user()["username"]),
        str(data.get("reason", ""))[:1000],
        timeout=15,
    )
    _audit("Ticket-Status geändert", "tickets", target=f"#{ticket_id}", after=result)
    return {"ok": True, "ticket": result}


@bp.post("/tickets/<int:ticket_id>/rating")
@require_login
def rate_ticket(ticket_id: int):
    ticket = _accessible_ticket(ticket_id)
    if not ticket or ticket.creator_id != str(_user()["id"]):
        return jsonify(error="Ticket nicht gefunden."), 404
    if ticket.status not in {"closed", "archived"}:
        return jsonify(error="Bewertungen sind nach dem Schließen möglich."), 409
    data = _body()
    rating = _int(data.get("rating"), "Bewertung", 1, 5)
    with session_scope() as db:
        row = db.get(Ticket, ticket_id)
        row.rating = rating
    return {"ok": True, "rating": rating}


@bp.route("/word-filters", methods=["GET", "POST"])
@require_permission("security.edit")
def word_filters():
    if request.method == "GET":
        with session_scope() as db:
            rows = list(
                db.scalars(
                    select(WordFilter)
                    .where(WordFilter.guild_id == str(settings.guild_id))
                    .order_by(WordFilter.id.desc())
                )
            )
            return {
                "items": [
                    {
                        "id": row.id,
                        "phrase": row.phrase,
                        "mode": row.mode,
                        "case_sensitive": row.case_sensitive,
                        "enabled": row.enabled,
                        "action": row.action,
                        "timeout_minutes": row.timeout_minutes,
                        "threshold": row.threshold,
                        "response": row.response,
                        "exceptions": row.exceptions,
                        "log_channel_id": row.log_channel_id,
                    }
                    for row in rows
                ]
            }
    data = _body()
    phrase = str(data.get("phrase", "")).strip()
    if not 2 <= len(phrase) <= 200:
        raise ValueError("Der Filterausdruck muss zwischen 2 und 200 Zeichen lang sein.")
    action = str(data.get("action", "delete"))
    if action not in {"delete", "warn", "timeout", "kick", "ban"}:
        raise ValueError("Ungültige Filteraktion.")
    roles, channels = _resource_maps()
    exceptions = data.get("exceptions", {})
    exceptions = {
        "role_ids": [
            _valid_role(item, roles) for item in exceptions.get("role_ids", [])
        ][:50],
        "channel_ids": [
            _valid_channel(
                item, channels, {"text", "announcement", "forum", "voice"}
            )
            for item in exceptions.get("channel_ids", [])
        ][:50],
    }
    row = WordFilter(
        guild_id=str(settings.guild_id),
        phrase=phrase,
        mode="exact" if data.get("mode") == "exact" else "contains",
        case_sensitive=bool(data.get("case_sensitive")),
        enabled=bool(data.get("enabled", True)),
        action=action,
        timeout_minutes=_int(data.get("timeout_minutes", 10), "Timeout", 1, 40320),
        threshold=_int(data.get("threshold", 1), "Verstoßgrenze", 1, 100),
        response=str(data.get("response", ""))[:300],
    )
    row.exceptions = exceptions
    with session_scope() as db:
        db.add(row)
        db.flush()
        row_id = row.id
    _audit("Wortfilter erstellt", "security", target=phrase, after=data)
    return {"ok": True, "id": row_id}, 201


@bp.delete("/word-filters/<int:filter_id>")
@require_permission("security.edit")
def delete_word_filter(filter_id: int):
    with session_scope() as db:
        row = db.get(WordFilter, filter_id)
        if not row or row.guild_id != str(settings.guild_id):
            return jsonify(error="Filter nicht gefunden."), 404
        phrase = row.phrase
        db.delete(row)
    _audit("Wortfilter gelöscht", "security", target=phrase)
    return {"ok": True}


@bp.route("/moderation", methods=["GET", "POST"])
@require_permission("moderation.execute")
def moderation():
    if request.method == "GET":
        with session_scope() as db:
            rows = list(
                db.scalars(
                    select(ModerationCase)
                    .where(ModerationCase.guild_id == str(settings.guild_id))
                    .order_by(ModerationCase.id.desc())
                    .limit(250)
                )
            )
            return {
                "items": [
                    {
                        "id": row.id,
                        "user_id": row.user_id,
                        "user_name": row.user_name,
                        "moderator_name": row.moderator_name,
                        "action": row.action,
                        "reason": row.reason,
                        "duration_minutes": row.duration_minutes,
                        "status": row.status,
                        "created_at": row.created_at.isoformat(),
                    }
                    for row in rows
                ]
            }
    data = _body()
    action = str(data.get("action", ""))
    if action not in {"warn", "timeout", "kick", "ban"}:
        raise ValueError("Ungültige Moderationsaktion.")
    user_id = str(data.get("user_id", "")).strip()
    if not user_id.isdigit():
        raise ValueError("Die Benutzer-ID ist ungültig.")
    reason = str(data.get("reason", "")).strip()
    if not 2 <= len(reason) <= 1000:
        raise ValueError("Der Grund muss zwischen 2 und 1.000 Zeichen lang sein.")
    result = runtime.call(
        "execute_moderation",
        action=action,
        user_id=int(user_id),
        moderator_id=int(_user()["id"]),
        moderator_name=str(_user()["username"]),
        reason=reason,
        duration_minutes=_int(
            data.get("duration_minutes", 10), "Dauer", 1, 40320
        )
        if action == "timeout"
        else None,
        timeout=15,
    )
    _audit("Moderation ausgeführt", "moderation", target=user_id, after=result)
    return {"ok": True, "case": result}, 201


@bp.post("/messages/send")
@require_permission("messages.send")
def send_message():
    data = _body()
    _, channels = _resource_maps()
    data["channel_id"] = _valid_channel(
        data.get("channel_id"), channels, {"text", "announcement"}
    )
    result = runtime.call("send_designed_embed", data, timeout=15)
    _audit("Nachricht veröffentlicht", "designer", target=data["channel_id"], after=data)
    return {"ok": True, "message": result}, 201


@bp.route("/announcements", methods=["GET", "POST"])
@require_permission("team.manage")
def announcements():
    if request.method == "GET":
        with session_scope() as db:
            rows = list(
                db.scalars(
                    select(TeamAnnouncement)
                    .where(TeamAnnouncement.guild_id == str(settings.guild_id))
                    .order_by(TeamAnnouncement.id.desc())
                    .limit(100)
                )
            )
            return {
                "items": [
                    {
                        "id": row.id,
                        "title": row.title,
                        "message": row.message,
                        "priority": row.priority,
                        "channel_id": row.channel_id,
                        "require_confirmation": row.require_confirmation,
                        "confirmations": len(
                            JsonMixin.decode(row.confirmed_user_ids_json, [])
                        ),
                        "published_at": row.published_at.isoformat()
                        if row.published_at
                        else None,
                        "created_at": row.created_at.isoformat(),
                    }
                    for row in rows
                ]
            }
    data = _body()
    roles, channels = _resource_maps()
    title = str(data.get("title", "")).strip()
    message = str(data.get("message", "")).strip()
    if not 2 <= len(title) <= 150 or not 2 <= len(message) <= 4000:
        raise ValueError("Titel oder Nachricht hat eine ungültige Länge.")
    row = TeamAnnouncement(
        guild_id=str(settings.guild_id),
        title=title,
        message=message,
        priority=(
            str(data.get("priority"))
            if data.get("priority") in {"normal", "important", "critical"}
            else "normal"
        ),
        target_role_ids_json=JsonMixin.encode(
            [_valid_role(item, roles) for item in data.get("target_role_ids", [])][
                :20
            ]
        ),
        channel_id=_valid_channel(
            data.get("channel_id"), channels, {"text", "announcement"}
        ),
        created_by=str(_user()["id"]),
        created_by_name=str(_user()["username"]),
        require_confirmation=bool(data.get("require_confirmation")),
    )
    with session_scope() as db:
        db.add(row)
        db.flush()
        row_id = row.id
    result = runtime.call("publish_announcement", row_id, timeout=15)
    _audit("Team-Ankündigung veröffentlicht", "team", target=title, after=data)
    return {"ok": True, "id": row_id, "message": result}, 201


@bp.post("/panels/<panel>/publish")
@require_permission("server.edit")
def publish_panel(panel: str):
    data = _body()
    _, channels = _resource_maps()
    channel_id = _valid_channel(
        data.get("channel_id"), channels, {"text", "announcement"}
    )
    result = runtime.call("publish_panel", panel, int(channel_id), timeout=15)
    _audit("Panel veröffentlicht", panel, target=channel_id, after=result)
    return {"ok": True, "message": result}, 201


@bp.route("/permissions", methods=["GET", "POST"])
@require_permission("roles.manage")
def permissions():
    if request.method == "GET":
        with session_scope() as db:
            rows = list(
                db.scalars(
                    select(DashboardRolePermission)
                    .where(
                        DashboardRolePermission.guild_id == str(settings.guild_id)
                    )
                    .order_by(DashboardRolePermission.role_name)
                )
            )
            return {
                "available": sorted(ALL_PERMISSIONS),
                "items": [
                    {
                        "id": row.id,
                        "role_id": row.role_id,
                        "role_name": row.role_name,
                        "permissions": row.permissions,
                    }
                    for row in rows
                ],
            }
    data = _body()
    roles, _ = _resource_maps()
    role_id = _valid_role(data.get("role_id"), roles)
    selected = sorted(
        {
            str(item)
            for item in data.get("permissions", [])
            if str(item) in ALL_PERMISSIONS
        }
    )
    if not selected:
        raise ValueError("Wähle mindestens eine Berechtigung.")
    with session_scope() as db:
        row = db.scalar(
            select(DashboardRolePermission).where(
                DashboardRolePermission.guild_id == str(settings.guild_id),
                DashboardRolePermission.role_id == role_id,
            )
        )
        if not row:
            row = DashboardRolePermission(
                guild_id=str(settings.guild_id), role_id=role_id
            )
            db.add(row)
        before = row.permissions
        row.role_name = roles[role_id]["name"]
        row.permissions = selected
        db.flush()
        row_id = row.id
    _audit(
        "Dashboard-Rolle gespeichert",
        "permissions",
        target=roles[role_id]["name"],
        before=before,
        after=selected,
    )
    return {"ok": True, "id": row_id}


@bp.delete("/permissions/<int:permission_id>")
@require_permission("roles.manage")
def delete_permission(permission_id: int):
    with session_scope() as db:
        row = db.get(DashboardRolePermission, permission_id)
        if not row or row.guild_id != str(settings.guild_id):
            return jsonify(error="Zuordnung nicht gefunden."), 404
        name = row.role_name
        db.delete(row)
    _audit("Dashboard-Rolle entfernt", "permissions", target=name)
    return {"ok": True}


@bp.get("/audit")
@require_permission("audit.view")
def audit_log():
    with session_scope() as db:
        rows = list(
            db.scalars(
                select(AuditLog)
                .where(AuditLog.guild_id == str(settings.guild_id))
                .order_by(AuditLog.id.desc())
                .limit(500)
            )
        )
        return {
            "items": [
                {
                    "id": row.id,
                    "user": row.user_name,
                    "user_id": row.user_id,
                    "action": row.action,
                    "area": row.area,
                    "target": row.target,
                    "before": JsonMixin.decode(row.before_json),
                    "after": JsonMixin.decode(row.after_json),
                    "ip_address": row.ip_address,
                    "created_at": row.created_at.isoformat(),
                }
                for row in rows
            ]
        }
