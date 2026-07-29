"""SQLAlchemy models for bot and dashboard data."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class JsonMixin:
    """Small JSON helper that keeps SQLite deployments portable."""

    @staticmethod
    def encode(value: Any) -> str:
        import json

        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def decode(value: str | None, fallback: Any = None) -> Any:
        import json

        if not value:
            return fallback
        try:
            return json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return fallback


class GuildSetting(Base, JsonMixin):
    __tablename__ = "guild_settings"
    __table_args__ = (Index("ux_guild_setting", "guild_id", "module", unique=True),)

    id: Mapped[int] = mapped_column(primary_key=True)
    guild_id: Mapped[str] = mapped_column(String(24), index=True)
    module: Mapped[str] = mapped_column(String(48))
    value_json: Mapped[str] = mapped_column(Text, default="{}")
    updated_by: Mapped[str | None] = mapped_column(String(24))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    @property
    def value(self) -> dict[str, Any]:
        return self.decode(self.value_json, {})

    @value.setter
    def value(self, data: dict[str, Any]) -> None:
        self.value_json = self.encode(data)


class DashboardRolePermission(Base, JsonMixin):
    __tablename__ = "dashboard_role_permissions"
    __table_args__ = (Index("ux_dashboard_role", "guild_id", "role_id", unique=True),)

    id: Mapped[int] = mapped_column(primary_key=True)
    guild_id: Mapped[str] = mapped_column(String(24), index=True)
    role_id: Mapped[str] = mapped_column(String(24))
    role_name: Mapped[str] = mapped_column(String(100), default="")
    permissions_json: Mapped[str] = mapped_column(Text, default="[]")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    @property
    def permissions(self) -> list[str]:
        return self.decode(self.permissions_json, [])

    @permissions.setter
    def permissions(self, data: list[str]) -> None:
        self.permissions_json = self.encode(sorted(set(data)))


class TicketType(Base, JsonMixin):
    __tablename__ = "ticket_types"

    id: Mapped[int] = mapped_column(primary_key=True)
    guild_id: Mapped[str] = mapped_column(String(24), index=True)
    name: Mapped[str] = mapped_column(String(80))
    description: Mapped[str] = mapped_column(String(300), default="")
    emoji: Mapped[str] = mapped_column(String(40), default="🎫")
    color: Mapped[str] = mapped_column(String(10), default="#7c5cff")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    category_id: Mapped[str | None] = mapped_column(String(24))
    support_role_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    log_channel_id: Mapped[str | None] = mapped_column(String(24))
    transcript_channel_id: Mapped[str | None] = mapped_column(String(24))
    max_open: Mapped[int] = mapped_column(Integer, default=1)
    cooldown_minutes: Mapped[int] = mapped_column(Integer, default=5)
    channel_format: Mapped[str] = mapped_column(String(80), default="ticket-{number}-{user}")
    welcome_message: Mapped[str] = mapped_column(
        Text, default="Danke für deine Anfrage. Das Team meldet sich in Kürze."
    )
    ping_roles: Mapped[bool] = mapped_column(Boolean, default=True)
    priority: Mapped[str] = mapped_column(String(20), default="normal")
    auto_close_hours: Mapped[int] = mapped_column(Integer, default=72)
    opening_hours_json: Mapped[str] = mapped_column(Text, default="{}")
    form_fields_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    @property
    def support_role_ids(self) -> list[str]:
        return self.decode(self.support_role_ids_json, [])

    @support_role_ids.setter
    def support_role_ids(self, data: list[str]) -> None:
        self.support_role_ids_json = self.encode(data)

    @property
    def form_fields(self) -> list[dict[str, Any]]:
        return self.decode(self.form_fields_json, [])

    @form_fields.setter
    def form_fields(self, data: list[dict[str, Any]]) -> None:
        self.form_fields_json = self.encode(data)


class Ticket(Base, JsonMixin):
    __tablename__ = "tickets"

    id: Mapped[int] = mapped_column(primary_key=True)
    guild_id: Mapped[str] = mapped_column(String(24), index=True)
    ticket_type_id: Mapped[int] = mapped_column(ForeignKey("ticket_types.id"))
    creator_id: Mapped[str] = mapped_column(String(24), index=True)
    creator_name: Mapped[str] = mapped_column(String(100))
    discord_channel_id: Mapped[str | None] = mapped_column(String(24), unique=True)
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)
    priority: Mapped[str] = mapped_column(String(20), default="normal")
    assigned_to_id: Mapped[str | None] = mapped_column(String(24))
    assigned_to_name: Mapped[str | None] = mapped_column(String(100))
    subject: Mapped[str] = mapped_column(String(150), default="")
    form_data_json: Mapped[str] = mapped_column(Text, default="{}")
    closed_reason: Mapped[str | None] = mapped_column(Text)
    rating: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    ticket_type: Mapped[TicketType] = relationship()
    messages: Mapped[list["TicketMessage"]] = relationship(
        back_populates="ticket", cascade="all, delete-orphan"
    )

    @property
    def form_data(self) -> dict[str, Any]:
        return self.decode(self.form_data_json, {})

    @form_data.setter
    def form_data(self, data: dict[str, Any]) -> None:
        self.form_data_json = self.encode(data)


class TicketMessage(Base, JsonMixin):
    __tablename__ = "ticket_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id"), index=True)
    author_id: Mapped[str] = mapped_column(String(24))
    author_name: Mapped[str] = mapped_column(String(100))
    author_avatar: Mapped[str | None] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(16), default="discord")
    discord_message_id: Mapped[str | None] = mapped_column(String(24), unique=True)
    attachments_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    ticket: Mapped[Ticket] = relationship(back_populates="messages")

    @property
    def attachments(self) -> list[dict[str, Any]]:
        return self.decode(self.attachments_json, [])

    @attachments.setter
    def attachments(self, data: list[dict[str, Any]]) -> None:
        self.attachments_json = self.encode(data)


class WordFilter(Base, JsonMixin):
    __tablename__ = "word_filters"

    id: Mapped[int] = mapped_column(primary_key=True)
    guild_id: Mapped[str] = mapped_column(String(24), index=True)
    phrase: Mapped[str] = mapped_column(String(200))
    mode: Mapped[str] = mapped_column(String(20), default="contains")
    case_sensitive: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    action: Mapped[str] = mapped_column(String(20), default="delete")
    timeout_minutes: Mapped[int] = mapped_column(Integer, default=10)
    threshold: Mapped[int] = mapped_column(Integer, default=1)
    response: Mapped[str] = mapped_column(
        String(300), default="Diese Nachricht verstößt gegen unsere Regeln."
    )
    exceptions_json: Mapped[str] = mapped_column(Text, default="{}")
    log_channel_id: Mapped[str | None] = mapped_column(String(24))

    @property
    def exceptions(self) -> dict[str, Any]:
        return self.decode(self.exceptions_json, {})

    @exceptions.setter
    def exceptions(self, data: dict[str, Any]) -> None:
        self.exceptions_json = self.encode(data)


class ModerationCase(Base):
    __tablename__ = "moderation_cases"

    id: Mapped[int] = mapped_column(primary_key=True)
    guild_id: Mapped[str] = mapped_column(String(24), index=True)
    user_id: Mapped[str] = mapped_column(String(24), index=True)
    user_name: Mapped[str] = mapped_column(String(100))
    moderator_id: Mapped[str] = mapped_column(String(24))
    moderator_name: Mapped[str] = mapped_column(String(100))
    action: Mapped[str] = mapped_column(String(24))
    reason: Mapped[str] = mapped_column(Text, default="Kein Grund angegeben")
    evidence: Mapped[str | None] = mapped_column(Text)
    duration_minutes: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="active")
    internal_notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_by: Mapped[str | None] = mapped_column(String(24))


class TeamAnnouncement(Base, JsonMixin):
    __tablename__ = "team_announcements"

    id: Mapped[int] = mapped_column(primary_key=True)
    guild_id: Mapped[str] = mapped_column(String(24), index=True)
    title: Mapped[str] = mapped_column(String(150))
    message: Mapped[str] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(String(20), default="normal")
    target_role_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    channel_id: Mapped[str] = mapped_column(String(24))
    created_by: Mapped[str] = mapped_column(String(24))
    created_by_name: Mapped[str] = mapped_column(String(100))
    publish_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    discord_message_id: Mapped[str | None] = mapped_column(String(24))
    require_confirmation: Mapped[bool] = mapped_column(Boolean, default=False)
    confirmed_user_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditLog(Base, JsonMixin):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    guild_id: Mapped[str] = mapped_column(String(24), index=True)
    user_id: Mapped[str] = mapped_column(String(24))
    user_name: Mapped[str] = mapped_column(String(100))
    action: Mapped[str] = mapped_column(String(100))
    area: Mapped[str] = mapped_column(String(48))
    target: Mapped[str | None] = mapped_column(String(150))
    before_json: Mapped[str | None] = mapped_column(Text)
    after_json: Mapped[str | None] = mapped_column(Text)
    ip_address: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
