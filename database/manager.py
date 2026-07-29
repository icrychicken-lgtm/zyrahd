"""Database initialization, default data and audit helpers."""

from __future__ import annotations

from typing import Any

from flask import Flask, request

from database.migrations import run_migrations
from database.models import AuditLog, GuildConfig, TicketType, db

DEFAULT_TICKET_TYPES = (
    (
        "Support",
        "Technische Fragen und allgemeine Hilfe",
        "🛟",
        ["Wobei benötigst du Hilfe?", "Was hast du bereits versucht?"],
    ),
    (
        "Bewerbung",
        "Bewirb dich für unser Team",
        "📝",
        ["Wie heißt du?", "Wie alt bist du?", "Warum sollten wir dich annehmen?"],
    ),
    (
        "Partnerschaft",
        "Anfragen für eine Server-Partnerschaft",
        "🤝",
        ["Wie heißt dein Server?", "Wie viele Mitglieder hat dein Server?"],
    ),
    ("Beschwerde", "Vertrauliche Beschwerde einreichen", "⚖️", ["Was ist passiert?"]),
    (
        "Entbannungsantrag",
        "Prüfung einer bestehenden Sperre beantragen",
        "🔓",
        ["Warum wurdest du gebannt?", "Warum sollen wir dich entbannen?"],
    ),
    ("Allgemeine Anfrage", "Alles, was sonst nirgends passt", "💬", ["Deine Anfrage"]),
)

DEFAULT_WELCOME = {
    "enabled": False,
    "channel_id": None,
    "message": "Willkommen {mention} auf **{server}**! Du bist Mitglied #{member_count}.",
    "embed": True,
    "title": "Willkommen bei {server}",
    "color": "#8b5cf6",
    "role_ids": [],
    "dm_enabled": False,
}

DEFAULT_VERIFY = {
    "enabled": False,
    "channel_id": None,
    "role_id": None,
    "remove_role_ids": [],
    "title": "Verifizierung",
    "description": "Klicke auf den Button, um dich zu verifizieren.",
    "color": "#8b5cf6",
    "button_text": "Verifizieren",
    "button_emoji": "✅",
    "minimum_account_days": 0,
    "log_channel_id": None,
    "dm_enabled": True,
}

DEFAULT_SECURITY = {
    "anti_spam": True,
    "spam_messages": 6,
    "spam_seconds": 8,
    "anti_invites": True,
    "anti_links": False,
    "anti_caps": False,
    "caps_percentage": 75,
    "mention_limit": 5,
    "log_channel_id": None,
    "exempt_role_ids": [],
    "exempt_channel_ids": [],
}


def init_database(app: Flask, guild_id: int) -> None:
    db.init_app(app)
    with app.app_context():
        # create_all is intentionally non-destructive: existing data and columns
        # remain untouched. Explicit migrations can be added for future schemas.
        db.create_all()
        run_migrations()
        seed_defaults(str(guild_id))


def seed_defaults(guild_id: str) -> None:
    if not guild_id or guild_id == "0":
        return
    config = db.session.scalar(
        db.select(GuildConfig).where(GuildConfig.guild_id == guild_id)
    )
    if config is None:
        db.session.add(
            GuildConfig(
                guild_id=guild_id,
                welcome=DEFAULT_WELCOME.copy(),
                verify=DEFAULT_VERIFY.copy(),
                security=DEFAULT_SECURITY.copy(),
                branding={"name": "zyrahd.net", "accent": "#8b5cf6"},
            )
        )
    existing = db.session.scalar(
        db.select(db.func.count(TicketType.id)).where(TicketType.guild_id == guild_id)
    )
    if not existing:
        for name, description, emoji, fields in DEFAULT_TICKET_TYPES:
            db.session.add(
                TicketType(
                    guild_id=guild_id,
                    name=name,
                    description=description,
                    emoji=emoji,
                    form_fields=[
                        {
                            "id": f"field-{index}",
                            "label": label,
                            "type": "long" if index else "short",
                            "required": True,
                            "placeholder": "",
                            "min_length": 1,
                            "max_length": 1000,
                        }
                        for index, label in enumerate(fields)
                    ],
                )
            )
    db.session.commit()


def write_audit(
    guild_id: str,
    user: dict[str, Any],
    action: str,
    area: str,
    *,
    target: str | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
) -> None:
    try:
        ip_address = request.headers.get("X-Forwarded-For", request.remote_addr)
        if ip_address and "," in ip_address:
            ip_address = ip_address.split(",", 1)[0].strip()
    except RuntimeError:
        ip_address = None
    db.session.add(
        AuditLog(
            guild_id=guild_id,
            actor_id=str(user.get("id", "system")),
            actor_name=user.get("global_name") or user.get("username") or "System",
            action=action,
            area=area,
            target=target,
            before=before,
            after=after,
            ip_address=ip_address,
        )
    )
