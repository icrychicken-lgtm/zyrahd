"""Database models for dashboard, bot and audit state."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


db = SQLAlchemy(model_class=Base, session_options={"expire_on_commit": False})


def utcnow() -> datetime:
    return datetime.now(UTC)


class SchemaVersion(db.Model):
    __tablename__ = "schema_versions"

    version: Mapped[int] = mapped_column(primary_key=True)
    applied_at: Mapped[datetime] = mapped_column(default=utcnow)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        default=utcnow, onupdate=utcnow, nullable=False
    )


class GuildConfig(db.Model, TimestampMixin):
    __tablename__ = "guild_configs"

    id: Mapped[int] = mapped_column(primary_key=True)
    guild_id: Mapped[str] = mapped_column(unique=True, index=True)
    welcome: Mapped[dict[str, Any]] = mapped_column(db.JSON, default=dict)
    verify: Mapped[dict[str, Any]] = mapped_column(db.JSON, default=dict)
    security: Mapped[dict[str, Any]] = mapped_column(db.JSON, default=dict)
    branding: Mapped[dict[str, Any]] = mapped_column(db.JSON, default=dict)


class DashboardRole(db.Model, TimestampMixin):
    __tablename__ = "dashboard_roles"
    __table_args__ = (UniqueConstraint("guild_id", "role_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    guild_id: Mapped[str] = mapped_column(index=True)
    role_id: Mapped[str] = mapped_column(index=True)
    role_name: Mapped[str] = mapped_column(default="Discord-Rolle")
    permissions: Mapped[list[str]] = mapped_column(db.JSON, default=list)


class TicketType(db.Model, TimestampMixin):
    __tablename__ = "ticket_types"

    id: Mapped[int] = mapped_column(primary_key=True)
    guild_id: Mapped[str] = mapped_column(index=True)
    name: Mapped[str] = mapped_column()
    description: Mapped[str] = mapped_column(default="")
    emoji: Mapped[str] = mapped_column(default="🎫")
    color: Mapped[str] = mapped_column(default="#8b5cf6")
    enabled: Mapped[bool] = mapped_column(default=True)
    category_id: Mapped[str | None] = mapped_column(nullable=True)
    support_role_ids: Mapped[list[str]] = mapped_column(db.JSON, default=list)
    log_channel_id: Mapped[str | None] = mapped_column(nullable=True)
    transcript_channel_id: Mapped[str | None] = mapped_column(nullable=True)
    max_open_per_user: Mapped[int] = mapped_column(default=1)
    cooldown_minutes: Mapped[int] = mapped_column(default=10)
    channel_name_format: Mapped[str] = mapped_column(default="ticket-{number}-{user}")
    greeting: Mapped[str] = mapped_column(
        default="Willkommen {mention}! Das Team ist gleich für dich da."
    )
    ping_roles: Mapped[bool] = mapped_column(default=True)
    priority: Mapped[str] = mapped_column(default="normal")
    inactivity_hours: Mapped[int] = mapped_column(default=72)
    form_fields: Mapped[list[dict[str, Any]]] = mapped_column(db.JSON, default=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "emoji": self.emoji,
            "color": self.color,
            "enabled": self.enabled,
            "category_id": self.category_id,
            "support_role_ids": self.support_role_ids or [],
            "log_channel_id": self.log_channel_id,
            "transcript_channel_id": self.transcript_channel_id,
            "max_open_per_user": self.max_open_per_user,
            "cooldown_minutes": self.cooldown_minutes,
            "channel_name_format": self.channel_name_format,
            "greeting": self.greeting,
            "ping_roles": self.ping_roles,
            "priority": self.priority,
            "inactivity_hours": self.inactivity_hours,
            "form_fields": self.form_fields or [],
        }


class Ticket(db.Model, TimestampMixin):
    __tablename__ = "tickets"

    id: Mapped[int] = mapped_column(primary_key=True)
    guild_id: Mapped[str] = mapped_column(index=True)
    ticket_type_id: Mapped[int] = mapped_column(db.ForeignKey("ticket_types.id"))
    creator_id: Mapped[str] = mapped_column(index=True)
    creator_name: Mapped[str] = mapped_column(default="Unbekannt")
    channel_id: Mapped[str | None] = mapped_column(unique=True, nullable=True)
    status: Mapped[str] = mapped_column(default="open", index=True)
    priority: Mapped[str] = mapped_column(default="normal")
    claimed_by_id: Mapped[str | None] = mapped_column(nullable=True)
    claimed_by_name: Mapped[str | None] = mapped_column(nullable=True)
    form_answers: Mapped[dict[str, Any]] = mapped_column(db.JSON, default=dict)
    closed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    close_reason: Mapped[str | None] = mapped_column(nullable=True)
    rating: Mapped[int | None] = mapped_column(nullable=True)

    ticket_type: Mapped[TicketType] = db.relationship(lazy="joined")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "number": f"ZY-{self.id:05d}",
            "type": self.ticket_type.name if self.ticket_type else "Ticket",
            "creator_id": self.creator_id,
            "creator_name": self.creator_name,
            "channel_id": self.channel_id,
            "status": self.status,
            "priority": self.priority,
            "claimed_by_name": self.claimed_by_name,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


class TicketMessage(db.Model):
    __tablename__ = "ticket_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int] = mapped_column(db.ForeignKey("tickets.id"), index=True)
    author_id: Mapped[str] = mapped_column()
    author_name: Mapped[str] = mapped_column()
    author_avatar: Mapped[str | None] = mapped_column(nullable=True)
    content: Mapped[str] = mapped_column(default="")
    source: Mapped[str] = mapped_column(default="discord")
    attachments: Mapped[list[dict[str, str]]] = mapped_column(db.JSON, default=list)
    is_system: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class WordFilter(db.Model, TimestampMixin):
    __tablename__ = "word_filters"

    id: Mapped[int] = mapped_column(primary_key=True)
    guild_id: Mapped[str] = mapped_column(index=True)
    phrase: Mapped[str] = mapped_column()
    match_type: Mapped[str] = mapped_column(default="contains")
    case_sensitive: Mapped[bool] = mapped_column(default=False)
    action: Mapped[str] = mapped_column(default="delete")
    timeout_minutes: Mapped[int] = mapped_column(default=10)
    threshold: Mapped[int] = mapped_column(default=1)
    response: Mapped[str] = mapped_column(default="")
    log_channel_id: Mapped[str | None] = mapped_column(nullable=True)
    exempt_role_ids: Mapped[list[str]] = mapped_column(db.JSON, default=list)
    exempt_channel_ids: Mapped[list[str]] = mapped_column(db.JSON, default=list)
    enabled: Mapped[bool] = mapped_column(default=True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "phrase": self.phrase,
            "match_type": self.match_type,
            "case_sensitive": self.case_sensitive,
            "action": self.action,
            "timeout_minutes": self.timeout_minutes,
            "threshold": self.threshold,
            "response": self.response,
            "log_channel_id": self.log_channel_id,
            "exempt_role_ids": self.exempt_role_ids or [],
            "exempt_channel_ids": self.exempt_channel_ids or [],
            "enabled": self.enabled,
        }


class ModerationCase(db.Model, TimestampMixin):
    __tablename__ = "moderation_cases"

    id: Mapped[int] = mapped_column(primary_key=True)
    guild_id: Mapped[str] = mapped_column(index=True)
    user_id: Mapped[str] = mapped_column(index=True)
    user_name: Mapped[str] = mapped_column(default="Unbekannt")
    moderator_id: Mapped[str] = mapped_column()
    moderator_name: Mapped[str] = mapped_column()
    action: Mapped[str] = mapped_column()
    reason: Mapped[str] = mapped_column()
    duration_minutes: Mapped[int | None] = mapped_column(nullable=True)
    evidence: Mapped[str | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(default="active")
    internal_notes: Mapped[str | None] = mapped_column(nullable=True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "case_number": f"MOD-{self.id:05d}",
            "user_id": self.user_id,
            "user_name": self.user_name,
            "moderator_name": self.moderator_name,
            "action": self.action,
            "reason": self.reason,
            "duration_minutes": self.duration_minutes,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
        }


class EmbedTemplate(db.Model, TimestampMixin):
    __tablename__ = "embed_templates"

    id: Mapped[int] = mapped_column(primary_key=True)
    guild_id: Mapped[str] = mapped_column(index=True)
    name: Mapped[str] = mapped_column(default="Unbenannter Entwurf")
    payload: Mapped[dict[str, Any]] = mapped_column(db.JSON, default=dict)
    created_by_id: Mapped[str] = mapped_column()


class TeamAnnouncement(db.Model, TimestampMixin):
    __tablename__ = "team_announcements"

    id: Mapped[int] = mapped_column(primary_key=True)
    guild_id: Mapped[str] = mapped_column(index=True)
    title: Mapped[str] = mapped_column()
    content: Mapped[str] = mapped_column()
    priority: Mapped[str] = mapped_column(default="normal")
    target_role_ids: Mapped[list[str]] = mapped_column(db.JSON, default=list)
    channel_id: Mapped[str] = mapped_column()
    require_confirmation: Mapped[bool] = mapped_column(default=False)
    published_message_id: Mapped[str | None] = mapped_column(nullable=True)
    created_by_id: Mapped[str] = mapped_column()
    created_by_name: Mapped[str] = mapped_column()


class AnnouncementConfirmation(db.Model):
    __tablename__ = "announcement_confirmations"
    __table_args__ = (UniqueConstraint("announcement_id", "user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    announcement_id: Mapped[int] = mapped_column(
        db.ForeignKey("team_announcements.id"), index=True
    )
    user_id: Mapped[str] = mapped_column()
    user_name: Mapped[str] = mapped_column()
    confirmed_at: Mapped[datetime] = mapped_column(default=utcnow)


class AuditLog(db.Model):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    guild_id: Mapped[str] = mapped_column(index=True)
    actor_id: Mapped[str] = mapped_column(index=True)
    actor_name: Mapped[str] = mapped_column()
    action: Mapped[str] = mapped_column(index=True)
    area: Mapped[str] = mapped_column(index=True)
    target: Mapped[str | None] = mapped_column(nullable=True)
    before: Mapped[dict[str, Any] | None] = mapped_column(db.JSON, nullable=True)
    after: Mapped[dict[str, Any] | None] = mapped_column(db.JSON, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "actor_name": self.actor_name,
            "action": self.action,
            "area": self.area,
            "target": self.target,
            "created_at": self.created_at.isoformat(),
        }
