"""JSON API for all interactive dashboard actions."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import requests
from flask import Blueprint, abort, jsonify, request
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from config import settings
from dashboard.app import limiter
from dashboard.decorators import (
    ALL_PERMISSIONS,
    can_access_ticket,
    current_user,
    login_required,
    permissions_for,
)
from database.manager import add_audit, get_setting, session_scope, set_setting
from database.models import (
    DashboardRole,
    ModerationCase,
    TeamAnnouncement,
    Ticket,
    TicketFormField,
    TicketMessage,
    TicketType,
    WordFilter,
)

api = Blueprint("api", __name__)


def _require(permission: str) -> None:
    granted = permissions_for()
    if permission not in granted and "admin" not in granted:
        abort(403)


def _internal(
    method: str, path: str, payload: dict[str, Any] | None = None
) -> tuple[dict[str, Any], int]:
    try:
        response = requests.request(
            method,
            f"http://{settings.internal_api_host}:{settings.internal_api_port}{path}",
            headers={"Authorization": f"Bearer {settings.internal_api_secret}"},
            json=payload,
            timeout=30,
        )
        try:
            body = response.json()
        except ValueError:
            body = {"error": "Die interne API hat ungültig geantwortet."}
        return body, response.status_code
    except requests.RequestException:
        return {"error": "Der Discord-Bot ist momentan nicht erreichbar."}, 503


def _json() -> dict[str, Any]:
    return request.get_json(silent=True) or {}


def _audit(
    db,
    action: str,
    area: str,
    old_value: Any = None,
    new_value: Any = None,
) -> None:
    user = current_user()
    add_audit(
        db,
        guild_id=str(settings.guild_id),
        user_id=str(user["id"]),
        user_name=str(user["username"]),
        action=action,
        area=area,
        old_value=old_value,
        new_value=new_value,
        ip_address=request.remote_addr,
    )


def _validate_resource_ids(data: dict[str, Any], schema: dict[str, str]) -> None:
    resources, status = _internal("GET", "/resources")
    if status != 200:
        abort(status, resources.get("error"))
    valid_roles = {
        item["id"] for item in resources.get("roles", []) if item.get("usable")
    }
    valid_channels: dict[str, set[str]] = {}
    for item in resources.get("channels", []):
        valid_channels.setdefault(item["type"], set()).add(item["id"])
    valid_channels["text_any"] = valid_channels.get("text", set()) | valid_channels.get(
        "announcement", set()
    )
    for key, kind in schema.items():
        values = data.get(key, [])
        values = values if isinstance(values, list) else [values]
        values = {str(item) for item in values if str(item)}
        allowed = valid_roles if kind == "role" else valid_channels.get(kind, set())
        if not values.issubset(allowed):
            abort(400, f"Die Auswahl für {key} enthält ungültige Discord-Ressourcen.")


@api.get("/resources")
@login_required
def resources():
    if not permissions_for():
        abort(403)
    body, status = _internal("GET", "/resources")
    return jsonify(body), status


SECTION_PERMISSIONS = {
    "welcome": "server.manage",
    "farewell": "server.manage",
    "verify": "server.manage",
    "security": "security.manage",
    "ticket_panel": "tickets.manage",
}

SECTION_SCHEMAS = {
    "welcome": {"channel_id": "text_any", "role_ids": "role"},
    "farewell": {"channel_id": "text_any"},
    "verify": {
        "channel_id": "text_any",
        "role_id": "role",
        "remove_role_ids": "role",
    },
    "security": {
        "ignored_channel_ids": "text_any",
        "ignored_role_ids": "role",
    },
    "ticket_panel": {"channel_id": "text_any"},
}


@api.route("/settings/<section>", methods=["GET", "PUT"])
@login_required
def section_settings(section: str):
    permission = SECTION_PERMISSIONS.get(section)
    if not permission:
        abort(404)
    _require(permission)
    if request.method == "GET":
        with session_scope() as db:
            value = get_setting(db, str(settings.guild_id), section, {})
        return jsonify(value)
    data = _json()
    if len(json.dumps(data)) > 20_000:
        return jsonify(error="Die Einstellungen sind zu groß."), 400
    _validate_resource_ids(data, SECTION_SCHEMAS.get(section, {}))
    with session_scope() as db:
        old = set_setting(db, str(settings.guild_id), section, data)
        _audit(
            db,
            f"{section.replace('_', ' ').title()} aktualisiert",
            section,
            old,
            data,
        )
    return jsonify(ok=True, message="Einstellungen wurden gespeichert.")


@api.post("/publish/<panel>")
@login_required
@limiter.limit("20 per hour")
def publish_panel(panel: str):
    permission = "tickets.manage" if panel == "ticket" else "server.manage"
    _require(permission)
    if panel not in {"ticket", "verify"}:
        abort(404)
    data = _json()
    _validate_resource_ids(data, {"channel_id": "text_any"})
    body, status = _internal("POST", f"/publish/{panel}", data)
    if status < 300:
        with session_scope() as db:
            _audit(db, f"{panel.title()}-Panel veröffentlicht", panel, None, data)
    return jsonify(body), status


def _serialize_ticket_type(item: TicketType) -> dict[str, Any]:
    return {
        "id": item.id,
        "name": item.name,
        "description": item.description,
        "emoji": item.emoji,
        "color": item.color,
        "category_id": item.category_id,
        "support_role_ids": json.loads(item.support_role_ids or "[]"),
        "log_channel_id": item.log_channel_id,
        "transcript_channel_id": item.transcript_channel_id,
        "max_open": item.max_open,
        "cooldown_minutes": item.cooldown_minutes,
        "welcome_message": item.welcome_message,
        "enabled": item.enabled,
        "fields": [
            {
                "id": field.id,
                "label": field.label,
                "field_type": field.field_type,
                "placeholder": field.placeholder,
                "required": field.required,
                "min_length": field.min_length,
                "max_length": field.max_length,
            }
            for field in item.fields
        ],
    }


@api.route("/ticket-types", methods=["GET", "POST"])
@login_required
def ticket_types():
    if request.method == "GET":
        with session_scope() as db:
            items = list(
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
        return jsonify([_serialize_ticket_type(item) for item in items])
    _require("tickets.manage")
    return _save_ticket_type(None)


@api.put("/ticket-types/<int:type_id>")
@login_required
def update_ticket_type(type_id: int):
    _require("tickets.manage")
    return _save_ticket_type(type_id)


def _save_ticket_type(type_id: int | None):
    data = _json()
    name = str(data.get("name", "")).strip()
    if not 2 <= len(name) <= 80:
        return jsonify(error="Der Name muss 2 bis 80 Zeichen haben."), 400
    resource_data = {
        "category_id": data.get("category_id", ""),
        "support_role_ids": data.get("support_role_ids", []),
        "log_channel_id": data.get("log_channel_id", ""),
        "transcript_channel_id": data.get("transcript_channel_id", ""),
    }
    _validate_resource_ids(
        resource_data,
        {
            "category_id": "category",
            "support_role_ids": "role",
            "log_channel_id": "text_any",
            "transcript_channel_id": "text_any",
        },
    )
    raw_fields = data.get("fields") or []
    if not isinstance(raw_fields, list) or len(raw_fields) > 5:
        return jsonify(error="Discord erlaubt maximal fünf Formularfelder."), 400
    for field in raw_fields:
        if not 1 <= len(str(field.get("label", "")).strip()) <= 45:
            return jsonify(error="Jedes Feld benötigt einen kurzen Namen."), 400
    with session_scope() as db:
        item = db.get(TicketType, type_id) if type_id else TicketType(
            guild_id=str(settings.guild_id)
        )
        if not item or item.guild_id != str(settings.guild_id):
            abort(404)
        old = _serialize_ticket_type(item) if type_id else None
        item.name = name
        item.description = str(data.get("description", ""))[:300]
        item.emoji = str(data.get("emoji", "🎫"))[:32]
        color = str(data.get("color", "#8b5cf6"))
        item.color = color if len(color) == 7 and color.startswith("#") else "#8b5cf6"
        item.category_id = str(data.get("category_id") or "") or None
        item.support_role_ids = json.dumps(data.get("support_role_ids") or [])
        item.log_channel_id = str(data.get("log_channel_id") or "") or None
        item.transcript_channel_id = (
            str(data.get("transcript_channel_id") or "") or None
        )
        item.max_open = max(1, min(int(data.get("max_open", 1)), 20))
        item.cooldown_minutes = max(
            0, min(int(data.get("cooldown_minutes", 5)), 10080)
        )
        item.welcome_message = str(data.get("welcome_message", ""))[:2000]
        item.enabled = bool(data.get("enabled", True))
        if not type_id:
            db.add(item)
            db.flush()
        item.fields.clear()
        for position, field in enumerate(raw_fields):
            item.fields.append(
                TicketFormField(
                    label=str(field["label"]).strip()[:45],
                    field_type=(
                        "short" if field.get("field_type") == "short" else "long"
                    ),
                    placeholder=str(field.get("placeholder", ""))[:100],
                    required=bool(field.get("required", True)),
                    min_length=max(0, min(int(field.get("min_length", 0)), 4000)),
                    max_length=max(1, min(int(field.get("max_length", 1000)), 4000)),
                    position=position,
                )
            )
        db.flush()
        new = _serialize_ticket_type(item)
        _audit(
            db,
            f"Ticket-Art {name} {'aktualisiert' if type_id else 'erstellt'}",
            "tickets",
            old,
            new,
        )
        item_id = item.id
    return jsonify(ok=True, id=item_id, message="Ticket-Art wurde gespeichert.")


@api.delete("/ticket-types/<int:type_id>")
@login_required
def delete_ticket_type(type_id: int):
    _require("tickets.manage")
    with session_scope() as db:
        item = db.get(TicketType, type_id)
        if not item or item.guild_id != str(settings.guild_id):
            abort(404)
        ticket_count = (
            db.scalar(
                select(func.count(Ticket.id)).where(Ticket.ticket_type_id == item.id)
            )
            or 0
        )
        if ticket_count:
            item.enabled = False
            action = "deaktiviert"
        else:
            db.delete(item)
            action = "gelöscht"
        _audit(db, f"Ticket-Art {item.name} {action}", "tickets")
    return jsonify(ok=True, message=f"Ticket-Art wurde {action}.")


@api.post("/tickets")
@login_required
@limiter.limit("10 per hour")
def create_ticket():
    user = current_user()
    data = _json()
    body, status = _internal(
        "POST",
        "/tickets",
        {
            "user_id": user["id"],
            "ticket_type_id": data.get("ticket_type_id"),
            "form_data": data.get("form_data") or {},
        },
    )
    return jsonify(body), status


@api.post("/tickets/<int:ticket_id>/messages")
@login_required
@limiter.limit("30 per minute")
def ticket_message(ticket_id: int):
    with session_scope() as db:
        ticket = db.get(Ticket, ticket_id)
        if not ticket or ticket.guild_id != str(settings.guild_id):
            abort(404)
        if not can_access_ticket(ticket):
            abort(403)
    user = current_user()
    data = _json()
    body, status = _internal(
        "POST",
        f"/tickets/{ticket_id}/messages",
        {
            "author_id": user["id"],
            "author_name": user["username"],
            "author_avatar": user["avatar"],
            "content": data.get("content", ""),
        },
    )
    return jsonify(body), status


@api.put("/tickets/<int:ticket_id>/status")
@login_required
def ticket_status(ticket_id: int):
    data = _json()
    status = str(data.get("status", ""))
    if status not in {"open", "claimed", "waiting", "closed", "archived"}:
        return jsonify(error="Ungültiger Ticket-Status."), 400
    with session_scope() as db:
        ticket = db.get(Ticket, ticket_id)
        if not ticket or ticket.guild_id != str(settings.guild_id):
            abort(404)
        is_owner_close = (
            ticket.creator_id == str(current_user()["id"]) and status == "closed"
        )
        if not is_owner_close:
            _require("tickets.manage")
        old = ticket.status
        ticket.status = status
        ticket.closed_at = datetime.now(UTC) if status == "closed" else None
        ticket.close_reason = str(data.get("reason", ""))[:1000] or None
        db.add(
            TicketMessage(
                ticket_id=ticket.id,
                author_id=str(current_user()["id"]),
                author_name=str(current_user()["username"]),
                content=f"Status von {old} zu {status} geändert.",
                source="system",
                system_event=True,
            )
        )
        _audit(db, f"Ticket #{ticket.number}: Status {status}", "tickets", old, status)
    return jsonify(ok=True, message="Ticket-Status wurde aktualisiert.")


@api.route("/word-filters", methods=["POST"])
@login_required
def create_word_filter():
    _require("security.manage")
    data = _json()
    phrase = str(data.get("phrase", "")).strip()
    if not 2 <= len(phrase) <= 200:
        return jsonify(error="Der Filter muss 2 bis 200 Zeichen haben."), 400
    with session_scope() as db:
        item = WordFilter(
            guild_id=str(settings.guild_id),
            phrase=phrase,
            match_type="exact" if data.get("match_type") == "exact" else "contains",
            case_sensitive=bool(data.get("case_sensitive")),
            action=(
                data.get("action")
                if data.get("action") in {"delete", "warn", "timeout", "kick", "ban"}
                else "delete"
            ),
            timeout_minutes=max(0, min(int(data.get("timeout_minutes", 0)), 40320)),
            response=str(data.get("response", ""))[:300],
        )
        db.add(item)
        db.flush()
        _audit(db, f"Wortfilter hinzugefügt: {phrase}", "security")
        item_id = item.id
    return jsonify(ok=True, id=item_id, message="Wortfilter wurde hinzugefügt."), 201


@api.delete("/word-filters/<int:filter_id>")
@login_required
def delete_word_filter(filter_id: int):
    _require("security.manage")
    with session_scope() as db:
        item = db.get(WordFilter, filter_id)
        if not item or item.guild_id != str(settings.guild_id):
            abort(404)
        phrase = item.phrase
        db.delete(item)
        _audit(db, f"Wortfilter entfernt: {phrase}", "security")
    return jsonify(ok=True, message="Wortfilter wurde entfernt.")


@api.post("/moderate")
@login_required
@limiter.limit("20 per hour")
def moderate():
    _require("moderation.execute")
    data = _json()
    body, status = _internal("POST", "/moderate", data)
    if status < 300:
        with session_scope() as db:
            number = (
                db.scalar(
                    select(func.max(ModerationCase.case_number)).where(
                        ModerationCase.guild_id == str(settings.guild_id)
                    )
                )
                or 0
            ) + 1
            db.add(
                ModerationCase(
                    guild_id=str(settings.guild_id),
                    case_number=number,
                    target_id=str(data.get("user_id")),
                    target_name=str(data.get("user_name", data.get("user_id")))[:100],
                    moderator_id=str(current_user()["id"]),
                    moderator_name=str(current_user()["username"]),
                    action=str(data.get("action"))[:30],
                    reason=str(data.get("reason", "Über Dashboard"))[:1000],
                    duration_seconds=(
                        int(data.get("minutes", 0)) * 60
                        if data.get("action") == "timeout"
                        else None
                    ),
                )
            )
            _audit(db, f"Moderation ausgeführt: {data.get('action')}", "moderation")
            body["case_number"] = number
    return jsonify(body), status


@api.post("/embeds")
@login_required
@limiter.limit("30 per hour")
def send_embed():
    _require("embeds.send")
    data = _json()
    _validate_resource_ids(data, {"channel_id": "text_any"})
    body, status = _internal("POST", "/embeds", data)
    if status < 300:
        with session_scope() as db:
            _audit(db, f"Embed gesendet: {data.get('title', 'Ohne Titel')}", "embeds")
    return jsonify(body), status


@api.post("/team-announcements")
@login_required
def team_announcement():
    _require("team.manage")
    data = _json()
    title = str(data.get("title", "")).strip()
    content = str(data.get("content", "")).strip()
    if not title or not content:
        return jsonify(error="Titel und Nachricht werden benötigt."), 400
    _validate_resource_ids(
        data, {"channel_id": "text_any", "target_role_ids": "role"}
    )
    with session_scope() as db:
        item = TeamAnnouncement(
            guild_id=str(settings.guild_id),
            author_id=str(current_user()["id"]),
            author_name=str(current_user()["username"]),
            title=title[:120],
            content=content[:4000],
            priority=(
                data.get("priority")
                if data.get("priority") in {"low", "normal", "high", "urgent"}
                else "normal"
            ),
            target_role_ids=json.dumps(data.get("target_role_ids") or []),
            channel_id=str(data.get("channel_id") or "") or None,
        )
        db.add(item)
        db.flush()
        _audit(db, f"Team-Ankündigung erstellt: {title}", "team")
        item_id = item.id
    if data.get("publish_now") and data.get("channel_id"):
        mentions = " ".join(
            f"<@&{role_id}>" for role_id in data.get("target_role_ids", [])
        )
        body, status = _internal(
            "POST",
            "/embeds",
            {
                "channel_id": data["channel_id"],
                "content": mentions,
                "title": title,
                "description": content,
                "color": "#ef4444" if data.get("priority") == "urgent" else "#8b5cf6",
                "timestamp": True,
                "footer": f"Team-Ankündigung · {current_user()['username']}",
            },
        )
        if status >= 300:
            return jsonify(error=body.get("error"), id=item_id), status
        with session_scope() as db:
            saved = db.get(TeamAnnouncement, item_id)
            saved.published = True
    return jsonify(ok=True, id=item_id, message="Ankündigung wurde erstellt."), 201


@api.put("/dashboard-roles/<role_id>")
@login_required
def save_dashboard_role(role_id: str):
    _require("roles.manage")
    data = _json()
    _validate_resource_ids({"role_id": role_id}, {"role_id": "role"})
    granted = {
        item for item in data.get("permissions", []) if item in ALL_PERMISSIONS
    }
    with session_scope() as db:
        mapping = db.scalar(
            select(DashboardRole).where(
                DashboardRole.guild_id == str(settings.guild_id),
                DashboardRole.role_id == role_id,
            )
        )
        old = json.loads(mapping.permissions) if mapping else []
        if not mapping:
            mapping = DashboardRole(
                guild_id=str(settings.guild_id),
                role_id=role_id,
                role_name=str(data.get("role_name", "Discord-Rolle"))[:100],
            )
            db.add(mapping)
        mapping.role_name = str(data.get("role_name", mapping.role_name))[:100]
        mapping.permissions = json.dumps(sorted(granted))
        _audit(
            db,
            f"Dashboard-Rechte für {mapping.role_name} aktualisiert",
            "roles",
            old,
            sorted(granted),
        )
    return jsonify(ok=True, message="Rollenrechte wurden gespeichert.")


@api.delete("/dashboard-roles/<role_id>")
@login_required
def delete_dashboard_role(role_id: str):
    _require("roles.manage")
    with session_scope() as db:
        mapping = db.scalar(
            select(DashboardRole).where(
                DashboardRole.guild_id == str(settings.guild_id),
                DashboardRole.role_id == role_id,
            )
        )
        if not mapping:
            abort(404)
        name = mapping.role_name
        db.delete(mapping)
        _audit(db, f"Dashboard-Rechte für {name} entfernt", "roles")
    return jsonify(ok=True, message="Rollenzuordnung wurde entfernt.")
