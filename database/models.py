"""SQLAlchemy models shared by the Discord bot and dashboard."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class GuildSetting(Base, TimestampMixin):
    __tablename__ = "guild_settings"
    __table_args__ = (UniqueConstraint("guild_id", "key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    guild_id: Mapped[str] = mapped_column(String(24), index=True)
    key: Mapped[str] = mapped_column(String(80))
    value: Mapped[str] = mapped_column(Text, default="null")


class DashboardRole(Base, TimestampMixin):
    __tablename__ = "dashboard_roles"
    __table_args__ = (UniqueConstraint("guild_id", "role_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    guild_id: Mapped[str] = mapped_column(String(24), index=True)
    role_id: Mapped[str] = mapped_column(String(24))
    role_name: Mapped[str] = mapped_column(String(100), default="Discord-Rolle")
    permissions: Mapped[str] = mapped_column(Text, default="[]")


class TicketType(Base, TimestampMixin):
    __tablename__ = "ticket_types"

    id: Mapped[int] = mapped_column(primary_key=True)
    guild_id: Mapped[str] = mapped_column(String(24), index=True)
    name: Mapped[str] = mapped_column(String(80))
    description: Mapped[str] = mapped_column(String(300), default="")
    emoji: Mapped[str] = mapped_column(String(32), default="🎫")
    color: Mapped[str] = mapped_column(String(10), default="#8b5cf6")
    category_id: Mapped[str | None] = mapped_column(String(24))
    support_role_ids: Mapped[str] = mapped_column(Text, default="[]")
    log_channel_id: Mapped[str | None] = mapped_column(String(24))
    transcript_channel_id: Mapped[str | None] = mapped_column(String(24))
    max_open: Mapped[int] = mapped_column(Integer, default=1)
    cooldown_minutes: Mapped[int] = mapped_column(Integer, default=5)
    welcome_message: Mapped[str] = mapped_column(
        Text, default="Danke für deine Anfrage. Das Team meldet sich in Kürze."
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    position: Mapped[int] = mapped_column(Integer, default=0)

    fields: Mapped[list["TicketFormField"]] = relationship(
        back_populates="ticket_type", cascade="all, delete-orphan", order_by="TicketFormField.position"
    )


class TicketFormField(Base):
    __tablename__ = "ticket_form_fields"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_type_id: Mapped[int] = mapped_column(ForeignKey("ticket_types.id"))
    label: Mapped[str] = mapped_column(String(100))
    field_type: Mapped[str] = mapped_column(String(20), default="long")
    placeholder: Mapped[str] = mapped_column(String(200), default="")
    required: Mapped[bool] = mapped_column(Boolean, default=True)
    min_length: Mapped[int] = mapped_column(Integer, default=0)
    max_length: Mapped[int] = mapped_column(Integer, default=1000)
    position: Mapped[int] = mapped_column(Integer, default=0)

    ticket_type: Mapped[TicketType] = relationship(back_populates="fields")


class Ticket(Base, TimestampMixin):
    __tablename__ = "tickets"

    id: Mapped[int] = mapped_column(primary_key=True)
    guild_id: Mapped[str] = mapped_column(String(24), index=True)
    number: Mapped[int] = mapped_column(Integer, index=True)
    ticket_type_id: Mapped[int] = mapped_column(ForeignKey("ticket_types.id"))
    creator_id: Mapped[str] = mapped_column(String(24), index=True)
    creator_name: Mapped[str] = mapped_column(String(100))
    channel_id: Mapped[str | None] = mapped_column(String(24), unique=True)
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)
    priority: Mapped[str] = mapped_column(String(20), default="normal")
    claimed_by_id: Mapped[str | None] = mapped_column(String(24))
    claimed_by_name: Mapped[str | None] = mapped_column(String(100))
    form_data: Mapped[str] = mapped_column(Text, default="{}")
    close_reason: Mapped[str | None] = mapped_column(Text)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rating: Mapped[int | None] = mapped_column(Integer)

    ticket_type: Mapped[TicketType] = relationship()
    messages: Mapped[list["TicketMessage"]] = relationship(
        back_populates="ticket", cascade="all, delete-orphan", order_by="TicketMessage.created_at"
    )


class TicketMessage(Base):
    __tablename__ = "ticket_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id"), index=True)
    author_id: Mapped[str] = mapped_column(String(24))
    author_name: Mapped[str] = mapped_column(String(100))
    author_avatar: Mapped[str | None] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(20), default="discord")
    attachment_url: Mapped[str | None] = mapped_column(Text)
    message_id: Mapped[str | None] = mapped_column(String(24))
    system_event: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    ticket: Mapped[Ticket] = relationship(back_populates="messages")


class ModerationCase(Base, TimestampMixin):
    __tablename__ = "moderation_cases"

    id: Mapped[int] = mapped_column(primary_key=True)
    guild_id: Mapped[str] = mapped_column(String(24), index=True)
    case_number: Mapped[int] = mapped_column(Integer)
    target_id: Mapped[str] = mapped_column(String(24), index=True)
    target_name: Mapped[str] = mapped_column(String(100))
    moderator_id: Mapped[str] = mapped_column(String(24))
    moderator_name: Mapped[str] = mapped_column(String(100))
    action: Mapped[str] = mapped_column(String(30))
    reason: Mapped[str] = mapped_column(Text)
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    evidence: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class WordFilter(Base, TimestampMixin):
    __tablename__ = "word_filters"

    id: Mapped[int] = mapped_column(primary_key=True)
    guild_id: Mapped[str] = mapped_column(String(24), index=True)
    phrase: Mapped[str] = mapped_column(String(200))
    match_type: Mapped[str] = mapped_column(String(20), default="contains")
    case_sensitive: Mapped[bool] = mapped_column(Boolean, default=False)
    action: Mapped[str] = mapped_column(String(20), default="delete")
    timeout_minutes: Mapped[int] = mapped_column(Integer, default=0)
    response: Mapped[str] = mapped_column(String(300), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class TeamAnnouncement(Base, TimestampMixin):
    __tablename__ = "team_announcements"

    id: Mapped[int] = mapped_column(primary_key=True)
    guild_id: Mapped[str] = mapped_column(String(24), index=True)
    author_id: Mapped[str] = mapped_column(String(24))
    author_name: Mapped[str] = mapped_column(String(100))
    title: Mapped[str] = mapped_column(String(120))
    content: Mapped[str] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(String(20), default="normal")
    target_role_ids: Mapped[str] = mapped_column(Text, default="[]")
    channel_id: Mapped[str | None] = mapped_column(String(24))
    published: Mapped[bool] = mapped_column(Boolean, default=False)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    guild_id: Mapped[str] = mapped_column(String(24), index=True)
    user_id: Mapped[str] = mapped_column(String(24))
    user_name: Mapped[str] = mapped_column(String(100))
    action: Mapped[str] = mapped_column(String(100))
    area: Mapped[str] = mapped_column(String(50))
    old_value: Mapped[str | None] = mapped_column(Text)
    new_value: Mapped[str | None] = mapped_column(Text)
    ip_address: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


MODEL_TYPES: tuple[type[Any], ...] = (
    GuildSetting,
    DashboardRole,
    TicketType,
    TicketFormField,
    Ticket,
    TicketMessage,
    ModerationCase,
    WordFilter,
    TeamAnnouncement,
    AuditLog,
)
