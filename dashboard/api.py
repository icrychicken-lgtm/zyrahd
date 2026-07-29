"""JSON API used by the dashboard. Every mutation is permission checked."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any

from flask import Blueprint, jsonify, request, session

from config import settings
from dashboard.internal_client import BotUnavailable, bot_request
from dashboard.permissions import (
    PERMISSIONS,
    current_user,
    has_permission,
    require_permission,
)
from database.manager import write_audit
from database.models import (
    AuditLog,
    DashboardRole,
    EmbedTemplate,
    GuildConfig,
    ModerationCase,
    TeamAnnouncement,
    Ticket,
    TicketMessage,
    TicketType,
    WordFilter,
    db,
)

api_bp = Blueprint("api", __name__, url_prefix="/api")
HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
GUILD_ID = str(settings.guild_id)


class ApiError(ValueError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


@api_bp.errorhandler(ApiError)
def handle_api_error(error: ApiError):
    return jsonify(error=str(error)), error.status


@api_bp.errorhandler(BotUnavailable)
def handle_bot_unavailable(error: BotUnavailable):
    return jsonify(error=str(error)), 503


def body() -> dict[str, Any]:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError("Ungültige Anfrage.")
    return data


def text(
    data: dict[str, Any],
    key: str,
    *,
    required: bool = False,
    maximum: int = 1000,
) -> str:
    value = str(data.get(key, "")).strip()
    if required and not value:
        raise ApiError(f"„{key}“ darf nicht leer sein.")
    if len(value) > maximum:
        raise ApiError(f"„{key}“ ist zu lang.")
    return value


def integer(
    data: dict[str, Any],
    key: str,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    try:
        value = int(data.get(key, default))
    except (TypeError, ValueError) as exc:
        raise ApiError(f"„{key}“ muss eine Zahl sein.") from exc
    if not minimum <= value <= maximum:
        raise ApiError(f"„{key}“ muss zwischen {minimum} und {maximum} liegen.")
    return value


def user() -> dict[str, Any]:
    return current_user() or {"id": "system", "username": "System"}


def config() -> GuildConfig:
    result = db.session.scalar(
        db.select(GuildConfig).where(GuildConfig.guild_id == GUILD_ID)
    )
    if result is None:
        raise ApiError("Serverkonfiguration wurde nicht initialisiert.", 500)
    return result


@api_bp.get("/overview")
@require_permission("dashboard.open")
def overview():
    now = datetime.now(UTC)
    start = now - timedelta(days=6)
    tickets = db.session.scalars(
        db.select(Ticket)
        .where(Ticket.guild_id == GUILD_ID)
        .order_by(Ticket.created_at.desc())
    ).all()
    cases_today = db.session.scalar(
        db.select(db.func.count(ModerationCase.id)).where(
            ModerationCase.guild_id == GUILD_ID,
            ModerationCase.created_at >= now.replace(
                hour=0, minute=0, second=0, microsecond=0
            ),
        )
    )
    chart = []
    for offset in range(7):
        day = (start + timedelta(days=offset)).date()
        chart.append(
            {
                "label": day.strftime("%d.%m"),
                "tickets": sum(1 for ticket in tickets if ticket.created_at.date() == day),
            }
        )
    recent = db.session.scalars(
        db.select(AuditLog)
        .where(AuditLog.guild_id == GUILD_ID)
        .order_by(AuditLog.created_at.desc())
        .limit(6)
    )
    try:
        status = bot_request("GET", "/status")
    except BotUnavailable:
        status = {
            "online": False,
            "guild_name": "Discord nicht verbunden",
            "members": 0,
            "online_members": 0,
            "guild_icon": None,
        }
    return jsonify(
        stats={
            "members": status.get("members", 0),
            "online_members": status.get("online_members", 0),
            "open_tickets": sum(
                ticket.status in {"open", "claimed", "waiting"} for ticket in tickets
            ),
            "tickets_today": sum(
                ticket.created_at.date() == now.date() for ticket in tickets
            ),
            "moderations_today": cases_today or 0,
        },
        chart=chart,
        recent_activity=[entry.to_dict() for entry in recent],
        server=status,
    )


@api_bp.get("/resources")
@require_permission("dashboard.open")
def resources():
    return jsonify(bot_request("GET", "/resources"))


SETTING_FIELDS = {
    "welcome": {
        "enabled",
        "channel_id",
        "message",
        "embed",
        "title",
        "color",
        "role_ids",
        "dm_enabled",
    },
    "verify": {
        "enabled",
        "channel_id",
        "role_id",
        "remove_role_ids",
        "title",
        "description",
        "color",
        "button_text",
        "button_emoji",
        "minimum_account_days",
        "log_channel_id",
        "dm_enabled",
    },
    "security": {
        "anti_spam",
        "spam_messages",
        "spam_seconds",
        "anti_invites",
        "anti_links",
        "anti_caps",
        "caps_percentage",
        "mention_limit",
        "log_channel_id",
        "exempt_role_ids",
        "exempt_channel_ids",
    },
}
SETTING_PERMISSION = {
    "welcome": "server.manage",
    "verify": "server.manage",
    "security": "security.manage",
}


@api_bp.route("/settings/<area>", methods=["GET", "PUT"])
@require_permission("dashboard.open")
def settings_area(area: str):
    if area not in SETTING_FIELDS:
        raise ApiError("Unbekannter Einstellungsbereich.", 404)
    required = SETTING_PERMISSION[area]
    if not has_permission(required):
        raise ApiError("Dafür fehlt dir die Berechtigung.", 403)
    guild_config = config()
    current = dict(getattr(guild_config, area) or {})
    if request.method == "GET":
        return jsonify(settings=current)

    data = body()
    unexpected = set(data) - SETTING_FIELDS[area]
    if unexpected:
        raise ApiError("Die Anfrage enthält unbekannte Einstellungen.")
    updated = {**current, **data}
    for key in ("title", "message", "description", "button_text"):
        if key in updated and len(str(updated[key])) > 4000:
            raise ApiError(f"„{key}“ ist zu lang.")
    if "color" in updated and not HEX_COLOR.match(str(updated["color"])):
        raise ApiError("Die Farbe muss im Format #8b5cf6 angegeben werden.")
    before = current.copy()
    setattr(guild_config, area, updated)
    write_audit(
        GUILD_ID,
        user(),
        "Einstellungen geändert",
        area,
        before=before,
        after=updated,
    )
    db.session.commit()
    try:
        bot_request("POST", "/reload", {"area": area})
        bot_online = True
    except BotUnavailable:
        # The bot reads from the same database on its next event. Saving the
        # durable configuration must not fail merely because Discord is offline.
        bot_online = False
    return jsonify(
        message="Einstellungen gespeichert.",
        settings=updated,
        bot_online=bot_online,
    )


@api_bp.post("/verify/publish")
@require_permission("server.manage")
def publish_verify():
    result = bot_request("POST", "/verify/publish")
    write_audit(GUILD_ID, user(), "Verify-Panel veröffentlicht", "verify")
    db.session.commit()
    return jsonify(message="Verify-Panel wurde veröffentlicht.", **result)


@api_bp.post("/ticket-panel/publish")
@require_permission("tickets.manage")
def publish_ticket_panel():
    data = body()
    channel_id = text(data, "channel_id", required=True, maximum=24)
    result = bot_request(
        "POST", "/ticket-panel/publish", {"channel_id": channel_id}
    )
    write_audit(
        GUILD_ID,
        user(),
        "Ticket-Panel veröffentlicht",
        "tickets",
        target=channel_id,
    )
    db.session.commit()
    return jsonify(message="Ticket-Panel wurde veröffentlicht.", **result)


@api_bp.route("/ticket-types", methods=["GET", "POST"])
@require_permission("tickets.view")
def ticket_types():
    if request.method == "GET":
        values = db.session.scalars(
            db.select(TicketType)
            .where(TicketType.guild_id == GUILD_ID)
            .order_by(TicketType.name)
        )
        return jsonify(items=[value.to_dict() for value in values])
    if not has_permission("tickets.manage"):
        raise ApiError("Dafür fehlt dir die Berechtigung.", 403)
    data = body()
    item = TicketType(guild_id=GUILD_ID)
    apply_ticket_type(item, data)
    db.session.add(item)
    db.session.flush()
    write_audit(
        GUILD_ID,
        user(),
        "Ticket-Art erstellt",
        "tickets",
        target=item.name,
        after=item.to_dict(),
    )
    db.session.commit()
    return jsonify(message="Ticket-Art erstellt.", item=item.to_dict()), 201


@api_bp.route("/ticket-types/<int:item_id>", methods=["PUT", "DELETE"])
@require_permission("tickets.manage")
def ticket_type_item(item_id: int):
    item = db.session.scalar(
        db.select(TicketType).where(
            TicketType.id == item_id, TicketType.guild_id == GUILD_ID
        )
    )
    if item is None:
        raise ApiError("Ticket-Art nicht gefunden.", 404)
    before = item.to_dict()
    if request.method == "DELETE":
        in_use = db.session.scalar(
            db.select(db.func.count(Ticket.id)).where(Ticket.ticket_type_id == item.id)
        )
        if in_use:
            item.enabled = False
            action = "Ticket-Art deaktiviert"
            message = "Vorhandene Tickets nutzen diese Art; sie wurde deaktiviert."
        else:
            db.session.delete(item)
            action = "Ticket-Art gelöscht"
            message = "Ticket-Art gelöscht."
        write_audit(
            GUILD_ID, user(), action, "tickets", target=item.name, before=before
        )
        db.session.commit()
        return jsonify(message=message)

    apply_ticket_type(item, body())
    write_audit(
        GUILD_ID,
        user(),
        "Ticket-Art geändert",
        "tickets",
        target=item.name,
        before=before,
        after=item.to_dict(),
    )
    db.session.commit()
    return jsonify(message="Ticket-Art gespeichert.", item=item.to_dict())


def apply_ticket_type(item: TicketType, data: dict[str, Any]) -> None:
    item.name = text(data, "name", required=True, maximum=80)
    item.description = text(data, "description", maximum=200)
    item.emoji = text(data, "emoji", maximum=32) or "🎫"
    color = text(data, "color", maximum=7) or "#8b5cf6"
    if not HEX_COLOR.match(color):
        raise ApiError("Ungültige Embed-Farbe.")
    item.color = color
    item.enabled = bool(data.get("enabled", True))
    item.category_id = str(data["category_id"]) if data.get("category_id") else None
    item.support_role_ids = [str(value) for value in data.get("support_role_ids", [])]
    item.log_channel_id = (
        str(data["log_channel_id"]) if data.get("log_channel_id") else None
    )
    item.transcript_channel_id = (
        str(data["transcript_channel_id"])
        if data.get("transcript_channel_id")
        else None
    )
    item.max_open_per_user = integer(data, "max_open_per_user", 1, 1, 20)
    item.cooldown_minutes = integer(data, "cooldown_minutes", 10, 0, 10080)
    item.inactivity_hours = integer(data, "inactivity_hours", 72, 0, 8760)
    item.channel_name_format = (
        text(data, "channel_name_format", maximum=80) or "ticket-{number}-{user}"
    )
    item.greeting = text(data, "greeting", maximum=2000)
    item.ping_roles = bool(data.get("ping_roles", True))
    item.priority = str(data.get("priority", "normal"))
    fields = data.get("form_fields", [])
    if not isinstance(fields, list) or len(fields) > 5:
        raise ApiError("Discord unterstützt höchstens fünf Formularfelder.")
    cleaned_fields = []
    for index, field in enumerate(fields):
        if not isinstance(field, dict):
            raise ApiError("Ungültiges Formularfeld.")
        label = text(field, "label", required=True, maximum=45)
        cleaned_fields.append(
            {
                "id": str(field.get("id") or f"field-{index}"),
                "label": label,
                "type": "long" if field.get("type") == "long" else "short",
                "required": bool(field.get("required", True)),
                "placeholder": text(field, "placeholder", maximum=100),
                "min_length": integer(field, "min_length", 0, 0, 4000),
                "max_length": integer(field, "max_length", 1000, 1, 4000),
            }
        )
    item.form_fields = cleaned_fields


@api_bp.get("/tickets")
@require_permission("tickets.view")
def tickets():
    query = db.select(Ticket).where(Ticket.guild_id == GUILD_ID)
    if request.args.get("mine") == "1" or not has_permission("tickets.manage"):
        query = query.where(Ticket.creator_id == str(user()["id"]))
    status = request.args.get("status")
    if status:
        query = query.where(Ticket.status == status)
    values = db.session.scalars(query.order_by(Ticket.updated_at.desc()).limit(100))
    return jsonify(items=[value.to_dict() for value in values])


@api_bp.post("/tickets")
@require_permission("dashboard.open")
def create_ticket():
    data = body()
    type_id = integer(data, "ticket_type_id", 0, 1, 2_147_483_647)
    ticket_type = db.session.scalar(
        db.select(TicketType).where(
            TicketType.id == type_id,
            TicketType.guild_id == GUILD_ID,
            TicketType.enabled.is_(True),
        )
    )
    if ticket_type is None:
        raise ApiError("Diese Ticket-Art ist nicht verfügbar.", 404)
    answers = data.get("answers", {})
    if not isinstance(answers, dict):
        raise ApiError("Ungültige Formularantworten.")
    for field in ticket_type.form_fields or []:
        value = str(answers.get(field["id"], "")).strip()
        if field.get("required") and not value:
            raise ApiError(f"„{field['label']}“ ist ein Pflichtfeld.")
        if len(value) > int(field.get("max_length", 1000)):
            raise ApiError(f"„{field['label']}“ ist zu lang.")
    result = bot_request(
        "POST",
        "/tickets",
        {
            "ticket_type_id": type_id,
            "creator_id": str(user()["id"]),
            "creator_name": user().get("global_name") or user().get("username"),
            "answers": answers,
        },
    )
    return jsonify(message="Dein Ticket wurde erstellt.", **result), 201


def permitted_ticket(ticket_id: int) -> Ticket:
    ticket = db.session.scalar(
        db.select(Ticket).where(Ticket.id == ticket_id, Ticket.guild_id == GUILD_ID)
    )
    if ticket is None:
        raise ApiError("Ticket nicht gefunden.", 404)
    if ticket.creator_id != str(user()["id"]) and not has_permission("tickets.manage"):
        raise ApiError("Du darfst dieses Ticket nicht öffnen.", 403)
    return ticket


@api_bp.get("/tickets/<int:ticket_id>/messages")
@require_permission("dashboard.open")
def ticket_messages(ticket_id: int):
    permitted_ticket(ticket_id)
    values = db.session.scalars(
        db.select(TicketMessage)
        .where(TicketMessage.ticket_id == ticket_id)
        .order_by(TicketMessage.created_at)
        .limit(500)
    )
    return jsonify(
        items=[
            {
                "id": value.id,
                "author_name": value.author_name,
                "author_avatar": value.author_avatar,
                "content": value.content,
                "source": value.source,
                "attachments": value.attachments or [],
                "is_system": value.is_system,
                "created_at": value.created_at.isoformat(),
            }
            for value in values
        ]
    )


@api_bp.post("/tickets/<int:ticket_id>/messages")
@require_permission("dashboard.open")
def post_ticket_message(ticket_id: int):
    ticket = permitted_ticket(ticket_id)
    content = text(body(), "content", required=True, maximum=1900)
    if ticket.status in {"closed", "archived"}:
        raise ApiError("Dieses Ticket ist bereits geschlossen.")
    result = bot_request(
        "POST",
        f"/tickets/{ticket_id}/messages",
        {
            "author_id": str(user()["id"]),
            "author_name": user().get("global_name") or user().get("username"),
            "author_avatar": user().get("avatar_url"),
            "content": content,
        },
    )
    return jsonify(message="Antwort gesendet.", **result)


@api_bp.post("/tickets/<int:ticket_id>/close")
@require_permission("dashboard.open")
def close_ticket(ticket_id: int):
    permitted_ticket(ticket_id)
    reason = text(body(), "reason", maximum=300) or "Im Dashboard geschlossen"
    result = bot_request(
        "POST",
        f"/tickets/{ticket_id}/close",
        {"actor_id": str(user()["id"]), "reason": reason},
    )
    return jsonify(message="Ticket geschlossen.", **result)


@api_bp.route("/word-filters", methods=["GET", "POST"])
@require_permission("security.manage")
def word_filters():
    if request.method == "GET":
        values = db.session.scalars(
            db.select(WordFilter)
            .where(WordFilter.guild_id == GUILD_ID)
            .order_by(WordFilter.phrase)
        )
        return jsonify(items=[value.to_dict() for value in values])
    data = body()
    item = WordFilter(
        guild_id=GUILD_ID,
        phrase=text(data, "phrase", required=True, maximum=120),
        match_type=(
            "exact" if data.get("match_type") == "exact" else "contains"
        ),
        case_sensitive=bool(data.get("case_sensitive", False)),
        action=str(data.get("action", "delete")),
        timeout_minutes=integer(data, "timeout_minutes", 10, 1, 40320),
        threshold=integer(data, "threshold", 1, 1, 50),
        response=text(data, "response", maximum=500),
        log_channel_id=(
            str(data["log_channel_id"]) if data.get("log_channel_id") else None
        ),
        exempt_role_ids=[str(value) for value in data.get("exempt_role_ids", [])],
        exempt_channel_ids=[
            str(value) for value in data.get("exempt_channel_ids", [])
        ],
        enabled=True,
    )
    if item.action not in {"delete", "warn", "timeout", "kick", "ban"}:
        raise ApiError("Unbekannte Filter-Aktion.")
    db.session.add(item)
    db.session.flush()
    write_audit(
        GUILD_ID,
        user(),
        "Wortfilter hinzugefügt",
        "security",
        target=item.phrase,
        after=item.to_dict(),
    )
    db.session.commit()
    return jsonify(message="Wortfilter hinzugefügt.", item=item.to_dict()), 201


@api_bp.delete("/word-filters/<int:item_id>")
@require_permission("security.manage")
def delete_word_filter(item_id: int):
    item = db.session.scalar(
        db.select(WordFilter).where(
            WordFilter.id == item_id, WordFilter.guild_id == GUILD_ID
        )
    )
    if item is None:
        raise ApiError("Wortfilter nicht gefunden.", 404)
    before = item.to_dict()
    db.session.delete(item)
    write_audit(
        GUILD_ID,
        user(),
        "Wortfilter gelöscht",
        "security",
        target=item.phrase,
        before=before,
    )
    db.session.commit()
    return jsonify(message="Wortfilter gelöscht.")


@api_bp.route("/moderation", methods=["GET", "POST"])
@require_permission("moderation.execute")
def moderation():
    if request.method == "GET":
        cases = db.session.scalars(
            db.select(ModerationCase)
            .where(ModerationCase.guild_id == GUILD_ID)
            .order_by(ModerationCase.created_at.desc())
            .limit(100)
        )
        return jsonify(items=[case.to_dict() for case in cases])
    data = body()
    action = str(data.get("action", "warn"))
    if action not in {"warn", "timeout", "kick", "ban", "untimeout", "unban"}:
        raise ApiError("Unbekannte Moderationsaktion.")
    payload = {
        "user_id": text(data, "user_id", required=True, maximum=24),
        "action": action,
        "reason": text(data, "reason", required=True, maximum=500),
        "duration_minutes": integer(data, "duration_minutes", 10, 1, 40320),
        "moderator_id": str(user()["id"]),
        "moderator_name": user().get("global_name") or user().get("username"),
    }
    result = bot_request("POST", "/moderation", payload)
    return jsonify(message="Moderationsaktion ausgeführt.", **result), 201


@api_bp.post("/embeds/send")
@require_permission("messages.send")
def send_embed():
    data = body()
    payload = {
        "channel_id": text(data, "channel_id", required=True, maximum=24),
        "content": text(data, "content", maximum=2000),
        "title": text(data, "title", maximum=256),
        "description": text(data, "description", maximum=4000),
        "color": text(data, "color", maximum=7) or "#8b5cf6",
        "footer": text(data, "footer", maximum=2048),
        "image_url": text(data, "image_url", maximum=1000),
        "thumbnail_url": text(data, "thumbnail_url", maximum=1000),
    }
    if not HEX_COLOR.match(payload["color"]):
        raise ApiError("Ungültige Embed-Farbe.")
    template = EmbedTemplate(
        guild_id=GUILD_ID,
        name=payload["title"] or "Discord-Nachricht",
        payload=payload,
        created_by_id=str(user()["id"]),
    )
    result = bot_request("POST", "/embeds", payload)
    db.session.add(template)
    write_audit(
        GUILD_ID,
        user(),
        "Embed gesendet",
        "designer",
        target=payload["channel_id"],
        after=payload,
    )
    db.session.commit()
    return jsonify(message="Nachricht wurde an Discord gesendet.", **result)


@api_bp.route("/announcements", methods=["GET", "POST"])
@require_permission("team.manage")
def announcements():
    if request.method == "GET":
        values = db.session.scalars(
            db.select(TeamAnnouncement)
            .where(TeamAnnouncement.guild_id == GUILD_ID)
            .order_by(TeamAnnouncement.created_at.desc())
            .limit(50)
        )
        return jsonify(
            items=[
                {
                    "id": value.id,
                    "title": value.title,
                    "content": value.content,
                    "priority": value.priority,
                    "channel_id": value.channel_id,
                    "target_role_ids": value.target_role_ids or [],
                    "created_by_name": value.created_by_name,
                    "published": bool(value.published_message_id),
                    "created_at": value.created_at.isoformat(),
                }
                for value in values
            ]
        )
    data = body()
    item = TeamAnnouncement(
        guild_id=GUILD_ID,
        title=text(data, "title", required=True, maximum=256),
        content=text(data, "content", required=True, maximum=4000),
        priority=str(data.get("priority", "normal")),
        target_role_ids=[str(value) for value in data.get("target_role_ids", [])],
        channel_id=text(data, "channel_id", required=True, maximum=24),
        require_confirmation=bool(data.get("require_confirmation", False)),
        created_by_id=str(user()["id"]),
        created_by_name=user().get("global_name") or user().get("username"),
    )
    db.session.add(item)
    db.session.flush()
    result = bot_request(
        "POST",
        "/announcements",
        {
            "announcement_id": item.id,
            "title": item.title,
            "content": item.content,
            "priority": item.priority,
            "target_role_ids": item.target_role_ids,
            "channel_id": item.channel_id,
            "require_confirmation": item.require_confirmation,
        },
    )
    item.published_message_id = str(result["message_id"])
    write_audit(
        GUILD_ID,
        user(),
        "Team-Ankündigung veröffentlicht",
        "announcements",
        target=item.title,
    )
    db.session.commit()
    return jsonify(message="Team-Ankündigung veröffentlicht.", **result), 201


@api_bp.route("/permissions", methods=["GET", "PUT"])
@require_permission("roles.manage")
def permissions():
    if request.method == "GET":
        grants = db.session.scalars(
            db.select(DashboardRole)
            .where(DashboardRole.guild_id == GUILD_ID)
            .order_by(DashboardRole.role_name)
        )
        return jsonify(
            available=PERMISSIONS,
            items=[
                {
                    "id": grant.id,
                    "role_id": grant.role_id,
                    "role_name": grant.role_name,
                    "permissions": grant.permissions or [],
                }
                for grant in grants
            ],
        )
    data = body()
    role_id = text(data, "role_id", required=True, maximum=24)
    role_name = text(data, "role_name", required=True, maximum=100)
    selected = data.get("permissions", [])
    if not isinstance(selected, list) or any(value not in PERMISSIONS for value in selected):
        raise ApiError("Die Berechtigungsauswahl ist ungültig.")
    grant = db.session.scalar(
        db.select(DashboardRole).where(
            DashboardRole.guild_id == GUILD_ID, DashboardRole.role_id == role_id
        )
    )
    before = (
        {"role_name": grant.role_name, "permissions": grant.permissions}
        if grant
        else None
    )
    if grant is None:
        grant = DashboardRole(guild_id=GUILD_ID, role_id=role_id)
        db.session.add(grant)
    grant.role_name = role_name
    grant.permissions = list(dict.fromkeys(selected))
    write_audit(
        GUILD_ID,
        user(),
        "Dashboard-Rechte geändert",
        "permissions",
        target=role_name,
        before=before,
        after={"role_name": role_name, "permissions": grant.permissions},
    )
    db.session.commit()
    return jsonify(message=f"Rechte für {role_name} gespeichert.")


@api_bp.get("/audit")
@require_permission("audit.view")
def audit():
    values = db.session.scalars(
        db.select(AuditLog)
        .where(AuditLog.guild_id == GUILD_ID)
        .order_by(AuditLog.created_at.desc())
        .limit(200)
    )
    return jsonify(items=[value.to_dict() for value in values])
